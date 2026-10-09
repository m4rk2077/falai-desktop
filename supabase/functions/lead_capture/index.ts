// Supabase Edge Function: lead_capture
// Receives signed lead payloads from website backend and stores canonical leads/events.

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
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-falai-signature, x-falai-timestamp, x-falai-key-id",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Vary": "Origin",
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const KEY_ID_RE = /^[a-zA-Z0-9_-]{1,40}$/;

class HttpError extends Error {
  status: number;
  code: string;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
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

function requiredEnvAny(names: string[]): string {
  for (const name of names) {
    const v = Deno.env.get(name);
    if (v && String(v).trim()) return String(v).trim();
  }
  throw new Error(`Missing env: one of [${names.join(", ")}]`);
}

function sanitizeText(value: unknown, maxLen: number): string {
  const s = String(value ?? "").trim();
  if (!s) return "";
  return s.slice(0, maxLen);
}

function normalizeEmail(value: unknown): string {
  return sanitizeText(value, 320).toLowerCase();
}

function normalizePhone(value: unknown): string {
  const raw = String(value ?? "");
  const digits = raw.replace(/\D+/g, "");
  if (!digits) return "";
  if (digits.startsWith("55") && digits.length >= 12) return digits;
  if (digits.length >= 10 && digits.length <= 11) return `55${digits}`;
  return digits.slice(0, 20);
}

function firstIpFromHeaders(req: Request): string {
  const xff = (req.headers.get("x-forwarded-for") ?? "").trim();
  if (xff) return xff.split(",")[0].trim();
  const xri = (req.headers.get("x-real-ip") ?? "").trim();
  if (xri) return xri;
  return "";
}

async function sha256Hex(value: string): Promise<string> {
  const data = new TextEncoder().encode(value);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(hash)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function hmacSha256Hex(secret: string, message: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signed = await crypto.subtle.sign("HMAC", key, enc.encode(message));
  return Array.from(new Uint8Array(signed)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function hexToBytes(hex: string): Uint8Array {
  const s = (hex || "").trim().toLowerCase();
  if (!/^[0-9a-f]+$/.test(s) || s.length % 2 === 1) return new Uint8Array();
  const out = new Uint8Array(s.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = Number.parseInt(s.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

function timingSafeEqualHex(a: string, b: string): boolean {
  const aa = hexToBytes(a);
  const bb = hexToBytes(b);
  if (!aa.length || aa.length !== bb.length) return false;
  let diff = 0;
  for (let i = 0; i < aa.length; i++) diff |= aa[i] ^ bb[i];
  return diff === 0;
}

function parseJsonObject(rawBody: string): Json {
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawBody);
  } catch {
    throw new HttpError("invalid_payload", "Body JSON invalido.", 400);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new HttpError("invalid_payload", "Body precisa ser um objeto JSON.", 400);
  }
  return parsed as Json;
}

function validateTimestamp(headerValue: string): number {
  const raw = String(headerValue ?? "").trim();
  const ts = Number.parseInt(raw, 10);
  if (!Number.isFinite(ts) || ts <= 0) {
    throw new HttpError("invalid_signature", "Timestamp invalido.", 401);
  }
  const now = Math.floor(Date.now() / 1000);
  const drift = Math.abs(now - ts);
  if (drift > 300) {
    throw new HttpError("replay_window", "Timestamp fora da janela permitida.", 401);
  }
  return ts;
}

function cleanSignature(raw: string): string {
  const s = String(raw ?? "").trim().toLowerCase();
  if (!s) return "";
  if (s.startsWith("sha256=")) return s.slice(7);
  return s;
}

function leadWebhookSecretFromKeyId(keyId: string): string {
  const candidates = [
    `LEAD_WEBHOOK_SECRET_${keyId}`,
    `LEAD_WEBHOOK_SECRET_${keyId.toUpperCase()}`,
  ];
  const secret = requiredEnvAny(candidates);
  return secret;
}

function parseMeta(v: unknown): Json {
  if (!v || typeof v !== "object" || Array.isArray(v)) return {};
  return v as Json;
}

Deno.serve(async (req) => {
  const corsHeaders = buildCorsHeaders(req);

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  if (req.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed", message: "Use POST." }, 405, corsHeaders);
  }

  try {
    const keyId = sanitizeText(req.headers.get("x-falai-key-id") ?? "", 40);
    if (!KEY_ID_RE.test(keyId)) {
      throw new HttpError("invalid_signature", "Key ID invalido.", 401);
    }

    const activeKeyId = sanitizeText(requiredEnvAny(["LEAD_ACTIVE_KEY_ID"]), 40);
    if (keyId !== activeKeyId) {
      throw new HttpError("invalid_signature", "Key ID nao autorizado.", 401);
    }

    const signature = cleanSignature(req.headers.get("x-falai-signature") ?? "");
    if (!signature) {
      throw new HttpError("invalid_signature", "Assinatura ausente.", 401);
    }

    const ts = validateTimestamp(req.headers.get("x-falai-timestamp") ?? "");

    const rawBody = await req.text();
    if (!rawBody || rawBody.length > 64_000) {
      throw new HttpError("invalid_payload", "Payload ausente ou muito grande.", 400);
    }

    const secret = leadWebhookSecretFromKeyId(keyId);
    const expectedSignature = await hmacSha256Hex(secret, `${ts}.${rawBody}`);
    if (!timingSafeEqualHex(expectedSignature, signature)) {
      throw new HttpError("invalid_signature", "Assinatura invalida.", 401);
    }

    const body = parseJsonObject(rawBody);

    const idempotencyKey = sanitizeText(body.idempotency_key, 64).toLowerCase();
    if (!UUID_RE.test(idempotencyKey)) {
      throw new HttpError("invalid_payload", "idempotency_key invalido (uuid esperado).", 422);
    }

    const nome = sanitizeText(body.nome, 160);
    const email = sanitizeText(body.email, 320);
    if (!nome) {
      throw new HttpError("invalid_payload", "Campo 'nome' e obrigatorio.", 422);
    }
    if (!email) {
      throw new HttpError("invalid_payload", "Campo 'email' e obrigatorio.", 422);
    }

    const emailNormalized = normalizeEmail(email);
    const whatsapp = sanitizeText(body.whatsapp, 40);
    const whatsappNormalized = normalizePhone(whatsapp);
    const motivo = sanitizeText(body.motivo, 500);
    const origemForm = sanitizeText(body.origem_form, 80) || "lp_beta_v1";

    const utmSource = sanitizeText(body.utm_source, 120);
    const utmMedium = sanitizeText(body.utm_medium, 120);
    const utmCampaign = sanitizeText(body.utm_campaign, 200);
    const utmContent = sanitizeText(body.utm_content, 200);
    const utmTerm = sanitizeText(body.utm_term, 200);
    const fbclid = sanitizeText(body.fbclid, 250);
    const gclid = sanitizeText(body.gclid, 250);

    const landingVariant = sanitizeText(body.landing_variant, 80);
    const referrer = sanitizeText(body.referrer, 1000);
    const pagePath = sanitizeText(body.page_path, 500);

    const userAgent = sanitizeText(req.headers.get("user-agent") ?? body.user_agent, 1000);
    const clientIp = firstIpFromHeaders(req);
    const ipHash = clientIp ? await sha256Hex(clientIp) : "";

    const meta = parseMeta(body.meta);
    const consentVersion = sanitizeText((meta.consent_version ?? body.consent_version) as unknown, 60);
    const consentAt = sanitizeText((meta.consent_at ?? body.consent_at) as unknown, 60) || new Date().toISOString();

    const sourcePayload: Json = {
      idempotency_key: idempotencyKey,
      key_id: keyId,
      received_at: new Date().toISOString(),
      request_timestamp: ts,
      consent_version: consentVersion || null,
      consent_at: consentAt,
      meta,
    };

    const supabaseUrl = requiredEnvAny(["EDGE_SUPABASE_URL", "SUPABASE_URL"]);
    const serviceRoleKey = requiredEnvAny([
      "EDGE_SUPABASE_SERVICE_ROLE_KEY",
      "SERVICE_ROLE_KEY",
      "SUPABASE_SERVICE_ROLE_KEY",
    ]);

    const supabaseAdmin = createClient(supabaseUrl, serviceRoleKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });

    // Idempotency/replay guard (exact same idempotency key).
    const { data: replayEvent, error: replayError } = await supabaseAdmin
      .from("lead_events")
      .select("lead_id")
      .eq("event_name", "lead_submit")
      .eq("event_payload->>idempotency_key", idempotencyKey)
      .limit(1)
      .maybeSingle();

    if (replayError) {
      console.warn("lead_capture replay check warning", replayError);
    }
    if (replayEvent?.lead_id) {
      return jsonResponse({ ok: true, lead_id: replayEvent.lead_id, status: "updated", replay: true }, 200, corsHeaders);
    }

    const nowIso = new Date().toISOString();
    let leadId = "";
    let status: "created" | "updated" = "created";

    const { data: existingLead, error: existingLeadError } = await supabaseAdmin
      .from("leads_beta")
      .select("id, submit_count, origem_form, status")
      .eq("email_normalized", emailNormalized)
      .limit(1)
      .maybeSingle();

    if (existingLeadError) {
      throw new HttpError("internal_error", `Erro ao consultar lead existente: ${existingLeadError.message}`, 500);
    }

    if (existingLead?.id) {
      status = "updated";
      const submitCount = Math.max(Number(existingLead.submit_count ?? 1), 1) + 1;
      const { data: updatedLead, error: updateErr } = await supabaseAdmin
        .from("leads_beta")
        .update({
          nome,
          email,
          whatsapp: whatsapp || null,
          whatsapp_normalized: whatsappNormalized || null,
          motivo: motivo || null,
          origem_form: origemForm || existingLead.origem_form,
          utm_source: utmSource || null,
          utm_medium: utmMedium || null,
          utm_campaign: utmCampaign || null,
          utm_content: utmContent || null,
          utm_term: utmTerm || null,
          fbclid: fbclid || null,
          gclid: gclid || null,
          landing_variant: landingVariant || null,
          referrer: referrer || null,
          page_path: pagePath || null,
          ip_hash: ipHash || null,
          user_agent: userAgent || null,
          source_payload: sourcePayload,
          last_seen_at: nowIso,
          submit_count: submitCount,
        })
        .eq("id", existingLead.id)
        .select("id")
        .single();

      if (updateErr) {
        throw new HttpError("internal_error", `Erro ao atualizar lead: ${updateErr.message}`, 500);
      }
      leadId = String(updatedLead.id);
    } else {
      const { data: insertedLead, error: insertErr } = await supabaseAdmin
        .from("leads_beta")
        .insert({
          nome,
          email,
          email_normalized: emailNormalized,
          whatsapp: whatsapp || null,
          whatsapp_normalized: whatsappNormalized || null,
          motivo: motivo || null,
          origem_form: origemForm,
          utm_source: utmSource || null,
          utm_medium: utmMedium || null,
          utm_campaign: utmCampaign || null,
          utm_content: utmContent || null,
          utm_term: utmTerm || null,
          fbclid: fbclid || null,
          gclid: gclid || null,
          landing_variant: landingVariant || null,
          referrer: referrer || null,
          page_path: pagePath || null,
          ip_hash: ipHash || null,
          user_agent: userAgent || null,
          source_payload: sourcePayload,
          first_seen_at: nowIso,
          last_seen_at: nowIso,
          submit_count: 1,
        })
        .select("id")
        .single();

      if (insertErr) {
        throw new HttpError("internal_error", `Erro ao inserir lead: ${insertErr.message}`, 500);
      }
      leadId = String(insertedLead.id);
      status = "created";
    }

    const leadEventPayload: Json = {
      idempotency_key: idempotencyKey,
      origem_form: origemForm,
      landing_variant: landingVariant || null,
      utm_source: utmSource || null,
      utm_medium: utmMedium || null,
      utm_campaign: utmCampaign || null,
      utm_content: utmContent || null,
      utm_term: utmTerm || null,
      fbclid: fbclid || null,
      gclid: gclid || null,
      consent_version: consentVersion || null,
      consent_at: consentAt || null,
      page_path: pagePath || null,
      referrer: referrer || null,
    };

    const { error: eventErr } = await supabaseAdmin
      .from("lead_events")
      .insert({
        lead_id: leadId,
        event_name: "lead_submit",
        event_source: "edge",
        event_payload: leadEventPayload,
      });

    if (eventErr) {
      // In race conditions (same idempotency key), treat unique violation as replay success.
      if (String(eventErr.code ?? "") === "23505") {
        return jsonResponse({ ok: true, lead_id: leadId, status: "updated", replay: true }, 200, corsHeaders);
      }
      throw new HttpError("internal_error", `Erro ao inserir evento: ${eventErr.message}`, 500);
    }

    return jsonResponse({ ok: true, lead_id: leadId, status }, 200, corsHeaders);
  } catch (err) {
    if (err instanceof HttpError) {
      return jsonResponse({ error: err.code, message: err.message }, err.status, corsHeaders);
    }

    const message = err instanceof Error ? err.message : "Erro interno";
    console.error("lead_capture unhandled", message);
    return jsonResponse({ error: "internal_error", message: "Erro interno." }, 500, corsHeaders);
  }
});
