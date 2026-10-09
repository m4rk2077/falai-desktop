from __future__ import annotations

from pathlib import Path

from src.backend.outbox_repo import OutboxRepo


def test_outbox_repo_persists_encrypted_payloads(tmp_path: Path):
    outbox_path = tmp_path / "outbox.enc"
    audio_dir = tmp_path / "outbox_audio"
    repo = OutboxRepo(outbox_path=outbox_path, audio_dir=audio_dir)

    wav_bytes = (b"RIFF" + b"\x01\x02\x03\x04") * 64
    item_id = repo.add_edge_transcribe(wav_bytes, {"language": "pt"})

    assert outbox_path.exists()
    outbox_raw = outbox_path.read_bytes()
    assert outbox_raw
    assert b"edge_transcribe" not in outbox_raw

    enc_audio = audio_dir / f"{item_id}.enc"
    assert enc_audio.exists()
    assert repo.get_audio_bytes(item_id) == wav_bytes
