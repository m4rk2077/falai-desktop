import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

type Json = Record<string, unknown>;

const TRIAL_DAYS = 7;
const TRIAL_DAILY_MINUTES = 15;
const TRIAL_MONTHLY_MINUTES = 450;

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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

function asUuid(value: unknown): string {
  const raw = String(value ?? "").trim();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(raw)) {
    throw new HttpError("invalid_payload", "lead_id invalido.", 422);
  }
  return raw;
}

function sanitizeText(value: unknown, maxLen: number): string {
  return String(value ?? "").trim().slice(0, maxLen);
}

function nowIso(): string {
  return new Date().toISOString();
}

function trialEndsIso(): string {
  return new Date(Date.now() + TRIAL_DAYS * 24 * 60 * 60 * 1000).toISOString();
}

function hasExpectedTrialWindow(
  startIso: string | null,
  endIso: string | null,
): boolean {
  if (!startIso || !endIso) return false;
  const startMs = new Date(startIso).getTime();
  const endMs = new Date(endIso).getTime();
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {
    return false;
  }
  const diffDays = (endMs - startMs) / (24 * 60 * 60 * 1000);
  return diffDays >= TRIAL_DAYS - 0.01;
}

function generateTemporaryPassword(): string {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%";
  const bytes = crypto.getRandomValues(new Uint8Array(14));
  let out = "";
  for (const byte of bytes) {
    out += chars[byte % chars.length];
  }
  return out;
}

