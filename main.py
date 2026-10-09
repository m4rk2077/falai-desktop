"""
FALAI - Voice Transcription App
Main application entry point (Tray-first architecture)
PySide6/Qt implementation
"""
import os
import base64
import json
import hashlib
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote
import webbrowser
from pathlib import Path
import numpy as np
import requests

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.logger import setup_logging, get_logger

_log_path = setup_logging()
logger = get_logger(__name__)
logger.info("Logging initialized: %s", _log_path)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from PySide6.QtCore import QTimer, QObject, Signal, QtMsgType, qInstallMessageHandler


def _qt_message_handler(mode: QtMsgType, context, message: str):
    # Qt sometimes emits noisy, non-actionable font warnings on Windows when stylesheets use px sizes.
    # We filter these to keep logs readable for users.
    if "QFont::setPointSize" in message:
        return
    try:
        sys.__stderr__.write(message + "\n")
    except Exception:
        pass


qInstallMessageHandler(_qt_message_handler)

def _set_windows_app_id(app_id: str):
    if sys.platform != "win32":
        return
    try:
        import ctypes  # local import to avoid non-windows issues
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        logger.warning("Failed to set AppUserModelID", exc_info=True)

from src.audio.recorder import AudioRecorder
from src.audio.transcriber import Transcriber
from src.audio.transcriber_groq import GroqTranscriber
from src.audio.wav_utils import numpy_to_wav_bytes
from src.config.plan_rules import access_block_message as shared_access_block_message
from src.config.plan_rules import effective_message_format_mode
from src.config.settings import Settings
from src.config.runtime_mode import get_runtime_mode, is_local_runtime
from src.utils.clipboard import ClipboardManager
from src.utils.hotkeys import HotkeyManager
from src.utils.history import TranscriptionHistory
from src.utils.groq_corrector import GroqCorrector
from src.utils.message_formatter import format_message_blocks
from src.utils.dictation_memory import DictationMemory, TextReplacements, save_debug_sample
from src.utils.window_manager import WindowManager
from src.utils.ui_state import UiStateController, UiState
from src.utils.sound_fx import play_start, play_stop, play_error
from src.utils.system_audio import SystemAudioDucker
from src.utils.startup import enable_startup, disable_startup
from src.ui.main_window import MainWindow
from src.ui.tray import TrayManager
from src.ui.floating_bar import FloatingBar
from src.ui.theme import get_stylesheet

from src.backend.supabase_client import SupabaseClient, SupabaseError
from src.backend.auth_service import AuthService
from src.backend.edge_transcribe_service import EdgeTranscribeService
from src.backend.client_events_repo import ClientEventsRepo
from src.backend.lead_funnel_service import LeadFunnelService
from src.backend.outbox_repo import OutboxLimits, OutboxRepo
from src.backend.outbox_worker import OutboxWorker
from src.backend.session_manager import LoginRequiredError, OfflineError, SessionManager
from src.backend.update_service import GitHubReleasesUpdateService
from src.utils.app_paths import get_outbox_audio_dir, get_outbox_path, get_updates_dir

PASSWORD_RESET_REDIRECT_URL = "https://falai.app/reset-password"


class HotkeySignals(QObject):
    """Signals for hotkey events (thread-safe communication)"""
    hotkey_pressed = Signal(bool)  # True = pressed, False = released


class UiDispatcher(QObject):
    """Signals para atualizacoes de UI (thread-safe)"""
    state_changed = Signal(str, object)  # state, message
    transcription_ready = Signal(str)
    notify = Signal(str, str)  # title, message
    update_download_started = Signal(str)  # version
    update_download_progress = Signal(int)  # percent (0-100) or -1 (indeterminate)
    update_download_completed = Signal(str)  # local path
    update_download_failed = Signal(str)  # message
    open_main = Signal()
    open_settings = Signal()
    open_history = Signal()
    open_stats = Signal()
    quit_requested = Signal()


