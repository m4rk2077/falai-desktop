// FWEB-008 - exchange_extension_token
// POST /functions/v1/exchange_extension_token
// Called by the EXTENSION (unauthenticated). Exchanges a raw pairing token for a
// real Supabase user session (access + refresh token). Single-use.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { jsonResponse, preflight } from "../_shared/cors.ts";
import { adminClient, getSupabaseUrl, sha256Hex } from "../_shared/supabase.ts";

Deno.serve(async (req) => {
  const origin = req.headers.get("origin");
  if (req.method === "OPTIONS") return preflight(origin);
  if (req.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed" }, 405, origin);
  }

  try {
    const body = (await req.json()) as Record<string, unknown>;
    const pairingToken = String(body.pairing_token ?? "").trim();
    const extensionId = String(body.extension_id ?? "").trim() || null;
    if (!pairingToken) {
      return jsonResponse({ error: "missing_pairing_token" }, 400, origin);
    }

    const tokenHash = await sha256Hex(pairingToken);
    const admin = adminClient();
    const nowIso = new Date().toISOString();

    // Claim the token before generating the session so concurrent requests
    // cannot exchange the same token twice.
    const { data: pairing, error: claimErr } = await admin
      .from("extension_pairings")
      .update({
        used_at: nowIso,
        extension_id: extensionId,
        user_agent: req.headers.get("user-agent")?.slice(0, 500) ?? null,
      })
      .eq("token_hash", tokenHash)
      .is("used_at", null)
      .is("revoked_at", null)
      .gt("expires_at", nowIso)
      .select("id, user_id, expires_at")
      .maybeSingle();

    if (claimErr) {
      return jsonResponse(
        { error: "token_claim_failed", detail: claimErr.message },
        500,
        origin,
      );
    }
    if (!pairing) {
      return jsonResponse({ error: "token_invalid_or_consumed" }, 410, origin);
    }

    const { data: userResp, error: userErr } = await admin.auth.admin.getUserById(
      pairing.user_id,
    );
    if (userErr || !userResp?.user?.email) {
      return jsonResponse(
        { error: "user_lookup_failed", detail: userErr?.message ?? "no_email" },
        500,
        origin,
      );
    }

    // Generate a magiclink and verify it server-side to obtain a session.
    const { data: linkData, error: linkErr } = await admin.auth.admin.generateLink({
      type: "magiclink",
      email: userResp.user.email,
    });
    if (linkErr || !linkData?.properties?.hashed_token) {
      return jsonResponse(
        {
          error: "link_generation_failed",
          detail: linkErr?.message ?? "no_hashed_token",
        },
        500,
        origin,
      );
    }

    // Modern GoTrue accepts {type, token_hash} for hashed tokens.
    // Use the verify GET endpoint which redirects with session in URL fragment,
    // OR call /auth/v1/otp/verify (PKCE flow). The simplest reliable path is to
    // call /auth/v1/token?grant_type=password is NOT applicable; instead we use
    // the admin admin.createUser session API: generate session via JWT directly.
    const apiKey =
      Deno.env.get("EDGE_SUPABASE_ANON_KEY") ??
      Deno.env.get("SUPABASE_ANON_KEY") ??
      "";

    // Try POST /auth/v1/verify with token_hash (modern), fall back to token (legacy).
    let verifyResp = await fetch(`${getSupabaseUrl()}/auth/v1/verify`, {
      method: "POST",
      headers: {
        apikey: apiKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        type: "magiclink",
        token_hash: linkData.properties.hashed_token,
      }),
    });

    if (!verifyResp.ok) {
      // Legacy fallback
      verifyResp = await fetch(`${getSupabaseUrl()}/auth/v1/verify`, {
        method: "POST",
        headers: {
          apikey: apiKey,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          type: "magiclink",
          token: linkData.properties.hashed_token,
        }),
      });
    }

    if (!verifyResp.ok) {
      const detail = await verifyResp.text();
      return jsonResponse(
        {
          error: "verify_failed",
          status: verifyResp.status,
          detail: detail.slice(0, 200),
        },
        502,
        origin,
      );
    }

    const session = (await verifyResp.json()) as Record<string, unknown>;
    const accessToken = String(session.access_token ?? "");
    const refreshToken = String(session.refresh_token ?? "");
    if (!accessToken || !refreshToken) {
      return jsonResponse({ error: "invalid_verify_payload" }, 502, origin);
    }

    return jsonResponse(
      {
        session: {
          access_token: accessToken,
          refresh_token: refreshToken,
          token_type: session.token_type ?? "bearer",
          expires_in: session.expires_in ?? null,
          expires_at: session.expires_at ?? null,
        },
        user: {
          id: pairing.user_id,
          email: userResp.user.email,
        },
      },
      200,
      origin,
    );
  } catch (err) {
    console.error(
      JSON.stringify({ event: "exchange_pairing_error", error: String(err) }),
    );
    return jsonResponse({ error: "internal_error", detail: String(err) }, 500, origin);
  }
});
