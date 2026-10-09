"""Authentication service backed by Supabase Auth."""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.utils.logger import get_logger
from src.backend.supabase_client import SupabaseClient, SupabaseError
from src.security.secure_store import SecureStore, get_secure_store

logger = get_logger(__name__)


@dataclass
class AuthSession:
    access_token: str
    refresh_token: str
    user_id: str
    email: str
    expires_in: int


class AuthService:
    def __init__(self, client: SupabaseClient, settings=None, secure_store: Optional[SecureStore] = None):
        self.client = client
        self.settings = settings
        self.secure_store = secure_store or get_secure_store()
        self._access_token_cache = ""
        self._refresh_token_cache = ""

        # Best-effort warm cache from secure store for remember_me sessions.
        try:
            self._access_token_cache = (self.secure_store.get_access_token() or "").strip()
        except Exception:
            self._access_token_cache = ""
        try:
            self._refresh_token_cache = (self.secure_store.get_refresh_token() or "").strip()
        except Exception:
            self._refresh_token_cache = ""

    def login(self, email: str, password: str, remember_me: bool = False) -> AuthSession:
        payload = self.client.auth_login(email=email, password=password)
        session = self._parse_session(payload)
        self._persist_session(session, remember_me=remember_me)
        return session

    def refresh(self, refresh_token: Optional[str] = None) -> AuthSession:
        token = (refresh_token or self._refresh_token_cache or self.get_refresh_token() or "").strip()
        if not token:
            raise SupabaseError("Refresh token ausente")
        payload = self.client.auth_refresh(refresh_token=token)
        session = self._parse_session(payload)
        self._persist_session(session, remember_me=self._get_setting("remember_me", False))
        return session

    def request_password_reset(self, email: str, redirect_to: str = "") -> None:
        mail = str(email or "").strip()
        if not mail:
            raise ValueError("E-mail é obrigatório para recuperar senha.")
        self.client.auth_recover(email=mail, redirect_to=redirect_to)

    def get_current_user(self) -> Dict[str, Any]:
        access_token = self.get_access_token()
        if not access_token:
            raise SupabaseError("Sessão não encontrada")
        return self.client.auth_get_user(access_token=access_token)

    def logout(self, *, keep_email: bool = False) -> None:
        self._access_token_cache = ""
        self._refresh_token_cache = ""
        try:
            self.secure_store.clear_session_tokens()
        except Exception:
            pass
        if not self.settings:
            return
        remembered_email = str(self.settings.get("user_email", "") or "").strip()
        remembered = bool(self.settings.get("remember_me", False))
        self.settings.set("auth_token", "")
        if not (keep_email and remembered and remembered_email):
            self.settings.set("user_email", "")
        self.settings.set("remember_me", False)
        self.settings.save()

    def is_authenticated(self) -> bool:
        return bool(self.get_access_token())

    def get_access_token(self) -> str:
        token = str(self._access_token_cache or "").strip()
        if token:
            return token
        try:
            token = str(self.secure_store.get_access_token() or "").strip()
        except Exception as exc:
            raise SupabaseError("Sessão indisponível. Faça login novamente.") from exc
        self._access_token_cache = token
        return token

    def get_refresh_token(self) -> str:
        token = str(self._refresh_token_cache or "").strip()
        if token:
            return token
        try:
            token = str(self.secure_store.get_refresh_token() or "").strip()
        except Exception:
            token = ""
        self._refresh_token_cache = token
        return token

    def _parse_session(self, payload: Dict[str, Any]) -> AuthSession:
        session_payload = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        user = payload.get("user") or session_payload.get("user") or {}
        return AuthSession(
            access_token=payload.get("access_token", "") or session_payload.get("access_token", ""),
            refresh_token=payload.get("refresh_token", "") or session_payload.get("refresh_token", ""),
            user_id=user.get("id", ""),
            email=user.get("email", ""),
            expires_in=int(payload.get("expires_in", 0) or session_payload.get("expires_in", 0) or 0),
        )

    def _persist_session(self, session: AuthSession, remember_me: bool) -> None:
        access_token = str(session.access_token or "").strip()
        refresh_token = str(session.refresh_token or "").strip()
        if access_token.lower().startswith("bearer "):
            access_token = access_token.split(" ", 1)[1].strip()
        if refresh_token.lower().startswith("bearer "):
            refresh_token = refresh_token.split(" ", 1)[1].strip()

        self._access_token_cache = access_token
        self._refresh_token_cache = refresh_token

        try:
            # Maximum-session mode: only remember_me sessions are persisted across restarts.
            if remember_me:
                self.secure_store.set_access_token(access_token)
                self.secure_store.set_refresh_token(refresh_token)
            else:
                self.secure_store.delete_access_token()
                self.secure_store.delete_refresh_token()
            self.secure_store.set_session_meta(
                {
                    "user_id": str(session.user_id or ""),
                    "email": str(session.email or ""),
                    "remember_me": bool(remember_me),
                    "updated_at": int(time.time()),
                }
            )
        except Exception as exc:
            # Any secure store issue must force re-login and avoid partial session state.
            self._access_token_cache = ""
            self._refresh_token_cache = ""
            raise SupabaseError("Falha ao proteger sessão local. Faça login novamente.") from exc

        if self.settings:
            self.settings.set("auth_token", f"supabase:{session.user_id}" if session.user_id else "")
            self.settings.set("user_email", session.email or "")
            self.settings.set("remember_me", bool(remember_me))
            self.settings.save()
        self._log_session_debug(access_token=access_token, refresh_token=refresh_token, user_id=session.user_id)

    @staticmethod
    def _jwt_claims(token: str) -> Dict[str, Any]:
        raw = str(token or "").strip()
        if raw.lower().startswith("bearer "):
            raw = raw.split(" ", 1)[1].strip()
        if raw.count(".") < 2:
            return {}
        try:
            payload_b64 = raw.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            decoded = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
            obj = json.loads(decoded.decode("utf-8"))
            if isinstance(obj, dict):
                return obj
        except Exception:
            return {}
        return {}

    def _log_session_debug(self, *, access_token: str, refresh_token: str, user_id: str) -> None:
        """Diagnostics only; never log full tokens."""
        try:
            claims = self._jwt_claims(access_token)
            now = int(time.time())
            exp = claims.get("exp")
            ttl = int(exp) - now if isinstance(exp, (int, float)) else None
            logger.info(
                "Auth session persisted: user_id=%s remember_me=%s access_len=%s access_dots=%s refresh_len=%s ttl_s=%s",
                user_id or "",
                bool(self._get_setting("remember_me", False)),
                len(str(access_token or "")),
                str(access_token or "").count("."),
                len(str(refresh_token or "")),
                str(ttl if ttl is not None else ""),
            )
        except Exception:
            pass

    def _get_setting(self, key: str, default: Any):
        if not self.settings:
            return default
        return self.settings.get(key, default)
