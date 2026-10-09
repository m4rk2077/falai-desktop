// FWEB shared CORS helper used by extension-facing edge functions.
// Accepts configured origins + any chrome-extension://<id>.

const DEFAULT_ALLOWED = [
  "https://falai.app",
  "https://www.falai.app",
  "https://portal.falai.app",
  "http://localhost:3000",
  "http://localhost:3001",
  "http://127.0.0.1:3000",
  "http://127.0.0.1:3001",
];

const BASE: Record<string, string> = {
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-app-version",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  Vary: "Origin",
};

export function getAllowedOrigins(): string[] {
  const raw = (Deno.env.get("ALLOWED_ORIGINS") ?? "").trim();
  if (!raw) return DEFAULT_ALLOWED;
  const parsed = raw.split(",").map((s) => s.trim()).filter(Boolean);
  return parsed.length ? parsed : DEFAULT_ALLOWED;
}

export function isAllowedOrigin(origin: string, allowed: string[]): boolean {
  if (allowed.includes("*")) return true;
  if (allowed.includes(origin)) return true;
  if (origin.startsWith("chrome-extension://")) return true;
  return false;
}

export function corsHeaders(origin: string | null): Record<string, string> {
  const allowed = getAllowedOrigins();
  if (allowed.includes("*")) {
    return { ...BASE, "Access-Control-Allow-Origin": "*" };
  }
  const effective = origin && isAllowedOrigin(origin, allowed) ? origin : allowed[0];
  return { ...BASE, "Access-Control-Allow-Origin": effective };
}

export function jsonResponse(
  body: unknown,
  status = 200,
  origin: string | null = null,
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...corsHeaders(origin),
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}

export function preflight(origin: string | null): Response {
  return new Response("ok", { headers: corsHeaders(origin) });
}
