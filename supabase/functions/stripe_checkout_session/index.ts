// FWEB — stripe_checkout_session
// POST /functions/v1/stripe_checkout_session  { plan: 'start'|'pro', success_url, cancel_url }
// Creates a Stripe Checkout session for new subscribers. Uses Supabase
// auth for the caller and maps to the plans table via `code`.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { jsonResponse, preflight } from "../_shared/cors.ts";
import {
  adminClient,
  resolveUserFromBearer,
  requireEnv,
} from "../_shared/supabase.ts";

const TRIAL_PERIOD_DAYS = Number(Deno.env.get("FWEB_TRIAL_DAYS") ?? "3");

async function stripeFormPost(
  path: string,
  params: Record<string, string>,
): Promise<Record<string, unknown>> {
  const key = requireEnv("STRIPE_SECRET_KEY");
  const body = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && String(v).trim() !== "") {
      body.set(k, String(v));
    }
  }
  const resp = await fetch(`https://api.stripe.com/v1/${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: body.toString(),
  });
  const txt = await resp.text();
  let payload: Record<string, unknown>;
  try {
    payload = txt ? JSON.parse(txt) : {};
  } catch {
    payload = { raw: txt };
  }
  if (!resp.ok) {
    throw new Error(
      `stripe_${path}_failed ${resp.status} ${JSON.stringify(payload)}`,
    );
  }
  return payload;
}

Deno.serve(async (req) => {
  const origin = req.headers.get("origin");
  if (req.method === "OPTIONS") return preflight(origin);
  if (req.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed" }, 405, origin);
  }

  try {
    const { user, error: authErr } = await resolveUserFromBearer(
      req.headers.get("authorization"),
    );
    if (!user) {
      return jsonResponse({ error: "invalid_session", detail: authErr }, 401, origin);
    }

    const body = (await req.json()) as Record<string, unknown>;
    const planCode = String(body.plan ?? "").toLowerCase();
    if (!["start", "pro"].includes(planCode)) {
      return jsonResponse({ error: "invalid_plan" }, 400, origin);
    }
    const successUrl =
      String(body.success_url ?? "").trim() ||
      `${Deno.env.get("PORTAL_URL") ?? "https://falai.app"}/dashboard?upgrade=success`;
    const cancelUrl =
      String(body.cancel_url ?? "").trim() ||
      `${Deno.env.get("PORTAL_URL") ?? "https://falai.app"}/billing`;

    const admin = adminClient();

    // Look up plan to get stripe_price_id
    const { data: plan, error: planErr } = await admin
      .from("plans")
      .select("id, code, stripe_price_id")
      .eq("code", planCode)
      .maybeSingle();
    if (planErr || !plan || !plan.stripe_price_id) {
      return jsonResponse(
        {
          error: "plan_not_configured",
          detail: planErr?.message ?? "missing_stripe_price_id",
          plan: planCode,
        },
        500,
        origin,
      );
    }

    // Resolve stripe customer (create if missing)
    const { data: profile } = await admin
      .from("profiles")
      .select("id, email, full_name, stripe_customer_id")
      .eq("id", user.id)
      .maybeSingle();

    let customerId =
      (profile as { stripe_customer_id?: string | null } | null)
        ?.stripe_customer_id ?? null;

    if (!customerId) {
      const customer = await stripeFormPost("customers", {
        email: user.email ?? "",
        name:
          ((profile as { full_name?: string | null } | null)?.full_name ?? "") ||
          "",
        "metadata[supabase_user_id]": user.id,
      });
      customerId = String((customer as { id?: string })?.id ?? "");
      if (!customerId) {
        return jsonResponse({ error: "customer_create_failed" }, 500, origin);
      }
      await admin
        .from("profiles")
        .update({ stripe_customer_id: customerId })
        .eq("id", user.id);
    }

    // Create checkout session
    const params: Record<string, string> = {
      mode: "subscription",
      customer: customerId,
      "line_items[0][price]": String(plan.stripe_price_id),
      "line_items[0][quantity]": "1",
      success_url: successUrl,
      cancel_url: cancelUrl,
      "metadata[supabase_user_id]": user.id,
      "metadata[plan_code]": planCode,
      "subscription_data[metadata][supabase_user_id]": user.id,
      "subscription_data[metadata][plan_code]": planCode,
      allow_promotion_codes: "true",
    };
    if (TRIAL_PERIOD_DAYS > 0) {
      params["subscription_data[trial_period_days]"] = String(TRIAL_PERIOD_DAYS);
    }

    const session = await stripeFormPost("checkout/sessions", params);
    const url = String((session as { url?: string })?.url ?? "");
    if (!url) {
      return jsonResponse(
        { error: "no_checkout_url", raw: session },
        500,
        origin,
      );
    }

    return jsonResponse({ url, plan: planCode }, 200, origin);
  } catch (err) {
    console.error(
      JSON.stringify({ event: "checkout_error", error: String(err) }),
    );
    return jsonResponse({ error: "internal_error", detail: String(err) }, 500, origin);
  }
});
