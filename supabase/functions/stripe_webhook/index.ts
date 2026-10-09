// Supabase Edge Function: stripe_webhook
// Receives Stripe events, syncs subscriptions + entitlements in Supabase.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

type Json = Record<string, unknown>;

function requiredEnv(name: string): string {
  const v = Deno.env.get(name);
  if (!v) throw new Error(`Missing env: ${name}`);
  return v;
}

function toIsoOrNull(epochSeconds: unknown): string | null {
  const n = Number(epochSeconds);
  if (!Number.isFinite(n) || n <= 0) return null;
  return new Date(n * 1000).toISOString();
}

function normalizeStripeStatus(status: string): { dbStatus: string; entitlementActive: boolean } {
  const s = String(status || "").trim().toLowerCase();
  if (s === "trialing") return { dbStatus: "trialing", entitlementActive: true };
  if (s === "active") return { dbStatus: "active", entitlementActive: true };
  if (s === "past_due") return { dbStatus: "past_due", entitlementActive: false };
  if (s === "canceled") return { dbStatus: "canceled", entitlementActive: false };
  if (s === "unpaid" || s === "incomplete" || s === "incomplete_expired") {
    return { dbStatus: "canceled", entitlementActive: false };
  }
  return { dbStatus: "expired", entitlementActive: false };
}

function toIntOrNull(v: unknown): number | null {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  if (!Number.isFinite(n)) return null;
  return Math.round(n);
}

function parseStripeSig(headerValue: string): { t: string; v1: string } | null {
  if (!headerValue) return null;
  const parts = headerValue.split(",").map((p) => p.trim());
  let t = "";
  let v1 = "";
  for (const p of parts) {
    const [k, ...rest] = p.split("=");
    const v = rest.join("=").trim();
    if (k === "t") t = v;
    if (k === "v1") v1 = v;
  }
  if (!t || !v1) return null;
  return { t, v1 };
}

