"""Minimal Supabase REST client wrapper.

Uses Supabase REST/Auth endpoints without introducing SDK lock-in.
"""
from __future__ import annotations

import base64
import json
import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter


class SupabaseError(RuntimeError):
    """Raised when Supabase request fails."""

    def __init__(self, message: str, status_code: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


@dataclass
class SupabaseConfig:
    url: str
    anon_key: str
    service_role_key: str = ""
    timeout_seconds: int = 12


class SupabaseClient:
    """HTTP client for Supabase Auth and PostgREST."""

    def __init__(self, config: SupabaseConfig, use_service_role: bool = False):
        self.config = config
        self.use_service_role = use_service_role
        # Reuse HTTP connections (TLS + TCP keep-alive) to reduce request latency.
        self._session = requests.Session()
        adapter = HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=0)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session_lock = threading.Lock()

    @classmethod
    def from_env(cls, use_service_role: bool = False) -> "SupabaseClient":
        # Public (non-secret) defaults can be shipped with the app build, so end-users don't
        # need to create a .env. Real secrets must NEVER be shipped on the client.
        default_url = ""
        default_anon = ""
        try:
            from src.config.public_config import SUPABASE_URL as _DEFAULT_URL  # type: ignore
            from src.config.public_config import SUPABASE_ANON_KEY as _DEFAULT_ANON  # type: ignore

            default_url = (_DEFAULT_URL or "").strip()
            default_anon = (_DEFAULT_ANON or "").strip()
        except Exception:
            pass

        cfg = SupabaseConfig(
            url=(os.getenv("SUPABASE_URL", "") or default_url).rstrip("/"),
            anon_key=os.getenv("SUPABASE_ANON_KEY", "") or default_anon,
            service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", "") or "",
            timeout_seconds=int(os.getenv("SUPABASE_TIMEOUT_SECONDS", "12")),
        )
        if not cfg.url or not cfg.anon_key:
            raise SupabaseError("SUPABASE_URL/SUPABASE_ANON_KEY não configurados")
        anon_role = cls._jwt_role(cfg.anon_key)
        if anon_role == "service_role":
            raise SupabaseError(
                "SUPABASE_ANON_KEY inválida: chave service_role detectada. "
                "Use a anon key pública do projeto."
            )
        if use_service_role and not cfg.service_role_key:
            raise SupabaseError("SUPABASE_SERVICE_ROLE_KEY não configurado para modo service role")
        if use_service_role and cfg.service_role_key:
            srv_role = cls._jwt_role(cfg.service_role_key)
            if srv_role and srv_role != "service_role":
                raise SupabaseError("SUPABASE_SERVICE_ROLE_KEY inválida para modo service role")
        return cls(cfg, use_service_role=use_service_role)

    @staticmethod
    def _jwt_role(token: str) -> str:
        raw = str(token or "").strip()
        if raw.count(".") < 2:
            return ""
        try:
            payload_b64 = raw.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            decoded = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
            payload = json.loads(decoded.decode("utf-8"))
            role = payload.get("role")
            if isinstance(role, str):
                return role.strip().lower()
        except Exception:
            return ""
        return ""

    def _api_key(self) -> str:
        if self.use_service_role and self.config.service_role_key:
            return self.config.service_role_key
        return self.config.anon_key

    def _headers(self, jwt: str = "", extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        auth_token = str(jwt or self._api_key() or "").strip()
        if auth_token.lower().startswith("bearer "):
            auth_token = auth_token.split(" ", 1)[1].strip()
        headers = {
            "apikey": self._api_key(),
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        jwt: str = "",
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Any:
        url = f"{self.config.url}{path}"
        timeout = float(timeout_seconds) if timeout_seconds is not None else self.config.timeout_seconds
        with self._session_lock:
            response = self._session.request(
                method=method,
                url=url,
                headers=self._headers(jwt=jwt, extra=extra_headers),
                params=params,
                json=json_body,
                timeout=timeout,
            )
        if response.status_code >= 400:
            try:
                payload = response.json()
            except Exception:
                payload = response.text
            raise SupabaseError(
                f"Supabase request falhou: {response.status_code}",
                status_code=response.status_code,
                payload=payload,
            )
        if not response.text:
            return None
        try:
            return response.json()
        except Exception:
            return response.text

    # ------------------------------
    # Edge Functions
    # ------------------------------
    def function_call(
        self,
        function_name: str,
        payload: Dict[str, Any],
        *,
        jwt: str = "",
        extra_headers: Optional[Dict[str, str]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Any:
        """Call a Supabase Edge Function via HTTPS."""
        headers = dict(extra_headers or {})
        try:
            from src import __version__ as _APP_VERSION

            app_version = str(_APP_VERSION or "").strip()
        except Exception:
            app_version = ""
        if not app_version:
            app_version = str(os.getenv("FALAI_APP_VERSION", "") or "").strip() or "0.0.0"
        headers["X-App-Version"] = app_version
        return self._request(
            "POST",
            f"/functions/v1/{function_name}",
            jwt=jwt,
            json_body=payload,
            extra_headers=headers if headers else None,
            timeout_seconds=timeout_seconds,
        )

    # ------------------------------
    # Auth
    # ------------------------------
    def auth_login(self, email: str, password: str) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/auth/v1/token",
            params={"grant_type": "password"},
            json_body={"email": email, "password": password},
        )

    def auth_refresh(self, refresh_token: str) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/auth/v1/token",
            params={"grant_type": "refresh_token"},
            json_body={"refresh_token": refresh_token},
        )

    def auth_get_user(self, access_token: str) -> Dict[str, Any]:
        return self._request("GET", "/auth/v1/user", jwt=access_token)

    def auth_recover(self, email: str, redirect_to: str = "") -> Dict[str, Any]:
        params = {"redirect_to": redirect_to} if str(redirect_to or "").strip() else None
        payload = self._request(
            "POST",
            "/auth/v1/recover",
            params=params,
            json_body={"email": email},
        )
        if isinstance(payload, dict):
            return payload
        return {}

    # ------------------------------
    # PostgREST
    # ------------------------------
    def table_select(
        self,
        table: str,
        *,
        select: str = "*",
        filters: Optional[Dict[str, str]] = None,
        jwt: str = "",
    ) -> Any:
        params = {"select": select}
        if filters:
            params.update(filters)
        return self._request("GET", f"/rest/v1/{table}", jwt=jwt, params=params)

    def table_insert(
        self,
        table: str,
        payload: Dict[str, Any],
        *,
        jwt: str = "",
        return_representation: bool = True,
    ) -> Any:
        headers = {}
        if return_representation:
            headers["Prefer"] = "return=representation"
        return self._request(
            "POST",
            f"/rest/v1/{table}",
            jwt=jwt,
            json_body=payload,
            extra_headers=headers,
        )

    def table_upsert(
        self,
        table: str,
        payload: Dict[str, Any],
        *,
        on_conflict: str,
        jwt: str = "",
        return_representation: bool = True,
    ) -> Any:
        headers = {
            "Prefer": "resolution=merge-duplicates" + (",return=representation" if return_representation else ""),
        }
        return self._request(
            "POST",
            f"/rest/v1/{table}",
            jwt=jwt,
            params={"on_conflict": on_conflict},
            json_body=payload,
            extra_headers=headers,
        )

    def table_update(
        self,
        table: str,
        payload: Dict[str, Any],
        *,
        filters: Dict[str, str],
        jwt: str = "",
        return_representation: bool = True,
    ) -> Any:
        headers = {}
        if return_representation:
            headers["Prefer"] = "return=representation"
        return self._request(
            "PATCH",
            f"/rest/v1/{table}",
            jwt=jwt,
            params=filters,
            json_body=payload,
            extra_headers=headers,
        )

    def rpc(self, fn_name: str, payload: Dict[str, Any], *, jwt: str = "") -> Any:
        return self._request("POST", f"/rest/v1/rpc/{fn_name}", jwt=jwt, json_body=payload)
