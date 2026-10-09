// FWEB-010 — generate_desktop_download_url
// POST /functions/v1/generate_desktop_download_url  { platform: 'windows'|'macos'|'linux' }
// Called by the PORTAL (authenticated). Verifies Pro subscription, returns a
// short-lived signed URL from Supabase Storage and audits in download_tokens.

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { jsonResponse, preflight } from "../_shared/cors.ts";
import { adminClient, resolveUserFromBearer } from "../_shared/supabase.ts";

const DOWNLOAD_BUCKET = Deno.env.get("FWEB_DOWNLOADS_BUCKET") ?? "desktop-builds";
const SIGNED_URL_TTL_SECONDS = 10 * 60; // 10 min

// Latest artifact naming convention. Can be overridden via env per platform.
function artifactPath(platform: string): string {
  const override = Deno.env.get(`FWEB_DOWNLOAD_${platform.toUpperCase()}_PATH`);
  if (override) return override;
  switch (platform) {
    case "windows":
      return "latest/FALAI-Setup-latest.exe";
    case "macos":
      return "latest/FALAI-latest.dmg";
    case "linux":
      return "latest/FALAI-latest.AppImage";
    default:
      return `latest/${platform}.bin`;
  }
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
    const platform = String(body.platform ?? "windows").toLowerCase();
    if (!["windows", "macos", "linux"].includes(platform)) {
      return jsonResponse({ error: "invalid_platform" }, 400, origin);
    }

    const admin = adminClient();

    // Check Pro entitlement: active/trialing subscription with plan tier = pro.
    const { data: sub, error: subErr } = await admin
      .from("subscriptions")
      .select("id, status, plan_id, plans:plan_id(code, tier)")
      .eq("user_id", user.id)
      .in("status", ["active", "trialing"])
      .order("current_period_end", { ascending: false })
      .limit(1)
      .maybeSingle();

    if (subErr) {
      return jsonResponse(
        { error: "subscription_lookup_failed", detail: subErr.message },
        500,
        origin,
      );
    }
    const plan = (sub?.plans as unknown as { code?: string; tier?: string } | null) ?? null;
    const tier = (plan?.tier ?? "").toLowerCase();
    if (!sub || tier !== "pro") {
      return jsonResponse(
        {
          error: "premium_required",
          reason: "pro_subscription_required",
          current_tier: tier || "none",
        },
        403,
        origin,
      );
    }

    const path = artifactPath(platform);

    // Create signed URL from storage. Fails if bucket/object doesn't exist.
    const { data: signed, error: signErr } = await admin.storage
      .from(DOWNLOAD_BUCKET)
      .createSignedUrl(path, SIGNED_URL_TTL_SECONDS);

    if (signErr || !signed?.signedUrl) {
      return jsonResponse(
        {
          error: "signed_url_failed",
          detail: signErr?.message ?? "no_url",
          bucket: DOWNLOAD_BUCKET,
          path,
        },
        404,
        origin,
      );
    }

    const expiresAt = new Date(Date.now() + SIGNED_URL_TTL_SECONDS * 1000).toISOString();

    // Audit: insert download_tokens row.
    const urlHash = await (async () => {
      const enc = new TextEncoder().encode(signed.signedUrl);
      const h = await crypto.subtle.digest("SHA-256", enc);
      return Array.from(new Uint8Array(h))
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("")
        .slice(0, 32);
    })();

    const { data: tokenRow, error: insErr } = await admin
      .from("download_tokens")
      .insert({
        user_id: user.id,
        artifact: path,
        platform,
        expires_at: expiresAt,
        user_agent: req.headers.get("user-agent")?.slice(0, 500) ?? null,
        signed_url_hash: urlHash,
      })
      .select("id")
      .single();

    if (insErr) {
      console.warn(
        JSON.stringify({ event: "download_audit_failed", err: insErr.message }),
      );
    }

    return jsonResponse(
      {
        download: {
          url: signed.signedUrl,
          expires_at: expiresAt,
          platform,
          artifact: path,
          token_id: tokenRow?.id ?? null,
        },
      },
      200,
      origin,
    );
  } catch (err) {
    console.error(
      JSON.stringify({ event: "generate_download_error", error: String(err) }),
    );
    return jsonResponse({ error: "internal_error", detail: String(err) }, 500, origin);
  }
});
