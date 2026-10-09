// Supabase Edge Function: transcribe
//
// Goals:
// - Keep Groq API key server-side (never expose to desktop client)
// - Enforce user entitlement + daily usage limits
// - Persist transcription + audit + usage accounting in Postgres

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

type Json = Record<string, unknown>;

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

type SpeedTier = "trial" | "start" | "pro";
type CorrectionStyle = "neutro" | "casual" | "formal";

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

function envFlag(name: string, defaultValue = false): boolean {
  const v = String(Deno.env.get(name) ?? "").trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(v)) return true;
  if (["0", "false", "no", "off"].includes(v)) return false;
  return defaultValue;
}

function envPercent(name: string, defaultValue: number): number {
  const raw = String(Deno.env.get(name) ?? "").trim();
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n)) return Math.max(0, Math.min(100, defaultValue));
  return Math.max(0, Math.min(100, n));
}

function envFloat(name: string, defaultValue: number): number {
  const raw = String(Deno.env.get(name) ?? "").trim();
  const n = Number.parseFloat(raw);
  if (!Number.isFinite(n)) return defaultValue;
  return n;
}

function deterministicBucket(value: string): number {
  const s = String(value || "");
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h >>> 0) % 100;
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
  const parsed = raw.split(",").map((v) => v.trim()).filter(Boolean);
  return parsed.length ? parsed : DEFAULT_ALLOWED_ORIGINS;
}