async function adminFetch<T>(
  supabaseUrl: string,
  serviceRoleKey: string,
  path: string,
  init: RequestInit,
): Promise<T> {
  const response = await fetch(`${supabaseUrl}${path}`, {
    ...init,
    headers: {
      "apikey": serviceRoleKey,
      "Authorization": `Bearer ${serviceRoleKey}`,
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  const text = await response.text();
  let payload: any = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { raw: text };
  }
  if (!response.ok) {
    throw new HttpError(
      "admin_api_error",
      `Supabase Auth admin falhou (${response.status}): ${JSON.stringify(payload)}`,
      500,
    );
  }
  return payload as T;
}

function isUserNotFoundAdminError(error: unknown): boolean {
  if (!(error instanceof HttpError)) return false;
  return error.code === "admin_api_error" && error.message.includes('"error_code":"user_not_found"');
}

async function findAuthUserByEmail(
  supabaseUrl: string,
  serviceRoleKey: string,
  supabaseAdmin: ReturnType<typeof createClient>,
  email: string,
): Promise<{ id: string; email: string } | null> {
  const normalized = sanitizeText(email, 320).toLowerCase();
  if (!normalized) return null;
  let payload: { users?: Array<{ id?: string; email?: string }> } | null = null;
  try {
    payload = await adminFetch<{ users?: Array<{ id?: string; email?: string }> }>(
      supabaseUrl,
      serviceRoleKey,
      "/auth/v1/admin/users?page=1&per_page=1000",
      { method: "GET" },
    );
  } catch (error) {
    if (isUserNotFoundAdminError(error)) return null;
    throw error;
  }
  const user = Array.isArray(payload?.users)
    ? payload.users.find((candidate) => sanitizeText(candidate?.email, 320).toLowerCase() === normalized) ?? null
    : null;
  const userId = String(user?.id ?? "").trim();
  if (userId) {
    return { id: userId, email: String(user?.email ?? normalized).trim() };
  }

  const { data: profile, error: profileError } = await supabaseAdmin
    .from("profiles")
    .select("id,email")
    .ilike("email", normalized)
    .limit(1)
    .maybeSingle();
  if (profileError) throw profileError;
  const profileId = String(profile?.id ?? "").trim();
  if (!profileId) return null;
  return { id: profileId, email: String(profile?.email ?? normalized).trim() };
}

async function createAuthUser(
  supabaseUrl: string,
  serviceRoleKey: string,
  params: { email: string; fullName: string; leadId: string; temporaryPassword: string },
): Promise<{ id: string; email: string }> {
  const payload = await adminFetch<{ id?: string; email?: string; user?: { id?: string; email?: string } }>(
    supabaseUrl,
    serviceRoleKey,
    "/auth/v1/admin/users",
    {
      method: "POST",
      body: JSON.stringify({
        email: params.email,
        password: params.temporaryPassword,
        email_confirm: true,
        user_metadata: {
          full_name: params.fullName,
          source: "official_lp",
          lead_id: params.leadId,
        },
      }),
    },
  );
  const userId = String(payload?.id ?? payload?.user?.id ?? "").trim();
  if (!userId) {
    throw new HttpError("user_create_failed", "Nao foi possivel criar usuario no Auth.", 500);
  }
  return { id: userId, email: String(payload?.email ?? payload?.user?.email ?? params.email).trim() };
}

async function generateRecoveryLink(
  supabaseUrl: string,
  serviceRoleKey: string,
  email: string,
): Promise<string> {
  const redirectTo = String(Deno.env.get("PASSWORD_RESET_REDIRECT_URL") ?? "https://reset.falaiapp.com.br/trocar-senha").trim();
  const payload = await adminFetch<{
    properties?: { action_link?: string; hashed_token?: string };
    action_link?: string;
    hashed_token?: string;
  }>(
    supabaseUrl,
    serviceRoleKey,
    "/auth/v1/admin/generate_link",
    {
      method: "POST",
      body: JSON.stringify({
        type: "recovery",
        email,
        options: { redirectTo },
      }),
    },
  );

  const hashedToken = String(
    payload?.properties?.hashed_token ?? payload?.hashed_token ?? "",
  ).trim();

  if (hashedToken) {
    return `${redirectTo}?token_hash=${encodeURIComponent(hashedToken)}&type=recovery`;
  }

  return String(payload?.properties?.action_link ?? payload?.action_link ?? "").trim();
}

async function ensureProfile(
  supabaseAdmin: ReturnType<typeof createClient>,
  params: { userId: string; email: string; fullName: string },
) {
  const { error } = await supabaseAdmin
    .from("profiles")
    .upsert({
      id: params.userId,
      email: params.email,
      full_name: params.fullName,
      role: "user",
    }, { onConflict: "id" });
  if (error) throw error;
}

async function insertLeadEvent(
  supabaseAdmin: ReturnType<typeof createClient>,
  leadId: string,
  eventName: string,
  eventSource: "edge" | "app" | "n8n" | "manual" | "site",
  eventPayload: Json,
) {
  const { error } = await supabaseAdmin.from("lead_events").insert({
    lead_id: leadId,
    event_name: eventName,
    event_source: eventSource,
    event_payload: eventPayload,
  });
  if (error) throw error;
}

async function hasActivePaidSubscription(
  supabaseAdmin: ReturnType<typeof createClient>,
  userId: string,
): Promise<boolean> {
  const { data, error } = await supabaseAdmin
    .from("subscriptions")
    .select("id")
    .eq("user_id", userId)
    .in("status", ["active", "trialing"])
    .limit(1)
    .maybeSingle();
  if (error) throw error;
  return Boolean(data?.id);
}

async function getEntitlement(
  supabaseAdmin: ReturnType<typeof createClient>,
  userId: string,
): Promise<any | null> {
  const { data, error } = await supabaseAdmin
    .from("user_entitlements")
    .select("user_id,can_transcribe,can_correct,daily_minutes_limit,monthly_minutes_limit,effective_from,effective_until,source")
    .eq("user_id", userId)
    .maybeSingle();
  if (error) throw error;
  return data ?? null;
}

async function ensureTrialEntitlement(
  supabaseAdmin: ReturnType<typeof createClient>,
  userId: string,
  grantFreshTrial: boolean,
): Promise<{ trialStartedAt: string | null; trialEndsAt: string | null; granted: boolean }> {
  const existingEntitlement = await getEntitlement(supabaseAdmin, userId);
  const hasPaid = await hasActivePaidSubscription(supabaseAdmin, userId);

  if (hasPaid) {
    return {
      trialStartedAt: null,
      trialEndsAt: null,
      granted: false,
    };
  }

  const existingStart = String(existingEntitlement?.effective_from ?? "").trim() || null;
  const existingEnd = String(existingEntitlement?.effective_until ?? "").trim() || null;
  const existingDaily = Number(existingEntitlement?.daily_minutes_limit ?? 0);
  const existingMonthly = Number(existingEntitlement?.monthly_minutes_limit ?? 0);
  const existingActive = Boolean(existingEntitlement?.can_transcribe);
  const existingWindowMatches = hasExpectedTrialWindow(existingStart, existingEnd);

  if (
    existingActive &&
    existingEnd &&
    existingDaily === TRIAL_DAILY_MINUTES &&
    existingMonthly === TRIAL_MONTHLY_MINUTES &&
    (!grantFreshTrial || existingWindowMatches)
  ) {
    return {
      trialStartedAt: existingStart,
      trialEndsAt: existingEnd,
      granted: false,
    };
  }

  if (!grantFreshTrial && existingEntitlement) {
    return {
      trialStartedAt: existingStart,
      trialEndsAt: existingEnd,
      granted: false,
    };
  }

  const startIso = nowIso();
  const endIso = trialEndsIso();
  const { error } = await supabaseAdmin
    .from("user_entitlements")
    .upsert({
      user_id: userId,
      can_transcribe: true,
      can_correct: true,
      daily_minutes_limit: TRIAL_DAILY_MINUTES,
      monthly_minutes_limit: TRIAL_MONTHLY_MINUTES,
      source: "plan",
      effective_from: startIso,
      effective_until: endIso,
    }, { onConflict: "user_id" });
  if (error) throw error;
  return {
    trialStartedAt: startIso,
    trialEndsAt: endIso,
    granted: true,
  };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204 });
  }
  if (req.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed" }, 405);
  }

  try {
    const provisionSecret = requiredEnv("LEAD_PROVISION_SECRET");
    const providedSecret = sanitizeText(req.headers.get("x-falai-provision-secret") ?? "", 200);
    if (!providedSecret || providedSecret !== provisionSecret) {
      throw new HttpError("invalid_secret", "Segredo de provisionamento invalido.", 401);
    }

    const body = await req.json().catch(() => ({})) as Json;
    const leadId = asUuid(body.lead_id);

    const supabaseUrl = requiredEnvAny(["EDGE_SUPABASE_URL", "SUPABASE_URL"]);
    const serviceRoleKey = requiredEnvAny([
      "EDGE_SUPABASE_SERVICE_ROLE_KEY",
      "SUPABASE_SERVICE_ROLE_KEY",
      "SERVICE_ROLE_KEY",
    ]);
    const supabaseAdmin = createClient(supabaseUrl, serviceRoleKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });

    const { data: lead, error: leadError } = await supabaseAdmin
      .from("leads_beta")
      .select("*")
      .eq("id", leadId)
      .maybeSingle();
    if (leadError) throw leadError;
    if (!lead) throw new HttpError("lead_not_found", "Lead nao encontrado.", 404);

    const leadEmail = sanitizeText(lead.email_normalized || lead.email, 320).toLowerCase();
    const leadName = sanitizeText(lead.nome, 160);
    if (!leadEmail || !leadName) {
      throw new HttpError("lead_invalid", "Lead sem nome ou email valido.", 422);
    }

    const processingStartedAt = nowIso();
    await supabaseAdmin
      .from("leads_beta")
      .update({
        provisioning_status: "provisioning",
        status: "provisionando",
        last_workflow_error: null,
      })
      .eq("id", leadId);

    let authUserId = sanitizeText(lead.auth_user_id, 64);
    let accountState = "already_provisioned";
    let temporaryPassword = "";
    let recoveryLink = "";

    if (!authUserId) {
      const existingAuthUser = await findAuthUserByEmail(supabaseUrl, serviceRoleKey, supabaseAdmin, leadEmail);
      if (existingAuthUser?.id) {
        authUserId = existingAuthUser.id;
        accountState = "reconciled_existing";
      } else {
        temporaryPassword = generateTemporaryPassword();
        const createdUser = await createAuthUser(supabaseUrl, serviceRoleKey, {
          email: leadEmail,
          fullName: leadName,
          leadId,
          temporaryPassword,
        });
        authUserId = createdUser.id;
        accountState = "created";
      }
    }

    await ensureProfile(supabaseAdmin, {
      userId: authUserId,
      email: leadEmail,
      fullName: leadName,
    });

    if (!temporaryPassword) {
      try {
        recoveryLink = await generateRecoveryLink(supabaseUrl, serviceRoleKey, leadEmail);
      } catch (error) {
        if (!isUserNotFoundAdminError(error)) throw error;

        temporaryPassword = generateTemporaryPassword();
        const recreatedUser = await createAuthUser(supabaseUrl, serviceRoleKey, {
          email: leadEmail,
          fullName: leadName,
          leadId,
          temporaryPassword,
        });
        authUserId = recreatedUser.id;
        accountState = "created_after_recovery_miss";

        await ensureProfile(supabaseAdmin, {
          userId: authUserId,
          email: leadEmail,
          fullName: leadName,
        });
      }
    }

    const trialInfo = await ensureTrialEntitlement(
      supabaseAdmin,
      authUserId,
      accountState === "created" || accountState === "reconciled_existing",
    );

    const nextStatus = accountState === "already_provisioned"
      ? sanitizeText(lead.status, 40) || "contatado"
      : "provisionando";

    const { error: updateLeadError } = await supabaseAdmin
      .from("leads_beta")
      .update({
        auth_user_id: authUserId,
        profile_id: authUserId,
        provisioning_status: "provisioned",
        provisioned_at: processingStartedAt,
        trial_started_at: trialInfo.trialStartedAt,
        trial_ends_at: trialInfo.trialEndsAt,
        status: nextStatus,
        last_workflow_error: null,
      })
      .eq("id", leadId);
    if (updateLeadError) throw updateLeadError;

    const eventPayload: Json = {
      account_state: accountState,
      auth_user_id: authUserId,
      trial_started_at: trialInfo.trialStartedAt,
      trial_ends_at: trialInfo.trialEndsAt,
      trial_granted: trialInfo.granted,
      has_recovery_link: Boolean(recoveryLink),
      email: leadEmail,
    };

    await insertLeadEvent(supabaseAdmin, leadId, `account_${accountState}`, "edge", eventPayload);
    if (trialInfo.trialStartedAt && trialInfo.trialEndsAt) {
      await insertLeadEvent(supabaseAdmin, leadId, "trial_started", "edge", {
        auth_user_id: authUserId,
        trial_started_at: trialInfo.trialStartedAt,
        trial_ends_at: trialInfo.trialEndsAt,
      });
    }

    return jsonResponse({
      ok: true,
      lead_id: leadId,
      nome: leadName,
      submit_count: Number(lead.submit_count ?? 1) || 1,
      event_key: `${leadId}:${Number(lead.submit_count ?? 1) || 1}`,
      auth_user_id: authUserId,
      account_state: accountState,
      provisioning_status: "provisioned",
      delivery_mode: temporaryPassword ? "temporary_password" : "recovery_link",
      email: leadEmail,
      temporary_password: temporaryPassword || null,
      recovery_link: recoveryLink || null,
      trial_started_at: trialInfo.trialStartedAt,
      trial_ends_at: trialInfo.trialEndsAt,
      next_lead_status: "contatado",
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Erro interno";
    const status = error instanceof HttpError ? error.status : 500;
    const code = error instanceof HttpError ? error.code : "internal_error";
    console.error("provision_lead_account", message);
    return jsonResponse({ error: code, message }, status);
  }
});
