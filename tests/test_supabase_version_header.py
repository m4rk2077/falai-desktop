from __future__ import annotations

from src.backend.supabase_client import SupabaseClient, SupabaseConfig


def test_function_call_adds_x_app_version_header(monkeypatch):
    client = SupabaseClient(SupabaseConfig(url="https://example.supabase.co", anon_key="anon-key"))
    captured = {}

    def _fake_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["headers"] = kwargs.get("extra_headers") or {}
        return {"ok": True}

    monkeypatch.setattr(client, "_request", _fake_request)
    result = client.function_call("transcribe", {"hello": "world"})

    assert result == {"ok": True}
    assert captured["method"] == "POST"
    assert captured["path"] == "/functions/v1/transcribe"
    assert "X-App-Version" in captured["headers"]
    assert str(captured["headers"]["X-App-Version"]).strip() != ""
