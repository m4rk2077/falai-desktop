"""
Settings management module
"""
import os
import json
import uuid
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

from src.utils.logger import get_logger
from src.utils.app_paths import (
    get_app_data_dir,
    get_config_path,
    get_history_path,
    get_legacy_history_path,
    get_outbox_audio_dir,
    get_outbox_path,
    get_legacy_outbox_path,
    ensure_app_data_dir,
)
from src.security.local_crypto import LocalCrypto
from src.security.secure_store import get_secure_store

logger = get_logger(__name__)


def coerce_bool(value: Any, default: bool = False) -> bool:
    """Safely coerce legacy bool-like values (e.g. "false", "0") to bool."""
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        return bool(default)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"1", "true", "yes", "on"}:
            return True
        if s in {"0", "false", "no", "off", ""}:
            return False
    return bool(default)


class Settings:
    """Manages application settings and configuration"""

    STORAGE_SECURITY_VERSION = 1
    
    DEFAULT_SETTINGS = {
        "language": "pt",
        "auto_paste": True,
        "activation_mode": "push_to_talk",  # push_to_talk, toggle, always_on
        "hotkey": "ctrl+shift",
        # Default to the light ("beige") theme for first install (better for beta onboarding).
        "theme": "beige",
        "gpt_correction": True,  # Enable GPT auto-correction
        "correction_style": "neutro",  # casual, formal, neutro
        # Text output formatting mode for corrected transcriptions.
        "message_format_mode": "balanced",  # balanced, message
        # Domain lexicon profile (deprecated — kept as "none" for compatibility).
        "domain_lexicon_profile": "none",
        "transcription_provider": "groq",  # openai, groq
        "corrector_provider": "groq",  # openai, groq
        "groq_stt_model": "whisper-large-v3-turbo",
        # Feed the last dictations (15 min window) to the corrector as reference (not to Whisper).
        "dictation_context": True,
        # Opt-in: keep the last 50 dictation clips locally (debug_audio/) to tune accuracy.
        "save_debug_audio": False,
        "groq_corrector_model": "openai/gpt-oss-120b",
        "launch_login": False,
        "show_dock": True,
        "show_floating": True,
        "dictation_fx": True,
        "mute_music": False,
        "onboarding_completed": False,
        "onboarding_version": 2,
        "auth_token": "",
        "user_email": "",
        "remember_me": False,
        "migration_version": 0,
        "storage_security_version": 0,
        "security_migration_failed": False,
        "security_migration_error": "",
        # Stable identifier for this device/install (no PII). Used for telemetry correlation.
        "device_id": "",
        # Beta: if offline, save audio locally and auto-send when internet returns.
        "offline_queue_enabled": True,
        # Updates (GitHub Releases) - beta "Option A" flow.
        "updates_enabled": True,
        "update_last_checked_at": 0.0,
        "update_available_version": "",
        "update_available_url": "",
        "update_release_url": "",
        "update_notified_version": "",
        # Best-effort hint for the Settings UI when checks fail (keeps users from thinking the button is broken).
        "update_last_error": "",
        # If an update was downloaded, keep its path so we can offer "Install now".
        "update_downloaded_version": "",
        "update_downloaded_path": "",
        "update_downloaded_at": 0.0,
        # Last speed tier observed from backend pipeline.
        "last_speed_tier": "trial",
        # Trial UX target: keep perceived response near ~4s for plan differentiation.
        "trial_latency_floor_ms": 4000,
    }
    
    def __init__(self, config_file: str | Path | None = None):
        """
        Initialize settings manager
        
        Args:
            config_file: Path to configuration file
        """
        ensure_app_data_dir()
        self.config_file = Path(config_file) if config_file is not None else get_config_path()
        self.settings = self.DEFAULT_SETTINGS.copy()
        
        # Load environment variables
        # Load .env from the project root (same folder that contains `src/`).
        # This makes behavior stable on Windows even when the process CWD changes (Startup shortcuts, etc).
        try:
            project_root = Path(__file__).resolve().parents[2]
            env_path = project_root / ".env"
            load_dotenv(dotenv_path=env_path, override=False)
            if env_path.exists():
                logger.info("Env loaded from %s", env_path)
        except Exception:
            # Fallback to default lookup behavior.
            load_dotenv()

        # Optional: also load .env from the user app data dir (useful for installed builds).
        try:
            app_env = get_app_data_dir() / ".env"
            load_dotenv(dotenv_path=app_env, override=False)
        except Exception:
            pass

        # Best-effort hint in logs (never prints secrets).
        if not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_ANON_KEY")):
            # For installed builds, we ship SUPABASE_URL + SUPABASE_ANON_KEY via src/config/public_config.py
            # (these are public values). Avoid confusing "not configured" warnings in that case.
            try:
                from src.config.public_config import SUPABASE_URL as _DEFAULT_URL  # type: ignore
                from src.config.public_config import SUPABASE_ANON_KEY as _DEFAULT_ANON  # type: ignore

                if (_DEFAULT_URL or "").strip() and (_DEFAULT_ANON or "").strip():
                    logger.info("Supabase public config carregado (build) - .env não é necessário")
                else:
                    logger.warning(
                        "Supabase não configurado: faltando SUPABASE_URL/SUPABASE_ANON_KEY no .env e no public_config"
                    )
            except Exception:
                logger.warning(
                    "Supabase não configurado: faltando SUPABASE_URL/SUPABASE_ANON_KEY no .env e no public_config"
                )

        # Migrate legacy local config on first run (from ./data/config.json to APPDATA).
        self._migrate_legacy_config()
        
        # Load settings from file if exists
        self.load()
        self._migrate_security_storage()
        self._ensure_device_id()

    def _ensure_device_id(self) -> None:
        """Generate a stable device_id once (no PII)."""
        try:
            current = str(self.settings.get("device_id", "") or "").strip()
            if current:
                return
            self.settings["device_id"] = str(uuid.uuid4())
            self.save()
        except Exception:
            # Best-effort; never block startup.
            logger.warning("Could not generate device_id", exc_info=True)

    def _migrate_legacy_config(self) -> None:
        """Move old ./data/config.json to the user-writable folder.

        This prevents failures when the app is installed under Program Files.
        """
        try:
            if self.config_file.exists():
                return

            legacy_candidates = []
            # Typical dev path (project folder)
            legacy_candidates.append(Path("data") / "config.json")
            try:
                project_root = Path(__file__).resolve().parents[2]
                legacy_candidates.append(project_root / "data" / "config.json")
            except Exception:
                pass

            legacy_path = None
            for p in legacy_candidates:
                try:
                    if p.exists():
                        legacy_path = p
                        break
                except Exception:
                    continue

            if not legacy_path:
                return

            # Copy file bytes (preserves formatting/encoding).
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            self.config_file.write_bytes(legacy_path.read_bytes())
            logger.info("Config migrated to %s", self.config_file)
        except Exception:
            # Migration is best-effort. If anything fails, app will just use defaults.
            logger.warning("Could not migrate legacy config", exc_info=True)

    def _migrate_security_storage(self) -> None:
        """One-time migration for secure session + encrypted local storage."""
        try:
            version = int(self.settings.get("storage_security_version", 0) or 0)
        except Exception:
            version = 0
        if version >= self.STORAGE_SECURITY_VERSION:
            return

        try:
            self._migrate_legacy_session_tokens()
            self._migrate_legacy_sensitive_files()
            self.settings["storage_security_version"] = self.STORAGE_SECURITY_VERSION
            self.settings["security_migration_failed"] = False
            self.settings["security_migration_error"] = ""
            self.save()
            logger.info("Storage security migration completed (v=%s)", self.STORAGE_SECURITY_VERSION)
        except Exception as exc:
            self.settings["security_migration_failed"] = True
            self.settings["security_migration_error"] = str(exc)[:300]
            try:
                self.save()
            except Exception:
                pass
            logger.error("Storage security migration failed", exc_info=True)

    @staticmethod
    def _strip_bearer(raw: str) -> str:
        token = str(raw or "").strip()
        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()
        return token

    def _migrate_legacy_session_tokens(self) -> None:
        """Move legacy plaintext tokens from settings JSON to secure store."""
        store = get_secure_store()
        remember_me = bool(self.settings.get("remember_me", False))

        legacy_access = self._strip_bearer(str(self.settings.get("access_token", "") or ""))
        legacy_refresh = self._strip_bearer(str(self.settings.get("refresh_token", "") or ""))
        if legacy_access and remember_me:
            store.set_access_token(legacy_access)
        if legacy_refresh and remember_me:
            store.set_refresh_token(legacy_refresh)

        meta = store.get_session_meta()
        meta.update(
            {
                "remember_me": bool(remember_me),
                "user_email": str(self.settings.get("user_email", "") or "").strip(),
                "auth_token": str(self.settings.get("auth_token", "") or "").strip(),
                "migrated_from": "legacy_config_json",
            }
        )
        store.set_session_meta(meta)

        # Remove any plaintext secret fields from in-memory settings payload.
        self.settings.pop("access_token", None)
        self.settings.pop("refresh_token", None)

        # For maximum-session mode, remember_me=false means no persisted refresh session.
        if not remember_me:
            store.clear_session_tokens()

    def _migrate_legacy_sensitive_files(self) -> None:
        """Encrypt legacy plaintext local data files."""
        crypto = LocalCrypto()
        # Fail fast if crypto backend is unavailable.
        crypto.encrypt_bytes(b"falai-security-check")

        history_legacy = get_legacy_history_path()
        history_secure = get_history_path()
        outbox_legacy = get_legacy_outbox_path()
        outbox_secure = get_outbox_path()
        audio_dir = get_outbox_audio_dir()

        crypto.migrate_json_file(history_legacy, history_secure, default_obj=[])
        crypto.migrate_json_file(outbox_legacy, outbox_secure, default_obj=[])

        for wav in audio_dir.glob("*.wav"):
            secure_audio = wav.with_suffix(".enc")
            crypto.migrate_binary_file(wav, secure_audio)

        # Cleanup stale migration backups (24h TTL).
        crypto.cleanup_backups(history_legacy.parent, ttl_seconds=24 * 3600)
        crypto.cleanup_backups(audio_dir, ttl_seconds=24 * 3600)
    
    def load(self):
        """Load settings from JSON file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    saved_settings = json.load(f)
                    self.settings.update(saved_settings)
                if self._normalize_legacy_types():
                    self.save()
                logger.info("Settings loaded from %s", self.config_file)
                self._validate_hotkey()
            except Exception as e:
                logger.error("Error loading settings. Using defaults.", exc_info=True)
        else:
            logger.info("No config file found. Using default settings.")

    def _normalize_legacy_types(self) -> bool:
        """Normalize legacy serialized types (mainly bool flags saved as strings)."""
        changed = False
        for key, default_value in self.DEFAULT_SETTINGS.items():
            if not isinstance(default_value, bool):
                continue
            raw = self.settings.get(key, default_value)
            normalized = coerce_bool(raw, default=default_value)
            if raw is not normalized:
                self.settings[key] = normalized
                changed = True
        return changed

    def _is_valid_hotkey(self, hotkey: str) -> bool:
        if not hotkey:
            return False
        parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
        if not parts:
            return False
        modifiers = {"ctrl", "shift", "alt", "win", "cmd"}
        specials = {"space", "enter", "tab", "esc"}
        for p in parts:
            if p in modifiers:
                continue
            if p in specials:
                continue
            if len(p) == 1:
                continue
            return False
        has_modifier = any(p in modifiers for p in parts)
        if not has_modifier:
            return False
        has_key = any((len(p) == 1) or (p in specials) for p in parts)
        modifier_count = sum(1 for p in parts if p in modifiers)
        if not has_key and modifier_count < 2:
            return False
        return True

    def _validate_hotkey(self):
        hotkey = self.settings.get("hotkey", self.DEFAULT_SETTINGS["hotkey"])
        if not self._is_valid_hotkey(hotkey):
            logger.warning("Invalid hotkey '%s'. Resetting to default.", hotkey)
            self.settings["hotkey"] = self.DEFAULT_SETTINGS["hotkey"]
            self.save()
    
    def save(self):
        """Save settings to JSON file"""
        try:
            # Secrets must never be persisted in config.json.
            self.settings.pop("access_token", None)
            self.settings.pop("refresh_token", None)
            # Create data directory if it doesn't exist
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            
            logger.info("Settings saved to %s", self.config_file)
            
        except Exception as e:
            logger.error("Error saving settings", exc_info=True)

    def is_security_ready(self) -> bool:
        try:
            version = int(self.settings.get("storage_security_version", 0) or 0)
        except Exception:
            version = 0
        failed = bool(self.settings.get("security_migration_failed", False))
        return (version >= self.STORAGE_SECURITY_VERSION) and (not failed)

    def get_security_migration_error(self) -> str:
        try:
            return str(self.settings.get("security_migration_error", "") or "").strip()
        except Exception:
            return ""
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value"""
        return self.settings.get(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a setting value coerced to bool for legacy compatibility."""
        return coerce_bool(self.settings.get(key, default), default=default)
    
    def set(self, key: str, value: Any):
        """Set a setting value"""
        self.settings[key] = value
    
    def get_api_key(self) -> str:
        """Get OpenAI API key from environment"""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY not found in environment variables. "
                "Please create a .env file with your API key."
            )
        return api_key
    
    def get_groq_api_key(self) -> str:
        """Get Groq API key from environment"""
        api_key = os.getenv("GROQ_API_KEY")
        # Don't raise error here, as it might not be configured yet
        return api_key or ""
    
    def get_all(self) -> Dict[str, Any]:
        """Get all settings"""
        return self.settings.copy()
    
    def reset_to_defaults(self):
        """Reset all settings to defaults"""
        self.settings = self.DEFAULT_SETTINGS.copy()
        self.save()
