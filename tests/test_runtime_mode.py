from src.config.runtime_mode import CLOUD, LOCAL, get_runtime_mode, is_local_runtime


def test_local_mode_is_the_safe_default(monkeypatch):
    monkeypatch.delenv("FALAI_RUNTIME_MODE", raising=False)

    assert get_runtime_mode() == LOCAL
    assert is_local_runtime() is True


def test_cloud_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("FALAI_RUNTIME_MODE", "cloud")

    assert get_runtime_mode() == CLOUD
    assert is_local_runtime() is False


def test_unknown_mode_stays_local(monkeypatch):
    monkeypatch.setenv("FALAI_RUNTIME_MODE", "anything-else")

    assert get_runtime_mode() == LOCAL
