// Supabase Edge Function: stripe_portal_session
// Creates a Stripe Customer Portal session URL for the authenticated user.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const DEFAULT_ALLOWED_ORIGINS = [
  "https://falai.app",
  "https://www.falai.app",
  "https://portal.falai.app",
  "http://localhost:3000",
  "http://localhost:3001",
  "http://localhost:5173",
  "http://127.0.0.1:3000",
  "http://127.0.0.1:3001",
  "http://127.0.0.1:5173",
];
const CORS_BASE_HEADERS: Record<string, string> = {
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Vary": "Origin",
};

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

function requiredEnv(name: string): string {
  const v = Deno.env.get(name);
  if (!v) throw new Error(`Missing env: ${name}`);
  return v;
}

async function stripeFormPost(path: string, params: Record<string, string>): Promise<any> {
  const key = requiredEnv("STRIPE_SECRET_KEY");
  const body = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && String(v).trim()) {
      body.set(k, String(v));
    }
  }

  const resp = await fetch(`https://api.stripe.com/v1/${path}`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${key}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: body.toString(),
  });

  const txt = await resp.text();
  let payload: any = {};
  try {
    payload = txt ? JSON.parse(txt) : {};
  } catch {
    payload = { raw: txt };
  }
  if (!resp.ok) {
    throw new Error(`Stripe ${path} failed: ${resp.status} ${JSON.stringify(payload)}`);
  }
  return payload;
}

async function resolveOrCreateCustomer(params: {
  supabaseAdmin: ReturnType<typeof createClient>;
  userId: string;
  email: string;
  fullName: string;
  stripeCustomerId: string;
}): Promise<string> {
  const { supabaseAdmin, userId, email, fullName, stripeCustomerId } = params;
  if (stripeCustomerId) return stripeCustomerId;

  const customer = await stripeFormPost("customers", {
    email: email || "",
    name: fullName || "",
    "metadata[supabase_user_id]": userId,
  });
  const customerId = String(customer?.id ?? "").trim();
  if (!customerId) {
    throw new Error("stripe_customer_create_failed");
  }

  await supabaseAdmin
    .from("profiles")
    .update({ stripe_customer_id: customerId })
    .eq("id", userId);

  return customerId;
}

Deno.serve(async (req) => {
  const reqCorsHeaders = buildCorsHeaders(req);
  const respondJson = (body: unknown, status = 200): Response => jsonResponse(body, status, reqCorsHeaders);

  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: reqCorsHeaders });
  }
  if (req.method !== "POST") {
    return respondJson({ error: "method_not_allowed" }, 405);
  }

  try {
    const supabaseUrl = requiredEnv("SUPABASE_URL");
    const anonKey = requiredEnv("SUPABASE_ANON_KEY");
    const serviceRole = requiredEnv("SUPABASE_SERVICE_ROLE_KEY");

    const authHeader = req.headers.get("Authorization") || "";
    const supabaseUser = createClient(supabaseUrl, anonKey, {
      global: { headers: { Authorization: authHeader } },
    });
    const supabaseAdmin = createClient(supabaseUrl, serviceRole);

    const { data: authData, error: authErr } = await supabaseUser.auth.getUser();
    if (authErr || !authData?.user?.id) {
      return respondJson({ error: "unauthenticated" }, 401);
    }

    const userId = String(authData.user.id);
    const email = String(authData.user.email ?? "").trim();
    const body = await req.json().catch(() => ({} as Record<string, unknown>));
    const returnUrl =
      String((body as any)?.return_url ?? "").trim()
      || String(Deno.env.get("BILLING_PORTAL_RETURN_URL") || "").trim()
      || "https://falai.app/conta";

    const { data: profile, error: profileErr } = await supabaseAdmin
      .from("profiles")
      .select("id, full_name, email, stripe_customer_id")
      .eq("id", userId)
      .maybeSingle();

    if (profileErr) {
      return respondJson({ error: "profile_fetch_failed" }, 500);
    }

    const fullName = String((profile as any)?.full_name ?? "").trim();
    const profEmail = String((profile as any)?.email ?? "").trim() || email;
    const stripeCustomerId = String((profile as any)?.stripe_customer_id ?? "").trim();

    const customerId = await resolveOrCreateCustomer({
      supabaseAdmin,
      userId,
      email: profEmail,
      fullName,
      stripeCustomerId,
    });

    const portal = await stripeFormPost("billing_portal/sessions", {
      customer: customerId,
      return_url: returnUrl,
    });

    const url = String(portal?.url ?? "").trim();
    if (!url) {
      return respondJson({ error: "portal_url_missing" }, 500);
    }

    return respondJson({
      ok: true,
      url,
      expires_at: portal?.created ? new Date(Number(portal.created) * 1000).toISOString() : null,
    });
  } catch (e) {
    return respondJson({ error: "internal_error", message: String((e as Error)?.message || e) }, 500);
  }
});
