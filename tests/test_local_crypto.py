from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.security.local_crypto import LocalCrypto, LocalCryptoError


def _crypto_or_skip(tmp_path: Path) -> LocalCrypto:
    crypto = LocalCrypto(app_dir=tmp_path / "app")
    try:
        crypto.encrypt_bytes(b"probe")
    except LocalCryptoError as exc:
        pytest.skip(f"LocalCrypto unavailable in this runtime: {exc}")
    return crypto


def test_local_crypto_roundtrip_bytes(tmp_path: Path):
    crypto = _crypto_or_skip(tmp_path)
    payload = b"falai-security-test"
    encrypted = crypto.encrypt_bytes(payload)
    assert encrypted != payload
    assert crypto.decrypt_bytes(encrypted) == payload


def test_local_crypto_migrates_plaintext_json(tmp_path: Path):
    crypto = _crypto_or_skip(tmp_path)
    legacy = tmp_path / "history.json"
    secure = tmp_path / "history.enc"
    legacy.write_text(json.dumps([{"id": 1, "text": "ok"}]), encoding="utf-8")

    changed = crypto.migrate_json_file(legacy, secure, default_obj=[])
    assert changed is True
    assert secure.exists()
    assert not legacy.exists()
    assert crypto.read_json(secure, default=[]) == [{"id": 1, "text": "ok"}]
