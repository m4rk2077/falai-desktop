"""Billing helpers (Stripe checkout links + Supabase portal function)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.backend.supabase_client import SupabaseClient, SupabaseError


class BillingError(RuntimeError):
    """Raised when billing action cannot be completed."""


@dataclass
class PortalSession:
    url: str
    expires_at: Optional[str] = None


class BillingService:
    def __init__(self, client: SupabaseClient):
        self.client = client

    @staticmethod
    def build_checkout_url(
        base_url: str,
        *,
        user_id: str,
        email: str = "",
        plan_code: str = "",
    ) -> str:
        """Append stable query params to a Stripe Payment Link URL."""
        raw = str(base_url or "").strip()
        if not raw:
            raise BillingError("checkout_link_missing")

        parsed = urlparse(raw)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise BillingError("checkout_link_invalid")

        q = dict(parse_qsl(parsed.query, keep_blank_values=True))
        uid = (user_id or "").strip()
        em = (email or "").strip()
        p = (plan_code or "").strip().lower()

        if uid:
            q["client_reference_id"] = uid
        if em:
            q["prefilled_email"] = em
        if p:
            q["plan"] = p

        new_query = urlencode(q, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    def create_portal_session(self, *, access_token: str, return_url: str = "") -> PortalSession:
        """Request a Stripe Customer Portal session URL from Supabase Edge Function."""
        payload: Dict[str, Any] = {}
        ru = str(return_url or "").strip()
        if ru:
            payload["return_url"] = ru

        data = self.client.function_call("stripe_portal_session", payload, jwt=access_token)
        if not isinstance(data, dict):
            raise BillingError("portal_response_invalid")

        url = str(data.get("url") or "").strip()
        if not url:
            raise BillingError("portal_url_missing")
        return PortalSession(url=url, expires_at=str(data.get("expires_at") or "").strip() or None)

    def get_plan_checkout_link(self, *, access_token: str, plan_code: str) -> str:
        """Fetch Stripe payment link for a plan from public.plans."""
        code = str(plan_code or "").strip().lower()
        if code not in ("start", "pro"):
            raise BillingError("invalid_plan_code")

        rows = self.client.table_select(
            "plans",
            select="code,stripe_payment_link_url,is_active",
            filters={
                "code": f"eq.{code}",
                "is_active": "eq.true",
                "limit": "1",
            },
            jwt=access_token,
        )
        if not isinstance(rows, list) or not rows:
            return ""

        link = str((rows[0] or {}).get("stripe_payment_link_url") or "").strip()
        if not link:
            return ""

        parsed = urlparse(link)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise BillingError("checkout_link_invalid")
        return link
