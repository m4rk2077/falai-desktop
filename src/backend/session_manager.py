"""Session management helpers for Supabase Auth (client-side).

Goals:
- Refresh access_token proactively (before calling Edge Functions)
- Avoid concurrent refresh races (multiple threads) with a lock
- Distinguish "offline" vs "login required" so we don't log users out on bad internet
"""

from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import dataclass
from typing import Optional

import requests

from src.backend.auth_service import AuthService, AuthSession
from src.backend.supabase_client import SupabaseError


class OfflineError(RuntimeError):
    """Raised when we cannot reach Supabase (network/temporary backend issue)."""


class LoginRequiredError(RuntimeError):
    """Raised when the current refresh/session is invalid and user must login again."""


@dataclass
class TokenInfo:
    access_token: str
    exp_epoch_seconds: Optional[int] = None

    def ttl_seconds(self) -> Optional[int]:
        if not self.exp_epoch_seconds:
            return None
        try:
            return int(self.exp_epoch_seconds) - int(time.time())
        except Exception:
            return None


def decode_jwt_exp(access_token: str) -> Optional[int]:
    """Best-effort decode of JWT exp claim (epoch seconds)."""
    token = (access_token or "").strip()
    if not token:
        return None
    parts = token.split(".")
    if len(parts) < 2:
        return None

    payload_b64 = parts[1].encode("ascii", errors="ignore")
    # Add padding for base64 decoder.
    pad = b"=" * ((4 - (len(payload_b64) % 4)) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload_b64 + pad)
        obj = json.loads(raw.decode("utf-8", errors="replace"))
        exp = obj.get("exp", None)
        if exp is None:
            return None
        return int(exp)
    except Exception:
        return None


class SessionManager:
    """Wrapper around AuthService to keep the access_token fresh and stable."""

    def __init__(self, auth_service: AuthService):
        self.auth = auth_service
        self._refresh_lock = threading.Lock()

    def get_token_info(self) -> TokenInfo:
        token = ""
        try:
            token = self.auth.get_access_token()
        except Exception:
            token = ""
        return TokenInfo(access_token=token, exp_epoch_seconds=decode_jwt_exp(token))

    def ensure_fresh_access_token(self, *, min_ttl_seconds: int = 60) -> str:
        """Return a usable access_token, refreshing if it expires soon.

        Raises:
          OfflineError: network/temporary failure (keep session, do not logout)
          LoginRequiredError: refresh token invalid or missing (user must login again)
        """
        info = self.get_token_info()
        if not info.access_token:
            raise LoginRequiredError("missing_access_token")

        ttl = info.ttl_seconds()
        if ttl is None:
            # Token doesn't look like a JWT; keep going and let server decide.
            return info.access_token
        if ttl > int(min_ttl_seconds):
            return info.access_token
        return self.force_refresh_access_token()

    def force_refresh_access_token(self, *, ignore_ttl: bool = False) -> str:
        """Refresh access token.

        Args:
          ignore_ttl: when True, always hit refresh endpoint even if current token
            still has TTL. Use this after a real 401 to avoid reusing a revoked token.
        """
        with self._refresh_lock:
            # Another thread might have refreshed already.
            info = self.get_token_info()
            ttl = info.ttl_seconds()
            if (not ignore_ttl) and info.access_token and ttl is not None and ttl > 60:
                return info.access_token

            try:
                session: AuthSession = self.auth.refresh()
            except requests.exceptions.RequestException as exc:
                raise OfflineError("offline_refresh") from exc
            except SupabaseError as exc:
                # Invalid refresh_token or session revoked.
                code = getattr(exc, "status_code", None)
                if code in (400, 401, 403):
                    raise LoginRequiredError("refresh_invalid") from exc
                # Other errors (rate limit, 5xx) should be treated as temporary.
                raise OfflineError("refresh_failed") from exc
            except Exception as exc:
                raise OfflineError("refresh_failed") from exc

            token = (session.access_token or "").strip() or (self.auth.get_access_token() or "").strip()
            if not token:
                raise LoginRequiredError("missing_access_token_after_refresh")
            return token
