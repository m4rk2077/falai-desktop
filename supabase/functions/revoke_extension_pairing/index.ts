// FWEB-009 — revoke_extension_pairing
// POST /functions/v1/revoke_extension_pairing  { pairing_id }
// Called by the PORTAL (authenticated). Owner-only. Marks revoked_at so the
// extension session tied to that pairing can no longer refresh.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { jsonResponse, preflight } from "../_shared/cors.ts";
import { adminClient, resolveUserFromBearer } from "../_shared/supabase.ts";

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
    const pairingId = String(body.pairing_id ?? "").trim();
    if (!pairingId) {
      return jsonResponse({ error: "missing_pairing_id" }, 400, origin);
    }

    const admin = adminClient();

    const { data: pairing, error: selErr } = await admin
      .from("extension_pairings")
      .select("id, user_id, revoked_at")
      .eq("id", pairingId)
      .maybeSingle();

    if (selErr) {
      return jsonResponse({ error: "lookup_failed", detail: selErr.message }, 500, origin);
    }
    if (!pairing) {
      return jsonResponse({ error: "not_found" }, 404, origin);
    }
    if (pairing.user_id !== user.id) {
      return jsonResponse({ error: "forbidden" }, 403, origin);
    }
    if (pairing.revoked_at) {
      return jsonResponse({ ok: true, already_revoked: true }, 200, origin);
    }

    const { error: updErr } = await admin
      .from("extension_pairings")
      .update({ revoked_at: new Date().toISOString() })
      .eq("id", pairingId);

    if (updErr) {
      return jsonResponse({ error: "revoke_failed", detail: updErr.message }, 500, origin);
    }

    return jsonResponse({ ok: true }, 200, origin);
  } catch (err) {
    console.error(
      JSON.stringify({ event: "revoke_pairing_error", error: String(err) }),
    );
    return jsonResponse({ error: "internal_error", detail: String(err) }, 500, origin);
  }
});