class FalaiApp:
    """Main application class - Tray-first architecture with PySide6"""

    def __init__(self):
        # Initialize Qt Application
        _set_windows_app_id("FALAI.App")
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)  # Keep running in tray

        # Global app icon (window/taskbar)
        icon_path = Path(__file__).parent / "assets" / "icons" / "app.ico"
        if icon_path.exists():
            self.app.setWindowIcon(QIcon(str(icon_path)))
        else:
            icon_png = Path(__file__).parent / "assets" / "icons" / "app.png"
            if icon_png.exists():
                self.app.setWindowIcon(QIcon(str(icon_png)))

        # Initialize settings
        self.settings = Settings()
        self.runtime_mode = get_runtime_mode()
        self._local_runtime = is_local_runtime()
        try:
            if not self.settings.is_security_ready():
                logger.error("Security migration is not ready: %s", self.settings.get_security_migration_error() or "unknown")
        except Exception:
            logger.error("Security migration status unavailable")
        current_theme = self.settings.get("theme", "dark")
        self.app.setStyleSheet(get_stylesheet(current_theme))
        self._root_dir = Path(__file__).parent

        # Initialize components that don't need API Key
        self.clipboard = ClipboardManager()
        self.hotkey_manager = HotkeyManager()
        self.window_manager = WindowManager()
        self.last_active_window = None
        self._audio_ducker = SystemAudioDucker()

        self._floating_enabled = self.settings.get("show_floating", True)
        self._sound_fx_enabled = self.settings.get("dictation_fx", True)
        self._duck_music_enabled = self.settings.get("mute_music", False)

        # Recording state lock
        self._is_recording = False

        # Main window reference (lazy loaded)
        self._main_window = None

        # Update download state (prevents multiple concurrent downloads).
        self._update_download_lock = threading.Lock()
        self._update_download_thread = None

        # Initialize floating bar
        self.floating_bar = FloatingBar()

        # Dispatcher de UI (thread-safe)
        self.ui_dispatcher = UiDispatcher()
        self.ui_dispatcher.state_changed.connect(self._apply_ui_state)
        self.ui_dispatcher.transcription_ready.connect(self._on_transcription_ready)
        self.ui_dispatcher.notify.connect(self._on_notify)
        self.ui_dispatcher.update_download_started.connect(self._on_update_download_started)
        self.ui_dispatcher.update_download_progress.connect(self._on_update_download_progress)
        self.ui_dispatcher.update_download_completed.connect(self._on_update_download_completed)
        self.ui_dispatcher.update_download_failed.connect(self._on_update_download_failed)
        # Thread-safe UI actions (tray/hotkey threads can emit these signals).
        self.ui_dispatcher.open_main.connect(self._show_main_window)
        self.ui_dispatcher.open_settings.connect(self.open_settings)
        self.ui_dispatcher.open_history.connect(self.open_history)
        self.ui_dispatcher.open_stats.connect(self.open_stats)
        self.ui_dispatcher.quit_requested.connect(self._do_quit)

        # Controlador de estados de UI
        self.ui_state = UiStateController(
            dispatch=self.ui_dispatcher.state_changed.emit,
            auto_reset_ms=1200,
            error_auto_reset_ms=2000,
            watchdog_ms=15000,
        )

        # Timer para atualizar waveform com nivel real do microfone
        self._level_timer = QTimer()
        self._level_timer.setInterval(50)
        self._level_timer.timeout.connect(self._update_audio_level)

        # Hotkey signals for thread-safe communication
        self.hotkey_signals = HotkeySignals()
        self.hotkey_signals.hotkey_pressed.connect(self._handle_hotkey)

        # Initialize tray icon
        icon_path = Path(__file__).parent / "assets" / "icons" / "app.png"
        self.tray = TrayManager(str(icon_path))
        self.tray.set_callbacks(
            on_settings=self._open_settings_from_tray,
            on_history=self._open_history_from_tray,
            on_stats=self._open_stats_from_tray,
            on_quit=self._quit_app,
            on_click=self._open_main_window_from_tray,
            on_update=self._on_update_menu_clicked,
        )

        # Always initialize recorder (doesn't need API Key)
        try:
            self.recorder = AudioRecorder(sample_rate=16000, channels=1)
        except Exception as e:
            logger.error("Error initializing audio recorder", exc_info=True)
            self.recorder = None

        # Cloud services are opt-in. Local mode transcribes directly with Groq.
        self.supabase = None
        self.auth_service = None
        self.edge_transcriber = None
        self.lead_funnel_service = None
        self.session_manager = None
        self.client_events_repo = None
        self.outbox_repo = None
        self.outbox_worker = None
        self._outbox_thread = None
        if self._local_runtime:
            logger.info("Local runtime: Supabase/Auth/Edge disabled")
        else:
            try:
                self.supabase = SupabaseClient.from_env()
                self.auth_service = AuthService(self.supabase, settings=self.settings)
                self.edge_transcriber = EdgeTranscribeService(self.supabase)
                self.lead_funnel_service = LeadFunnelService(self.supabase)
                logger.info("Supabase backend configured")
            except Exception as e:
                logger.warning("Supabase backend not configured: %s", e)
                self.supabase = None
                self.auth_service = None
                self.edge_transcriber = None
                self.lead_funnel_service = None

        # Offline outbox + telemetry (safe even without session; worker starts after login).
        try:
            self.outbox_repo = OutboxRepo(get_outbox_path(), get_outbox_audio_dir(), limits=OutboxLimits())
        except Exception:
            self.outbox_repo = None

        # Access/quota cache (to avoid blocking the hotkey path with network calls).
        self._access_cache = None
        self._access_cache_checked_at = 0.0
        self._access_cache_ttl_seconds = 20.0
        self._access_cache_lock = threading.Lock()
        self._access_cache_refresh_inflight = False

        # Local mode always uses direct Groq. Keep the old flag for cloud-mode devs.
        self._allow_local_stt = self._local_runtime or self._env_flag("FALAI_ALLOW_LOCAL_STT")

        # Transcription backend selector:
        # - edge: Supabase Edge Function (server-side Groq)
        # - local_groq: direct Groq SDK (local runtime)
        # - none: not configured
        self.transcriber = None  # only used in local_groq mode
        self.transcription_mode = "none"
        self.api_key_configured = False
        self._refresh_transcription_backend()

        # Initialize history manager
        self.history = TranscriptionHistory()

        # Short-term dictation context (fed to Whisper/corrector) + user replacement rules.
        self.dictation_memory = DictationMemory()
        self.dictation_memory.seed_from_history(self.history.history)
        self.text_replacements = TextReplacements()

        # Create session helpers if possible, and start the outbox worker (best-effort).
        self._ensure_outbox_worker()

        # Initialize corrector (optional). This still uses a local Groq key if present.
        self.corrector = None
        self._refresh_corrector()

        # Set up hotkey
        hotkey = self.settings.get("hotkey", "ctrl+shift")
        self.hotkey_manager.set_hotkey(hotkey)
        self.hotkey_manager.start_listening(self.on_hotkey_event)
        self._hotkey_enabled = True

        logger.info("=" * 50)
        logger.info("FALAI - Voice Transcription App")
        logger.info("Running in system tray (check near the clock)")
        if self.transcription_mode == "edge":
            logger.info("Transcription: Supabase Edge (server-side)")
            logger.info("Language: %s", self.settings.get("language", "pt"))
        elif self.transcription_mode == "local_groq":
            logger.info("Transcription: local Groq")
            logger.info("Language: %s", self.settings.get("language", "pt"))
        else:
            logger.warning("Transcription not configured (GROQ_API_KEY required in local mode)")
        logger.info("Hotkey: %s", hotkey)
        logger.info("Mode: %s", self.settings.get("activation_mode", "push_to_talk"))
        logger.info("=" * 50)

        self._apply_runtime_flags()
        self._apply_startup_setting()

        # Update check (non-blocking). We delay to avoid impacting startup/hotkey.
        try:
            if self.settings.get_bool("updates_enabled", True):
                # If we already have cached info saying an update is available, remind the user
                # shortly after startup (without hitting the network).
                QTimer.singleShot(6000, self._notify_cached_update_available)
                QTimer.singleShot(8000, self._check_updates_background)
        except Exception:
            pass

    def _on_notify(self, title: str, message: str):
        """Show a user notification (must run on main thread)."""
        try:
            self.tray.show_notification(str(title or "FALAI"), str(message or ""))
        except Exception:
            pass

    # ------------------------------
    # Updates (GitHub Releases) - Option A (notify + open link)
    # ------------------------------
    @staticmethod
    def _update_service() -> GitHubReleasesUpdateService:
        # Repo that hosts the installers; forks point FALAI_UPDATE_REPO ("owner/repo") at their own releases.
        owner, _, repo = (os.getenv("FALAI_UPDATE_REPO") or "m4rk2077/falai-desktop").partition("/")
        return GitHubReleasesUpdateService(owner=owner, repo=repo or "falai-desktop", timeout_seconds=6)

    def _get_update_cached(self) -> tuple[str, str, str, str, int, str]:
        """Return cached update info from settings.

        Returns:
            (version, download_url, release_url, asset_id, asset_size, asset_sha256)
        """
        try:
            v = str(self.settings.get("update_available_version", "") or "").strip()
            du = str(self.settings.get("update_available_url", "") or "").strip()
            ru = str(self.settings.get("update_release_url", "") or "").strip()
            aid = str(self.settings.get("update_available_asset_id", "") or "").strip()
            raw_size = self.settings.get("update_available_asset_size", 0) or 0
            try:
                size = int(raw_size)
            except Exception:
                size = 0
            sha = str(self.settings.get("update_available_asset_sha256", "") or "").strip().lower()
            if sha.startswith("sha256:"):
                sha = sha.split(":", 1)[1].strip().lower()
            if len(sha) != 64:
                sha = ""
            return v, du, ru, aid, max(0, size), sha
        except Exception:
            return "", "", "", "", 0, ""

    @staticmethod
    def _sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest().lower()

    def _validate_update_installer(
        self,
        path: Path,
        *,
        expected_size: int = 0,
        expected_sha256: str = "",
    ) -> tuple[bool, str]:
        """Validate a downloaded installer file.

        Validation policy:
        - If expected_size > 0, size must match.
        - If expected_sha256 is provided, hash must match.
        """
        try:
            if not path.exists() or not path.is_file():
                return False, "arquivo ausente"
        except Exception:
            return False, "arquivo ausente"

        try:
            st = path.stat()
        except Exception:
            return False, "não consegui ler arquivo"

        if expected_size and int(st.st_size) != int(expected_size):
            return False, "tamanho inválido"

        sha = str(expected_sha256 or "").strip().lower()
        if sha:
            if sha.startswith("sha256:"):
                sha = sha.split(":", 1)[1].strip().lower()
            if len(sha) != 64:
                return False, "hash esperado inválido"
            try:
                actual = self._sha256_file(path)
            except Exception:
                return False, "não consegui calcular hash"
            if actual != sha:
                return False, "hash inválido"

        return True, ""

    def _open_update_url(self, url: str) -> bool:
        try:
            u = str(url or "").strip()
            if not u:
                return False
            return bool(webbrowser.open(u))
        except Exception:
            return False

    def _check_updates_background(self):
        """Fire-and-forget background update check."""
        self._check_updates_async(force=False, open_if_available=False)

    def _notify_cached_update_available(self):
        """Startup reminder: if cached update info indicates a newer version, notify (rate-limited)."""
        try:
            current = self._get_app_version()
            latest, _, _, _, _, _ = self._get_update_cached()
            if not latest or not current:
                return

            from src.backend.update_service import is_newer_version

            if not is_newer_version(latest, current):
                return

            now = time.time()
            try:
                last_ver = str(self.settings.get("update_remind_version", "") or "").strip()
            except Exception:
                last_ver = ""
            try:
                last_at = float(self.settings.get("update_remind_at", 0.0) or 0.0)
            except Exception:
                last_at = 0.0

            # Remind at most once per version per 12h.
            if last_ver == latest and last_at and (now - last_at) < (12 * 3600):
                return

            try:
                self.settings.set("update_remind_version", latest)
                self.settings.set("update_remind_at", now)
                self.settings.save()
            except Exception:
                pass

            self.ui_dispatcher.notify.emit(
                "Atualizacao disponivel",
                f"Nova versao {latest} disponivel. Abra o menu Atualizacoes.",
            )
        except Exception:
            # Never break startup for an update reminder.
            return

    def _on_update_menu_clicked(self):
        """Tray menu click handler (runs in a background thread)."""
        # If we already know there is an update, open it immediately.
        current = self._get_app_version()
        latest, du, ru, _, _, _ = self._get_update_cached()
        try:
            from src.backend.update_service import is_newer_version

            if latest and is_newer_version(latest, current):
                self.ui_dispatcher.notify.emit("Atualizacao", "Abrindo pagina para baixar...")
                if not self._open_update_url(du or ru):
                    self.ui_dispatcher.notify.emit("Atualizacao", "Nao consegui abrir o link.")
                return
        except Exception:
            pass

        # Otherwise, force a check now and open if available.
        self._check_updates_async(force=True, open_if_available=True)

    def _check_updates_async(self, *, force: bool, open_if_available: bool):
        """Check GitHub Releases in a worker thread (never blocks UI/hotkey)."""
        if not self.settings.get_bool("updates_enabled", True):
            return

        try:
            now = time.time()
        except Exception:
            now = 0.0

        try:
            last = float(self.settings.get("update_last_checked_at", 0.0) or 0.0)
        except Exception:
            last = 0.0

        # Daily check by default (unless forced).
        # For beta, we want to pick up releases faster than 24h. Default: 2 hours.
        try:
            interval = float(self.settings.get("update_check_interval_seconds", 2 * 3600) or (2 * 3600))
        except Exception:
            interval = 2 * 3600
        interval = max(5 * 60, interval)  # never spam GitHub

        if not force and last and (now - last) < interval:
            return

        def _worker():
            current_version = self._get_app_version()
            try:
                info = self._update_service().check_latest(current_version=current_version)
            except Exception as e:
                # Offline or GitHub transient issues. Persist a best-effort hint so the
                # Settings UI can explain what happened (instead of looking "stuck").
                try:
                    self.settings.set("update_last_checked_at", time.time())
                    self.settings.set("update_last_error", str(e)[:200])
                    self.settings.save()
                except Exception:
                    pass
                return

            if not info:
                return

            try:
                self.settings.set("update_last_checked_at", time.time())
                self.settings.set("update_available_version", info.latest_version or "")
                self.settings.set("update_available_url", info.download_url or "")
                self.settings.set("update_release_url", info.release_url or "")
                self.settings.set("update_available_asset_id", info.asset_id or "")
                self.settings.set("update_available_asset_size", int(info.asset_size or 0))
                self.settings.set("update_available_asset_sha256", info.asset_sha256 or "")
                self.settings.set("update_last_error", "")
                self.settings.save()
            except Exception:
                pass

            if not info.available:
                if open_if_available:
                    self.ui_dispatcher.notify.emit("Atualizacoes", "Voce ja esta na ultima versao.")
                return

            # Validate existing downloaded installer (if any) against current release metadata.
            try:
                downloaded_version = str(self.settings.get("update_downloaded_version", "") or "").strip()
                downloaded_path = str(self.settings.get("update_downloaded_path", "") or "").strip()
                valid_download = False
                if (
                    downloaded_version
                    and downloaded_path
                    and downloaded_version == (info.latest_version or "")
                ):
                    ok, _ = self._validate_update_installer(
                        Path(downloaded_path),
                        expected_size=int(info.asset_size or 0),
                        expected_sha256=str(info.asset_sha256 or ""),
                    )
                    valid_download = bool(ok)
                self.settings.set("update_downloaded_valid", bool(valid_download))
                self.settings.save()
            except Exception:
                pass

            # Notify at most once per version.
            try:
                notified = str(self.settings.get("update_notified_version", "") or "").strip()
            except Exception:
                notified = ""

            if notified != (info.latest_version or ""):
                try:
                    self.settings.set("update_notified_version", info.latest_version or "")
                    self.settings.save()
                except Exception:
                    pass
                self.ui_dispatcher.notify.emit(
                    "Atualizacao disponivel",
                    f"Nova versao {info.latest_version} disponivel. Abra o menu Atualizacoes.",
                )

            if open_if_available:
                self.ui_dispatcher.notify.emit("Atualizacao", "Abrindo pagina para baixar...")
                if not self._open_update_url(info.download_url or info.release_url):
                    self.ui_dispatcher.notify.emit("Atualizacao", "Nao consegui abrir o link.")

        threading.Thread(target=_worker, daemon=True).start()

    def _update_download_filename(self, download_url: str, latest_version: str) -> str:
        """Best-effort derive a stable installer filename for the local updates dir."""
        u = str(download_url or "").strip()
        name = ""
        try:
            name = Path(unquote(urlparse(u).path)).name
        except Exception:
            name = ""

        if not name or not name.lower().endswith(".exe"):
            # Fallback: derive from version digits.
            import re

            m = re.search(r"(\d+(?:\.\d+)*)", str(latest_version or ""))
            ver = m.group(1) if m else (str(latest_version or "").strip() or "latest")
            name = f"FALAI-Setup-{ver}.exe"

        # Minimal Windows-safe sanitization.
        for ch in '<>:"/\\\\|?*':
            name = name.replace(ch, "_")
        name = name.strip().strip(".")
        if not name:
            name = "FALAI-Setup.exe"
        return name

    def _download_update_async(self):
        """Download the latest installer into APPDATA\\FALAI\\updates (non-blocking)."""
        latest, download_url, release_url, asset_id, asset_size, asset_sha256 = self._get_update_cached()
        download_url = str(download_url or "").strip()
        if not download_url:
            self.ui_dispatcher.notify.emit("Atualização", "Link de download indisponível.")
            if release_url:
                self._open_update_url(release_url)
            return

        # Avoid concurrent downloads.
        with self._update_download_lock:
            if self._update_download_thread and self._update_download_thread.is_alive():
                self.ui_dispatcher.notify.emit("Atualização", "Download já em andamento.")
                return

        def _worker():
            filename = self._update_download_filename(download_url, latest)
            updates_dir = get_updates_dir()
            dest = updates_dir / filename
            part = dest.with_suffix(dest.suffix + ".part")

            self.ui_dispatcher.update_download_started.emit(latest or "")
            self.ui_dispatcher.update_download_progress.emit(-1)

            try:
                if dest.exists():
                    # Do not trust cached files blindly: validate size/hash first.
                    ok, reason = self._validate_update_installer(
                        dest,
                        expected_size=int(asset_size or 0),
                        expected_sha256=str(asset_sha256 or ""),
                    )
                    if ok:
                        try:
                            self.settings.set("update_downloaded_version", latest or "")
                            self.settings.set("update_downloaded_path", str(dest))
                            self.settings.set("update_downloaded_asset_id", asset_id or "")
                            self.settings.set("update_downloaded_valid", True)
                            self.settings.set("update_downloaded_at", time.time())
                            self.settings.save()
                        except Exception:
                            pass
                        self.ui_dispatcher.update_download_completed.emit(str(dest))
                        return

                    logger.warning("Cached update file invalid (%s): %s", reason, dest)
                    try:
                        dest.unlink()
                    except Exception:
                        pass
                    try:
                        self.settings.set("update_downloaded_valid", False)
                        self.settings.save()
                    except Exception:
                        pass

                try:
                    if part.exists():
                        part.unlink()
                except Exception:
                    pass

                headers = {"User-Agent": "FALAI-App"}
                downloaded = 0
                total = 0
                last_emit = 0.0
                last_percent = -1

                with requests.get(download_url, headers=headers, stream=True, timeout=(6, 120)) as resp:
                    resp.raise_for_status()
                    try:
                        total = int(resp.headers.get("Content-Length") or 0)
                    except Exception:
                        total = 0

                    if total > 0:
                        self.ui_dispatcher.update_download_progress.emit(0)
                        last_percent = 0

                    with open(part, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=256 * 1024):
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)

                            if total > 0:
                                percent = int((downloaded / total) * 100)
                                percent = max(0, min(100, percent))
                                now = time.time()
                                if percent != last_percent and (now - last_emit) >= 0.2:
                                    self.ui_dispatcher.update_download_progress.emit(percent)
                                    last_percent = percent
                                    last_emit = now

                # Atomic-ish replace.
                try:
                    if dest.exists():
                        dest.unlink()
                except Exception:
                    pass
                part.replace(dest)

                # Validate downloaded file before exposing "Install now".
                ok, reason = self._validate_update_installer(
                    dest,
                    expected_size=int(asset_size or 0),
                    expected_sha256=str(asset_sha256 or ""),
                )
                if not ok:
                    try:
                        dest.unlink()
                    except Exception:
                        pass
                    raise RuntimeError(f"Arquivo de atualização inválido ({reason}). Baixe novamente.")

                try:
                    self.settings.set("update_downloaded_version", latest or "")
                    self.settings.set("update_downloaded_path", str(dest))
                    self.settings.set("update_downloaded_asset_id", asset_id or "")
                    self.settings.set("update_downloaded_valid", True)
                    self.settings.set("update_downloaded_at", time.time())
                    self.settings.save()
                except Exception:
                    pass

                self.ui_dispatcher.update_download_progress.emit(100)
                self.ui_dispatcher.update_download_completed.emit(str(dest))
            except Exception as e:
                try:
                    if part.exists():
                        part.unlink()
                except Exception:
                    pass
                try:
                    self.settings.set("update_downloaded_valid", False)
                    self.settings.save()
                except Exception:
                    pass
                logger.warning("Update download failed", exc_info=True)
                self.ui_dispatcher.update_download_failed.emit(str(e)[:200])

        t = threading.Thread(target=_worker, daemon=True)
        with self._update_download_lock:
            self._update_download_thread = t
        t.start()

    def _install_downloaded_update(self):
        """Launch the downloaded setup.exe and quit the app so it can update safely."""
        try:
            raw = str(self.settings.get("update_downloaded_path", "") or "").strip()
        except Exception:
            raw = ""
        if not raw:
            self.ui_dispatcher.notify.emit("Atualização", "Nenhuma atualização baixada ainda.")
            return

        path = Path(raw)
        if not path.exists():
            self.ui_dispatcher.notify.emit("Atualização", "Arquivo da atualização não encontrado. Baixe novamente.")
            return

        # Final validation before execution (defensive).
        try:
            latest, _, _, _, asset_size, asset_sha256 = self._get_update_cached()
            downloaded_version = str(self.settings.get("update_downloaded_version", "") or "").strip()
            expected_size = int(asset_size or 0) if downloaded_version == latest else 0
            expected_sha = str(asset_sha256 or "") if downloaded_version == latest else ""
            ok, reason = self._validate_update_installer(
                path,
                expected_size=expected_size,
                expected_sha256=expected_sha,
            )
            if not ok:
                self.settings.set("update_downloaded_valid", False)
                self.settings.save()
                self.ui_dispatcher.notify.emit("Atualização", "Arquivo de atualização inválido. Baixe novamente.")
                return
        except Exception:
            # If validation helper fails unexpectedly, keep safe default.
            self.ui_dispatcher.notify.emit("Atualização", "Não consegui validar a atualização. Baixe novamente.")
            return

        try:
            # Important: run installer detached so it keeps running after we exit.
            kwargs = {"cwd": str(path.parent)}
            if sys.platform == "win32":
                flags = 0
                flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
                if flags:
                    kwargs["creationflags"] = flags
            subprocess.Popen([str(path)], close_fds=True, **kwargs)  # noqa: S603,S607 (local installer)
        except Exception:
            logger.warning("Failed to launch installer", exc_info=True)
            self.ui_dispatcher.notify.emit("Atualização", "Não consegui abrir o instalador.")
            return

        self.ui_dispatcher.notify.emit("Atualização", "Abrindo instalador. O app vai fechar para atualizar.")
        QTimer.singleShot(300, lambda: self.ui_dispatcher.quit_requested.emit())

    def _on_update_download_started(self, version: str):
        try:
            if self._main_window and hasattr(self._main_window, "settings_page"):
                page = getattr(self._main_window, "settings_page", None)
                if page and hasattr(page, "on_update_download_started"):
                    page.on_update_download_started(version)
        except Exception:
            pass

    def _on_update_download_progress(self, percent: int):
        try:
            if self._main_window and hasattr(self._main_window, "settings_page"):
                page = getattr(self._main_window, "settings_page", None)
                if page and hasattr(page, "on_update_download_progress"):
                    page.on_update_download_progress(percent)
        except Exception:
            pass

    def _on_update_download_completed(self, path: str):
        try:
            if self._main_window and hasattr(self._main_window, "settings_page"):
                page = getattr(self._main_window, "settings_page", None)
                if page and hasattr(page, "on_update_download_completed"):
                    page.on_update_download_completed(path)
        except Exception:
            pass

    def _on_update_download_failed(self, message: str):
        try:
            if self._main_window and hasattr(self._main_window, "settings_page"):
                page = getattr(self._main_window, "settings_page", None)
                if page and hasattr(page, "on_update_download_failed"):
                    page.on_update_download_failed(message)
        except Exception:
            pass

    def _get_device_id(self) -> str:
        try:
            return str(self.settings.get("device_id", "") or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _get_app_version() -> str:
        try:
            from src import __version__

            return str(__version__ or "").strip()
        except Exception:
            return ""

    def _ensure_outbox_worker(self) -> None:
        """Start the outbox drain worker when we have Supabase + Auth available."""
        if self._local_runtime:
            return
        try:
            if not self.outbox_repo:
                return
            try:
                if not self.settings.is_security_ready():
                    return
            except Exception:
                return
            if not (self.supabase and self.auth_service and self.edge_transcriber):
                return
            if not self.session_manager:
                self.session_manager = SessionManager(self.auth_service)
            if not self.client_events_repo:
                self.client_events_repo = ClientEventsRepo(self.supabase)
            if self._outbox_thread and self._outbox_thread.is_alive():
                return

            worker = OutboxWorker(
                outbox=self.outbox_repo,
                session=self.session_manager,
                edge_transcriber=self.edge_transcriber,
                client_events=self.client_events_repo,
                get_device_id=self._get_device_id,
                get_app_version=self._get_app_version,
                history_add=self.history.add,
                history_update_corrected=getattr(self.history, "update_corrected_by_transcription_id", None),
                notify=lambda t, m: self.ui_dispatcher.notify.emit(t, m),
                record_event=self._record_client_event,
                usage_callback=self._update_access_cache_from_usage,
                poll_seconds=20,
            )
            self.outbox_worker = worker
            self._outbox_thread = threading.Thread(target=worker.run_forever, daemon=True)
            self._outbox_thread.start()
        except Exception:
            logger.warning("Failed to start outbox worker", exc_info=True)

    def _clear_session_tokens(self, *, keep_email: bool = True) -> None:
        """Clear session tokens without punishing the user for bad internet."""
        try:
            email = (self.settings.get("user_email", "") or "").strip()
            remember = self.settings.get_bool("remember_me", False)
        except Exception:
            email = ""
            remember = False

        try:
            if self.auth_service:
                self.auth_service.logout(keep_email=keep_email)
            else:
                self.settings.set("auth_token", "")
                if not (keep_email and remember and email):
                    self.settings.set("user_email", "")
                self.settings.set("remember_me", False)
                self.settings.save()
        except Exception:
            pass
        self._clear_access_cache()
        self._refresh_transcription_backend()

    def _logout_from_ui(self) -> None:
        """User-triggered logout from Settings page."""
        email = ""
        try:
            email = (self.settings.get("user_email", "") or "").strip()
        except Exception:
            email = ""

        self._clear_session_tokens(keep_email=True)
        try:
            self.ui_dispatcher.notify.emit("Conta", "Sessao encerrada com sucesso.")
        except Exception:
            pass
        self._open_login_ui(reason="Voce saiu da conta. Faca login para continuar.", prefill_email=email)

    def _open_login_ui(self, *, reason: str, prefill_email: str = "") -> None:
        """Open the Login page (not onboarding). Safe to call from any thread."""

        def _show():
            try:
                window = self._get_main_window()
                window.showNormal()
                window.raise_()
                window.activateWindow()
                if hasattr(window, "show_login"):
                    window.show_login(reason=reason, prefill_email=prefill_email)
                else:
                    window.switch_page("login")
            except Exception:
                logger.warning("Failed to open login UI", exc_info=True)

        QTimer.singleShot(0, _show)

    def _open_trial_expired_ui(self, *, reason: str = "") -> None:
        """Cloud-only: tell the user access expired (no plans UI in this build).

        Kept because the transcription flow still calls it when the Edge backend
        answers `entitlement_expired`. Safe to call from any thread.
        """
        try:
            self.ui_dispatcher.notify.emit("FALAI", str(reason or "").strip() or "Seu acesso expirou.")
        except Exception:
            pass

    def _request_password_reset(self, email: str) -> str | None:
        """Request password reset e-mail (used by LoginPage and onboarding)."""
        if self._local_runtime:
            return "Recuperação de senha não existe no modo local."
        mail = str(email or "").strip()
        if not mail:
            return "Informe seu e-mail para recuperar a senha."

        try:
            if not self.auth_service:
                if not self.supabase:
                    return "Supabase não configurado (SUPABASE_URL/SUPABASE_ANON_KEY)."
                self.auth_service = AuthService(self.supabase, settings=self.settings)
            self.auth_service.request_password_reset(
                email=mail,
                redirect_to=PASSWORD_RESET_REDIRECT_URL,
            )
            return None
        except ValueError as exc:
            return str(exc)
        except requests.exceptions.RequestException:
            return "Sem internet. Conecte-se e tente novamente."
        except SupabaseError as exc:
            if "SUPABASE_URL/SUPABASE_ANON_KEY" in str(exc):
                return "Supabase não configurado (SUPABASE_URL/SUPABASE_ANON_KEY)."
            return "Não foi possível enviar o e-mail de recuperação agora."
        except Exception:
            return "Não foi possível enviar o e-mail de recuperação agora."

    def _login_from_ui(self, email: str, password: str, remember_me: bool) -> str | None:
        """Authenticate using app-level services so session is immediately usable."""
        mail = str(email or "").strip()
        pwd = str(password or "").strip()
        if not mail:
            return "Informe seu e-mail."
        if self._local_runtime:
            self.settings.set("auth_token", f"local:{mail.lower()}")
            self.settings.set("user_email", mail if remember_me else "")
            self.settings.set("remember_me", bool(remember_me))
            self.settings.save()
            self._refresh_transcription_backend()
            self._refresh_corrector()
            return None
        if not pwd:
            return "Informe sua senha."
        try:
            if not self.supabase:
                self.supabase = SupabaseClient.from_env()
            if not self.auth_service:
                self.auth_service = AuthService(self.supabase, settings=self.settings)
            if not self.edge_transcriber and self.supabase:
                self.edge_transcriber = EdgeTranscribeService(self.supabase)
            if not self.session_manager and self.auth_service:
                self.session_manager = SessionManager(self.auth_service)
            if not self.client_events_repo and self.supabase:
                self.client_events_repo = ClientEventsRepo(self.supabase)
            if not self.lead_funnel_service and self.supabase:
                self.lead_funnel_service = LeadFunnelService(self.supabase)

            # Newly provisioned users (created by automation) can have a short consistency window.
            # Retry once on explicit invalid credentials before surfacing an error.
            session = None
            last_exc = None
            for attempt in range(2):
                try:
                    session = self.auth_service.login(email=mail, password=pwd, remember_me=bool(remember_me))
                    last_exc = None
                    break
                except Exception as login_exc:
                    last_exc = login_exc
                    is_invalid_credentials = False
                    if isinstance(login_exc, SupabaseError):
                        payload = getattr(login_exc, "payload", None)
                        if isinstance(payload, dict):
                            desc = (payload.get("error_description") or payload.get("message") or "").strip().lower()
                            is_invalid_credentials = "invalid login credentials" in desc
                    if attempt == 0 and is_invalid_credentials:
                        time.sleep(0.8)
                        continue
                    raise
            if last_exc is not None:
                raise last_exc
            token = str(session.access_token or "").strip()
            if not token:
                return "Falha ao entrar. Verifique e tente novamente."
            # Do not block login UX on transient post-login validation issues.
            # We keep a strict check only for persistent 401.
            try:
                self.supabase.auth_get_user(token)
            except SupabaseError as user_exc:
                if getattr(user_exc, "status_code", None) == 401:
                    time.sleep(0.4)
                    self.supabase.auth_get_user(token)
                else:
                    logger.info("Login post-check skipped due transient Supabase error")
            except requests.exceptions.RequestException:
                logger.info("Login post-check skipped due transient network error")
            except Exception:
                logger.info("Login post-check skipped due transient unexpected error")

            self._refresh_transcription_backend()
            self._refresh_corrector()
            self._ensure_outbox_worker()
            self._record_lead_lifecycle_event_async(
                "first_login",
                metadata={"source": "desktop_login"},
            )
            return None
        except Exception as exc:
            msg = "Falha ao entrar. Verifique seu e-mail e senha."
            try:
                if isinstance(exc, SupabaseError):
                    payload = getattr(exc, "payload", None)
                    if isinstance(payload, dict):
                        desc = (payload.get("error_description") or payload.get("message") or "").strip()
                        if desc and "invalid login credentials" in desc.lower():
                            msg = "E-mail ou senha inválidos."
                    if "SUPABASE_URL/SUPABASE_ANON_KEY" in str(exc):
                        msg = "Supabase não configurado (SUPABASE_URL/SUPABASE_ANON_KEY)."
            except Exception:
                pass
            logger.warning("Login failed (app-level): %s", type(exc).__name__)
            return msg

    def _record_client_event(
        self,
        *,
        event_type: str,
        severity: str = "error",
        message: str,
        details: dict | None = None,
    ) -> None:
        """Best-effort client telemetry.

        - Never blocks UX (runs in background threads).
        - If offline, it will be queued in the outbox and sent later.
        """
        try:
            if not self.outbox_repo:
                return
            user_id = self._get_current_user_id()
            if not user_id:
                return

            payload = {
                "user_id": user_id,
                "device_id": self._get_device_id() or None,
                "app_version": self._get_app_version() or None,
                "event_type": str(event_type or "unknown"),
                "severity": str(severity or "error"),
                "message": str(message or "")[:200],
                "details": details if isinstance(details, dict) else {},
            }

            token = self._get_access_token()
            if self.client_events_repo and token:
                try:
                    self.client_events_repo.create_event(payload, access_token=token)
                    return
                except requests.exceptions.RequestException:
                    pass
                except SupabaseError:
                    pass
                except Exception:
                    pass

            # Offline/failed: enqueue to outbox for later.
            self.outbox_repo.add_client_event(payload)
        except Exception:
            # Telemetry must never crash the app.
            return

    def _record_lead_lifecycle_event_sync(
        self,
        event_name: str,
        *,
        transcription_id: str = "",
        metadata: dict | None = None,
    ) -> None:
        try:
            token = self._get_access_token()
            if not token:
                return
            if not self.lead_funnel_service and self.supabase:
                self.lead_funnel_service = LeadFunnelService(self.supabase)
            if not self.lead_funnel_service:
                return
            self.lead_funnel_service.record_lifecycle_event(
                access_token=token,
                event_name=event_name,
                transcription_id=transcription_id,
                metadata=metadata if isinstance(metadata, dict) else {},
            )
        except Exception:
            return

    def _record_lead_lifecycle_event_async(
        self,
        event_name: str,
        *,
        transcription_id: str = "",
        metadata: dict | None = None,
    ) -> None:
        def _worker():
            self._record_lead_lifecycle_event_sync(
                event_name,
                transcription_id=transcription_id,
                metadata=metadata,
            )

        try:
            threading.Thread(target=_worker, daemon=True).start()
        except Exception:
            return

    @staticmethod
    def _env_flag(name: str, default: bool = False) -> bool:
        v = (os.getenv(name, "") or "").strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
        return default

    def _get_access_token(self) -> str:
        try:
            token = ""
            if self.auth_service:
                token = (self.auth_service.get_access_token() or "").strip()
            if token.lower().startswith("bearer "):
                token = token.split(" ", 1)[1].strip()
            return token
        except Exception:
            return ""

    def _get_refresh_token(self) -> str:
        try:
            token = ""
            if self.auth_service:
                token = (self.auth_service.get_refresh_token() or "").strip()
            if token.lower().startswith("bearer "):
                token = token.split(" ", 1)[1].strip()
            return token
        except Exception:
            return ""

    def _security_migration_blocked_message(self) -> str:
        err = ""
        try:
            err = self.settings.get_security_migration_error()
        except Exception:
            err = ""
        if err:
            return f"Migracao de seguranca pendente: {err}"
        return "Migracao de seguranca pendente. Entre novamente para concluir."

    def _handle_upgrade_required(self, payload: object) -> None:
        min_ver = ""
        message = "Atualizacao obrigatoria para continuar transcrevendo."
        try:
            if isinstance(payload, dict):
                min_ver = str(payload.get("min_supported_version") or "").strip()
                msg = str(payload.get("message") or "").strip()
                if msg:
                    message = msg
        except Exception:
            pass

        title = "Atualizacao obrigatoria"
        body = message if not min_ver else f"{message} Versao minima: {min_ver}."
        try:
            self.ui_dispatcher.notify.emit(title, body)
        except Exception:
            pass
        try:
            if self._main_window:
                self._main_window.switch_page("settings")
        except Exception:
            pass
        try:
            self._check_updates_async(force=True, open_if_available=True)
        except Exception:
            pass

    @staticmethod
    def _is_invalid_jwt_payload(payload: object) -> bool:
        try:
            if isinstance(payload, dict):
                msg = str(payload.get("message", "") or payload.get("error", "") or "").strip().lower()
                code = str(payload.get("code", "") or "").strip().lower()
                return "invalid jwt" in msg or code == "invalid_jwt"
            if isinstance(payload, str):
                return "invalid jwt" in payload.strip().lower()
        except Exception:
            return False
        return False

    @staticmethod
    def _decode_jwt_claims(token: str) -> dict:
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

    def _log_access_token_diagnostics(self, stage: str, token: str) -> None:
        try:
            claims = self._decode_jwt_claims(token)
            now = int(time.time())
            exp = claims.get("exp")
            ttl = int(exp) - now if isinstance(exp, (int, float)) else None
            logger.warning(
                "Auth diagnostics[%s]: len=%s dots=%s exp_ttl=%s",
                str(stage or ""),
                len(str(token or "")),
                str(token or "").count("."),
                str(ttl if ttl is not None else ""),
            )
        except Exception:
            pass

    def _verify_session_state(self, token: str) -> str:
        """Check if access token is still valid in Auth service.

        Returns:
          "valid"   -> /auth/v1/user accepted the token
          "invalid" -> token rejected as unauthorized
          "unknown" -> transient/network/backend issue (do not force logout)
        """
        tk = str(token or "").strip()
        if not tk or not self.supabase:
            return "invalid"
        try:
            self.supabase.auth_get_user(tk)
            return "valid"
        except requests.exceptions.RequestException:
            return "unknown"
        except SupabaseError as exc:
            code = getattr(exc, "status_code", None)
            if code == 401:
                return "invalid"
            return "unknown"
        except Exception:
            return "unknown"

    def _refresh_transcription_backend(self) -> None:
        """Select which transcription backend should be used right now.

        This is re-evaluated at runtime because onboarding/login can happen after app start.
        """
        prev_mode = getattr(self, "transcription_mode", "none")

        # Security migration must complete before transcription is allowed.
        try:
            if not self.settings.is_security_ready():
                self.transcription_mode = "none"
                self.transcriber = None
                self.api_key_configured = False
                return
        except Exception:
            self.transcription_mode = "none"
            self.transcriber = None
            self.api_key_configured = False
            return

        # The local product never consults cloud entitlement or billing.
        if self._local_runtime:
            groq_key = self.settings.get_groq_api_key()
            if groq_key:
                language = self.settings.get("language", "pt")
                groq_model = self.settings.get("groq_stt_model", "whisper-large-v3-turbo")
                if prev_mode != "local_groq" or self.transcriber is None:
                    self.transcriber = GroqTranscriber(api_key=groq_key, language=language, model=groq_model, vocabulary=self.settings.get("personal_vocabulary", ""))
                self.transcription_mode = "local_groq"
                self.api_key_configured = True
                return

        # Prefer Supabase Edge when we have a valid session.
        if self.supabase and self.edge_transcriber and self._get_access_token():
            self.transcription_mode = "edge"
            self.transcriber = None
            self.api_key_configured = True
            # Prime access cache once when we enter edge mode (non-blocking).
            if prev_mode != "edge":
                self._refresh_access_cache_async(force=True)
            return

        # DEV-only local fallback.
        if getattr(self, "_allow_local_stt", False):
            groq_key = self.settings.get_groq_api_key()
            if groq_key:
                language = self.settings.get("language", "pt")
                groq_model = self.settings.get("groq_stt_model", "whisper-large-v3-turbo")
                if prev_mode != "local_groq" or self.transcriber is None:
                    self.transcriber = GroqTranscriber(api_key=groq_key, language=language, model=groq_model, vocabulary=self.settings.get("personal_vocabulary", ""))
                self.transcription_mode = "local_groq"
                self.api_key_configured = True
                return

        # Nothing configured.
        self.transcription_mode = "none"
        self.transcriber = None
        self.api_key_configured = False

    def _refresh_corrector(self) -> None:
        """Initialize/disable the optional text corrector."""
        self.corrector = None
        if not self.settings.get_bool("gpt_correction", True):
            return

        # In production (edge transcription), correction is handled server-side.
        # Local corrector is DEV-only and only enabled for local transcription mode.
        if getattr(self, "transcription_mode", "none") != "local_groq":
            return

        # Corrector currently only supports Groq locally. If no key, correction is disabled silently.
        groq_key = self.settings.get_groq_api_key()
        if not groq_key:
            return

        try:
            groq_corrector_model = self.settings.get("groq_corrector_model", "openai/gpt-oss-120b")
            self.corrector = GroqCorrector(api_key=groq_key, model=groq_corrector_model, vocabulary=self.settings.get("personal_vocabulary", ""))
            logger.info("Corrector enabled (Groq: %s)", groq_corrector_model)
        except Exception:
            logger.warning("Could not initialize corrector; disabling", exc_info=True)
            self.corrector = None

    def _effective_message_format_mode(self) -> str:
        """Message-style formatting only applies when correction is enabled."""
        if not self.settings:
            return "balanced"
        return effective_message_format_mode(
            self.settings.get("message_format_mode", "balanced"),
            self.settings.get_bool("gpt_correction", True),
        )

    def _transcription_not_ready_message(self) -> str:
        """User-facing message when transcription cannot run."""
        try:
            if not self.settings.is_security_ready():
                return self._security_migration_blocked_message()
        except Exception:
            return "Migracao de seguranca pendente."
        if self._local_runtime:
            return "GROQ_API_KEY não configurada para o modo local."
        if self.supabase:
            return "Faça login para transcrever"
        return "Supabase não configurado (.env)"

    def _check_transcription_access(self) -> dict:
        """Fast entitlement/quota check used to block recording early (best effort)."""
        try:
            if not self.settings.is_security_ready():
                raise SupabaseError(self._security_migration_blocked_message())
        except SupabaseError:
            raise
        except Exception:
            raise SupabaseError("Migracao de seguranca pendente.")
        if self._local_runtime:
            return {"allowed": True, "plan": "local", "reason": ""}
        if not self.supabase:
            raise SupabaseError("Supabase não configurado.")
        token = self._get_access_token()
        if not token:
            raise SupabaseError("Sessão ausente (faça login).")
        rows = self.supabase.rpc("check_transcription_access", {}, jwt=token)
        if isinstance(rows, list) and rows:
            return rows[0] if isinstance(rows[0], dict) else {}
        if isinstance(rows, dict):
            return rows
        return {}

    def _get_current_user_id(self) -> str:
        """Best-effort user id from settings/session."""
        auth_token = (self.settings.get("auth_token", "") or "").strip()
        if auth_token.startswith("supabase:"):
            return (auth_token.split(":", 1)[1] or "").strip()

        # Fallback: fetch from Supabase Auth if available.
        if self.auth_service:
            try:
                user = self.auth_service.get_current_user()
                if isinstance(user, dict):
                    uid = (user.get("id") or "").strip()
                    if uid:
                        return uid
                    u2 = user.get("user") or {}
                    if isinstance(u2, dict):
                        return (u2.get("id") or "").strip()
            except Exception:
                return ""
        return ""

    def _get_cached_access(self) -> dict | None:
        """Return cached access data if it's fresh, otherwise None.

        This is used only to avoid blocking the hotkey path with network calls.
        The server (Edge Function) is always the source of truth.
        """
        try:
            now = time.time()
        except Exception:
            return None

        with self._access_cache_lock:
            access = self._access_cache
            checked_at = float(self._access_cache_checked_at or 0.0)
            ttl = float(self._access_cache_ttl_seconds or 0.0)

        if not isinstance(access, dict) or not access:
            return None
        if not checked_at or ttl <= 0:
            return None
        if (now - checked_at) > ttl:
            return None
        return dict(access)

    def _set_cached_access(self, access: dict | None) -> None:
        access_dict = dict(access) if isinstance(access, dict) else None
        try:
            now = time.time()
        except Exception:
            now = 0.0
        with self._access_cache_lock:
            self._access_cache = access_dict
            self._access_cache_checked_at = now

    def _clear_access_cache(self) -> None:
        with self._access_cache_lock:
            self._access_cache = None
            self._access_cache_checked_at = 0.0
            self._access_cache_refresh_inflight = False

    def _update_access_cache_from_usage(self, usage: dict) -> None:
        """Update cache based on Edge Function response usage (post-transcription)."""
        if not isinstance(usage, dict) or not usage:
            return
        access = {
            "allowed": True,
            "reason": "",
            "daily_limit_seconds": usage.get("daily_limit_seconds", None),
            "used_today_seconds": usage.get("used_today_seconds", None),
            "remaining_seconds": usage.get("remaining_seconds", None),
            "monthly_limit_seconds": usage.get("monthly_limit_seconds", None),
            "used_month_seconds": usage.get("used_month_seconds", None),
            "remaining_month_seconds": usage.get("remaining_month_seconds", None),
        }
        self._set_cached_access(access)

    def _refresh_access_cache_async(self, force: bool = False) -> None:
        """Refresh access cache in a background thread (never blocks UI/hotkey)."""
        if not self.supabase:
            return
        if getattr(self, "transcription_mode", "none") != "edge":
            return

        # Only refresh if we have some session token. Even if it's expired,
        # we do not want to poison the cache with a 401 because refresh_token can fix it later.
        if not self._get_access_token():
            return

        try:
            now = time.time()
        except Exception:
            now = 0.0

        with self._access_cache_lock:
            if self._access_cache_refresh_inflight:
                return
            if not force and self._access_cache_checked_at and (now - float(self._access_cache_checked_at)) < float(self._access_cache_ttl_seconds):
                return
            self._access_cache_refresh_inflight = True

        def _worker():
            access = None
            try:
                access = self._check_transcription_access()
            except SupabaseError as exc:
                # 401 can happen if access_token expired; refresh might fix later, so don't overwrite cache.
                if getattr(exc, "status_code", None) == 401:
                    access = None
                else:
                    access = None
            except Exception:
                access = None

            try:
                if isinstance(access, dict) and access:
                    self._set_cached_access(access)
            finally:
                with self._access_cache_lock:
                    self._access_cache_refresh_inflight = False

        threading.Thread(target=_worker, daemon=True).start()

    def _access_block_message(self, reason: str, access: dict | None = None) -> str:
        return shared_access_block_message(reason, access)

    def _is_onboarding_active(self) -> bool:
        return bool(self._main_window and hasattr(self._main_window, "is_onboarding_active") and self._main_window.is_onboarding_active())

    def _get_main_window(self):
        """Get or create the main window (lazy loading)"""
        logger.debug("_get_main_window() called")
        if self._main_window is None:
            logger.debug("Creating new MainWindow...")
            try:
                self._main_window = MainWindow(self.settings, self.history, self._apply_theme)
                logger.info("MainWindow created successfully")
                self._main_window.set_show_in_taskbar(True)
                self._main_window.set_record_callback(self.start_recording)
                self._main_window.set_stop_callback(self.stop_recording)
                self._main_window.set_settings_callback(self.open_settings)
                self._main_window.set_history_callback(self.open_history)
                self._main_window.set_stats_callback(self.open_stats)
                if hasattr(self._main_window, "set_hotkey_enabled_callback"):
                    self._main_window.set_hotkey_enabled_callback(self._set_hotkey_enabled)
                if hasattr(self._main_window, "set_password_reset_callback"):
                    self._main_window.set_password_reset_callback(self._request_password_reset)
                if hasattr(self._main_window, "set_login_callback"):
                    self._main_window.set_login_callback(self._login_from_ui)
                if hasattr(self._main_window, "set_logout_callback"):
                    self._main_window.set_logout_callback(self._logout_from_ui)
                if hasattr(self._main_window, "set_settings_saved_callback"):
                    self._main_window.set_settings_saved_callback(self.on_settings_saved)
                # Updates: Settings page button (Option A).
                if hasattr(self._main_window, "set_update_callbacks"):
                    self._main_window.set_update_callbacks(
                        check_callback=lambda: self._check_updates_async(force=True, open_if_available=False),
                        open_callback=self._on_update_menu_clicked,
                        download_callback=self._download_update_async,
                        install_callback=self._install_downloaded_update,
                    )
                logger.debug("Callbacks set")

                # Update UI with settings
                mode = self.settings.get("activation_mode", "push_to_talk")
                hotkey = self.settings.get("hotkey", "ctrl+shift")
                self._main_window.update_mode_info(mode, hotkey)

                # Show a clear status message when transcription isn't ready.
                self._refresh_transcription_backend()
                if self.transcription_mode == "none":
                    if self.supabase:
                        self._main_window.set_error_status("Faça login para transcrever")
                    else:
                        self._main_window.set_error_status("Supabase não configurado (.env)")
                logger.debug("MainWindow fully configured")
            except Exception as e:
                logger.error("Failed to create MainWindow", exc_info=True)
                raise
        else:
            logger.debug("Returning existing MainWindow")

        return self._main_window

    def _open_main_window_from_tray(self):
        """Open main window from tray icon click"""
        try:
            self.ui_dispatcher.open_main.emit()
        except Exception:
            pass

    def _show_main_window(self):
        """Show the main window"""
        logger.debug("_show_main_window() called")
        try:
            window = self._get_main_window()
            logger.debug("Got main window: %s", window)
            window.showNormal()
            logger.debug("window.show() called")
            window.raise_()
            logger.debug("window.raise_() called")
            window.activateWindow()
            logger.debug("window.activateWindow() called")
        except Exception as e:
            logger.error("Error showing main window", exc_info=True)

    def _apply_theme(self, theme: str):
        """Aplica tema globalmente no app"""
        self.app.setStyleSheet(get_stylesheet(theme))

    def _apply_runtime_flags(self):
        self._floating_enabled = self.settings.get("show_floating", True)
        self._sound_fx_enabled = self.settings.get("dictation_fx", True)
        self._duck_music_enabled = self.settings.get("mute_music", False)

        if not self._floating_enabled:
            self.floating_bar.hide()
            if self._level_timer.isActive():
                self._level_timer.stop()
        elif not self._is_recording:
            self.floating_bar.show_idle()
        if not self._duck_music_enabled:
            self._audio_ducker.restore()

        if self._main_window:
            self._main_window.set_show_in_taskbar(True)

    def _apply_startup_setting(self, approve: bool = False):
        if self.settings.get("launch_login", False):
            try:
                enable_startup(self._root_dir, executable_path=Path(sys.executable), approve=approve)
            except Exception:
                logger.warning("Failed to enable startup")
        else:
            try:
                disable_startup()
            except Exception:
                logger.warning("Failed to disable startup")

    def _safe_floating_idle(self):
        """Transition floating bar to idle only if it's in a terminal state."""
        if self._floating_enabled and self.floating_bar.state in (
            self.floating_bar.STATE_SUCCESS,
            self.floating_bar.STATE_ERROR,
        ):
            self.floating_bar.show_idle()

    def _cleanup_streaming_uploader(self):
        """Release any active streaming uploader and detach it from the recorder."""
        uploader = getattr(self, "_streaming_uploader", None)
        self._streaming_uploader = None
        try:
            if self.recorder:
                self.recorder._streaming_uploader = None
        except Exception:
            pass
        if uploader is not None:
            try:
                uploader.cleanup()
            except Exception:
                logger.debug("Failed to cleanup streaming uploader", exc_info=True)

    def _create_streaming_uploader(self):
        """Prepare the local streaming buffer before microphone capture starts."""
        if self.transcription_mode != "edge":
            return None
        if not self.settings.get("streaming_enabled", False):
            return None
        if not self.supabase or not self.recorder:
            return None

        access_token = self._get_access_token()
        if not access_token:
            logger.info("Streaming disabled for this recording: no access token")
            return None

        try:
            from src.audio.streaming_uploader import StreamingUploader

            uploader = StreamingUploader(
                client=self.supabase,
                access_token=access_token,
                language=self.settings.get("language", "pt"),
                model=self.settings.get("groq_stt_model", "whisper-large-v3-turbo"),
                correct=self.settings.get_bool("gpt_correction", True),
                correction_style=self.settings.get("correction_style", "neutro"),
                format_mode=self._effective_message_format_mode(),
                domain_profile=self.settings.get("domain_lexicon_profile", "none"),
                device_id=self._get_device_id() or None,
                sample_rate=self.recorder.sample_rate,
            )
            if not uploader.start_session():
                return None
            return uploader
        except Exception:
            logger.warning("Streaming uploader init failed, batch fallback", exc_info=True)
            return None

    def _apply_ui_state(self, state: str, message=None):
        """Aplica estado na UI (sempre na thread principal)"""
        if state == UiState.PROCESSING.value:
            if self._floating_enabled:
                self.floating_bar.show_processing()
            if self._main_window and self._main_window.isVisible():
                self._main_window.set_processing_ui()
        elif state == UiState.DONE.value:
            if self._floating_enabled:
                self.floating_bar.show_success(auto_hide_ms=0)
                QTimer.singleShot(900, self._safe_floating_idle)
            if self._main_window:
                self._main_window.is_recording = False
            if self._main_window and self._main_window.isVisible():
                self._main_window.set_idle_ui()
        elif state == UiState.ERROR.value:
            msg = str(message or "Erro")[:30]
            if self._floating_enabled:
                self.floating_bar.show_error(msg, auto_hide_ms=0)
                QTimer.singleShot(2000, self._safe_floating_idle)
            if self._main_window:
                self._main_window.is_recording = False
            if self._main_window and self._main_window.isVisible():
                self._main_window.set_error_status(msg)
            # If onboarding is open, show the error there too (must be main thread).
            if self._is_onboarding_active() and self._main_window:
                self._main_window.onboarding_error(msg)
        elif state == UiState.IDLE.value:
            if self._floating_enabled:
                self.floating_bar.show_idle()
            if self._main_window:
                self._main_window.is_recording = False
            if self._main_window and self._main_window.isVisible():
                self._main_window.set_idle_ui()

    def _on_transcription_ready(self, text: str):
        """Atualiza transcricao na UI"""
        if self._main_window and self._main_window.isVisible():
            self._main_window.update_transcription(text)
        # Onboarding dialog also needs the transcription (main thread).
        if self._is_onboarding_active() and self._main_window:
            self._main_window.onboarding_transcription(text)

    def _update_audio_level(self):
        """Atualiza nivel de audio no waveform"""
        if self._is_recording and self.recorder:
            level = self.recorder.get_level()
            if self._floating_enabled:
                self.floating_bar.set_audio_level(level)
            if self._main_window and self._main_window.isVisible():
                home_page = getattr(self._main_window, "home_page", None)
                status_badge = getattr(home_page, "status_badge", None) if home_page else None
                if status_badge:
                    status_badge.set_level(level)

    def _open_settings_from_tray(self):
        """Open settings from tray menu"""
        try:
            self.ui_dispatcher.open_settings.emit()
        except Exception:
            pass

    def _open_history_from_tray(self):
        """Open history from tray menu"""
        try:
            self.ui_dispatcher.open_history.emit()
        except Exception:
            pass

    def _open_stats_from_tray(self):
        """Open stats from tray menu"""
        try:
            self.ui_dispatcher.open_stats.emit()
        except Exception:
            pass

    def _quit_app(self):
        """Quit the application"""
        try:
            self.ui_dispatcher.quit_requested.emit()
        except Exception:
            pass

    def _do_quit(self):
        """Actually quit the app (must run in main thread)"""
        self.hotkey_manager.stop_listening()
        self.tray.stop()
        if self._level_timer.isActive():
            self._level_timer.stop()
        self._audio_ducker.restore()
        self.app.quit()
        logger.info("FALAI closed. Goodbye!")
        sys.exit(0)

    def open_settings(self):
        """Open settings window"""
        window = self._get_main_window()
        window.show()
        window.raise_()
        window.activateWindow()
        window.switch_page("settings")

    def open_history(self):
        """Open history window"""
        window = self._get_main_window()
        window.show()
        window.raise_()
        window.activateWindow()
        window.switch_page("history")

    def open_stats(self):
        """Open stats window"""
        window = self._get_main_window()
        window.show()
        window.raise_()
        window.activateWindow()
        window.switch_page("stats")

    def on_settings_saved(self, changed_keys=None):
        """Callback when settings are saved"""
        # For UI toggles, avoid full reload/reinit to prevent flicker
        if changed_keys:
            changed = set(changed_keys)
            runtime_keys = {"show_floating", "dictation_fx", "mute_music"}
            if changed & runtime_keys:
                self._apply_runtime_flags()
            if "launch_login" in changed:
                self._apply_startup_setting(approve=True)
            if "hotkey" in changed:
                hotkey = self.settings.get("hotkey", "ctrl+shift")
                self._restart_hotkey_listener(hotkey)
                mode = self.settings.get("activation_mode", "push_to_talk")
                if self._main_window:
                    self._main_window.update_mode_info(mode, hotkey)
            if changed & {"groq_api_key", "personal_vocabulary"}:
                # Recreate Groq clients so the new key/vocabulary take effect immediately.
                self.transcriber = None
                self._refresh_transcription_backend()
                self._refresh_corrector()
                if self._main_window:
                    if self.transcription_mode == "none":
                        self._main_window.set_error_status(self._transcription_not_ready_message())
                    else:
                        self._main_window.set_ready_status()
            if "auth_session" in changed:
                # Login completed; keep current in-memory services/tokens.
                self._refresh_transcription_backend()
                self._refresh_corrector()
                self._ensure_outbox_worker()
                if self._main_window:
                    if self.transcription_mode == "none":
                        self._main_window.set_error_status(self._transcription_not_ready_message())
                    else:
                        self._main_window.set_ready_status()
                self._refresh_access_cache_async(force=True)
            return

        logger.info("Reloading settings...")

        # Reload settings (fallback path)
        self.settings.load()

        # Ensure recorder exists
        if not self.recorder:
            try:
                self.recorder = AudioRecorder(sample_rate=16000, channels=1)
            except Exception:
                logger.error("Error initializing audio recorder", exc_info=True)

        # Local-only builds must never recreate cloud services after settings reload.
        if self._local_runtime:
            self.supabase = None
            self.auth_service = None
            self.edge_transcriber = None
            self.lead_funnel_service = None
            self.session_manager = None
            self.client_events_repo = None
        else:
            # Re-initialize Supabase backend (in case .env changed).
            try:
                self.supabase = SupabaseClient.from_env()
                self.auth_service = AuthService(self.supabase, settings=self.settings)
                self.edge_transcriber = EdgeTranscribeService(self.supabase)
            except Exception:
                self.supabase = None
                self.auth_service = None
                self.edge_transcriber = None
                self.session_manager = None
                self.client_events_repo = None

        # Refresh runtime configuration
        self._refresh_transcription_backend()
        self._refresh_corrector()

        # (Re)start outbox worker if possible after login/settings changes.
        self._ensure_outbox_worker()

        # Update UI status
        if self._main_window:
            if self.transcription_mode == "none":
                self._main_window.set_error_status(self._transcription_not_ready_message())
            else:
                self._main_window.set_ready_status()

        self._apply_runtime_flags()
        self._apply_startup_setting()

        # Update hotkey
        hotkey = self.settings.get("hotkey", "ctrl+shift")
        self._restart_hotkey_listener(hotkey)

        # Update UI info
        mode = self.settings.get("activation_mode", "push_to_talk")
        if self._main_window:
            self._main_window.update_mode_info(mode, hotkey)
        self._refresh_access_cache_async(force=True)

    def _restart_hotkey_listener(self, hotkey: str | None = None):
        """Restart hotkey listener if enabled (keeps disabled state)."""
        if hotkey is None:
            hotkey = self.settings.get("hotkey", "ctrl+shift")
        self.hotkey_manager.stop_listening()
        self.hotkey_manager.set_hotkey(hotkey)
        if getattr(self, "_hotkey_enabled", True):
            self.hotkey_manager.start_listening(self.on_hotkey_event)

    def _set_hotkey_enabled(self, enabled: bool):
        """Enable/disable hotkey listener (used by onboarding)."""
        if getattr(self, "_hotkey_enabled", True) == enabled:
            return
        self._hotkey_enabled = enabled
        if enabled:
            hotkey = self.settings.get("hotkey", "ctrl+shift")
            self.hotkey_manager.stop_listening()
            self.hotkey_manager.set_hotkey(hotkey)
            self.hotkey_manager.start_listening(self.on_hotkey_event)
            logger.info("Hotkey listener resumed")
        else:
            self.hotkey_manager.stop_listening()
            logger.info("Hotkey listener paused")

    def on_hotkey_event(self, pressed: bool):
        """Handle hotkey press/release events (called from hotkey thread)"""
        # Emit signal to handle in main thread
        self.hotkey_signals.hotkey_pressed.emit(pressed)

    def _handle_hotkey(self, pressed: bool):
        """Handle hotkey in main thread (slot)"""
        # Block new recordings while still processing a previous one
        if pressed and not self._is_recording and self.ui_state.state == UiState.PROCESSING:
            logger.warning("Hotkey ignored: still processing previous recording")
            return

        mode = self.settings.get("activation_mode", "push_to_talk")

        if mode == "push_to_talk":
            # Hold to record
            if pressed and not self._is_recording:
                self.start_recording()
            elif not pressed and self._is_recording:
                self.stop_recording()

        elif mode == "toggle":
            # Toggle on press only; apply cooldown to prevent double-tap glitch
            if pressed:
                now = time.time()
                last = getattr(self, "_last_toggle_time", 0.0)
                if now - last < 0.4:
                    return
                self._last_toggle_time = now
                if not self._is_recording:
                    self.start_recording()
                else:
                    self.stop_recording()

    def start_recording(self):
        """Start recording audio"""
        # Check if already recording
        if self._is_recording:
            return
        if self.ui_state.state == UiState.PROCESSING:
            logger.warning("Ainda processando, aguarde...")
            return

        # If a previous transcription flagged an auth issue, verify the session
        # NOW (before recording) so the user gets redirected to login before
        # wasting time recording audio that can't be sent.
        if getattr(self, "_auth_recovery_needed", False):
            try:
                if self.session_manager:
                    self.session_manager.force_refresh_access_token(ignore_ttl=True)
                self._auth_recovery_needed = False
                logger.info("Auth recovery succeeded — session still valid")
            except OfflineError:
                logger.info("Auth recovery postponed — temporary refresh failure")
            except LoginRequiredError:
                logger.warning("Auth recovery failed — redirecting to login")
                self._auth_recovery_needed = False
                self._clear_session_tokens(keep_email=True)
                self._open_login_ui(
                    reason="Sessão expirada. Faça login novamente.",
                    prefill_email=str(self.settings.get("user_email", "") or ""),
                )
                if self._floating_enabled:
                    self.floating_bar.show_error("Faça login", auto_hide_ms=3000)
                return

        # Ensure we have a working transcription backend before starting.
        self._refresh_transcription_backend()
        if self.transcription_mode == "none":
            msg = self._transcription_not_ready_message()
            logger.warning(msg)
            if self._floating_enabled:
                self.floating_bar.show_error(msg[:30])
            if self._main_window:
                # MainWindow.start_recording() might have been called already by the UI click.
                self._main_window.is_recording = False
                if self._main_window.isVisible():
                    self._main_window.set_idle_ui()
            return

        # Best-effort early block using cached access (never blocks UI).
        # Source of truth is still the Edge Function, which enforces entitlement/quota.
        if self.transcription_mode == "edge":
            access = self._get_cached_access()
            if isinstance(access, dict) and access:
                allowed = bool(access.get("allowed", True))
                try:
                    rem = access.get("remaining_seconds", None)
                    if rem is not None and float(rem) <= 0:
                        allowed = False
                        if not access.get("reason"):
                            access["reason"] = "daily_limit_reached"
                except Exception:
                    pass

                if not allowed:
                    reason = str(access.get("reason") or "")
                    msg = self._access_block_message(reason, access)
                    logger.warning("Transcription blocked before recording (cached): %s", reason or "blocked")
                    if reason == "entitlement_expired":
                        self._record_lead_lifecycle_event_async(
                            "trial_expired_seen",
                            metadata={"source": "pre_recording_gate", "reason": reason},
                        )
                        self._open_trial_expired_ui(reason=msg)
                    if self._floating_enabled:
                        self.floating_bar.show_error(msg[:30])
                    if self._main_window:
                        self._main_window.is_recording = False
                        if self._main_window.isVisible():
                            self._main_window.set_idle_ui()
                    return

            # Refresh cache in background for the next hotkey press.
            self._refresh_access_cache_async()

        # Check if recorder exists
        if not self.recorder:
            logger.error("Audio recorder not initialized")
            if self._floating_enabled:
                self.floating_bar.show_error("Microfone não disponível")
            return

        try:
            # Capture active window handle BEFORE updating UI or anything else
            self.last_active_window = self.window_manager.get_active_window()

            self._cleanup_streaming_uploader()
            streaming_uploader = self._create_streaming_uploader()
            if streaming_uploader is not None:
                self._streaming_uploader = streaming_uploader
                self.recorder._streaming_uploader = streaming_uploader
            # Capture first: UI, sound and music ducking must not eat the first words.
            self.recorder.start_recording()

            self.ui_state.force_reset()
            self._is_recording = True
            logger.info("Starting recording")
            self._warm_up_groq_async()

            # Show floating bar
            if self._floating_enabled:
                self.floating_bar.show_recording()
                if not self._level_timer.isActive():
                    self._level_timer.start()

            if self._sound_fx_enabled:
                play_start()
            if self._duck_music_enabled:
                self._audio_ducker.duck()

            # Update main window if visible
            if self._main_window and self._main_window.isVisible():
                self._main_window.start_recording()

        except Exception as e:
            self._is_recording = False
            if self.recorder and self.recorder.is_recording:
                self.recorder.stop_recording()
            self._cleanup_streaming_uploader()
            if self._main_window:
                # Recording can be started via hotkey (bypassing MainWindow._toggle_recording()),
                # so if the recorder fails we must not leave the UI "recording" flag stuck.
                self._main_window.is_recording = False
                if self._main_window.isVisible():
                    self._main_window.set_idle_ui()
            logger.error("Error starting recording", exc_info=True)
            if self._floating_enabled:
                self.floating_bar.show_error(str(e)[:30])
            if self._sound_fx_enabled:
                play_error()
            if self._duck_music_enabled:
                self._audio_ducker.restore()

    def stop_recording(self):
        """Stop recording and transcribe"""
        # Check if actually recording
        if not self._is_recording:
            return

        self._is_recording = False
        if self._main_window:
            # Keep MainWindow state consistent when stop is triggered by hotkey.
            self._main_window.is_recording = False

        try:
            logger.info("Stopping recording")

            if self._sound_fx_enabled:
                play_stop()
            if self._duck_music_enabled:
                self._audio_ducker.restore()

            # Para atualizacao de waveform
            if self._level_timer.isActive():
                self._level_timer.stop()

            # Stop recording and get audio data
            audio_data = self.recorder.stop_recording()

            if len(audio_data) == 0:
                logger.warning("No audio recorded")
                self._cleanup_streaming_uploader()
                self.ui_state.force_reset()
                if self._floating_enabled:
                    self.floating_bar.show_error("Nenhum áudio captado", auto_hide_ms=2000)
                    QTimer.singleShot(2200, self._safe_floating_idle)
                if self._main_window and self._main_window.isVisible():
                    self._main_window.set_idle_ui()
                if self._sound_fx_enabled:
                    play_error()
                if self._duck_music_enabled:
                    self._audio_ducker.restore()
                return

            try:
                duration_seconds = len(audio_data) / self.recorder.sample_rate
                mono = audio_data
                if hasattr(audio_data, "ndim") and audio_data.ndim > 1:
                    mono = audio_data.mean(axis=1)
                if len(mono):
                    rms = float(np.sqrt(np.mean(mono ** 2)))
                    peak = float(np.max(np.abs(mono)))
                    # More permissive voice activity threshold so distant microphones
                    # don't get filtered as silence.
                    active_ratio = float(np.mean(np.abs(mono) > 0.01))
                else:
                    rms = 0.0
                    peak = 0.0
                    active_ratio = 0.0
            except Exception:
                duration_seconds = 0.0
                rms = 0.0
                peak = 0.0
                active_ratio = 0.0

            logger.info(
                "Audio metrics: dur=%.2fs rms=%.4f peak=%.4f active=%.3f",
                duration_seconds, rms, peak, active_ratio
            )

            min_duration = 0.45
            min_rms = 0.008
            min_peak = 0.03
            min_active_ratio = 0.02
            # Use OR between rms+peak (both very low = silence) and active_ratio
            # to catch cases where background noise inflates just one metric.
            likely_silent = (
                (rms < min_rms and peak < min_peak)
                or active_ratio < min_active_ratio
            )
            if duration_seconds < min_duration or likely_silent:
                logger.warning(
                    "Audio muito curto ou silencioso (dur=%.2fs, rms=%.4f, peak=%.4f, active=%.3f)",
                    duration_seconds, rms, peak, active_ratio
                )
                self._cleanup_streaming_uploader()
                # Show error directly on floating bar (ui_state is still IDLE here,
                # so finish_error would be a no-op).
                if self._floating_enabled:
                    self.floating_bar.show_error("Nenhuma fala detectada", auto_hide_ms=2000)
                    QTimer.singleShot(2200, self._safe_floating_idle)
                if self._main_window and self._main_window.isVisible():
                    self._main_window.set_idle_ui()
                if self._sound_fx_enabled:
                    play_error()
                return

            # Atualiza estado de UI para processamento
            self.ui_state.start_processing()

            # Update main window if visible
            if self._main_window and self._main_window.isVisible():
                self._main_window.set_processing_ui()

            # Transcribe in separate daemon thread to avoid blocking UI.
            # Track it to prevent concurrent transcription threads from piling up.
            prev = getattr(self, "_transcribe_thread", None)
            if prev is not None and prev.is_alive():
                self._cleanup_streaming_uploader()
                logger.warning("Previous transcription thread still running — skipping new transcription")
                self.ui_state.finish_error("Aguarde a transcrição anterior")
                if self._sound_fx_enabled:
                    play_error()
                return
            self._transcribe_thread = threading.Thread(
                target=self._transcribe_audio,
                args=(audio_data,),
                daemon=True,
            )
            self._transcribe_thread.start()

        except Exception as e:
            logger.error("Error stopping recording", exc_info=True)
            self._cleanup_streaming_uploader()
            self.ui_state.finish_error(str(e)[:30])
            if self._sound_fx_enabled:
                play_error()
            if self._duck_music_enabled:
                self._audio_ducker.restore()

    def _warm_up_groq_async(self) -> None:
        """Pre-open Groq connections during recording (local mode) to cut first-call latency."""
        if getattr(self, "transcription_mode", "none") != "local_groq":
            return
        targets = [t for t in (self.transcriber, self.corrector) if t is not None and hasattr(t, "warm_up")]
        if targets:
            threading.Thread(target=lambda: [t.warm_up() for t in targets], daemon=True).start()

    def _transcribe_audio(self, audio_data):
        """Transcribe audio in background thread"""
        try:
            t0 = time.perf_counter()
            # Default duration (will be overwritten by backend duration when available).
            duration_seconds = len(audio_data) / self.recorder.sample_rate
            trial_floor_applied_ms = 0

            self._refresh_transcription_backend()

            transcription = ""
            original_text = None
            corrected_text = None
            transcription_id = ""
            stage_ms: dict = {}
            dictation_context = (
                self.dictation_memory.context() if self.settings.get_bool("dictation_context", True) else ""
            )
            processing_tier = "trial"
            correction_pending = False

            if self.transcription_mode == "edge":
                access_token = self._get_access_token()  # default, may be refreshed later
                # --- Streaming path: if uploader was active, finish it (near-instant) ---
                streaming_uploader = self._streaming_uploader
                if streaming_uploader and streaming_uploader.is_active:
                    try:
                        stream_chunks = streaming_uploader.chunks_sent
                        logger.info("Streaming finish: %d chunks fed during recording", stream_chunks)
                        result = streaming_uploader.finish(timeout_seconds=30)
                        self._cleanup_streaming_uploader()
                        if result and result.text:
                            # Use streaming result — skip batch upload entirely
                            original_text = str((result.transcription or {}).get("original_text") or "").strip()
                            corrected_text_raw = str((result.transcription or {}).get("corrected_text") or "").strip()
                            corrected_text = corrected_text_raw or None
                            transcription_id = str((result.transcription or {}).get("id") or "").strip()
                            correction_pending = bool((result.transcription or {}).get("correction_pending", False))
                            processing_tier = str((result.processing or {}).get("tier") or "").strip().lower() or "pro"
                            transcription = corrected_text or original_text or result.text
                            try:
                                dur = (result.transcription or {}).get("audio_duration_seconds")
                                if dur is not None:
                                    duration_seconds = float(dur)
                            except Exception:
                                pass
                            try:
                                self.settings.set("last_speed_tier", processing_tier)
                                self.settings.save()
                            except Exception:
                                pass
                            self._record_client_event(
                                event_type="streaming_transcription_complete",
                                severity="info",
                                message="Streaming transcription completed",
                                details={
                                    "tier": processing_tier,
                                    "correction_pending": correction_pending,
                                    "chunks_sent": stream_chunks,
                                    "source": "stream",
                                },
                            )
                            logger.info("Streaming result ready, skipping batch upload")
                        else:
                            logger.warning("Streaming returned empty result, falling back to batch")
                    except Exception as stream_err:
                        logger.warning("Streaming finish failed, falling back to batch: %s", stream_err)
                        self._cleanup_streaming_uploader()
                else:
                    self._cleanup_streaming_uploader()

                # --- Batch path (fallback or default) ---
                if not transcription:
                    if not self.edge_transcriber or not self.supabase:
                        raise SupabaseError("Supabase não configurado.")

                    access_token = self._get_access_token()
                    if not access_token:
                        raise SupabaseError("Sessão ausente. Faça login.")

                    wav_bytes = numpy_to_wav_bytes(audio_data, sample_rate=self.recorder.sample_rate)
                    if not wav_bytes:
                        self.ui_state.finish_error("Audio vazio")
                        return

                language = self.settings.get("language", "pt")
                model = self.settings.get("groq_stt_model", "whisper-large-v3-turbo")
                correct = self.settings.get_bool("gpt_correction", True)
                correction_style = self.settings.get("correction_style", "neutro")
                format_mode = self._effective_message_format_mode()
                domain_profile = self.settings.get("domain_lexicon_profile", "none")
                corrector_model = self.settings.get("groq_corrector_model", "llama-3.3-70b-versatile")
                device_id = self._get_device_id() or None
                offline_queue_enabled = self.settings.get_bool("offline_queue_enabled", True)
                request_timeout_seconds = max(45.0, min(240.0, 20.0 + (float(duration_seconds) * 3.0)))

                def _call(token: str):
                    return self.edge_transcriber.transcribe_wav_bytes(
                        wav_bytes,
                        access_token=token,
                        language=language,
                        model=model,
                        correct=correct,
                        correction_style=correction_style,
                        format_mode=format_mode,
                        domain_profile=domain_profile,
                        corrector_model=corrector_model,
                        device_id=device_id,
                        metadata={"app_version": self._get_app_version() or None},
                        request_timeout_seconds=request_timeout_seconds,
                    )

                try:
                    # Ensure we have a fresh token before calling Edge Functions (prevents random 401s).
                    token = access_token
                    try:
                        if self.session_manager:
                            token = self.session_manager.ensure_fresh_access_token(min_ttl_seconds=60)
                    except OfflineError:
                        token = access_token  # keep current token; we'll handle offline below
                    except LoginRequiredError:
                        # Refresh token rejected — but since the user was able to
                        # START recording (session was valid moments ago), this is
                        # likely a transient server issue. Keep the current token
                        # and let the batch call try; if it also fails, the retry
                        # logic will queue the audio for later.
                        self._record_client_event(
                            event_type="refresh_transient_in_transcribe",
                            severity="warning",
                            message="Token refresh failed during transcription; using current token",
                            details={"stage": "ensure_fresh"},
                        )
                        self._auth_recovery_needed = True
                        token = access_token

                    # If streaming already got the result, skip the batch call
                    if transcription:
                        result = None  # streaming already set transcription vars
                    else:
                        result = _call(token)
                except requests.exceptions.RequestException as e:
                    # Network failures and long backend processing should not force logout.
                    is_timeout = isinstance(e, requests.exceptions.ReadTimeout)
                    notify_title = "Servidor demorou" if is_timeout else "Sem internet"
                    notify_msg = (
                        "A transcrição demorou mais que o esperado. Salvamos sua gravação e vamos concluir automaticamente."
                        if is_timeout
                        else "Salvamos sua gravação e vamos enviar automaticamente quando a conexão voltar."
                    )
                    ui_err = "Servidor lento" if is_timeout else "Sem internet"
                    self._record_client_event(
                        event_type="transcribe_timeout" if is_timeout else "transcribe_network_error",
                        severity="warning",
                        message="Timeout during transcribe" if is_timeout else "Network error during transcribe",
                        details={"exception": type(e).__name__},
                    )
                    if offline_queue_enabled and self.outbox_repo:
                        try:
                            outbox_id = self.outbox_repo.add_edge_transcribe(
                                wav_bytes,
                                {
                                    "language": language,
                                    "model": model,
                                    "correct": correct,
                                    "correction_style": correction_style,
                                    "format_mode": format_mode,
                                    "domain_profile": domain_profile,
                                    "corrector_model": corrector_model,
                                    "duration_seconds": float(duration_seconds),
                                    "queued_reason": "timeout" if is_timeout else "network",
                                },
                            )
                            self._record_client_event(
                                event_type="transcribe_offline_queued",
                                severity="info",
                                message="Queued offline transcription",
                                details={"outbox_id": outbox_id},
                            )
                        except Exception:
                            pass
                        try:
                            self.ui_dispatcher.notify.emit(
                                notify_title,
                                notify_msg,
                            )
                        except Exception:
                            pass
                        self.ui_state.finish_error(ui_err)
                        if self._sound_fx_enabled:
                            play_error()
                        return

                    self.ui_state.finish_error(ui_err)
                    if self._sound_fx_enabled:
                        play_error()
                    return
                except SupabaseError as e:
                    try:
                        logger.warning(
                            "Transcribe SupabaseError: status=%s payload_type=%s",
                            getattr(e, "status_code", None),
                            type(getattr(e, "payload", None)).__name__,
                        )
                    except Exception:
                        pass
                    # Forced update gate from backend (minimum supported version).
                    if getattr(e, "status_code", None) == 426:
                        self._record_client_event(
                            event_type="force_update_required",
                            severity="warning",
                            message="Backend requires client update",
                            details={"stage": "transcribe"},
                        )
                        self._handle_upgrade_required(getattr(e, "payload", None))
                        self.ui_state.finish_error("Atualizacao obrigatoria")
                        if self._sound_fx_enabled:
                            play_error()
                        return
                    # If token is expired/invalid, try refresh once with a lock.
                    if e.status_code == 401 and self.session_manager:
                        invalid_jwt_first = self._is_invalid_jwt_payload(getattr(e, "payload", None))
                        self._log_access_token_diagnostics("transcribe_401_initial", token)
                        self._record_client_event(
                            event_type="transcribe_401_invalid_jwt" if invalid_jwt_first else "transcribe_401_user_session_invalid",
                            severity="error",
                            message="Edge returned 401 (invalid JWT)" if invalid_jwt_first else "Edge returned 401",
                            details={"stage": "call", "invalid_jwt": invalid_jwt_first},
                        )
                        try:
                            token2 = self.session_manager.force_refresh_access_token(ignore_ttl=True)
                            self._record_client_event(
                                event_type="refresh_success_after_401",
                                severity="info",
                                message="Refresh succeeded after 401",
                                details={"stage": "force_refresh"},
                            )
                            result = _call(token2)
                        except OfflineError:
                            self._record_client_event(
                                event_type="refresh_failed_after_401",
                                severity="warning",
                                message="Refresh failed after 401 (offline)",
                                details={"stage": "force_refresh", "reason": "offline"},
                            )
                            # Treat as temporary connectivity issue (do not logout).
                            if offline_queue_enabled and self.outbox_repo:
                                try:
                                    outbox_id = self.outbox_repo.add_edge_transcribe(
                                        wav_bytes,
                                        {
                                            "language": language,
                                            "model": model,
                                            "correct": correct,
                                            "correction_style": correction_style,
                                            "format_mode": format_mode,
                                            "domain_profile": domain_profile,
                                            "corrector_model": corrector_model,
                                            "duration_seconds": float(duration_seconds),
                                            "queued_reason": "offline_refresh",
                                        },
                                    )
                                    self._record_client_event(
                                        event_type="transcribe_offline_queued",
                                        severity="info",
                                        message="Queued after refresh offline",
                                        details={"outbox_id": outbox_id},
                                    )
                                except Exception:
                                    pass
                                try:
                                    self.ui_dispatcher.notify.emit(
                                        "Sem internet",
                                        "Salvamos sua gravacao e vamos enviar automaticamente quando a conexao voltar.",
                                    )
                                except Exception:
                                    pass
                                self.ui_state.finish_error("Sem internet")
                                if self._sound_fx_enabled:
                                    play_error()
                                return

                            self.ui_state.finish_error("Conexao instavel")
                            if self._sound_fx_enabled:
                                play_error()
                            return
                        except LoginRequiredError:
                            # Refresh rejected — but user was recording moments ago,
                            # so treat as transient. Queue audio for retry, don't logout.
                            # Flag for auth check on next recording attempt.
                            self._auth_recovery_needed = True
                            self._record_client_event(
                                event_type="refresh_failed_after_401",
                                severity="warning",
                                message="Refresh failed after 401; queuing audio for retry",
                                details={"stage": "force_refresh"},
                            )
                            if offline_queue_enabled and self.outbox_repo:
                                try:
                                    self.outbox_repo.add_edge_transcribe(
                                        wav_bytes,
                                        {
                                            "language": language,
                                            "model": model,
                                            "correct": correct,
                                            "correction_style": correction_style,
                                            "format_mode": format_mode,
                                            "domain_profile": domain_profile,
                                            "corrector_model": corrector_model,
                                            "duration_seconds": float(duration_seconds),
                                            "queued_reason": "refresh_failed_transient",
                                        },
                                    )
                                except Exception:
                                    pass
                            try:
                                self.ui_dispatcher.notify.emit(
                                    "Erro temporário",
                                    "Salvamos sua gravação e vamos enviar automaticamente em instantes.",
                                )
                            except Exception:
                                pass
                            self.ui_state.finish_error("Reenviando em breve")
                            if self._sound_fx_enabled:
                                play_error()
                            return
                        except SupabaseError as e2:
                            try:
                                logger.warning(
                                    "Transcribe retry SupabaseError: status=%s payload_type=%s",
                                    getattr(e2, "status_code", None),
                                    type(getattr(e2, "payload", None)).__name__,
                                )
                            except Exception:
                                pass
                            if getattr(e2, "status_code", None) == 401:
                                # The refresh SUCCEEDED (we got token2), which proves
                                # the session is valid. A 401 on retry is always a
                                # transient server issue — never force logout here.
                                self._log_access_token_diagnostics("transcribe_401_retry", token2 if "token2" in locals() else self._get_access_token())
                                self._record_client_event(
                                    event_type="transcribe_backend_invalid_jwt",
                                    severity="error",
                                    message="Backend rejected freshly refreshed JWT — transient server issue",
                                    details={"stage": "retry"},
                                )
                                # Queue audio for automatic retry so user's recording is not lost.
                                if offline_queue_enabled and self.outbox_repo:
                                    try:
                                        outbox_id = self.outbox_repo.add_edge_transcribe(
                                            wav_bytes,
                                            {
                                                "language": language,
                                                "model": model,
                                                "correct": correct,
                                                "correction_style": correction_style,
                                                "format_mode": format_mode,
                                                "domain_profile": domain_profile,
                                                "corrector_model": corrector_model,
                                                "duration_seconds": float(duration_seconds),
                                                "queued_reason": "server_auth_transient",
                                            },
                                        )
                                        self._record_client_event(
                                            event_type="transcribe_queued_after_server_401",
                                            severity="info",
                                            message="Queued transcription after transient server 401",
                                            details={"outbox_id": outbox_id},
                                        )
                                    except Exception:
                                        pass
                                try:
                                    self.ui_dispatcher.notify.emit(
                                        "Erro temporário",
                                        "Salvamos sua gravação e vamos enviar automaticamente em instantes.",
                                    )
                                except Exception:
                                    pass
                                self.ui_state.finish_error("Reenviando em breve")
                                if self._sound_fx_enabled:
                                    play_error()
                                return
                            raise

                    # Quota/entitlement block: show a friendly message.
                    if e.status_code == 403 and isinstance(e.payload, dict):
                        try:
                            self._set_cached_access(e.payload)
                        except Exception:
                            pass
                        reason = str(e.payload.get("reason") or "")
                        msg = self._access_block_message(reason, e.payload)
                        if reason == "entitlement_expired":
                            self._record_lead_lifecycle_event_async(
                                "trial_expired_seen",
                                metadata={"source": "transcribe_response", "reason": reason},
                            )
                            self._open_trial_expired_ui(reason=msg)
                        self.ui_state.finish_error(msg)
                        if self._sound_fx_enabled:
                            play_error()
                        return

                    raise

                # Backend result (skip if streaming already populated these)
                if result is not None:
                    original_text = str((result.transcription or {}).get("original_text") or "").strip()
                    corrected_text_raw = str((result.transcription or {}).get("corrected_text") or "").strip()
                    corrected_text = corrected_text_raw or None
                    transcription_id = str((result.transcription or {}).get("id") or "").strip()
                    correction_pending = bool((result.transcription or {}).get("correction_pending", False))
                    processing_tier = str((result.processing or {}).get("tier") or "").strip().lower() or "trial"
                    transcription = corrected_text or original_text or result.text
                    try:
                        self._update_access_cache_from_usage(result.usage)
                    except Exception:
                        pass
                    try:
                        self.settings.set("last_speed_tier", processing_tier)
                        self.settings.save()
                    except Exception:
                        pass
                    self._record_client_event(
                        event_type="tier_resolved",
                        severity="info",
                        message=f"Tier resolved: {processing_tier}",
                        details={
                            "tier": processing_tier,
                            "correction_pending": correction_pending,
                            "transcription_id": transcription_id,
                        },
                    )
                    try:
                        dur = result.transcription.get("audio_duration_seconds", None)
                        if dur is not None:
                            duration_seconds = float(dur)
                    except Exception:
                        pass

                # Pro "quase real-time": paste now, refine in background via outbox worker.
                if (
                    processing_tier == "pro"
                    and correction_pending
                    and transcription_id
                    and self.outbox_repo is not None
                ):
                    try:
                        outbox_id = self.outbox_repo.add_edge_postprocess(
                            {
                                "transcription_id": transcription_id,
                                "style": correction_style,
                                "format_mode": format_mode,
                                "domain_profile": domain_profile,
                            }
                        )
                        self._record_client_event(
                            event_type="postprocess_queued",
                            severity="info",
                            message="Queued async postprocess",
                            details={"outbox_id": outbox_id, "transcription_id": transcription_id, "tier": processing_tier},
                        )
                    except Exception as exc:
                        self._record_client_event(
                            event_type="postprocess_failed",
                            severity="warning",
                            message="Failed to queue async postprocess",
                            details={"error": type(exc).__name__, "transcription_id": transcription_id},
                        )

            elif self.transcription_mode == "local_groq":
                if not self.transcriber:
                    raise ValueError("Transcriber not initialized")
                # Transcribe locally (DEV-only fallback)
                t_stt = time.perf_counter()
                # No dictation context here: on real speech Whisper copied the previous
                # dictations from the prompt (11/13 correct without context vs 2/13 with it).
                transcription = self.transcriber.transcribe(
                    audio_data,
                    sample_rate=self.recorder.sample_rate,
                )
                stage_ms["stt"] = int((time.perf_counter() - t_stt) * 1000)
            else:
                raise SupabaseError(self._transcription_not_ready_message())

            if not transcription or not transcription.strip() or len(transcription.strip()) < 2:
                logger.warning("Empty or trivial transcription: %r", transcription)
                self.ui_state.finish_error("Nenhuma fala detectada")
                if self._sound_fx_enabled:
                    play_error()
                return

            # Store original (local transcription path)
            if original_text is None:
                original_text = transcription
            replaced_text = self.text_replacements.apply(transcription)
            if replaced_text != transcription:
                transcription = replaced_text
                corrected_text = replaced_text

            # Trial plan keeps a deliberate floor for perceived speed differentiation.
            if self.transcription_mode == "edge" and processing_tier == "trial":
                try:
                    floor_raw = self.settings.get("trial_latency_floor_ms", 4000)
                    floor_ms = int(float(floor_raw))
                except Exception:
                    floor_ms = 4000
                if floor_ms > 0:
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    if elapsed_ms < floor_ms:
                        trial_floor_applied_ms = floor_ms - elapsed_ms
                        time.sleep(trial_floor_applied_ms / 1000.0)
                        self._record_client_event(
                            event_type="trial_floor_applied",
                            severity="info",
                            message="Applied trial latency floor",
                            details={
                                "tier": processing_tier,
                                "elapsed_ms_before_floor": elapsed_ms,
                                "floor_ms": floor_ms,
                                "applied_ms": trial_floor_applied_ms,
                            },
                        )

            # Apply correction if enabled
            if (
                self.transcription_mode == "local_groq"
                and self.settings.get_bool("gpt_correction", True)
                and self.corrector
            ):
                style = self.settings.get("correction_style", "neutro")
                format_mode = self._effective_message_format_mode()
                domain_profile = self.settings.get("domain_lexicon_profile", "none")
                t_corr = time.perf_counter()
                corrected_text_local = self.corrector.correct(
                    transcription,
                    style,
                    format_mode=format_mode,
                    domain_profile=domain_profile,
                    context=dictation_context,
                )
                stage_ms["revisor"] = int((time.perf_counter() - t_corr) * 1000)
                if corrected_text_local:
                    corrected_text_local = self.text_replacements.apply(corrected_text_local)
                if corrected_text_local and corrected_text_local != transcription:
                    corrected_text = corrected_text_local
                    transcription = corrected_text_local

            # Save to history
            output_format_mode = self._effective_message_format_mode()
            if output_format_mode == "message":
                transcription = format_message_blocks(
                    transcription,
                    audio_data=audio_data,
                    sample_rate=self.recorder.sample_rate,
                )
                if corrected_text:
                    corrected_text = transcription

            if not self._is_onboarding_active():
                self.dictation_memory.remember(transcription)
                if self.settings.get_bool("save_debug_audio", False):
                    save_debug_sample(
                        numpy_to_wav_bytes(audio_data, self.recorder.sample_rate),
                        original_text or "",
                        transcription,
                    )
                self.history.add(
                    original=original_text,
                    corrected=corrected_text,
                    duration_seconds=duration_seconds,
                    transcription_id=transcription_id or None,
                )
                if self.transcription_mode == "edge" and transcription_id:
                    self._record_lead_lifecycle_event_async(
                        "first_transcription_detected",
                        transcription_id=transcription_id,
                        metadata={
                            "tier": processing_tier,
                            "duration_seconds": round(float(duration_seconds), 2),
                        },
                    )

            # Update main window if visible
            self.ui_dispatcher.transcription_ready.emit(transcription)

            # Auto-paste if enabled
            if self.settings.get("auto_paste", True) and not self._is_onboarding_active():
                # Restore focus to the window that was active when recording started
                if self.last_active_window:
                    self.window_manager.set_foreground_window(self.last_active_window)

                self.clipboard.paste_to_active_field(transcription)
            elif not self._is_onboarding_active():
                self.clipboard.copy_to_clipboard(transcription)

            e2e_ms = int((time.perf_counter() - t0) * 1000)
            stage_ms["total"] = e2e_ms
            logger.info(
                "Latency: %s audio=%.1fs",
                " ".join(f"{k}={v}ms" for k, v in stage_ms.items()),
                duration_seconds,
            )
            if self.transcription_mode == "edge":
                self._record_client_event(
                    event_type="e2e_latency_sample",
                    severity="info",
                    message="Captured e2e latency sample",
                    details={
                        "tier": processing_tier,
                        "correction_pending": correction_pending,
                        "duration_seconds": round(float(duration_seconds), 2),
                        "e2e_ms": e2e_ms,
                        "trial_floor_applied_ms": trial_floor_applied_ms,
                    },
                )
                # Server-side latency breakdown for diagnostics
                _proc = (result.processing or {}) if result is not None and hasattr(result, 'processing') else {}
                server_latency = _proc.get("latency_ms", {}) if _proc else {}
                server_correction_mode = str(_proc.get("correction_mode", "?"))
                server_speed_tier = _proc.get("speed_tier_enabled", "?")
                logger.info(
                    "E2E latency sample: tier=%s e2e_ms=%s floor_applied_ms=%s dur=%.2fs | server: stt=%s corr=%s total=%s mode=%s speed_tier=%s pending=%s",
                    processing_tier,
                    e2e_ms,
                    trial_floor_applied_ms,
                    float(duration_seconds),
                    server_latency.get("stt", "?"),
                    server_latency.get("correction", "?"),
                    server_latency.get("total", "?"),
                    server_correction_mode,
                    server_speed_tier,
                    correction_pending,
                )

            # Transcription succeeded — clear any pending auth recovery flag.
            self._auth_recovery_needed = False

            # Show success in floating bar
            self.ui_state.finish_success()

            logger.info("Transcription complete")
            logger.debug("Result: %s", transcription)

        except Exception as e:
            logger.error("Error during transcription", exc_info=True)
            if self._sound_fx_enabled:
                play_error()
            self.ui_state.finish_error(str(e)[:30])

    def run(self):
        """Run the application"""
        try:
            # Check if microphone is available
            if self.recorder and not self.recorder.is_microphone_available():
                logger.error("No microphone detected")
            elif self.recorder:
                try:
                    self.recorder.prepare()
                except Exception:
                    logger.warning("Microphone preparation failed; retry on recording", exc_info=True)

            # Start system tray
            logger.debug("Starting system tray")
            self.tray.start()

            # Show notification
            self.tray.show_notification(
                "FALAI Ativo",
                f"Pressione {self.settings.get('hotkey', 'Ctrl+Shift')} para ditar"
            )

            # Open main window automatically on startup
            logger.debug("Opening main window")
            self._show_main_window()
            logger.debug("Main window should be visible now")

            # Start Qt event loop
            logger.debug("Starting Qt event loop")
            sys.exit(self.app.exec())

        except Exception as e:
            logger.error("Exception in run()", exc_info=True)

        finally:
            # Cleanup
            if self.recorder:
                self.recorder.close()
            self.hotkey_manager.stop_listening()
            self.tray.stop()
            logger.info("FALAI closed. Goodbye!")


def main():
    """Main entry point"""
    app = FalaiApp()
    app.run()


if __name__ == "__main__":
    main()