function buildCorsHeaders(req: Request): Record<string, string> {
  const requestOrigin = (req.headers.get("origin") ?? "").trim();
  const allowedOrigins = getAllowedOrigins();

  if (allowedOrigins.includes("*")) {
    return { ...CORS_BASE_HEADERS, "Access-Control-Allow-Origin": "*" };
  }
  if (requestOrigin && (allowedOrigins.includes(requestOrigin) || requestOrigin.startsWith("chrome-extension://"))) {
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

function bytesToAscii(bytes: Uint8Array, start: number, len: number): string {
  return String.fromCharCode(...bytes.slice(start, start + len));
}

function wavDurationSeconds(bytes: Uint8Array): number {
  if (bytes.byteLength < 44) throw new Error("Arquivo WAV invalido (muito pequeno)");

  const riff = bytesToAscii(bytes, 0, 4);
  const wave = bytesToAscii(bytes, 8, 4);
  if (riff !== "RIFF" || wave !== "WAVE") {
    throw new Error("Formato nao suportado. Envie um WAV (RIFF/WAVE).");
  }

  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 12;

  let sampleRate = 0;
  let blockAlign = 0;
  let dataSize = 0;

  while (offset + 8 <= bytes.byteLength) {
    const chunkId = bytesToAscii(bytes, offset, 4);
    const chunkSize = view.getUint32(offset + 4, true);
    offset += 8;

    if (chunkId === "fmt ") {
      if (chunkSize < 16) throw new Error("WAV fmt chunk invalido");
      const audioFormat = view.getUint16(offset, true);
      const numChannels = view.getUint16(offset + 2, true);
      sampleRate = view.getUint32(offset + 4, true);
      blockAlign = view.getUint16(offset + 12, true);
      const bitsPerSample = view.getUint16(offset + 14, true);

      // 1 = PCM. We intentionally limit to PCM so duration calc is trustworthy.
      if (audioFormat !== 1) {
        throw new Error("WAV nao-PCM nao suportado (converta para PCM 16-bit).");
      }
      if (numChannels < 1 || sampleRate <= 0 || blockAlign <= 0 || bitsPerSample <= 0) {
        throw new Error("WAV header invalido");
      }
    } else if (chunkId === "data") {
      dataSize = chunkSize;
      break;
    }

    offset += chunkSize;
    if (chunkSize % 2 === 1) offset += 1; // word align
  }

  if (!sampleRate || !blockAlign || !dataSize) {
    throw new Error("WAV incompleto (chunks fmt/data nao encontrados).");
  }

  const seconds = dataSize / (sampleRate * blockAlign);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    throw new Error("Duracao WAV invalida.");
  }
  return Math.round(seconds * 100) / 100;
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

  // Guardrail for very short inputs: never allow large expansions/hallucination.
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

function toNumberOrNull(v: unknown): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string") {
    const n = Number.parseFloat(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function normalizeTier(v: unknown): SpeedTier {
  const s = String(v ?? "").trim().toLowerCase();
  if (s === "start") return "start";
  if (s === "pro") return "pro";
  return "trial";
}

function parseVersionTuple(value: string): number[] {
  const raw = String(value ?? "").trim().toLowerCase();
  const clean = raw.startsWith("v") ? raw.slice(1) : raw;
  const parts = clean.split(".").map((p) => Number.parseInt(p, 10));
  if (!parts.length || parts.some((n) => !Number.isFinite(n) || n < 0)) {
    return [];
  }
  return parts;
}

function isVersionLower(current: string, minimum: string): boolean {
  const c = parseVersionTuple(current);
  const m = parseVersionTuple(minimum);
  if (!c.length || !m.length) {
    return true;
  }
  const size = Math.max(c.length, m.length);
  for (let i = 0; i < size; i++) {
    const cv = c[i] ?? 0;
    const mv = m[i] ?? 0;
    if (cv < mv) return true;
    if (cv > mv) return false;
  }
  return false;
}

async function resolveTranscriptionTier(
  supabaseAdmin: ReturnType<typeof createClient>,
  userId: string,
  dailyLimitSeconds: number | null,
): Promise<ResolvedTier> {
  try {
    const { data, error } = await supabaseAdmin.rpc("resolve_transcription_tier", { p_user_id: userId });
    if (!error) {
      const row = Array.isArray(data) ? (data[0] as any) : (data as any);
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
    // Fallback below.
  }

  // Fallback when migration/RPC is not present yet.
  if (dailyLimitSeconds === null) {
    return { tier: "pro", planCode: "pro", entitlementSource: "fallback", dailyMinutesLimit: null };
  }
  if (Number(dailyLimitSeconds) >= 1800) {
    return { tier: "start", planCode: "start", entitlementSource: "fallback", dailyMinutesLimit: 30 };
  }
  return { tier: "trial", planCode: "trial", entitlementSource: "fallback", dailyMinutesLimit: 15 };
}

function base64ToBytes(b64: string): Uint8Array {
  // Support url-safe base64 too.
  const normalized = b64.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(normalized);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function normalizeUuid(v: unknown): string | undefined {
  if (v === null || v === undefined) return undefined;
  if (v instanceof File) return undefined;
  const s = String(v).trim();
  if (!s) return undefined;
  return UUID_RE.test(s) ? s : undefined;
}

async function readRequest(req: Request): Promise<{
  audioBytes: Uint8Array;
  language: string;
  model: string;
  correct: boolean;
  correctionStyle: CorrectionStyle;
  formatMode: "balanced" | "message";
  domainProfile: "none" | "imobiliario_marketing";
  correctorModel?: string;
  deviceId?: string;
  metadata?: Json;
}> {
  const ct = (req.headers.get("content-type") ?? "").toLowerCase();

  const parseBool = (v: unknown): boolean => {
    if (v === true || v === 1) return true;
    if (v === false || v === 0) return false;
    const s = String(v ?? "").trim().toLowerCase();
    return ["1", "true", "yes", "on"].includes(s);
  };

  const normalizeStyle = (v: unknown): CorrectionStyle => {
    const s = String(v ?? "").trim().toLowerCase();
    if (s === "casual") return "casual";
    if (s === "formal") return "formal";
    return "neutro";
  };

  const normalizeFormatMode = (v: unknown): "balanced" | "message" => {
    const s = String(v ?? "").trim().toLowerCase();
    if (s === "message") return "message";
    return "balanced";
  };

  const normalizeDomainProfile = (v: unknown): "none" | "imobiliario_marketing" => {
    const s = String(v ?? "").trim().toLowerCase();
    if (s === "imobiliario_marketing") return "imobiliario_marketing";
    return "none";
  };

  if (ct.includes("multipart/form-data") || ct.includes("application/x-www-form-urlencoded")) {
    const fd = await req.formData();
    const file = fd.get("file");
    if (!(file instanceof File)) {
      throw new HttpError("bad_request", "Campo 'file' ausente (multipart/form-data).", 400);
    }
    const audioBytes = new Uint8Array(await file.arrayBuffer());
    const language = String(fd.get("language") ?? "pt");
    const model = String(fd.get("model") ?? "whisper-large-v3-turbo");
    const correct = parseBool(fd.get("correct"));
    const correctionStyle = normalizeStyle(fd.get("correction_style"));
    const formatMode = normalizeFormatMode(fd.get("format_mode"));
    const domainProfile = normalizeDomainProfile(fd.get("domain_profile"));
    const correctorModel = fd.get("corrector_model") ? String(fd.get("corrector_model")) : undefined;
    const deviceId = normalizeUuid(fd.get("device_id"));

    let metadata: Json | undefined;
    const metadataRaw = fd.get("metadata");
    if (metadataRaw) {
      try {
        metadata = JSON.parse(String(metadataRaw));
      } catch {
        // ignore malformed metadata
      }
    }
    return { audioBytes, language, model, correct, correctionStyle, formatMode, domainProfile, correctorModel, deviceId, metadata };
  }

  if (ct.includes("application/json")) {
    const body = (await req.json().catch(() => ({}))) as Record<string, unknown>;
    const audioB64 = body.audio_wav_base64;
    if (typeof audioB64 !== "string" || !audioB64) {
      throw new HttpError("bad_request", "Campo 'audio_wav_base64' ausente (JSON).", 400);
    }
    let audioBytes: Uint8Array;
    try {
      audioBytes = base64ToBytes(audioB64);
    } catch {
      throw new HttpError("bad_request", "Base64 invalido em 'audio_wav_base64'.", 400);
    }
    const language = typeof body.language === "string" ? body.language : "pt";
    const model = typeof body.model === "string" ? body.model : "whisper-large-v3-turbo";
    const correct = parseBool(body.correct);
    const correctionStyle = normalizeStyle(body.correction_style);
    const formatMode = normalizeFormatMode(body.format_mode);
    const domainProfile = normalizeDomainProfile(body.domain_profile);
    const correctorModel = typeof body.corrector_model === "string" ? body.corrector_model : undefined;
    const deviceId = normalizeUuid(body.device_id);
    const metadata = typeof body.metadata === "object" && body.metadata ? (body.metadata as Json) : undefined;
    return { audioBytes, language, model, correct, correctionStyle, formatMode, domainProfile, correctorModel, deviceId, metadata };
  }

  throw new HttpError(
    "bad_request",
    "Content-Type nao suportado. Use multipart/form-data ou application/json.",
    400,
  );
}

async function safeAudit(
  supabaseAdmin: ReturnType<typeof createClient>,
  payload: { user_id: string; device_id?: string; action: string; resource: string; resource_id?: string; metadata?: Json },
): Promise<void> {
  try {
    await supabaseAdmin.from("audit_logs").insert({
      user_id: payload.user_id,
      device_id: payload.device_id ?? null,
      action: payload.action,
      resource: payload.resource,
      resource_id: payload.resource_id ?? null,
      metadata: payload.metadata ?? {},
    });
  } catch {
    // Audit must never break the main flow.
  }
}

function metadataString(meta: Json | undefined, key: string): string | undefined {
  const v = meta?.[key];
  if (typeof v !== "string") return undefined;
  const s = v.trim();
  return s ? s : undefined;
}

async function resolveOrRegisterDeviceId(
  supabaseAdmin: ReturnType<typeof createClient>,
  userId: string,
  requestedDeviceId: string | undefined,
  metadata: Json | undefined,
): Promise<string | undefined> {
  const deviceId = normalizeUuid(requestedDeviceId);
  if (!deviceId) return undefined;

  // Best-effort only: device tracking must never break transcriptions.
  try {
    const { data: existing, error: selErr } = await supabaseAdmin
      .from("user_devices")
      .select("id, user_id")
      .eq("id", deviceId)
      .maybeSingle();
    if (selErr) return undefined;

    const nowIso = new Date().toISOString();
    const appVersion = metadataString(metadata, "app_version");
    const platform = metadataString(metadata, "platform");
    const deviceName = metadataString(metadata, "device_name");

    if (existing) {
      // Prevent cross-user device id collisions from breaking the request.
      if (String((existing as any).user_id ?? "") !== userId) return undefined;

      // Touch last seen. Ignore errors.
      await supabaseAdmin
        .from("user_devices")
        .update({
          last_seen_at: nowIso,
          app_version: appVersion ?? null,
          platform: platform ?? null,
          device_name: deviceName ?? null,
        })
        .eq("id", deviceId);
      return deviceId;
    }

    const { error: insErr } = await supabaseAdmin.from("user_devices").insert({
      id: deviceId,
      user_id: userId,
      device_fingerprint: deviceId,
      app_version: appVersion ?? null,
      platform: platform ?? null,
      device_name: deviceName ?? null,
      last_seen_at: nowIso,
      is_active: true,
    });
    if (!insErr) return deviceId;

    // If a concurrent request registered the device, try to load it by fingerprint.
    const { data: byFingerprint } = await supabaseAdmin
      .from("user_devices")
      .select("id")
      .eq("user_id", userId)
      .eq("device_fingerprint", deviceId)
      .maybeSingle();
    const foundId = (byFingerprint as any)?.id;
    return typeof foundId === "string" ? foundId : undefined;
  } catch {
    return undefined;
  }
}

function stripOuterQuotes(text: string): string {
  const t = text.trim();
  if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) {
    return t.slice(1, -1).trim();
  }
  return t;
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
    if (!userId) {
      return { user: null, error: "auth_get_user_invalid_payload" };
    }
    return { user: { id: userId }, error: null };
  } catch (err) {
    const msg = err instanceof Error ? err.message : "auth_get_user_exception";
    return { user: null, error: msg };
  }
}

function applyDomainTextNormalization(text: string, domainProfile: "none" | "imobiliario_marketing"): string {
  let t = String(text ?? "");
  if (domainProfile !== "imobiliario_marketing") return t;

  // Unit normalization.
  t = t.replace(/\bm\s*2\b/gi, "m²");
  t = t.replace(/\bmetros?\s+quadrados?\b/gi, "m²");
  t = t.replace(/\bmetragem\s+de\s+(\d+(?:[.,]\d+)?)\s*m2\b/gi, "metragem de $1 m²");

  // Currency normalization (pt-BR).
  // "por 350 mil" / "custa 350 mil" -> "por R$ 350 mil"
  t = t.replace(
    /\b(por|de|valor(?:\s+de)?|pre[çc]o(?:\s+de)?|custa|custando|sai\s+por|fica\s+em)\s+(\d+(?:[.,]\d+)?)\s+mil\b(?!\s*(?:reais|r\$))/gi,
    "$1 R$ $2 mil",
  );
  t = t.replace(/\b(\d+(?:[.,]\d+)?)\s+mil(?:\s+de)?\s+reais\b/gi, "R$ $1 mil");
  t = t.replace(/\b(\d+(?:[.,]\d+)?)\s+reais\b/gi, "R$ $1");
  t = t.replace(/R\$\s*R\$/gi, "R$");
  return t;
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
  if (segments.length && normalizeForGuard(text) === normalizeForGuard(segments.map((segment) => segment.text).join(" "))) {
    const fromSegments = buildMessageBlocksFromSegments(segments).join("\n\n");
    if (fromSegments) return fromSegments;
  }
  return formatMessageText(text, buildMessageBlockTargets(segments));
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
    if (!serviceRoleKey) {
      throw new Error(
        "Missing env: SUPABASE_SERVICE_ROLE_KEY (padrao) ou SERVICE_ROLE_KEY (custom).",
      );
    }

    const groqApiKey = requiredEnv("GROQ_API_KEY");

    const authHeader = req.headers.get("authorization") ?? "";
    if (!authHeader) {
      authValidationStage = "missing_authorization";
      console.warn(
        JSON.stringify({
          event: "auth_validation",
          request_id: requestId,
          auth_validation_stage: authValidationStage,
        }),
      );
      return respondJson({ error: "missing_authorization", request_id: requestId }, 401);
    }
    // Validate user JWT explicitly (supabase-js server clients do not keep auth session state).
    const accessToken = authHeader.replace(/^Bearer\s+/i, "").trim();
    if (!accessToken) {
      authValidationStage = "missing_bearer_token";
      console.warn(
        JSON.stringify({
          event: "auth_validation",
          request_id: requestId,
          auth_validation_stage: authValidationStage,
        }),
      );
      return respondJson({ error: "missing_authorization", request_id: requestId }, 401);
    }

    // Validate JWT against Supabase Auth endpoint (more reliable than SDK session state in Edge runtime).
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
          event: "auth_validation",
          request_id: requestId,
          auth_validation_stage: authValidationStage,
          auth_error: userErrMsg ?? "unknown",
        }),
      );
      return respondJson({ error: "invalid_session", request_id: requestId }, 401);
    }
    authValidationStage = "authenticated";
    console.log(
      JSON.stringify({
        event: "auth_validation",
        request_id: requestId,
        auth_validation_stage: authValidationStage,
        user_id: user.id,
      }),
    );

    const supabaseAdmin = createClient(supabaseUrl, serviceRoleKey, {
      auth: { persistSession: false },
    });

    const {
      audioBytes,
      language,
      model,
      correct,
      correctionStyle,
      formatMode,
      domainProfile,
      correctorModel,
      deviceId: requestedDeviceId,
      metadata,
    } = await readRequest(req);
    const deviceId = await resolveOrRegisterDeviceId(supabaseAdmin, user.id, requestedDeviceId, metadata);
    if (audioBytes.byteLength > 20_000_000) {
      throw new HttpError("payload_too_large", "Audio muito grande (limite 20MB).", 413);
    }
    let audioDurationSeconds = 0;
    try {
      audioDurationSeconds = wavDurationSeconds(audioBytes);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Arquivo WAV invalido.";
      throw new HttpError("bad_request", msg, 400);
    }

    // 1) Entitlement / quota check (server-side).
    const { data: accessRows, error: accessErr } = await supabaseAdmin.rpc(
      "check_transcription_access",
      { p_user_id: user.id },
    );
    if (accessErr) {
      throw new Error(`check_transcription_access falhou: ${accessErr.message}`);
    }
    const access = Array.isArray(accessRows) ? (accessRows[0] as any) : (accessRows as any);
    const allowed = Boolean(access?.allowed);
    const dailyLimitSeconds = toNumberOrNull(access?.daily_limit_seconds);
    const usedTodaySeconds = toNumberOrNull(access?.used_today_seconds) ?? 0;
    const remainingSeconds = toNumberOrNull(access?.remaining_seconds);
    const monthlyLimitSeconds = toNumberOrNull(access?.monthly_limit_seconds);
    const usedMonthSeconds = toNumberOrNull(access?.used_month_seconds) ?? 0;
    const remainingMonthSeconds = toNumberOrNull(access?.remaining_month_seconds);
    const reason = String(access?.reason ?? "unknown");

    if (!allowed) {
      await safeAudit(supabaseAdmin, {
        user_id: user.id,
        device_id: deviceId,
        action: "transcribe_blocked",
        resource: "transcriptions",
        metadata: {
          reason,
          audio_duration_seconds: audioDurationSeconds,
          daily_limit_seconds: dailyLimitSeconds,
          used_today_seconds: usedTodaySeconds,
          remaining_seconds: remainingSeconds,
          monthly_limit_seconds: monthlyLimitSeconds,
          used_month_seconds: usedMonthSeconds,
          remaining_month_seconds: remainingMonthSeconds,
        },
      });
      return respondJson(
        {
          allowed: false,
          reason,
          usage: {
            daily_limit_seconds: dailyLimitSeconds,
            used_today_seconds: usedTodaySeconds,
            remaining_seconds: remainingSeconds,
            monthly_limit_seconds: monthlyLimitSeconds,
            used_month_seconds: usedMonthSeconds,
            remaining_month_seconds: remainingMonthSeconds,
          },
        },
        403,
      );
    }

    if (remainingSeconds !== null && audioDurationSeconds > remainingSeconds) {
      const denyReason = "daily_remaining_insufficient";
      await safeAudit(supabaseAdmin, {
        user_id: user.id,
        device_id: deviceId,
        action: "transcribe_blocked",
        resource: "transcriptions",
        metadata: {
          reason: denyReason,
          audio_duration_seconds: audioDurationSeconds,
          daily_limit_seconds: dailyLimitSeconds,
          used_today_seconds: usedTodaySeconds,
          remaining_seconds: remainingSeconds,
          monthly_limit_seconds: monthlyLimitSeconds,
          used_month_seconds: usedMonthSeconds,
          remaining_month_seconds: remainingMonthSeconds,
        },
      });
      return respondJson(
        {
          allowed: false,
          reason: denyReason,
          usage: {
            daily_limit_seconds: dailyLimitSeconds,
            used_today_seconds: usedTodaySeconds,
            remaining_seconds: remainingSeconds,
            monthly_limit_seconds: monthlyLimitSeconds,
            used_month_seconds: usedMonthSeconds,
            remaining_month_seconds: remainingMonthSeconds,
          },
        },
        403,
      );
    }

    if (remainingMonthSeconds !== null && audioDurationSeconds > remainingMonthSeconds) {
      const denyReason = "monthly_remaining_insufficient";
      await safeAudit(supabaseAdmin, {
        user_id: user.id,
        device_id: deviceId,
        action: "transcribe_blocked",
        resource: "transcriptions",
        metadata: {
          reason: denyReason,
          audio_duration_seconds: audioDurationSeconds,
          daily_limit_seconds: dailyLimitSeconds,
          used_today_seconds: usedTodaySeconds,
          remaining_seconds: remainingSeconds,
          monthly_limit_seconds: monthlyLimitSeconds,
          used_month_seconds: usedMonthSeconds,
          remaining_month_seconds: remainingMonthSeconds,
        },
      });
      return respondJson(
        {
          allowed: false,
          reason: denyReason,
          usage: {
            daily_limit_seconds: dailyLimitSeconds,
            used_today_seconds: usedTodaySeconds,
            remaining_seconds: remainingSeconds,
            monthly_limit_seconds: monthlyLimitSeconds,
            used_month_seconds: usedMonthSeconds,
            remaining_month_seconds: remainingMonthSeconds,
          },
        },
        403,
      );
    }

    const tierResolved = await resolveTranscriptionTier(supabaseAdmin, user.id, dailyLimitSeconds);
    const speedTierEnabled = isTierEnabledForUser(user.id, tierResolved.tier);

    const processingVersion = "speed_tiers_v1";
    const startedAtMs = Date.now();

    // 2) Call Groq (OpenAI-compatible) STT endpoint.
    const groqForm = new FormData();
    groqForm.append("file", new Blob([audioBytes], { type: "audio/wav" }), "audio.wav");
    groqForm.append("model", model);
    groqForm.append("language", language);
    groqForm.append("response_format", "verbose_json");
    groqForm.append("timestamp_granularities[]", "segment");
    groqForm.append("prompt", buildSttPrompt(language));

    const sttStartMs = Date.now();
    const groqResp = await fetch("https://api.groq.com/openai/v1/audio/transcriptions", {
      method: "POST",
      headers: { Authorization: `Bearer ${groqApiKey}` },
      body: groqForm,
    });
    const sttMs = Math.max(0, Date.now() - sttStartMs);

    let groqText = "";
    let groqErrorMessage: string | null = null;
    let sttSegments: TranscriptionSegment[] = [];
    if (groqResp.ok) {
      const payload = (await groqResp.json().catch(() => ({}))) as Record<string, unknown>;
      groqText = String(payload.text ?? "").trim();
      sttSegments = parseTranscriptionSegments(payload);
    } else {
      groqErrorMessage = await groqResp.text().catch(() => "groq_error");
    }

    const sttStatus = groqResp.ok ? (groqText ? "success" : "empty") : "error";
    const words = wordCount(groqText);

    // 2b) Optional correction (server-side) so clients don't need LLM keys.
    let correctedText: string | null = null;
    let correctionPending = false;
    let correctionMs: number | null = null;
    let correctionMode: "sync" | "background" | "off" = "off";
    let correctionMeta: Json = {};
    let correctionModelSelected: string | null = null;
    let correctionMaxTokensSelected: number | null = null;
    let correctionPromptCompact: boolean | null = null;
    if (correct && groqText) {
      // Check entitlement for correction (best-effort; never blocks transcription).
      let canCorrect = true;
      try {
        const { data: entRow, error: entErr } = await supabaseAdmin
          .from("user_entitlements")
          .select("can_correct")
          .eq("user_id", user.id)
          .maybeSingle();
        if (entErr) throw entErr;
        canCorrect = Boolean((entRow as any)?.can_correct);
      } catch {
        // If this check fails, we err on the safe side and skip correction.
        canCorrect = false;
      }

      if (!canCorrect) {
        correctionMode = "off";
        correctionMeta = {
          correction_requested: true,
          correction_applied: false,
          reason: "correction_disabled",
          correction_pending: false,
          correction_mode: "off",
          processing_version: processingVersion,
          format_mode_applied: formatMode,
          domain_profile_applied: domainProfile,
        };
      } else {
        const tier = tierResolved.tier;
        const syncCorrectionMaxAudioSeconds = Math.max(
          30,
          envFloat("SYNC_CORRECTION_MAX_AUDIO_SECONDS", 120),
        );
        const skipSyncByAudioLength = audioDurationSeconds >= syncCorrectionMaxAudioSeconds;
        // For PRO, keep max speed by default. But when user explicitly selects
        // "formal", prefer sync correction so the pasted text already comes formal.
        const useBackground = Boolean(
          speedTierEnabled && tier === "pro" && correctionStyle !== "formal",
        );
        if (useBackground) {
          const plannedModel =
            Deno.env.get("GROQ_CORRECTOR_MODEL_PRO")
            || Deno.env.get("GROQ_CORRECTOR_MODEL")
            || "llama-3.3-70b-versatile";
          correctionModelSelected = plannedModel;
          correctionMaxTokensSelected = domainProfile === "imobiliario_marketing" ? 220 : 420;
          correctionPromptCompact = false;
          correctionMode = "background";
          correctionPending = true;
          correctionMeta = {
            correction_requested: true,
            correction_applied: false,
            correction_pending: true,
            correction_mode: "background",
            correction_style: correctionStyle,
            format_mode_applied: formatMode,
            domain_profile_applied: domainProfile,
            jargon_pack_version: domainProfile === "imobiliario_marketing" ? "imob_mkt_v1" : "",
            correction_model_selected: correctionModelSelected,
            correction_max_tokens_selected: correctionMaxTokensSelected,
            correction_prompt_compact: correctionPromptCompact,
            processing_version: processingVersion,
          };
        } else if (skipSyncByAudioLength) {
          correctionModelSelected = null;
          correctionMaxTokensSelected = null;
          correctionPromptCompact = null;
          // Short-term safety: avoid sync correction on long audio to prevent
          // truncation/cutoff from LLM output token limits.
          correctionMode = "off";
          correctionMeta = {
            correction_requested: true,
            correction_applied: false,
            correction_pending: false,
            correction_mode: "off",
            reason: "correction_skipped_long_audio",
            audio_duration_seconds: audioDurationSeconds,
            sync_correction_max_audio_seconds: syncCorrectionMaxAudioSeconds,
            processing_version: processingVersion,
            format_mode_applied: formatMode,
            domain_profile_applied: domainProfile,
            correction_model_selected: correctionModelSelected,
            correction_max_tokens_selected: correctionMaxTokensSelected,
            correction_prompt_compact: correctionPromptCompact,
          };
        } else {
          correctionMode = "sync";
        const styleInst = {
          neutro: "Adicione apenas pontuação e maiúsculas. NÃO mude palavras. NÃO adicione frases novas. NÃO invente conteúdo.",
          casual: "Corrija pontuação. Mantenha gírias. NÃO mude o conteúdo. NÃO adicione frases novas. NÃO invente conteúdo.",
          formal:
            "Reescreva em português formal e profissional. Remova gírias, vícios de linguagem e repetições. Preserve 100% do significado e fatos. NÃO invente conteúdo. NÃO adicione frases novas. O texto corrigido deve ter tamanho SIMILAR ao original.",
        }[correctionStyle];
        const preserveTermsInst = "Preserve exatamente palavras em inglês, nomes de marcas, produtos, plataformas, siglas e nomes próprios. Nunca traduza ou substitua termos como Facebook, Instagram, WhatsApp, Meta, Google Ads, CRM, lead, briefing, call, dashboard, direct, story, feed e reels. Se um termo parecer ser inglês ou nome de marca, mantenha como está.";

        const compactPrompt = Boolean(
          (speedTierEnabled && tier === "start" && correctionStyle !== "formal") ||
            (domainProfile === "imobiliario_marketing" && correctionStyle !== "formal"),
        );
        const formatInst = formatMode === "message"
          ? (compactPrompt
            ? "Formate como mensagens curtas de chat. Quebre em blocos pequenos com linha em branco entre eles. Use uma nova quebra quando houver pausa natural, mudança de ideia ou frase longa demais. Cada bloco deve ter 1-2 frases curtas."
            : "Formate como mensagens curtas de chat, prontas para WhatsApp/Instagram. Quebre em blocos pequenos com linha em branco entre eles. Use uma nova quebra quando houver pausa natural, mudança de ideia, enumeração ou frase longa demais. Cada bloco deve ter 1-2 frases curtas e evitar um bloco único grande.")
          : formatMode === "balanced"
            ? (compactPrompt
              ? "Apenas melhore pontuação e organização em no máximo 2 parágrafos curtos."
              : "Formate em parágrafos curtos e legíveis (1-3 frases por parágrafo). Quebre linha em mudança clara de assunto. Evite excesso de quebras.")
            : "";

        const domainInst = domainProfile === "imobiliario_marketing"
          ? (compactPrompt
            ? "No contexto imobiliário/marketing, aplique apenas normalizações objetivas: metros quadrados -> m² e valores em reais -> R$ quando houver contexto claro."
            : "Se houver contexto claro, prefira termos de imobiliário e marketing: m², metragem, planta, lançamento, captação, lead, campanha, anúncio, CPL, tráfego pago, funil e conversão. Normalizações permitidas: 'metro(s) quadrado(s)' -> 'm²'; valores em reais podem usar 'R$' (ex.: 450 mil reais -> R$ 450 mil). Não force substituição sem contexto.")
          : "";

        const defaultModel =
          Deno.env.get("GROQ_CORRECTOR_MODEL") || "llama-3.3-70b-versatile";
        const startFastModel =
          Deno.env.get("GROQ_CORRECTOR_MODEL_START") || "llama-3.1-8b-instant";
        const proFastModel =
          Deno.env.get("GROQ_CORRECTOR_MODEL_PRO") || startFastModel;
        const trialModel =
          Deno.env.get("GROQ_CORRECTOR_MODEL_TRIAL") || defaultModel;

        let modelToUse = correctorModel || defaultModel;
        let maxTokens = compactPrompt ? 180 : 420;

        // Enforce speed tiers on sync correction path.
        if (speedTierEnabled) {
          if (tier === "start") {
            modelToUse = startFastModel;
            maxTokens = correctionStyle === "formal" ? 220 : 180;
          } else if (tier === "pro") {
            // PRO on non-formal usually runs background. For formal (sync path),
            // keep fast model for low latency.
            modelToUse = proFastModel;
            maxTokens = correctionStyle === "formal" ? 220 : 180;
          } else {
            // trial
            modelToUse = trialModel;
            maxTokens = correctionStyle === "formal" ? 380 : 320;
          }
        }
        correctionModelSelected = modelToUse;
        correctionMaxTokensSelected = maxTokens;
        correctionPromptCompact = compactPrompt;

        const corrStartMs = Date.now();
        const corrResp = await fetch("https://api.groq.com/openai/v1/chat/completions", {
          method: "POST",
          headers: { Authorization: `Bearer ${groqApiKey}`, "Content-Type": "application/json" },
          body: JSON.stringify({
            model: modelToUse,
            messages: [
              {
                role: "system",
                content:
                  "Você corrige textos. Retorne SOMENTE o texto corrigido. Sem aspas. Sem explicação. Sem comentários.",
              },
              {
                role: "user",
                content: [styleInst, preserveTermsInst, formatInst, domainInst, `Texto: ${groqText}`].filter(Boolean).join("\n\n"),
              },
            ],
            temperature: 0.1,
            max_tokens: maxTokens,
          }),
        });
          correctionMs = Math.max(0, Date.now() - corrStartMs);

        if (corrResp.ok) {
          const corrPayload = (await corrResp.json().catch(() => ({}))) as any;
          const c = stripOuterQuotes(String(corrPayload?.choices?.[0]?.message?.content ?? ""));
          correctedText = c ? applyDomainTextNormalization(c, domainProfile) : null;

          // Guardrail 1: if sync correction returns a much shorter text than STT,
          // keep original STT output to avoid losing user content.
          let correctionShortOutput = false;
          let correctionExpansionOutput = false;
          let correctionExpansionReason = "";
          let originalWords = 0;
          let correctedWords = 0;
          let correctionWordRatio = 1;
          let correctionUnseenRatio = 0;
          if (correctedText) {
            originalWords = wordCount(groqText);
            correctedWords = wordCount(correctedText);
            if (originalWords >= 40 && correctedWords > 0 && correctedWords < Math.floor(originalWords * 0.6)) {
              correctionShortOutput = true;
              correctedText = null;
            }
            if (correctedText) {
              const guard = evaluateCorrectionGuard(groqText, correctedText, correctionStyle);
              correctionWordRatio = guard.ratio;
              correctionUnseenRatio = guard.unseenRatio;
              if (!guard.accepted) {
                correctionExpansionOutput = true;
                correctionExpansionReason = guard.reason;
                correctedText = null;
              }
            }
          }

          correctionMeta = {
            correction_requested: true,
            correction_applied: Boolean(correctedText),
            correction_pending: false,
            correction_mode: "sync",
            correction_style: correctionStyle,
            format_mode_applied: formatMode,
            domain_profile_applied: domainProfile,
            jargon_pack_version: domainProfile === "imobiliario_marketing" ? "imob_mkt_v1" : "",
            corrector_provider: "groq",
            corrector_model: modelToUse,
            correction_model_selected: correctionModelSelected,
            correction_max_tokens_selected: correctionMaxTokensSelected,
            correction_prompt_compact: correctionPromptCompact,
            correction_ms: correctionMs,
            processing_version: processingVersion,
            correction_short_output_guard: correctionShortOutput,
            correction_short_output_original_words: originalWords,
            correction_short_output_corrected_words: correctedWords,
            correction_expansion_guard: correctionExpansionOutput,
            correction_expansion_reason: correctionExpansionReason || null,
            correction_expansion_ratio: correctionWordRatio,
            correction_expansion_unseen_ratio: correctionUnseenRatio,
            ...(correctionShortOutput ? { reason: "correction_output_too_short" } : {}),
            ...(correctionExpansionOutput ? { reason: correctionExpansionReason || "correction_expansion_guard" } : {}),
          };
        } else {
          const corrErrText = await corrResp.text().catch(() => "correction_error");
          correctionMeta = {
            correction_requested: true,
            correction_applied: false,
            correction_pending: false,
            correction_mode: "sync",
            correction_style: correctionStyle,
            format_mode_applied: formatMode,
            domain_profile_applied: domainProfile,
            jargon_pack_version: domainProfile === "imobiliario_marketing" ? "imob_mkt_v1" : "",
            corrector_provider: "groq",
            corrector_model: modelToUse,
            correction_model_selected: correctionModelSelected,
            correction_max_tokens_selected: correctionMaxTokensSelected,
            correction_prompt_compact: correctionPromptCompact,
            error_code: `groq_chat_http_${corrResp.status}`,
            error_message: corrErrText,
            correction_ms: correctionMs,
            processing_version: processingVersion,
          };
        }
        }
      }
    }

    const totalMs = Math.max(0, Date.now() - startedAtMs);

    const normalizedOriginalText =
      domainProfile === "imobiliario_marketing"
        ? applyDomainTextNormalization(groqText || "", domainProfile)
        : (groqText || "");
    const domainNormalizationApplied = normalizedOriginalText !== (groqText || "");

    // If LLM correction is unavailable/rejected, still apply deterministic domain normalization.
    const finalCorrectedText = correctedText
      ? applyOutputFormatting(correctedText, formatMode, sttSegments)
      : (domainNormalizationApplied ? applyOutputFormatting(normalizedOriginalText, formatMode, sttSegments) : null);
    const textToPaste = finalCorrectedText || applyOutputFormatting(normalizedOriginalText, formatMode, sttSegments) || "";

    // 3) Persist transcription.
    const insertPayload = {
      user_id: user.id,
      device_id: deviceId ?? null,
      audio_duration_seconds: audioDurationSeconds,
      original_text: groqText || "",
      corrected_text: finalCorrectedText,
      correction_style: correctedText ? correctionStyle : null,
      language,
      stt_provider: "groq",
      stt_model: model,
      corrector_provider: correctedText ? "groq" : null,
      corrector_model: correctedText
        ? (correctorModel || Deno.env.get("GROQ_CORRECTOR_MODEL") || "llama-3.3-70b-versatile")
        : null,
      status: sttStatus,
      error_code: groqResp.ok ? null : `groq_http_${groqResp.status}`,
      error_message: groqResp.ok ? null : groqErrorMessage,
      metadata: {
        ...(metadata ?? {}),
        groq_status: groqResp.status,
        groq_request_id: groqResp.headers.get("x-request-id"),
        tier_applied: tierResolved.tier,
        plan_code_applied: tierResolved.planCode || "",
        entitlement_source_applied: tierResolved.entitlementSource || "",
        speed_tier_enabled: speedTierEnabled,
        correction_mode: correctionMode,
        correction_pending: correctionPending,
        correction_requested: Boolean(correct),
        correction_style_requested: correct ? correctionStyle : null,
        format_mode_requested: formatMode,
        domain_profile_requested: domainProfile,
        correction_model_selected: correctionModelSelected,
        correction_max_tokens_selected: correctionMaxTokensSelected,
        correction_prompt_compact: correctionPromptCompact,
        stt_ms: sttMs,
        stt_segments: sttSegments,
        correction_ms: correctionMs,
        total_ms: totalMs,
        processing_version: processingVersion,
        domain_normalization_applied: domainNormalizationApplied,
        ...(correctionMeta ?? {}),
      },
    };

    const { data: inserted, error: insertErr } = await supabaseAdmin
      .from("transcriptions")
      .insert(insertPayload)
      .select("id, created_at, status, word_count")
      .single();
    if (insertErr) {
      throw new Error(`insert transcriptions falhou: ${insertErr.message}`);
    }

    // 4) Usage accounting (backend-only, service role). We count usage even if Groq returned error,
    // because the provider may still have billed the request.
    const { data: usageRow, error: usageErr } = await supabaseAdmin.rpc("register_transcription_usage", {
      p_audio_seconds: audioDurationSeconds,
      p_words_count: words,
      p_transcriptions_count: 1,
      p_user_id: user.id,
    });
    if (usageErr) {
      throw new Error(`register_transcription_usage falhou: ${usageErr.message}`);
    }

    const usage = Array.isArray(usageRow) ? (usageRow[0] as any) : (usageRow as any);
    const usedAfter = toNumberOrNull(usage?.audio_seconds) ?? usedTodaySeconds;
    const remainingAfter =
      dailyLimitSeconds === null ? null : Math.max(dailyLimitSeconds - usedAfter, 0);
    const usedMonthAfter = usedMonthSeconds + audioDurationSeconds;
    const remainingMonthAfter =
      monthlyLimitSeconds === null ? null : Math.max(monthlyLimitSeconds - usedMonthAfter, 0);

    await safeAudit(supabaseAdmin, {
      user_id: user.id,
      device_id: deviceId,
      action: "transcribe",
      resource: "transcriptions",
      resource_id: inserted.id,
      metadata: {
        status: sttStatus,
        audio_duration_seconds: audioDurationSeconds,
        words_count: words,
        daily_limit_seconds: dailyLimitSeconds,
        used_today_seconds: usedAfter,
        remaining_seconds: remainingAfter,
        monthly_limit_seconds: monthlyLimitSeconds,
        used_month_seconds: usedMonthAfter,
        remaining_month_seconds: remainingMonthAfter,
        tier_applied: tierResolved.tier,
        correction_mode: correctionMode,
        stt_ms: sttMs,
        correction_ms: correctionMs,
        total_ms: totalMs,
      },
    });

    return respondJson({
      transcription: {
        id: inserted.id,
        created_at: inserted.created_at,
        status: inserted.status,
        audio_duration_seconds: audioDurationSeconds,
        original_text: groqText,
        corrected_text: finalCorrectedText,
        correction_pending: correctionPending,
        text_to_paste: textToPaste,
        correction_style: correctedText ? correctionStyle : null,
        word_count: inserted.word_count,
        language,
        stt_provider: "groq",
        stt_model: model,
      },
      processing: {
        tier: tierResolved.tier,
        correction_mode: correctionMode,
        speed_tier_enabled: speedTierEnabled,
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
    });
  } catch (err) {
    if (err instanceof HttpError) {
      console.warn(
        JSON.stringify({
          event: "transcribe_error",
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
        event: "transcribe_error",
        request_id: requestId,
        auth_validation_stage: authValidationStage,
        error: "internal_error",
        message,
      }),
    );
    return respondJson({ error: "internal_error", message, request_id: requestId }, 500);
  }
});
