from __future__ import annotations

from dataclasses import dataclass

from src.backend.auth_service import AuthService


class _FakeSettings:
    def __init__(self):
        self.data = {"remember_me": False, "user_email": "", "auth_token": ""}
        self.saved = 0

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        self.saved += 1


@dataclass
class _FakeSession:
    access: str = ""
    refresh: str = ""
    meta: dict | None = None


class _FakeSecureStore:
    def __init__(self):
        self.state = _FakeSession(meta={})

    def get_access_token(self):
        return self.state.access

    def get_refresh_token(self):
        return self.state.refresh

    def set_access_token(self, token: str):
        self.state.access = token

    def set_refresh_token(self, token: str):
        self.state.refresh = token

    def delete_access_token(self):
        self.state.access = ""

    def delete_refresh_token(self):
        self.state.refresh = ""

    def clear_session_tokens(self):
        self.state.access = ""
        self.state.refresh = ""
        self.state.meta = {}

    def set_session_meta(self, meta):
        self.state.meta = dict(meta or {})


class _FakeClient:
    def auth_login(self, email: str, password: str):
        return {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_in": 3600,
            "user": {"id": "u1", "email": email},
        }

    def auth_refresh(self, refresh_token: str):
        if refresh_token != "refresh-1":
            raise RuntimeError("unexpected refresh token")
        return {
            "access_token": "access-2",
            "refresh_token": "refresh-2",
            "expires_in": 3600,
            "user": {"id": "u1", "email": "user@example.com"},
        }


def test_auth_service_remember_false_does_not_persist_between_restarts():
    settings = _FakeSettings()
    store = _FakeSecureStore()
    client = _FakeClient()

    auth = AuthService(client, settings=settings, secure_store=store)
    auth.login("user@example.com", "secret", remember_me=False)

    assert auth.get_access_token() == "access-1"
    assert auth.get_refresh_token() == "refresh-1"
    assert store.get_access_token() == ""
    assert store.get_refresh_token() == ""

    # New AuthService instance simulates app restart.
    auth_after_restart = AuthService(client, settings=settings, secure_store=store)
    assert auth_after_restart.get_access_token() == ""
    assert auth_after_restart.get_refresh_token() == ""


def test_auth_service_remember_true_persists_and_logout_clears_secure_store():
    settings = _FakeSettings()
    store = _FakeSecureStore()
    client = _FakeClient()

    auth = AuthService(client, settings=settings, secure_store=store)
    auth.login("user@example.com", "secret", remember_me=True)

    assert store.get_access_token() == "access-1"
    assert store.get_refresh_token() == "refresh-1"
    assert settings.get("remember_me") is True

    auth_after_restart = AuthService(client, settings=settings, secure_store=store)
    assert auth_after_restart.get_access_token() == "access-1"
    assert auth_after_restart.get_refresh_token() == "refresh-1"

    auth_after_restart.logout(keep_email=True)
    assert store.get_access_token() == ""
    assert store.get_refresh_token() == ""
    assert settings.get("remember_me") is False
