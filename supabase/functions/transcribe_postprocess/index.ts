// Supabase Edge Function: transcribe_postprocess
//
// Purpose:
// - Apply post-processing correction asynchronously for fast Pro pipeline.
// - Keep correction model/key server-side.
// - Enforce ownership of transcription (auth user only).

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

type Json = Record<string, unknown>;
type CorrectionStyle = "neutro" | "casual" | "formal";
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

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function getAllowedOrigins(): string[] {
  const raw = (Deno.env.get("ALLOWED_ORIGINS") ?? "").trim();
  if (!raw) return DEFAULT_ALLOWED_ORIGINS;
  const parsed = raw.split(",").map((v) => v.trim()).filter(Boolean);
  return parsed.length ? parsed : DEFAULT_ALLOWED_ORIGINS;
}

function buildCorsHeaders(req: Request): Record<string, string> {
  const requestOrigin = (req.headers.get("origin") ?? "").trim();
  const allowedOrigins = getAllowedOrigins();
  if (allowedOrigins.includes("*")) return { ...CORS_BASE_HEADERS, "Access-Control-Allow-Origin": "*" };
  if (requestOrigin && allowedOrigins.includes(requestOrigin)) {
    return { ...CORS_BASE_HEADERS, "Access-Control-Allow-Origin": requestOrigin };
  }
  if (!requestOrigin && allowedOrigins.length > 0) {
    return { ...CORS_BASE_HEADERS, "Access-Control-Allow-Origin": allowedOrigins[0] };
  }
  return { ...CORS_BASE_HEADERS };
}

function jsonResponse(body: unknown, status = 200, corsHeaders: Record<string, string> = CORS_BASE_HEADERS): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...corsHeaders },
  });
}

