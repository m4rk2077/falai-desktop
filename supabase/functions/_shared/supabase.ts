// Shared Supabase client builders for FWEB edge functions.
import { createClient, SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2";

export function requireEnv(name: string, ...fallbacks: string[]): string {
  for (const key of [name, ...fallbacks]) {
    const v = Deno.env.get(key);
    if (v) return v;
  }
  throw new Error(`Missing required env: ${name}`);
}

export function getSupabaseUrl(): string {
  return requireEnv("EDGE_SUPABASE_URL", "SUPABASE_URL");
}

export function getAnonKey(): string {
  return requireEnv("EDGE_SUPABASE_ANON_KEY", "SUPABASE_ANON_KEY");
}

export function getServiceRoleKey(): string {
  return requireEnv(
    "EDGE_SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SERVICE_ROLE_KEY",
  );
}

export function adminClient(): SupabaseClient {
  return createClient(getSupabaseUrl(), getServiceRoleKey(), {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

export async function resolveUserFromBearer(
  authHeader: string | null,
): Promise<{ user: { id: string; email: string | null } | null; error: string | null }> {
  const raw = (authHeader ?? "").replace(/^Bearer\s+/i, "").trim();
  if (!raw) return { user: null, error: "missing_authorization" };
  try {
    const client = createClient(getSupabaseUrl(), getAnonKey(), {
      auth: { persistSession: false, autoRefreshToken: false },
      global: { headers: { Authorization: `Bearer ${raw}` } },
    });
    const { data, error } = await client.auth.getUser(raw);
    if (error || !data?.user) return { user: null, error: error?.message ?? "user_not_found" };
    return {
      user: { id: data.user.id, email: data.user.email ?? null },
      error: null,
    };
  } catch (err) {
    return { user: null, error: String(err) };
  }
}

export async function sha256Hex(value: string): Promise<string> {
  const enc = new TextEncoder().encode(value);
  const hash = await crypto.subtle.digest("SHA-256", enc);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function randomToken(byteLen = 32): string {
  const bytes = new Uint8Array(byteLen);
  crypto.getRandomValues(bytes);
  // URL-safe base64
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}
