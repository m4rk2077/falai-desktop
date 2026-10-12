import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.config.settings import Settings


class FakeStore:
    data: dict = {}

    def get_secret(self, target):
        return self.data.get(target, "")

    def set_secret(self, target, value):
        if value:
            self.data[target] = value
        else:
            self.data.pop(target, None)

    def __getattr__(self, name):
        # Session-token API used by the settings security migration: irrelevant here.
        return lambda *args, **kwargs: ""


@pytest.fixture
def store(monkeypatch):
    FakeStore.data = {}
    monkeypatch.setattr("src.security.secure_store.SecureStore", FakeStore)
    monkeypatch.setattr("src.security.secure_store.get_secure_store", lambda: FakeStore())
    # Never read the developer's real .env (it holds a real key).
    monkeypatch.setattr("src.config.settings.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    yield FakeStore
    os.environ.pop("GROQ_API_KEY", None)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_groq_key_roundtrip_via_secure_store(tmp_path, store):
    settings = Settings(config_file=tmp_path / "config.json")
    assert settings.get_groq_api_key() == ""
    settings.set_groq_api_key("gsk_abc")
    os.environ.pop("GROQ_API_KEY", None)  # simulate a fresh start: only the encrypted store remains
    assert settings.get_groq_api_key() == "gsk_abc"
    settings.set_groq_api_key("")
    assert settings.get_groq_api_key() == ""


def test_local_onboarding_asks_groq_key(app, store, monkeypatch):
    monkeypatch.setenv("FALAI_RUNTIME_MODE", "local")
    from src.ui.onboarding import OnboardingDialog

    payloads = []
    dialog = OnboardingDialog(on_complete=payloads.append)
    assert not dialog.groq_key_input.isHidden()
    assert dialog.login_email.isHidden() and dialog.login_password.isHidden()

    dialog._continue_local_mode()
    assert payloads == [] and "chave Groq" in dialog.login_status.text()

    dialog.groq_key_input.setText("sk-wrong")
    dialog._continue_local_mode()
    assert payloads == [] and "gsk_" in dialog.login_status.text()

    dialog.groq_key_input.setText("gsk_ok")
    dialog._continue_local_mode()
    assert payloads[0]["groq_api_key"] == "gsk_ok" and payloads[0]["local_mode"] is True


def test_settings_page_saves_key_and_vocabulary(app, store, tmp_path):
    from src.ui.pages.pages import SettingsPage

    settings = Settings(config_file=tmp_path / "config.json")
    page = SettingsPage(settings)
    emitted = []
    page.settings_saved.connect(emitted.append)

    page._groq_key_input.setText("gsk_new")
    page._on_save_groq_key()
    assert settings.get_groq_api_key() == "gsk_new"

    page._vocab_input.setText("Supabase,  n8n , ,Hermes VPS")
    page._on_save_vocabulary()
    assert settings.get("personal_vocabulary") == "Supabase, n8n, Hermes VPS"
    assert emitted == [["groq_api_key"], ["personal_vocabulary"]]


def test_settings_page_hides_account_card_in_local_mode(app, store, tmp_path, monkeypatch):
    monkeypatch.setenv("FALAI_RUNTIME_MODE", "local")
    from src.ui.pages.pages import SettingsPage

    page = SettingsPage(Settings(config_file=tmp_path / "config.json"))
    assert page._btn_logout.parentWidget().parentWidget().isHidden()
