// Supabase Edge Function: transcribe_stream
//
// Stateless streaming endpoint for FALAI.
// The client buffers PCM locally during recording and sends everything at stop.
// This endpoint must preserve the same server-side access rules as `transcribe`.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

type Json = Record<string, unknown>;
type SpeedTier = "trial" | "start" | "pro";
type ResolvedTier = {
  tier: SpeedTier;
  planCode: string;
  entitlementSource: string;
  dailyMinutesLimit: number | null;
};
type TranscriptionSegment = {
  start: number;
  end: number;
  text: string;
};

const DEFAULT_ALLOWED_ORIGINS = [
  "https://falai.app",
  "https://www.falai.app",
  "http://localhost:3000",
  "http://localhost:5173",
  "http://127.0.0.1:3000",
  "http://127.0.0.1:5173",
];

const CORS_BASE_HEADERS: Record<string, string> = {
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-app-version",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Vary": "Origin",
};

function requiredEnv(name: string): string {
  const value = Deno.env.get(name);
  if (!value) throw new Error(`Missing required env: ${name}`);
  return value;
}

function envFlag(name: string, defaultValue = false): boolean {
  const value = String(Deno.env.get(name) ?? "").trim().toLowerCase();
  if (!value) return defaultValue;
  if (["1", "true", "yes", "on"].includes(value)) return true;
  if (["0", "false", "no", "off"].includes(value)) return false;
  return defaultValue;
}

function envPercent(name: string, defaultValue: number): number {
  const raw = String(Deno.env.get(name) ?? "").trim();
  const value = Number.parseInt(raw, 10);
  if (!Number.isFinite(value)) return Math.max(0, Math.min(100, defaultValue));
  return Math.max(0, Math.min(100, value));
}

function deterministicBucket(value: string): number {
  const input = String(value || "");
  let hash = 2166136261;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash >>> 0) % 100;
}

function isTierEnabledForUser(userId: string, tier: SpeedTier): boolean {
  if (!envFlag("SPEED_TIERS_ENABLED", false)) return false;
  const bucket = deterministicBucket(userId);
  if (tier === "pro") return bucket < envPercent("SPEED_TIERS_PRO_PERCENT", 100);
  if (tier === "start") return bucket < envPercent("SPEED_TIERS_START_PERCENT", 100);
  return false;
}

function getAllowedOrigins(): string[] {
  const raw = (Deno.env.get("ALLOWED_ORIGINS") ?? "").trim();
  if (!raw) return DEFAULT_ALLOWED_ORIGINS;
  const parsed = raw.split(",").map((part) => part.trim()).filter(Boolean);
  return parsed.length ? parsed : DEFAULT_ALLOWED_ORIGINS;
}

function isAllowedOrigin(origin: string, allowed: string[]): boolean {
  if (allowed.includes("*")) return true;
  if (allowed.includes(origin)) return true;
  // FWEB: accept any chrome-extension://<id> origin — extension ID is unknown at deploy
  // time and changes between dev (unpacked) and Chrome Web Store builds.
  if (origin.startsWith("chrome-extension://")) return true;
  return false;
}

function corsHeaders(origin: string | null): Record<string, string> {
  const allowed = getAllowedOrigins();
  if (allowed.includes("*")) {
    return { ...CORS_BASE_HEADERS, "Access-Control-Allow-Origin": "*" };
  }
  const effectiveOrigin = origin && isAllowedOrigin(origin, allowed) ? origin : allowed[0];
  return { ...CORS_BASE_HEADERS, "Access-Control-Allow-Origin": effectiveOrigin };
}

function respondJson(body: Json, status = 200, origin: string | null = null): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders(origin), "Content-Type": "application/json; charset=utf-8" },
  });
}