class HttpError extends Error {
  status: number;
  code: string;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

function requiredEnv(name: string): string {
  const v = Deno.env.get(name);
  if (!v) throw new Error(`Missing env: ${name}`);
  return v;
}

function stripOuterQuotes(text: string): string {
  const t = text.trim();
  if ((t.startsWith("\"") && t.endsWith("\"")) || (t.startsWith("'") && t.endsWith("'"))) {
    return t.slice(1, -1).trim();
  }
  return t;
}

function wordCount(text: string): number {
  const t = text.trim();
  if (!t) return 0;
  return t.split(/\s+/).length;
}

function normalizeForGuard(text: string): string {
  return String(text ?? "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function hasDuplicateBlock(text: string): boolean {
  const t = normalizeForGuard(text);
  if (t.length < 160) return false;
  const half = Math.floor(t.length / 2);
  const left = t.slice(0, half).trim();
  const right = t.slice(half).trim();
  if (left.length < 60 || right.length < 60) return false;
  const leftPrefix = left.slice(0, 100);
  const rightPrefix = right.slice(0, 100);
  return right.includes(leftPrefix) || left.includes(rightPrefix);
}

function evaluateCorrectionGuard(
  originalText: string,
  correctedText: string,
  style: CorrectionStyle,
): {
  accepted: boolean;
  reason: string;
  originalWords: number;
  correctedWords: number;
  ratio: number;
  unseenRatio: number;
  duplicateBlock: boolean;
} {
  const originalNorm = normalizeForGuard(originalText);
  const correctedNorm = normalizeForGuard(correctedText);
  const originalWords = wordCount(originalNorm);
  const correctedWords = wordCount(correctedNorm);
  const ratio = originalWords > 0 ? correctedWords / originalWords : 1;
  const duplicateBlock = hasDuplicateBlock(correctedNorm);

  const correctedTokens = correctedNorm.split(" ").filter(Boolean);
  const originalTokenSet = new Set(originalNorm.split(" ").filter(Boolean));
  let unseenCount = 0;
  for (const token of correctedTokens) {
    if (!originalTokenSet.has(token)) unseenCount++;
  }
  const unseenRatio = correctedTokens.length > 0 ? unseenCount / correctedTokens.length : 0;

  const strictMode = style !== "formal";
  const maxExpansionRatio = style === "casual" ? 1.18 : style === "neutro" ? 1.25 : 1.55;

  if (duplicateBlock) {
    return {
      accepted: false,
      reason: "correction_duplicate_block",
      originalWords,
      correctedWords,
      ratio,
      unseenRatio,
      duplicateBlock,
    };
  }
  if (strictMode && originalWords > 0 && originalWords <= 6 && correctedWords > (originalWords + 8)) {
    return {
      accepted: false,
      reason: "correction_short_input_expansion_guard",
      originalWords,
      correctedWords,
      ratio,
      unseenRatio,
      duplicateBlock,
    };
  }
  if (strictMode && originalWords >= 8 && ratio > maxExpansionRatio) {
    return {
      accepted: false,
      reason: "correction_expansion_guard",
      originalWords,
      correctedWords,
      ratio,
      unseenRatio,
      duplicateBlock,
    };
  }
  if (strictMode && originalWords >= 10 && ratio > 1.05 && unseenRatio > 0.38) {
    return {
      accepted: false,
      reason: "correction_new_terms_guard",
      originalWords,
      correctedWords,
      ratio,
      unseenRatio,
      duplicateBlock,
    };
  }

  return {
    accepted: true,
    reason: "ok",
    originalWords,
    correctedWords,
    ratio,
    unseenRatio,
    duplicateBlock,
  };
}

function normalizeSpacing(text: string): string {
  return String(text ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function parseStoredSegments(value: unknown): TranscriptionSegment[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((segment) => {
      if (!segment || typeof segment !== "object") return null;
      const row = segment as Record<string, unknown>;
      const text = normalizeSpacing(String(row.text ?? ""));
      const start = typeof row.start === "number" ? row.start : Number.parseFloat(String(row.start ?? ""));
      const end = typeof row.end === "number" ? row.end : Number.parseFloat(String(row.end ?? ""));
      if (!text || !Number.isFinite(start) || !Number.isFinite(end)) return null;
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
  if (segments.length && normalizeForGuard(text) === normalizeForGuard(segments.map((segment) => segment.text).join(" "))) {
    const fromSegments = buildMessageBlocksFromSegments(segments).join("\n\n");
    if (fromSegments) return fromSegments;
  }
  return formatMessageText(text, buildMessageBlockTargets(segments));
}

function applyDomainTextNormalization(text: string, domainProfile: "none" | "imobiliario_marketing"): string {
  let t = String(text ?? "");
  if (domainProfile !== "imobiliario_marketing") return t;
  t = t.replace(/\bm\s*2\b/gi, "m²");
  t = t.replace(/\bmetros?\s+quadrados?\b/gi, "m²");
  t = t.replace(/\bmetragem\s+de\s+(\d+(?:[.,]\d+)?)\s*m2\b/gi, "metragem de $1 m²");
  t = t.replace(
    /\b(por|de|valor(?:\s+de)?|pre[çc]o(?:\s+de)?|custa|custando|sai\s+por|fica\s+em)\s+(\d+(?:[.,]\d+)?)\s+mil\b(?!\s*(?:reais|r\$))/gi,
    "$1 R$ $2 mil",
  );
  t = t.replace(/\b(\d+(?:[.,]\d+)?)\s+mil(?:\s+de)?\s+reais\b/gi, "R$ $1 mil");
  t = t.replace(/\b(\d+(?:[.,]\d+)?)\s+reais\b/gi, "R$ $1");
  t = t.replace(/R\$\s*R\$/gi, "R$");
  return t;
}

function normalizeStyle(v: unknown): CorrectionStyle {
  const s = String(v ?? "").trim().toLowerCase();
  if (s === "casual") return "casual";
  if (s === "formal") return "formal";
  return "neutro";
}

function normalizeFormatMode(v: unknown): "balanced" | "message" {
  const s = String(v ?? "").trim().toLowerCase();
  if (s === "message") return "message";
  return "balanced";
}

function normalizeDomainProfile(v: unknown): "none" | "imobiliario_marketing" {
  const s = String(v ?? "").trim().toLowerCase();
  if (s === "imobiliario_marketing") return "imobiliario_marketing";
  return "none";
}

async function resolveUserFromAccessToken(
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
      global: {
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      },
    });
    const { data, error } = await client.auth.getUser(accessToken);
    if (error || !data?.user) {
      return { user: null, error: error?.message || "user_not_found" };
    }
    const userId = String(data.user.id || "").trim();
    if (!userId) return { user: null, error: "auth_get_user_invalid_payload" };
    return { user: { id: userId }, error: null };
  } catch (err) {
    const msg = err instanceof Error ? err.message : "auth_get_user_exception";
    return { user: null, error: msg };
  }
}

function parseVersionTuple(value: string): number[] {
  const raw = String(value ?? "").trim().toLowerCase();
  const clean = raw.startsWith("v") ? raw.slice(1) : raw;
  const parts = clean.split(".").map((p) => Number.parseInt(p, 10));
  if (!parts.length || parts.some((n) => !Number.isFinite(n) || n < 0)) return [];
  return parts;
}

function isVersionLower(current: string, minimum: string): boolean {
  const c = parseVersionTuple(current);
  const m = parseVersionTuple(minimum);
  if (!c.length || !m.length) return true;
  const size = Math.max(c.length, m.length);
  for (let i = 0; i < size; i++) {
    const cv = c[i] ?? 0;
    const mv = m[i] ?? 0;
    if (cv < mv) return true;
    if (cv > mv) return false;
  }
  return false;
}

Deno.serve(async (req: Request) => {
  const requestId = (req.headers.get("x-request-id") ?? "").trim() || crypto.randomUUID();
  let authValidationStage = "init";
  const reqCorsHeaders = buildCorsHeaders(req);
  const respondJson = (body: unknown, status = 200): Response => jsonResponse(body, status, reqCorsHeaders);

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: reqCorsHeaders });
  }
  if (req.method !== "POST") {
    return respondJson({ error: "method_not_allowed" }, 405);
  }

  const appVersion = (req.headers.get("x-app-version") ?? "").trim();
  const minSupported = (Deno.env.get("MIN_SUPPORTED_APP_VERSION") ?? "").trim();
  const updateUrl = (Deno.env.get("APP_UPDATE_URL") ?? "").trim();

  if (!appVersion) {
    return respondJson(
      {
        error: "upgrade_required",
        code: "missing_app_version",
        message: "Atualização obrigatória para continuar.",
        min_supported_version: minSupported || null,
        update_url: updateUrl || null,
      },
      426,
    );
  }
  if (minSupported && isVersionLower(appVersion, minSupported)) {
    return respondJson(
      {
        error: "upgrade_required",
        code: "minimum_version_required",
        message: "Atualização obrigatória para continuar.",
        min_supported_version: minSupported,
        current_version: appVersion,
        update_url: updateUrl || null,
      },
      426,
    );
  }

  try {
    const supabaseUrl = Deno.env.get("EDGE_SUPABASE_URL") || requiredEnv("SUPABASE_URL");
    const supabaseAnonKey = Deno.env.get("EDGE_SUPABASE_ANON_KEY") || requiredEnv("SUPABASE_ANON_KEY");
    const serviceRoleKey =
      Deno.env.get("EDGE_SUPABASE_SERVICE_ROLE_KEY") ||
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ||
      Deno.env.get("SERVICE_ROLE_KEY") ||
      "";
    if (!serviceRoleKey) throw new Error("Missing env: SUPABASE_SERVICE_ROLE_KEY");
    const groqApiKey = requiredEnv("GROQ_API_KEY");

    const authHeader = req.headers.get("authorization") ?? "";
    if (!authHeader) {
      authValidationStage = "missing_authorization";
      console.warn(
        JSON.stringify({
          event: "postprocess_auth_validation",
          request_id: requestId,
          auth_validation_stage: authValidationStage,
        }),
      );
      return respondJson({ error: "missing_authorization", request_id: requestId }, 401);
    }

    const accessToken = authHeader.replace(/^Bearer\s+/i, "").trim();
    if (!accessToken) {
      authValidationStage = "missing_bearer_token";
      console.warn(
        JSON.stringify({
          event: "postprocess_auth_validation",
          request_id: requestId,
          auth_validation_stage: authValidationStage,
        }),
      );
      return respondJson({ error: "missing_authorization", request_id: requestId }, 401);
    }

    authValidationStage = "validating_user_jwt";
    const { user, error: userErrMsg } = await resolveUserFromAccessToken(
      supabaseUrl,
      supabaseAnonKey,
      accessToken,
    );
    if (!user) {
      authValidationStage = "invalid_session";
      console.warn(
        JSON.stringify({
          event: "postprocess_auth_validation",
          request_id: requestId,
          auth_validation_stage: authValidationStage,
          auth_error: userErrMsg ?? "unknown",
        }),
      );
      return respondJson({ error: "invalid_session", request_id: requestId }, 401);
    }
    authValidationStage = "authenticated";

    const supabaseAdmin = createClient(supabaseUrl, serviceRoleKey, {
      auth: { persistSession: false },
    });

    const body = (await req.json().catch(() => ({}))) as Record<string, unknown>;
    const transcriptionId = String(body.transcription_id ?? "").trim();
    if (!UUID_RE.test(transcriptionId)) {
      throw new HttpError("bad_request", "Campo 'transcription_id' inválido.", 400);
    }

    const correctionStyle = normalizeStyle(body.style);
    const formatMode = normalizeFormatMode(body.format_mode);
    const domainProfile = normalizeDomainProfile(body.domain_profile);

    const { data: row, error: rowErr } = await supabaseAdmin
      .from("transcriptions")
      .select("id,user_id,original_text,corrected_text,metadata")
      .eq("id", transcriptionId)
      .eq("user_id", user.id)
      .maybeSingle();
    if (rowErr) throw rowErr;
    if (!row) return respondJson({ error: "not_found" }, 404);

    const originalText = String((row as any).original_text ?? "").trim();
    const existingCorrected = String((row as any).corrected_text ?? "").trim();
    const baseMeta = (row as any).metadata && typeof (row as any).metadata === "object"
      ? ((row as any).metadata as Json)
      : {};

    if (existingCorrected) {
      return respondJson({
        ok: true,
        transcription_id: transcriptionId,
        corrected_text: existingCorrected,
        correction_pending: false,
        already_corrected: true,
        request_id: requestId,
      });
    }

    if (!originalText) {
      const mergedMeta = {
        ...baseMeta,
        correction_pending: false,
        correction_requested: true,
        correction_applied: false,
        correction_mode: "background",
        correction_error: "empty_original_text",
      };
      await supabaseAdmin
        .from("transcriptions")
        .update({ metadata: mergedMeta })
        .eq("id", transcriptionId)
        .eq("user_id", user.id);
      return respondJson({
        ok: true,
        transcription_id: transcriptionId,
        corrected_text: "",
        correction_pending: false,
        request_id: requestId,
      });
    }

    const styleInst = {
      neutro: "Adicione apenas pontuação e maiúsculas. NÃO mude palavras. NÃO adicione frases novas. NÃO invente conteúdo.",
      casual: "Corrija pontuação. Mantenha gírias. NÃO mude o conteúdo. NÃO adicione frases novas. NÃO invente conteúdo.",
      formal:
        "Reescreva em português formal e profissional. Remova gírias, vícios de linguagem e repetições. Preserve 100% do significado e fatos. NÃO invente conteúdo.",
    }[correctionStyle];
    const preserveTermsInst = "Preserve exatamente palavras em inglês, nomes de marcas, produtos, plataformas, siglas e nomes próprios. Nunca traduza ou substitua termos como Facebook, Instagram, WhatsApp, Meta, Google Ads, CRM, lead, briefing, call, dashboard, direct, story, feed e reels. Se um termo parecer ser inglês ou nome de marca, mantenha como está.";

    const formatInst = formatMode === "message"
      ? "Formate como mensagens curtas de chat, prontas para WhatsApp/Instagram. Quebre em blocos pequenos com linha em branco entre eles. Use uma nova quebra quando houver pausa natural, mudança de ideia, enumeração ou frase longa demais. Cada bloco deve ter 1-2 frases curtas e evitar um bloco único grande."
      : formatMode === "balanced"
        ? "Formate em parágrafos curtos e legíveis (1-3 frases por parágrafo). Quebre linha em mudança clara de assunto. Evite excesso de quebras."
        : "";

    const domainInst = domainProfile === "imobiliario_marketing"
      ? "No contexto imobiliário/marketing, aplique apenas normalizações objetivas: metros quadrados -> m² e valores em reais -> R$ quando houver contexto claro. Não invente informação."
      : "";

    const modelToUse =
      Deno.env.get("GROQ_CORRECTOR_MODEL_PRO")
      || Deno.env.get("GROQ_CORRECTOR_MODEL")
      || "llama-3.3-70b-versatile";
    const maxTokens = domainProfile === "imobiliario_marketing" ? 220 : 420;

    const corrStart = Date.now();
    const corrResp = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST",
      headers: { Authorization: `Bearer ${groqApiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        model: modelToUse,
        messages: [
          {
            role: "system",
            content: "Você corrige textos. Retorne SOMENTE o texto corrigido. Sem aspas. Sem explicação. Sem comentários.",
          },
          {
            role: "user",
            content: [styleInst, preserveTermsInst, formatInst, domainInst, `Texto: ${originalText}`].filter(Boolean).join("\n\n"),
          },
        ],
        temperature: 0.1,
        max_tokens: maxTokens,
      }),
    });
    const corrMs = Math.max(0, Date.now() - corrStart);

    if (!corrResp.ok) {
      const corrErrText = await corrResp.text().catch(() => "correction_error");
      const mergedMeta = {
        ...baseMeta,
        correction_pending: true,
        correction_requested: true,
        correction_applied: false,
        correction_mode: "background",
        correction_error: `groq_chat_http_${corrResp.status}`,
        correction_error_message: String(corrErrText || "").slice(0, 600),
        correction_model_used: modelToUse,
        correction_max_tokens_used: maxTokens,
      };
      await supabaseAdmin
        .from("transcriptions")
        .update({ metadata: mergedMeta })
        .eq("id", transcriptionId)
        .eq("user_id", user.id);
      return respondJson({ error: "correction_failed", request_id: requestId }, 502);
    }

    const corrPayload = (await corrResp.json().catch(() => ({}))) as Record<string, unknown>;
    const choices = Array.isArray(corrPayload.choices) ? corrPayload.choices : [];
    const raw = choices.length > 0 && choices[0] && typeof choices[0] === "object"
      ? String((choices[0] as Record<string, unknown>)?.message && typeof (choices[0] as any).message === "object"
        ? ((choices[0] as any).message?.content ?? "")
        : "")
      : "";
    const normalizedOriginalText =
      domainProfile === "imobiliario_marketing"
        ? applyDomainTextNormalization(originalText, domainProfile)
        : originalText;
    const domainNormalizationApplied = normalizedOriginalText !== originalText;
    const sttSegments = parseStoredSegments((baseMeta as Record<string, unknown>).stt_segments);

    let correctedText = applyDomainTextNormalization(stripOuterQuotes(raw), domainProfile);
    let correctionExpansionOutput = false;
    let correctionExpansionReason = "";
    let correctionWordRatio = 1;
    let correctionUnseenRatio = 0;
    if (correctedText) {
      const guard = evaluateCorrectionGuard(originalText, correctedText, correctionStyle);
      correctionWordRatio = guard.ratio;
      correctionUnseenRatio = guard.unseenRatio;
      if (!guard.accepted) {
        correctionExpansionOutput = true;
        correctionExpansionReason = guard.reason;
        correctedText = "";
      }
    }
    if (!correctedText && domainNormalizationApplied) {
      correctedText = normalizedOriginalText;
    }
    if (correctedText) {
      correctedText = applyOutputFormatting(correctedText, formatMode, sttSegments);
    }

    const mergedMeta = {
      ...baseMeta,
      correction_pending: false,
      correction_requested: true,
      correction_applied: Boolean(correctedText),
      correction_mode: "background",
      correction_style: correctionStyle,
      format_mode_applied: formatMode,
      domain_profile_applied: domainProfile,
      corrector_provider: "groq",
      corrector_model: modelToUse,
      correction_model_used: modelToUse,
      correction_max_tokens_used: maxTokens,
      correction_ms: corrMs,
      processing_version: "speed_tiers_v1",
      domain_normalization_applied: domainNormalizationApplied,
      correction_expansion_guard: correctionExpansionOutput,
      correction_expansion_reason: correctionExpansionReason || null,
      correction_expansion_ratio: correctionWordRatio,
      correction_expansion_unseen_ratio: correctionUnseenRatio,
      ...(correctionExpansionOutput ? { reason: correctionExpansionReason || "correction_expansion_guard" } : {}),
    };

    await supabaseAdmin
      .from("transcriptions")
      .update({
        corrected_text: correctedText || null,
        correction_style: correctedText ? correctionStyle : null,
        corrector_provider: correctedText ? "groq" : null,
        corrector_model: correctedText ? modelToUse : null,
        metadata: mergedMeta,
      })
      .eq("id", transcriptionId)
      .eq("user_id", user.id);

    return respondJson({
      ok: true,
      transcription_id: transcriptionId,
      corrected_text: correctedText,
      correction_pending: false,
      correction_ms: corrMs,
      request_id: requestId,
    });
  } catch (err) {
    if (err instanceof HttpError) {
      console.warn(
        JSON.stringify({
          event: "postprocess_error",
          request_id: requestId,
          auth_validation_stage: authValidationStage,
          error: err.code,
          message: err.message,
          status: err.status,
        }),
      );
      return respondJson({ error: err.code, message: err.message, request_id: requestId }, err.status);
    }
    const message = err instanceof Error ? err.message : "unknown_error";
    console.error(
      JSON.stringify({
        event: "postprocess_error",
        request_id: requestId,
        auth_validation_stage: authValidationStage,
        error: "internal_error",
        message,
      }),
    );
    return respondJson({ error: "internal_error", message, request_id: requestId }, 500);
  }
});
