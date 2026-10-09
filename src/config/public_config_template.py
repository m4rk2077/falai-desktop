"""
Public Supabase config used by the desktop client.

This file is a TEMPLATE. For a packaged build (setup.exe), create:
  - src/config/public_config.py
and set:
  - SUPABASE_URL
- SUPABASE_ANON_KEY
- STRIPE_START_PAYMENT_LINK (opcional)
- STRIPE_PRO_PAYMENT_LINK (opcional)
- BILLING_PORTAL_RETURN_URL (opcional)

Important:
- SUPABASE_ANON_KEY is public by design (client-side).
- NEVER ship SUPABASE_SERVICE_ROLE_KEY in the desktop app.
"""

SUPABASE_URL = ""
SUPABASE_ANON_KEY = ""

# Optional billing links (public URLs). Keep empty if not configured yet.
STRIPE_START_PAYMENT_LINK = ""
STRIPE_PRO_PAYMENT_LINK = ""

# Where Stripe Customer Portal should return after management actions.
# This is used by backend functions and the desktop fallback UX.
BILLING_PORTAL_RETURN_URL = ""
