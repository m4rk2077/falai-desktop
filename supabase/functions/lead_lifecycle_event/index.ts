import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

type Json = Record<string, unknown>;

const ALLOWED_EVENTS = new Set([
  "first_login",
  "first_transcription_detected",
  "trial_expired_seen",
]);

class HttpError extends Error {
  status: number;
  code: string;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

function requiredEnv(name: string): string {
  const value = String(Deno.env.get(name) ?? "").trim();
  if (!value) throw new Error(`Missing env: ${name}`);
  return value;
}

function requiredEnvAny(names: string[]): string {
  for (const name of names) {
    const value = String(Deno.env.get(name) ?? "").trim();
    if (value) return value;
  }
  throw new Error(`Missing env: one of [${names.join(", ")}]`);
}

function sanitizeText(value: unknown, maxLen: number): string {
  return String(value ?? "").trim().slice(0, maxLen);
}

function nowIso(): string {
  return new Date().toISOString();
}

function maybeJson(value: unknown): Json {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Json : {};
}

function normalizeEventName(value: unknown): string {
  const name = sanitizeText(value, 80).toLowerCase();
  if (!ALLOWED_EVENTS.has(name)) {
    throw new HttpError("invalid_payload", "event_name invalido.", 422);
  }
  return name;
}

async function resolveUserIdFromJwt(
  supabaseUrl: string,
  anonKey: string,
  accessToken: string,
): Promise<string> {
  const client = createClient(supabaseUrl, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
    global: {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    },
  });
  const { data, error } = await client.auth.getUser(accessToken);
  if (error || !data?.user?.id) {
    throw new HttpError("unauthorized", "Sessao invalida.", 401);
  }
  return String(data.user.id).trim();
}

async function findLeadByUser(
  supabaseAdmin: ReturnType<typeof createClient>,
  userId: string,
): Promise<any | null> {
  const { data, error } = await supabaseAdmin
    .from("leads_beta")
    .select("id,status,first_login_at,first_transcription_at,trial_started_at,trial_ends_at,converted_at,auth_user_id")
    .eq("auth_user_id", userId)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw error;
  return data ?? null;
}

async function eventAlreadyExists(
  supabaseAdmin: ReturnType<typeof createClient>,
  leadId: string,
  eventName: string,
): Promise<boolean> {
  const { data, error } = await supabaseAdmin
    .from("lead_events")
    .select("id")
    .eq("lead_id", leadId)
    .eq("event_name", eventName)
    .eq("event_source", "app")
    .limit(1)
    .maybeSingle();
  if (error) throw error;
  return Boolean(data?.id);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204 });
  }
  if (req.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed" }, 405);
  }

  try {
    const accessToken = sanitizeText(req.headers.get("authorization") ?? "", 4000).replace(/^Bearer\s+/i, "").trim();
    if (!accessToken) {
      throw new HttpError("unauthorized", "Authorization ausente.", 401);
    }

    const body = await req.json().catch(() => ({})) as Json;
    const eventName = normalizeEventName(body.event_name);
    const metadata = maybeJson(body.metadata);
    const transcriptionId = sanitizeText(body.transcription_id, 64);

    const supabaseUrl = requiredEnvAny(["EDGE_SUPABASE_URL", "SUPABASE_URL"]);
    const anonKey = requiredEnvAny(["EDGE_SUPABASE_ANON_KEY", "SUPABASE_ANON_KEY"]);
    const serviceRoleKey = requiredEnvAny([
      "EDGE_SUPABASE_SERVICE_ROLE_KEY",
      "SUPABASE_SERVICE_ROLE_KEY",
      "SERVICE_ROLE_KEY",
    ]);
    const userId = await resolveUserIdFromJwt(supabaseUrl, anonKey, accessToken);
    const supabaseAdmin = createClient(supabaseUrl, serviceRoleKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });

    const lead = await findLeadByUser(supabaseAdmin, userId);
    if (!lead?.id) {
      return jsonResponse({ ok: true, ignored: true, reason: "lead_not_linked" });
    }

    if (await eventAlreadyExists(supabaseAdmin, String(lead.id), eventName)) {
      return jsonResponse({ ok: true, lead_id: lead.id, replay: true });
    }

    const timestamp = nowIso();
    const updatePayload: Record<string, unknown> = {};

    if (eventName === "first_login") {
      updatePayload.first_login_at = lead.first_login_at || timestamp;
      if (String(lead.status ?? "").trim() === "novo") {
        updatePayload.status = "contatado";
      }
    }

    if (eventName === "first_transcription_detected") {
      updatePayload.first_transcription_at = lead.first_transcription_at || timestamp;
      const currentStatus = String(lead.status ?? "").trim();
      if (!["convertido", "desqualificado"].includes(currentStatus)) {
        updatePayload.status = "ativado";
      }
    }

    if (eventName === "trial_expired_seen") {
      const currentStatus = String(lead.status ?? "").trim();
      if (!["convertido", "desqualificado"].includes(currentStatus)) {
        updatePayload.status = "trial_expirado";
      }
    }

    if (Object.keys(updatePayload).length > 0) {
      const { error: updateError } = await supabaseAdmin
        .from("leads_beta")
        .update(updatePayload)
        .eq("id", lead.id);
      if (updateError) throw updateError;
    }

    const { error: eventError } = await supabaseAdmin
      .from("lead_events")
      .insert({
        lead_id: lead.id,
        event_name: eventName,
        event_source: "app",
        event_payload: {
          metadata,
          transcription_id: transcriptionId || null,
          auth_user_id: userId,
          recorded_at: timestamp,
        },
      });
    if (eventError) throw eventError;

    return jsonResponse({ ok: true, lead_id: lead.id, event_name: eventName });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Erro interno";
    const status = error instanceof HttpError ? error.status : 500;
    const code = error instanceof HttpError ? error.code : "internal_error";
    console.error("lead_lifecycle_event", message);
    return jsonResponse({ error: code, message }, status);
  }
});