function hexToBytes(hex: string): Uint8Array {
  const s = (hex || "").trim().toLowerCase();
  if (!/^[0-9a-f]+$/.test(s) || s.length % 2 !== 0) return new Uint8Array();
  const out = new Uint8Array(s.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = Number.parseInt(s.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

function timingSafeEqualHex(a: string, b: string): boolean {
  const aa = hexToBytes(a);
  const bb = hexToBytes(b);
  if (aa.length !== bb.length || aa.length === 0) return false;
  let diff = 0;
  for (let i = 0; i < aa.length; i++) diff |= aa[i] ^ bb[i];
  return diff === 0;
}

async function verifyStripeSignature(rawBody: string, stripeSigHeader: string): Promise<boolean> {
  const whsec = requiredEnv("STRIPE_WEBHOOK_SECRET");
  const sig = parseStripeSig(stripeSigHeader);
  if (!sig) return false;

  const payload = `${sig.t}.${rawBody}`;
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(whsec),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signed = await crypto.subtle.sign("HMAC", key, enc.encode(payload));
  const computed = Array.from(new Uint8Array(signed)).map((b) => b.toString(16).padStart(2, "0")).join("");
  return timingSafeEqualHex(computed, sig.v1);
}

async function stripeGet(path: string): Promise<any> {
  const key = requiredEnv("STRIPE_SECRET_KEY");
  const resp = await fetch(`https://api.stripe.com/v1/${path}`, {
    method: "GET",
    headers: { "Authorization": `Bearer ${key}` },
  });
  const txt = await resp.text();
  let payload: any = {};
  try {
    payload = txt ? JSON.parse(txt) : {};
  } catch {
    payload = { raw: txt };
  }
  if (!resp.ok) {
    throw new Error(`Stripe GET ${path} failed: ${resp.status} ${JSON.stringify(payload)}`);
  }
  return payload;
}

async function insertBillingEvent(
  supabaseAdmin: ReturnType<typeof createClient>,
  userId: string | null,
  eventType: string,
  payload: Json,
) {
  const { error } = await supabaseAdmin.from("billing_events").insert({
    user_id: userId,
    event_type: eventType,
    provider: "stripe",
    payload,
  });
  if (error) throw error;
}

function parsePriceIdFromSubscriptionObject(sub: any): string {
  return String(
    sub?.items?.data?.[0]?.price?.id
      ?? sub?.plan?.id
      ?? "",
  ).trim();
}

function maybeUuid(v: unknown): string | null {
  const s = String(v ?? "").trim();
  if (!s) return null;
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(s) ? s : null;
}

async function getPlanByPriceId(supabaseAdmin: ReturnType<typeof createClient>, priceId: string): Promise<any | null> {
  if (!priceId) return null;
  const { data, error } = await supabaseAdmin
    .from("plans")
    .select("id, code, name, limits")
    .eq("stripe_price_id", priceId)
    .eq("is_active", true)
    .limit(1)
    .maybeSingle();
  if (error) throw error;
  return data ?? null;
}

async function getPlanByCode(supabaseAdmin: ReturnType<typeof createClient>, code: string): Promise<any | null> {
  if (!code) return null;
  const { data, error } = await supabaseAdmin
    .from("plans")
    .select("id, code, name, limits")
    .eq("code", code)
    .eq("is_active", true)
    .limit(1)
    .maybeSingle();
  if (error) throw error;
  return data ?? null;
}

async function findSubscriptionByProviderId(
  supabaseAdmin: ReturnType<typeof createClient>,
  providerSubscriptionId: string,
): Promise<any | null> {
  if (!providerSubscriptionId) return null;
  const { data, error } = await supabaseAdmin
    .from("subscriptions")
    .select("id, user_id, plan_id")
    .eq("provider", "stripe")
    .eq("provider_subscription_id", providerSubscriptionId)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw error;
  return data ?? null;
}

async function findUserByStripeCustomer(
  supabaseAdmin: ReturnType<typeof createClient>,
  customerId: string,
): Promise<string | null> {
  if (!customerId) return null;
  const { data, error } = await supabaseAdmin
    .from("profiles")
    .select("id")
    .eq("stripe_customer_id", customerId)
    .limit(1)
    .maybeSingle();
  if (error) throw error;
  return String(data?.id ?? "").trim() || null;
}

async function setProfileStripeCustomer(
  supabaseAdmin: ReturnType<typeof createClient>,
  userId: string,
  customerId: string,
) {
  if (!userId || !customerId) return;
  await supabaseAdmin
    .from("profiles")
    .update({ stripe_customer_id: customerId })
    .eq("id", userId);
}

async function markLeadConverted(
  supabaseAdmin: ReturnType<typeof createClient>,
  params: {
    userId: string;
    planCode: string;
    customerId: string;
    subscriptionId: string;
    triggerEvent: string;
  },
) {
  const { data: lead, error: leadError } = await supabaseAdmin
    .from("leads_beta")
    .select("id, status, converted_at")
    .eq("auth_user_id", params.userId)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (leadError || !lead?.id) return;

  const alreadyConverted = Boolean(String(lead.converted_at ?? "").trim());
  const convertedAt = alreadyConverted ? String(lead.converted_at) : new Date().toISOString();

  await supabaseAdmin
    .from("leads_beta")
    .update({
      status: "convertido",
      converted_at: convertedAt,
      last_workflow_error: null,
    })
    .eq("id", String(lead.id));

  if (alreadyConverted) return;

  await supabaseAdmin.from("lead_events").insert({
    lead_id: String(lead.id),
    event_name: "subscription_activated",
    event_source: "edge",
    event_payload: {
      trigger_event: params.triggerEvent,
      auth_user_id: params.userId,
      customer_id: params.customerId || null,
      subscription_id: params.subscriptionId || null,
      plan_code: params.planCode || null,
      converted_at: convertedAt,
    },
  });
}

async function upsertSubscription(
  supabaseAdmin: ReturnType<typeof createClient>,
  params: {
    userId: string;
    planId: string | null;
    providerCustomerId: string;
    providerSubscriptionId: string;
    providerPriceId: string;
    providerCheckoutSessionId: string;
    status: string;
    currentPeriodStart: string | null;
    currentPeriodEnd: string | null;
    cancelAtPeriodEnd: boolean;
  },
): Promise<any | null> {
  const existing = await findSubscriptionByProviderId(supabaseAdmin, params.providerSubscriptionId);
  const planId = params.planId || String(existing?.plan_id ?? "").trim() || null;
  if (!planId) return null;

  if (existing?.id) {
    const { data, error } = await supabaseAdmin
      .from("subscriptions")
      .update({
        user_id: params.userId,
        plan_id: planId,
        provider: "stripe",
        provider_customer_id: params.providerCustomerId || null,
        provider_subscription_id: params.providerSubscriptionId || null,
        provider_price_id: params.providerPriceId || null,
        provider_checkout_session_id: params.providerCheckoutSessionId || null,
        status: params.status,
        current_period_start: params.currentPeriodStart,
        current_period_end: params.currentPeriodEnd,
        cancel_at_period_end: params.cancelAtPeriodEnd,
      })
      .eq("id", existing.id)
      .select("id, user_id, plan_id")
      .maybeSingle();
    if (error) throw error;
    return data ?? existing;
  }

  const { data, error } = await supabaseAdmin
    .from("subscriptions")
    .insert({
      user_id: params.userId,
      plan_id: planId,
      provider: "stripe",
      provider_customer_id: params.providerCustomerId || null,
      provider_subscription_id: params.providerSubscriptionId || null,
      provider_price_id: params.providerPriceId || null,
      provider_checkout_session_id: params.providerCheckoutSessionId || null,
      status: params.status,
      current_period_start: params.currentPeriodStart,
      current_period_end: params.currentPeriodEnd,
      cancel_at_period_end: params.cancelAtPeriodEnd,
    })
    .select("id, user_id, plan_id")
    .maybeSingle();
  if (error) throw error;
  return data ?? null;
}

async function applyEntitlementFromPlan(
  supabaseAdmin: ReturnType<typeof createClient>,
  params: {
    userId: string;
    plan: any | null;
    entitlementActive: boolean;
    periodStartIso: string | null;
    periodEndIso: string | null;
  },
) {
  const { userId, plan, entitlementActive, periodStartIso, periodEndIso } = params;
  if (!userId || !plan) return;

  const limits = (plan?.limits ?? {}) as Record<string, unknown>;
  const daily = toIntOrNull(limits["daily_minutes_limit"]);
  const monthly = toIntOrNull(limits["monthly_minutes_limit"]);

  if (entitlementActive) {
    await supabaseAdmin
      .from("user_entitlements")
      .upsert({
        user_id: userId,
        can_transcribe: true,
        can_correct: true,
        daily_minutes_limit: daily,
        monthly_minutes_limit: monthly,
        source: "plan",
        effective_from: periodStartIso || new Date().toISOString(),
        effective_until: null,
      }, { onConflict: "user_id" });
    return;
  }

  await supabaseAdmin
    .from("user_entitlements")
    .update({
      can_transcribe: false,
      can_correct: false,
      source: "plan",
      effective_until: periodEndIso || new Date().toISOString(),
    })
    .eq("user_id", userId);
}

async function resolveUserForSubscriptionEvent(
  supabaseAdmin: ReturnType<typeof createClient>,
  subscriptionId: string,
  customerId: string,
): Promise<string | null> {
  const existingSub = await findSubscriptionByProviderId(supabaseAdmin, subscriptionId);
  if (existingSub?.user_id) return String(existingSub.user_id);
  return await findUserByStripeCustomer(supabaseAdmin, customerId);
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }

  const stripeSig = req.headers.get("stripe-signature") || "";
  const rawBody = await req.text();

  try {
    const valid = await verifyStripeSignature(rawBody, stripeSig);
    if (!valid) {
      return new Response(JSON.stringify({ error: "invalid_signature" }), { status: 401 });
    }
  } catch (e) {
    return new Response(JSON.stringify({ error: "signature_check_failed", message: String(e) }), { status: 500 });
  }

  let event: any;
  try {
    event = rawBody ? JSON.parse(rawBody) : {};
  } catch {
    return new Response(JSON.stringify({ error: "invalid_json" }), { status: 400 });
  }

  const eventType = String(event?.type ?? "").trim();
  const eventObj = (event?.data?.object ?? {}) as any;

  try {
    const supabaseUrl = requiredEnv("SUPABASE_URL");
    const serviceRole = requiredEnv("SUPABASE_SERVICE_ROLE_KEY");
    const supabaseAdmin = createClient(supabaseUrl, serviceRole);

    // checkout.session.completed
    if (eventType === "checkout.session.completed") {
      const sessionId = String(eventObj?.id ?? "").trim();
      const customerId = String(eventObj?.customer ?? "").trim();
      const subscriptionId = String(eventObj?.subscription ?? "").trim();
      const planCode = String(eventObj?.metadata?.plan ?? "").trim().toLowerCase();
      const userIdFromRef = maybeUuid(eventObj?.client_reference_id);
      let userId = userIdFromRef;
      if (!userId && customerId) {
        userId = await findUserByStripeCustomer(supabaseAdmin, customerId);
      }

      // Pull richer session details (line_items etc.) when possible.
      let priceId = String(eventObj?.metadata?.price_id ?? "").trim();
      let currentPeriodStart: string | null = null;
      let currentPeriodEnd: string | null = null;
      let status = "active";
      let cancelAtPeriodEnd = false;

      if (sessionId) {
        try {
          const li = await stripeGet(`checkout/sessions/${sessionId}/line_items?limit=1`);
          priceId = String(li?.data?.[0]?.price?.id ?? priceId).trim();
        } catch {
          // best effort only
        }
      }

      if (subscriptionId) {
        try {
          const sub = await stripeGet(`subscriptions/${subscriptionId}`);
          priceId = String(parsePriceIdFromSubscriptionObject(sub) || priceId).trim();
          currentPeriodStart = toIsoOrNull(sub?.current_period_start);
          currentPeriodEnd = toIsoOrNull(sub?.current_period_end);
          cancelAtPeriodEnd = Boolean(sub?.cancel_at_period_end);
          status = normalizeStripeStatus(String(sub?.status ?? "active")).dbStatus;
        } catch {
          // keep defaults
        }
      }

      let plan = await getPlanByPriceId(supabaseAdmin, priceId);
      if (!plan && planCode) {
        plan = await getPlanByCode(supabaseAdmin, planCode);
      }

      if (userId && customerId) {
        await setProfileStripeCustomer(supabaseAdmin, userId, customerId);
      }

      if (userId && plan) {
        await upsertSubscription(supabaseAdmin, {
          userId,
          planId: String(plan.id),
          providerCustomerId: customerId,
          providerSubscriptionId: subscriptionId,
          providerPriceId: priceId,
          providerCheckoutSessionId: sessionId,
          status,
          currentPeriodStart,
          currentPeriodEnd,
          cancelAtPeriodEnd,
        });
        const norm = normalizeStripeStatus(status);
        await applyEntitlementFromPlan(supabaseAdmin, {
          userId,
          plan,
          entitlementActive: norm.entitlementActive,
          periodStartIso: currentPeriodStart,
          periodEndIso: currentPeriodEnd,
        });
        if (norm.entitlementActive) {
          await markLeadConverted(supabaseAdmin, {
            userId,
            planCode: String(plan.code ?? planCode ?? "").trim().toLowerCase(),
            customerId,
            subscriptionId,
            triggerEvent: eventType,
          });
        }
      }

      await insertBillingEvent(
        supabaseAdmin,
        userId ?? null,
        eventType,
        {
          event_id: String(event?.id ?? ""),
          session_id: sessionId,
          customer_id: customerId,
          subscription_id: subscriptionId,
          plan_code: planCode || null,
          price_id: priceId || null,
          user_id: userId,
        },
      );

      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }

    // customer.subscription.*
    if (
      eventType === "customer.subscription.created"
      || eventType === "customer.subscription.updated"
      || eventType === "customer.subscription.deleted"
    ) {
      const subscriptionId = String(eventObj?.id ?? "").trim();
      const customerId = String(eventObj?.customer ?? "").trim();
      const priceId = parsePriceIdFromSubscriptionObject(eventObj);
      const stripeStatus = String(eventObj?.status ?? "").trim();
      const norm = normalizeStripeStatus(stripeStatus);
      const currentPeriodStart = toIsoOrNull(eventObj?.current_period_start);
      const currentPeriodEnd = toIsoOrNull(eventObj?.current_period_end);
      const cancelAtPeriodEnd = Boolean(eventObj?.cancel_at_period_end);

      const userId = await resolveUserForSubscriptionEvent(supabaseAdmin, subscriptionId, customerId);
      let plan = await getPlanByPriceId(supabaseAdmin, priceId);
      if (!plan) {
        const existingSub = await findSubscriptionByProviderId(supabaseAdmin, subscriptionId);
        if (existingSub?.plan_id) {
          const { data } = await supabaseAdmin
            .from("plans")
            .select("id, code, name, limits")
            .eq("id", String(existingSub.plan_id))
            .limit(1)
            .maybeSingle();
          plan = data ?? null;
        }
      }

      if (userId && customerId) {
        await setProfileStripeCustomer(supabaseAdmin, userId, customerId);
      }
      if (userId && plan) {
        await upsertSubscription(supabaseAdmin, {
          userId,
          planId: String(plan.id),
          providerCustomerId: customerId,
          providerSubscriptionId: subscriptionId,
          providerPriceId: priceId,
          providerCheckoutSessionId: "",
          status: norm.dbStatus,
          currentPeriodStart,
          currentPeriodEnd,
          cancelAtPeriodEnd,
        });
        await applyEntitlementFromPlan(supabaseAdmin, {
          userId,
          plan,
          entitlementActive: norm.entitlementActive,
          periodStartIso: currentPeriodStart,
          periodEndIso: currentPeriodEnd,
        });
        if (norm.entitlementActive) {
          await markLeadConverted(supabaseAdmin, {
            userId,
            planCode: String(plan.code ?? "").trim().toLowerCase(),
            customerId,
            subscriptionId,
            triggerEvent: eventType,
          });
        }
      }

      await insertBillingEvent(
        supabaseAdmin,
        userId ?? null,
        eventType,
        {
          event_id: String(event?.id ?? ""),
          customer_id: customerId || null,
          subscription_id: subscriptionId || null,
          status: stripeStatus || null,
          price_id: priceId || null,
          user_id: userId,
        },
      );

      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }

    // invoice.paid -> billing history (renewals + first successful charge)
    if (eventType === "invoice.paid") {
      const customerId = String(eventObj?.customer ?? "").trim();
      const subscriptionId = String(eventObj?.subscription ?? "").trim();
      const userId = await resolveUserForSubscriptionEvent(supabaseAdmin, subscriptionId, customerId);
      await insertBillingEvent(
        supabaseAdmin,
        userId ?? null,
        eventType,
        {
          event_id: String(event?.id ?? ""),
          customer_id: customerId || null,
          subscription_id: subscriptionId || null,
          invoice_id: String(eventObj?.id ?? ""),
          billing_reason: String(eventObj?.billing_reason ?? ""),
          status: String(eventObj?.status ?? ""),
          amount_paid_cents: Number(eventObj?.amount_paid ?? 0),
          currency: String(eventObj?.currency ?? ""),
          period_start: toIsoOrNull(eventObj?.period_start),
          period_end: toIsoOrNull(eventObj?.period_end),
          hosted_invoice_url: String(eventObj?.hosted_invoice_url ?? ""),
          invoice_pdf: String(eventObj?.invoice_pdf ?? ""),
          user_id: userId,
        },
      );
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }

    // invoice.payment_failed -> soft-log, status change arrives via subscription.updated
    if (eventType === "invoice.payment_failed") {
      const customerId = String(eventObj?.customer ?? "").trim();
      const subscriptionId = String(eventObj?.subscription ?? "").trim();
      const userId = await resolveUserForSubscriptionEvent(supabaseAdmin, subscriptionId, customerId);
      await insertBillingEvent(
        supabaseAdmin,
        userId ?? null,
        eventType,
        {
          event_id: String(event?.id ?? ""),
          customer_id: customerId || null,
          subscription_id: subscriptionId || null,
          invoice_id: String(eventObj?.id ?? ""),
          billing_reason: String(eventObj?.billing_reason ?? ""),
          status: String(eventObj?.status ?? ""),
          amount_due_cents: Number(eventObj?.amount_due ?? 0),
          currency: String(eventObj?.currency ?? ""),
          next_payment_attempt: toIsoOrNull(eventObj?.next_payment_attempt),
          user_id: userId,
        },
      );
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }

    // Ignore everything else (ack as success).
    return new Response(JSON.stringify({ ok: true, ignored: true }), { status: 200 });
  } catch (e) {
    return new Response(
      JSON.stringify({
        error: "webhook_processing_failed",
        message: String((e as Error)?.message || e),
      }),
      { status: 500 },
    );
  }
});