function toNumberOrNull(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function wordCount(text: string): number {
  const clean = normalizeSpacing(text);
  if (!clean) return 0;
  return clean.split(/\s+/).length;
}

function normalizeTier(value: unknown): SpeedTier {
  const tier = String(value ?? "").trim().toLowerCase();
  if (tier === "start") return "start";
  if (tier === "pro") return "pro";
  return "trial";
}

function normalizeFormatMode(value: unknown): "balanced" | "message" {
  const mode = String(value ?? "").trim().toLowerCase();
  if (mode === "message") return "message";
  return "balanced";
}

function normalizeDomainProfile(value: unknown): "none" | "imobiliario_marketing" {
  const profile = String(value ?? "").trim().toLowerCase();
  if (profile === "imobiliario_marketing") return "imobiliario_marketing";
  return "none";
}

function normalizeSpacing(text: string): string {
  return String(text ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function buildSttPrompt(language: string): string {
  const lang = String(language ?? "").trim().toLowerCase();
  if (lang.startsWith("pt")) {
    return "Audio em português do Brasil com mistura natural de termos em inglês, marcas, siglas e nomes próprios. Preserve a grafia correta de marcas e palavras em inglês quando reconhecidas, como Facebook, Instagram, WhatsApp, Meta, Google Ads, CRM, lead, briefing, call, dashboard, direct, story, feed e reels.";
  }
  return "Preserve the exact spelling of English brand names, product names, acronyms, and mixed-language terms when recognized.";
}

function parseTranscriptionSegments(payload: Record<string, unknown>): TranscriptionSegment[] {
  const rawSegments = Array.isArray(payload.segments) ? payload.segments : [];
  return rawSegments
    .map((segment) => {
      if (!segment || typeof segment !== "object") return null;
      const row = segment as Record<string, unknown>;
      const text = normalizeSpacing(String(row.text ?? ""));
      const start = toNumberOrNull(row.start);
      const end = toNumberOrNull(row.end);
      if (!text || start === null || end === null) return null;
      return { start, end, text };
    })
    .filter((segment): segment is TranscriptionSegment => Boolean(segment));
}

function splitMessageUnits(text: string): string[] {
  const clean = normalizeSpacing(text);
  if (!clean) return [];
  const sentenceParts = clean
    .split(/(?<=[.!?])\s+/)
    .map((part) => part.trim())
    .filter(Boolean);
  const sourceParts = sentenceParts.length ? sentenceParts : [clean];
  const units: string[] = [];
  for (const part of sourceParts) {
    if (wordCount(part) > 18 && /[,;:]/.test(part)) {
      const subparts = part.split(/(?<=[,;:])\s+/).map((item) => item.trim()).filter(Boolean);
      units.push(...(subparts.length ? subparts : [part]));
    } else if (wordCount(part) > 18) {
      const words = part.split(/\s+/).filter(Boolean);
      for (let start = 0; start < words.length; start += 10) {
        units.push(words.slice(start, start + 10).join(" "));
      }
    } else {
      units.push(part);
    }
  }
  return units.filter(Boolean);
}

function buildMessageBlocksFromSegments(segments: TranscriptionSegment[]): string[] {
  if (!segments.length) return [];
  const blocks: string[] = [];
  let currentParts: string[] = [];
  let currentWords = 0;
  let previousEnd: number | null = null;

  for (const segment of segments) {
    const segText = normalizeSpacing(segment.text);
    if (!segText) continue;
    const gap = previousEnd === null ? 0 : Math.max(0, segment.start - previousEnd);
    const segWords = wordCount(segText);
    const shouldBreak = currentParts.length > 0 && (
      gap >= 0.9 ||
      currentWords >= 18 ||
      (gap >= 0.45 && currentWords >= 10)
    );

    if (shouldBreak) {
      blocks.push(normalizeSpacing(currentParts.join(" ")));
      currentParts = [];
      currentWords = 0;
    }

    currentParts.push(segText);
    currentWords += segWords;
    previousEnd = segment.end;
  }

  if (currentParts.length) {
    blocks.push(normalizeSpacing(currentParts.join(" ")));
  }

  return blocks.filter(Boolean);
}

function buildMessageBlockTargets(segments: TranscriptionSegment[]): number[] {
  return buildMessageBlocksFromSegments(segments)
    .map((block) => wordCount(block))
    .filter((count) => count > 0);
}

function formatMessageText(text: string, targetWordCounts: number[] = []): string {
  const units = splitMessageUnits(text);
  if (!units.length) return normalizeSpacing(text);
  const blocks: string[] = [];
  let currentUnits: string[] = [];
  let currentWords = 0;
  let targetIndex = 0;

  for (const unit of units) {
    const unitWords = wordCount(unit);
    const targetWords = targetWordCounts[targetIndex] ?? 16;
    const limitWords = Math.max(12, targetWords + 4);
    const shouldBreak = currentUnits.length > 0 && (
      currentWords + unitWords > limitWords ||
      currentUnits.length >= 2 ||
      currentWords >= Math.max(10, targetWords)
    );

    if (shouldBreak) {
      blocks.push(normalizeSpacing(currentUnits.join(" ")));
      currentUnits = [];
      currentWords = 0;
      targetIndex += 1;
    }

    currentUnits.push(unit);
    currentWords += unitWords;
  }

  if (currentUnits.length) {
    blocks.push(normalizeSpacing(currentUnits.join(" ")));
  }

  return blocks.filter(Boolean).join("\n\n");
}

function applyOutputFormatting(
  text: string,
  formatMode: "balanced" | "message",
  segments: TranscriptionSegment[] = [],
): string {
  if (formatMode !== "message") return normalizeSpacing(text);
  if (segments.length && normalizeSpacing(text) === normalizeSpacing(segments.map((segment) => segment.text).join(" "))) {
    const fromSegments = buildMessageBlocksFromSegments(segments).join("\n\n");
    if (fromSegments) return fromSegments;
  }
  return formatMessageText(text, buildMessageBlockTargets(segments));
}

async function resolveTranscriptionTier(
  supabaseAdmin: ReturnType<typeof createClient>,
  userId: string,
  dailyLimitSeconds: number | null,
): Promise<ResolvedTier> {
  try {
    const { data, error } = await supabaseAdmin.rpc("resolve_transcription_tier", { p_user_id: userId });
    if (!error) {
      const row = Array.isArray(data) ? (data[0] as Record<string, unknown>) : (data as Record<string, unknown>);
      if (row && typeof row === "object") {
        return {
          tier: normalizeTier(row.tier),
          planCode: String(row.plan_code ?? "").trim().toLowerCase(),
          entitlementSource: String(row.entitlement_source ?? "").trim().toLowerCase(),
          dailyMinutesLimit: toNumberOrNull(row.daily_minutes_limit),
        };
      }
    }
  } catch {
    // Fallback below when the RPC is unavailable.
  }

  if (dailyLimitSeconds === null) {
    return { tier: "pro", planCode: "pro", entitlementSource: "fallback", dailyMinutesLimit: null };
  }
  if (Number(dailyLimitSeconds) >= 1800) {
    return { tier: "start", planCode: "start", entitlementSource: "fallback", dailyMinutesLimit: 30 };
  }
  return { tier: "trial", planCode: "trial", entitlementSource: "fallback", dailyMinutesLimit: 15 };
}

async function resolveUser(
  supabaseUrl: string,
  supabaseAnonKey: string,
  accessToken: string,
): Promise<{ user: { id: string } | null; error: string | null }> {
  try {
    const client = createClient(supabaseUrl, supabaseAnonKey, {
      auth: {
        persistSession: false,
        autoRefreshToken: false,
      },
      global: { headers: { Authorization: `Bearer ${accessToken}` } },
    });
    const { data, error } = await client.auth.getUser(accessToken);
    if (error || !data?.user) return { user: null, error: error?.message || "user_not_found" };
    return { user: { id: data.user.id }, error: null };
  } catch (err) {
    return { user: null, error: String(err) };
  }
}

function pcmToWav(pcm: Uint8Array, sampleRate: number, channels: number): Uint8Array {
  const bitsPerSample = 16;
  const byteRate = sampleRate * channels * (bitsPerSample / 8);
  const blockAlign = channels * (bitsPerSample / 8);
  const dataSize = pcm.length;
  const wav = new Uint8Array(44 + dataSize);
  const view = new DataView(wav.buffer);
  wav.set([0x52, 0x49, 0x46, 0x46], 0);
  view.setUint32(4, 36 + dataSize, true);
  wav.set([0x57, 0x41, 0x56, 0x45], 8);
  wav.set([0x66, 0x6d, 0x74, 0x20], 12);
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);
  wav.set([0x64, 0x61, 0x74, 0x61], 36);
  view.setUint32(40, dataSize, true);
  wav.set(pcm, 44);
  return wav;
}

function b64decode(base64Value: string): Uint8Array {
  const raw = atob(base64Value);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) output[i] = raw.charCodeAt(i);
  return output;
}

Deno.serve(async (req) => {
  const origin = req.headers.get("origin");

  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders(origin) });
  }
  if (req.method !== "POST") {
    return respondJson({ error: "method_not_allowed" }, 405, origin);
  }

  const requestId = crypto.randomUUID();

  try {
    const body = await req.json() as Json;
    const action = String(body.action ?? "").trim();

    if (action === "ping" || action === "start") {
      return respondJson({ status: "ready", request_id: requestId }, 200, origin);
    }

    if (action === "chunk") {
      return respondJson({ status: "received", request_id: requestId }, 200, origin);
    }

    if (action !== "transcribe") {
      return respondJson({ error: "unknown_action", request_id: requestId }, 400, origin);
    }

    const pcmB64 = String(body.audio_pcm_base64 ?? "");
    if (!pcmB64) {
      return respondJson({ error: "missing_audio_data", request_id: requestId }, 400, origin);
    }

    const sampleRate = Number(body.sample_rate) || 16000;
    const channels = Number(body.channels) || 1;
    const language = String(body.language ?? "pt");
    const model = String(body.model ?? "whisper-large-v3-turbo");
    const correct = Boolean(body.correct ?? true);
    const correctionStyle = String(body.correction_style ?? "neutro");
    const formatMode = normalizeFormatMode(body.format_mode);
    const domainProfile = normalizeDomainProfile(body.domain_profile);
    const deviceId = body.device_id ? String(body.device_id) : null;

    const supabaseUrl = Deno.env.get("EDGE_SUPABASE_URL") || requiredEnv("SUPABASE_URL");
    const supabaseAnonKey = Deno.env.get("EDGE_SUPABASE_ANON_KEY") || requiredEnv("SUPABASE_ANON_KEY");
    const serviceRoleKey =
      Deno.env.get("EDGE_SUPABASE_SERVICE_ROLE_KEY")
      || Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")
      || requiredEnv("SERVICE_ROLE_KEY");
    const groqApiKey = requiredEnv("GROQ_API_KEY");

    const authHeader = req.headers.get("authorization") ?? "";
    const accessToken = authHeader.replace(/^Bearer\s+/i, "").trim();
    const effectiveToken = accessToken || String(body.access_token ?? "");
    if (!effectiveToken) {
      return respondJson({ error: "missing_authorization", request_id: requestId }, 401, origin);
    }

    const { user, error: authErr } = await resolveUser(supabaseUrl, supabaseAnonKey, effectiveToken);
    if (!user) {
      return respondJson({ error: "invalid_session", detail: authErr, request_id: requestId }, 401, origin);
    }

    const pcmBytes = b64decode(pcmB64);
    const wavBytes = pcmToWav(pcmBytes, sampleRate, channels);
    const audioDurationSeconds = Math.round(((pcmBytes.length / 2) / sampleRate) * 100) / 100;

    const supabaseAdmin = createClient(supabaseUrl, serviceRoleKey, {
      auth: { autoRefreshToken: false, persistSession: false },
    });

    const { data: accessRows, error: accessErr } = await supabaseAdmin.rpc(
      "check_transcription_access",
      { p_user_id: user.id },
    );
    if (accessErr) {
      throw new Error(`check_transcription_access failed: ${accessErr.message}`);
    }

    const access = Array.isArray(accessRows) ? (accessRows[0] as Record<string, unknown>) : (accessRows as Record<string, unknown>);
    const allowed = Boolean(access?.allowed);
    const dailyLimitSeconds = toNumberOrNull(access?.daily_limit_seconds);
    const usedTodaySeconds = toNumberOrNull(access?.used_today_seconds) ?? 0;
    const remainingSeconds = toNumberOrNull(access?.remaining_seconds);
    const monthlyLimitSeconds = toNumberOrNull(access?.monthly_limit_seconds);
    const usedMonthSeconds = toNumberOrNull(access?.used_month_seconds) ?? 0;
    const remainingMonthSeconds = toNumberOrNull(access?.remaining_month_seconds);
    const accessReason = String(access?.reason ?? "unknown");

    if (!allowed) {
      return respondJson({
        allowed: false,
        reason: accessReason,
        usage: {
          daily_limit_seconds: dailyLimitSeconds,
          used_today_seconds: usedTodaySeconds,
          remaining_seconds: remainingSeconds,
          monthly_limit_seconds: monthlyLimitSeconds,
          used_month_seconds: usedMonthSeconds,
          remaining_month_seconds: remainingMonthSeconds,
        },
        request_id: requestId,
      }, 403, origin);
    }

    if (remainingSeconds !== null && audioDurationSeconds > remainingSeconds) {
      return respondJson({
        allowed: false,
        reason: "daily_remaining_insufficient",
        usage: {
          daily_limit_seconds: dailyLimitSeconds,
          used_today_seconds: usedTodaySeconds,
          remaining_seconds: remainingSeconds,
          monthly_limit_seconds: monthlyLimitSeconds,
          used_month_seconds: usedMonthSeconds,
          remaining_month_seconds: remainingMonthSeconds,
        },
        request_id: requestId,
      }, 403, origin);
    }

    if (remainingMonthSeconds !== null && audioDurationSeconds > remainingMonthSeconds) {
      return respondJson({
        allowed: false,
        reason: "monthly_remaining_insufficient",
        usage: {
          daily_limit_seconds: dailyLimitSeconds,
          used_today_seconds: usedTodaySeconds,
          remaining_seconds: remainingSeconds,
          monthly_limit_seconds: monthlyLimitSeconds,
          used_month_seconds: usedMonthSeconds,
          remaining_month_seconds: remainingMonthSeconds,
        },
        request_id: requestId,
      }, 403, origin);
    }

    const tierResolved = await resolveTranscriptionTier(supabaseAdmin, user.id, dailyLimitSeconds);
    const speedTierEnabled = isTierEnabledForUser(user.id, tierResolved.tier);

    const groqForm = new FormData();
    groqForm.append("file", new Blob([wavBytes], { type: "audio/wav" }), "audio.wav");
    groqForm.append("model", model);
    groqForm.append("language", language);
    groqForm.append("response_format", "verbose_json");
    groqForm.append("timestamp_granularities[]", "segment");
    groqForm.append("prompt", buildSttPrompt(language));

    const sttStart = Date.now();
    const groqResp = await fetch("https://api.groq.com/openai/v1/audio/transcriptions", {
      method: "POST",
      headers: { Authorization: `Bearer ${groqApiKey}` },
      body: groqForm,
    });
    const sttMs = Math.max(0, Date.now() - sttStart);

    if (!groqResp.ok) {
      const errorBody = await groqResp.text().catch(() => "");
      console.error(JSON.stringify({
        event: "groq_stt_error",
        request_id: requestId,
        status: groqResp.status,
        body: errorBody.slice(0, 500),
      }));
      return respondJson({ error: "stt_failed", detail: `Groq ${groqResp.status}`, request_id: requestId }, 502, origin);
    }

    const groqPayload = (await groqResp.json().catch(() => ({}))) as Record<string, unknown>;
    const groqText = String(groqPayload.text ?? "").trim();
    const sttSegments = parseTranscriptionSegments(groqPayload);
    if (!groqText) {
      return respondJson({ error: "empty_transcription", request_id: requestId }, 422, origin);
    }

    const words = groqText.split(/\s+/).filter(Boolean).length;

    let correctedText: string | null = null;
    let correctionMs: number | null = null;
    let correctionMode = "off";
    let correctionPending = false;

    if (correct) {
      let canCorrect = true;
      try {
        const { data: entRow, error: entErr } = await supabaseAdmin
          .from("user_entitlements")
          .select("can_correct")
          .eq("user_id", user.id)
          .maybeSingle();
        if (entErr) throw entErr;
        canCorrect = Boolean((entRow as Record<string, unknown> | null)?.can_correct);
      } catch {
        canCorrect = false;
      }

      if (canCorrect) {
        const useBackground = tierResolved.tier === "pro" && correctionStyle !== "formal";
        if (useBackground) {
          correctionMode = "background";
          correctionPending = true;
        } else if (correctionStyle === "formal") {
          correctionMode = "sync";

          const formatInstructions = formatMode === "message"
            ? "Formate como mensagens curtas de chat, prontas para WhatsApp/Instagram. Quebre em blocos pequenos com linha em branco entre eles. Use uma nova quebra quando houver pausa natural, mudanca de ideia, enumeracao ou frase longa demais. Cada bloco deve ter 1-2 frases curtas e evitar um bloco unico grande."
            : formatMode === "balanced"
              ? "Formate em paragrafos curtos e legiveis (1-3 frases por paragrafo). Quebre linha em mudanca clara de assunto. Evite excesso de quebras."
              : "";
          const domainInstructions = domainProfile === "imobiliario_marketing"
            ? "Se houver contexto claro, prefira termos de imobiliario e marketing: m², metragem, planta, lancamento, captacao, lead, campanha, anuncio, CPL, trafego pago, funil e conversao. Normalizacoes permitidas: 'metro(s) quadrado(s)' -> 'm²'; valores em reais podem usar 'R$' quando houver contexto."
            : "";

          const correctionParts = [
            "Reescreva em portugues formal e profissional. Remova girias, vicios de linguagem e repeticoes. Preserve 100% do significado e fatos. Nao invente conteudo. Nao adicione frases novas. O texto corrigido deve ter tamanho similar ao original.",
          ];
          correctionParts.push("Preserve exatamente palavras em inglês, nomes de marcas, produtos, plataformas, siglas e nomes próprios. Nunca traduza ou substitua termos como Facebook, Instagram, WhatsApp, Meta, Google Ads, CRM, lead, briefing, call, dashboard, direct, story, feed e reels. Se um termo parecer ser inglês ou nome de marca, mantenha como está.");
          if (formatInstructions) correctionParts.push(formatInstructions);
          if (domainInstructions) correctionParts.push(domainInstructions);
          correctionParts.push(`Texto: ${groqText}`);

          const corrModel =
            Deno.env.get("GROQ_CORRECTOR_MODEL_PRO")
            || Deno.env.get("GROQ_CORRECTOR_MODEL_START")
            || "llama-3.1-8b-instant";

          const corrStart = Date.now();
          const corrResp = await fetch("https://api.groq.com/openai/v1/chat/completions", {
            method: "POST",
            headers: { Authorization: `Bearer ${groqApiKey}`, "Content-Type": "application/json" },
            body: JSON.stringify({
              model: corrModel,
              messages: [
                {
                  role: "system",
                  content: "Voce corrige textos. Retorne somente o texto corrigido. Sem aspas. Sem explicacao. Sem comentarios. Sem introducoes. Nunca adicione frases que nao existiam no original.",
                },
                {
                  role: "user",
                  content: correctionParts.join("\n\n"),
                },
              ],
              temperature: 0.05,
              max_tokens: domainProfile === "imobiliario_marketing" ? 220 : 420,
            }),
          });
          correctionMs = Math.max(0, Date.now() - corrStart);

          if (corrResp.ok) {
            const correctionPayload = (await corrResp.json().catch(() => ({}))) as Record<string, unknown>;
            const choices = correctionPayload.choices as Array<{ message?: { content?: string } }> | undefined;
            const candidate = choices?.[0]?.message?.content?.trim() ?? "";
            if (candidate && candidate.length > groqText.length * 0.5 && candidate.length < groqText.length * 1.8) {
              correctedText = applyOutputFormatting(candidate, formatMode, sttSegments);
            } else if (candidate) {
              console.warn(JSON.stringify({
                event: "correction_guardrail",
                request_id: requestId,
                reason: candidate.length < groqText.length * 0.5 ? "too_short" : "too_expanded",
                original_len: groqText.length,
                corrected_len: candidate.length,
              }));
            }
          }
        }
      }
    }

    const textToPaste = correctedText
      ? applyOutputFormatting(correctedText, formatMode, sttSegments)
      : applyOutputFormatting(groqText, formatMode, sttSegments);
    const totalMs = Math.max(0, Date.now() - sttStart);

    const insertPayload = {
      user_id: user.id,
      original_text: groqText,
      corrected_text: correctedText,
      status: "done",
      audio_duration_seconds: audioDurationSeconds,
      language,
      metadata: {
        stt_ms: sttMs,
        correction_ms: correctionMs,
        total_ms: totalMs,
        correction_mode: correctionMode,
        correction_pending: correctionPending,
        format_mode_applied: formatMode,
        domain_profile_applied: domainProfile,
        stt_segments: sttSegments,
        tier_applied: tierResolved.tier,
        source: "stream",
        model,
        device_id: deviceId,
      },
    };

    const { data: inserted, error: insertErr } = await supabaseAdmin
      .from("transcriptions")
      .insert(insertPayload)
      .select("id, created_at, status, word_count")
      .single();
    if (insertErr) {
      console.warn(JSON.stringify({
        event: "stream_insert_error",
        request_id: requestId,
        error: insertErr.message,
      }));
    }

    const { data: usageRow, error: usageErr } = await supabaseAdmin.rpc("register_transcription_usage", {
      p_user_id: user.id,
      p_audio_seconds: audioDurationSeconds,
      p_words_count: words,
      p_transcriptions_count: 1,
    });
    if (usageErr) {
      console.warn(JSON.stringify({
        event: "stream_usage_error",
        request_id: requestId,
        error: usageErr.message,
      }));
    }

    const usage = Array.isArray(usageRow) ? (usageRow[0] as Record<string, unknown>) : (usageRow as Record<string, unknown>);
    const usedAfter = toNumberOrNull(usage?.audio_seconds) ?? usedTodaySeconds;
    const remainingAfter = dailyLimitSeconds === null
      ? null
      : (remainingSeconds ?? Math.max(dailyLimitSeconds - usedAfter, 0));
    const usedMonthAfter = toNumberOrNull(usage?.used_month_seconds) ?? usedMonthSeconds;
    const remainingMonthAfter = monthlyLimitSeconds === null
      ? null
      : (remainingMonthSeconds ?? Math.max(monthlyLimitSeconds - usedMonthAfter, 0));
    const canQueuePostprocess = Boolean(inserted?.id);
    const responseCorrectionPending = correctionPending && canQueuePostprocess;

    console.log(JSON.stringify({
      event: "stream_complete",
      request_id: requestId,
      user_id: user.id,
      tier: tierResolved.tier,
      audio_s: audioDurationSeconds,
      stt_ms: sttMs,
      corr_ms: correctionMs,
      total_ms: totalMs,
      words,
    }));

    return respondJson({
      transcription: {
        id: String(inserted?.id ?? ""),
        created_at: String(inserted?.created_at ?? ""),
        status: String(inserted?.status ?? "done"),
        audio_duration_seconds: audioDurationSeconds,
        original_text: groqText,
        corrected_text: correctedText,
        correction_pending: responseCorrectionPending,
        text_to_paste: textToPaste,
        correction_style: correctedText ? correctionStyle : null,
        word_count: toNumberOrNull(inserted?.word_count) ?? words,
        language,
        stt_provider: "groq",
        stt_model: model,
      },
      processing: {
        tier: tierResolved.tier,
        correction_mode: correctionMode,
        speed_tier_enabled: speedTierEnabled,
        source: "stream",
        request_id: requestId,
        latency_ms: {
          stt: sttMs,
          correction: correctionMs,
          total: totalMs,
        },
      },
      usage: {
        daily_limit_seconds: dailyLimitSeconds,
        used_today_seconds: usedAfter,
        remaining_seconds: remainingAfter,
        monthly_limit_seconds: monthlyLimitSeconds,
        used_month_seconds: usedMonthAfter,
        remaining_month_seconds: remainingMonthAfter,
      },
    }, 200, origin);
  } catch (err) {
    console.error(JSON.stringify({
      event: "stream_error",
      request_id: requestId,
      error: String(err),
      stack: (err as Error).stack ?? "",
    }));
    return respondJson({ error: "internal_error", detail: String(err), request_id: requestId }, 500, origin);
  }
});
