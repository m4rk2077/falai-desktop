// FWEB-007 — create_extension_pairing
// POST /functions/v1/create_extension_pairing
// Called by the PORTAL (authenticated user). Returns a raw pairing token exactly once.
// The token's sha256 hash is stored. Rate-limited to 3 calls/minute/user.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { corsHeaders, jsonResponse, preflight } from "../_shared/cors.ts";
import {
  adminClient,
  randomToken,
  resolveUserFromBearer,
  sha256Hex,
} from "../_shared/supabase.ts";

const PAIRING_TTL_MS = 5 * 60 * 1000; // 5 minutes
const RATE_LIMIT_PER_MIN = 3;

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

    const admin = adminClient();

    // Rate limit: count pairings created in last 60s for this user.
    const since = new Date(Date.now() - 60_000).toISOString();
    const { count, error: countErr } = await admin
      .from("extension_pairings")
      .select("id", { count: "exact", head: true })
      .eq("user_id", user.id)
      .gte("created_at", since);

    if (countErr) {
      return jsonResponse(
        { error: "rate_check_failed", detail: countErr.message },
        500,
        origin,
      );
    }
    if ((count ?? 0) >= RATE_LIMIT_PER_MIN) {
      return jsonResponse(
        { error: "rate_limited", retry_after_seconds: 60 },
        429,
        origin,
      );
    }

    // Optional body fields (label, user_agent hint from portal).
    let body: Record<string, unknown> = {};
    try {
      body = (await req.json()) as Record<string, unknown>;
    } catch {
      body = {};
    }
    const label = body.label ? String(body.label).slice(0, 120) : null;
    const userAgent = req.headers.get("user-agent")?.slice(0, 500) ?? null;

    const rawToken = randomToken(32);
    const tokenHash = await sha256Hex(rawToken);
    const expiresAt = new Date(Date.now() + PAIRING_TTL_MS).toISOString();

    const { data: inserted, error: insertErr } = await admin
      .from("extension_pairings")
      .insert({
        user_id: user.id,
        token_hash: tokenHash,
        expires_at: expiresAt,
        user_agent: userAgent,
        label,
      })
      .select("id, created_at, expires_at, label")
      .single();

    if (insertErr || !inserted) {
      return jsonResponse(
        { error: "insert_failed", detail: insertErr?.message ?? "unknown" },
        500,
        origin,
      );
    }

    return jsonResponse(
      {
        pairing: {
          id: inserted.id,
          token: rawToken, // RAW — shown only once
          expires_at: inserted.expires_at,
          label: inserted.label,
        },
      },
      200,
      origin,
    );
  } catch (err) {
    console.error(
      JSON.stringify({ event: "create_pairing_error", error: String(err) }),
    );
    return jsonResponse({ error: "internal_error", detail: String(err) }, 500, origin);
  }
});
