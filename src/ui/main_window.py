"""
Main window UI - PySide6/Qt interface for FALAI (Premium)
"""
from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QApplication, QFrame, QBoxLayout, QGraphicsOpacityEffect
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QPropertyAnimation
from PySide6.QtGui import QPixmap, QFont, QIcon, QFontDatabase, QImage, QColor

from src.ui.theme import get_stylesheet, get_colors
from src.ui.components import IconNavButton
from src.utils.logger import get_logger

logger = get_logger(__name__)
from src.ui.pages import (
    HomePage,
    LoginPage,
    SettingsPage,
    HistoryPage,
    StatsPage,
)
from src.ui.onboarding import OnboardingDialog, ONBOARDING_VERSION
from src.config.runtime_mode import is_local_runtime

PASSWORD_RESET_REDIRECT_URL = "https://falai.app/reset-password"

try:
    import qtawesome as qta
except Exception:
    qta = None


class MainWindow(QMainWindow):
    """Main application window"""

    # Signals for communication with main app
    record_requested = Signal()
    stop_requested = Signal()
    settings_requested = Signal()
    history_requested = Signal()
    stats_requested = Signal()
    logout_requested = Signal()
    settings_saved = Signal(object)
    login_finished = Signal(str)  # empty string => success; otherwise user-facing error
    password_reset_finished = Signal(str)  # empty string => success; otherwise user-facing error

    def __init__(self, settings=None, history=None, on_theme_change=None):
        super().__init__()

        self.is_recording = False
        self.settings = settings
        self.history = history
        self.on_theme_change = on_theme_change
        self._page_changed_callback = None
        self._hotkey_toggle_callback = None
        self._password_reset_callback = None
        self._login_callback = None
        self._logo_pixmap_cache = {}
        self._login_required_lock = False
        self._local_runtime = is_local_runtime()
        self.theme = self.settings.get("theme", "dark") if self.settings else "dark"
        self.colors = get_colors(self.theme)

        self.setWindowTitle("FALAI - Voice Transcription")
        self.resize(980, 640)
        # Prevent shrinking too much (keeps layout stable), but allow maximize.
        self.setMinimumSize(960, 600)

        self._load_fonts()

        icon_ico = Path(__file__).parent.parent.parent / "assets" / "icons" / "app.ico"
        icon_png = Path(__file__).parent.parent.parent / "assets" / "icons" / "app.png"
        if icon_ico.exists():
            self.setWindowIcon(QIcon(str(icon_ico)))
        elif icon_png.exists():
            self.setWindowIcon(QIcon(str(icon_png)))

        self._create_ui()
        self._sidebar_breakpoint = 860
        self.login_finished.connect(self._on_login_finished_ui)
        self.password_reset_finished.connect(self._on_password_reset_finished_ui)

    def _load_fonts(self):
        """Carrega fontes locais (se existirem)"""
        font_dir = Path(__file__).parent.parent.parent / "assets" / "fonts"
        loaded = False
        loaded_fonts = []
        missing_fonts = []
        for name in [
            "Manrope-Regular.ttf",
            "Manrope-SemiBold.ttf",
            "manrope-regular.otf",
            "manrope-semibold.otf",
        ]:
            path = font_dir / name
            if path.exists():
                if QFontDatabase.addApplicationFont(str(path)) != -1:
                    loaded = True
                    loaded_fonts.append(name)
                else:
                    logger.warning("Failed to load font file: %s", path)
            else:
                missing_fonts.append(name)
        if loaded:
            app = QApplication.instance()
            if app:
                app.setFont(QFont("Manrope", 10))
            logger.info("Manrope fonts loaded: %s", ", ".join(loaded_fonts))
            logger.info("Global font set to Manrope")
        else:
            logger.warning("Manrope fonts not loaded; using theme defaults")
            if missing_fonts:
                logger.debug("Missing font files: %s", ", ".join(missing_fonts))

    def _icon(self, name: str) -> QIcon:
        if qta:
            return qta.icon(name, color=self.colors["foreground"])
        return QIcon()

    def _get_logo_path(self) -> Path:
        base = Path(__file__).parent.parent.parent / "logos e files design" / "ui logos"
        if self.theme == "beige":
            return base / "logo_01-_icone_-_preto-removebg-preview.png"
        return base / "logo_01-_icone-_branco-removebg-preview.png"

    def _refresh_brand_logo(self):
        logo_path = self._get_logo_path()
        if logo_path.exists():
            cache_key = f"{self.theme}:{str(logo_path)}"
            logo_pixmap = self._logo_pixmap_cache.get(cache_key)
            if logo_pixmap is None:
                logo_pixmap = QPixmap(str(logo_path))
                logo_pixmap = self._process_logo_pixmap(logo_pixmap)
                self._logo_pixmap_cache[cache_key] = logo_pixmap
            height = 32 if getattr(self, "sidebar_collapsed", False) else 42
            self.brand_logo.setPixmap(logo_pixmap.scaledToHeight(height, Qt.SmoothTransformation))
            self.brand_logo.setMinimumSize(height, height)
        else:
            self.brand_logo.setText("🎙")
            self.brand_logo.setStyleSheet("font-size: 28px;")

    def _process_logo_pixmap(self, pixmap: QPixmap) -> QPixmap:
        if self.theme != "beige":
            return pixmap
        image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        width = image.width()
        height = image.height()
        for y in range(height):
            for x in range(width):
                color = QColor(image.pixel(x, y))
                if color.red() >= 245 and color.green() >= 245 and color.blue() >= 245:
                    color.setAlpha(0)
                    image.setPixelColor(x, y, color)
        return QPixmap.fromImage(image)

    def _create_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(240)
        self.sidebar_collapsed = False
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(16, 20, 16, 20)
        side_layout.setSpacing(8)
        self.side_layout = side_layout

        # Brand
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        self.brand_logo = QLabel()
        self.brand_logo.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._refresh_brand_logo()
        brand_row.addWidget(self.brand_logo)
        self.brand_text = QWidget()
        title_col = QVBoxLayout(self.brand_text)
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(0)
        self.brand_title = QLabel("FALAI")
        self.brand_title.setObjectName("brandTitle")
        self.brand_title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.brand_sub = QLabel("")
        self.brand_sub.setObjectName("brandSubtitle")
        self.brand_sub.setVisible(False)
        title_col.addWidget(self.brand_title)
        if self.brand_sub.text():
            title_col.addWidget(self.brand_sub)
        brand_row.addWidget(self.brand_text)
        brand_row.setAlignment(self.brand_text, Qt.AlignVCenter)
        brand_row.addStretch()
        side_layout.addLayout(brand_row)

        side_layout.addSpacing(6)

        self.nav_buttons = {}
        items = [
            ("home", "Início", "fa5s.microphone", True),
            ("history", "Histórico", "fa5s.history", True),
            ("settings", "Configurações", "fa5s.cog", True),
            ("stats", "Estatísticas", "fa5s.chart-bar", True),
        ]

        for key, label, icon, is_page in items:
            btn = IconNavButton(label, self._icon(icon), checkable=is_page)
            btn.setToolTip(label)
            btn.setProperty("fullText", label)
            btn.clicked.connect(lambda checked, k=key: self._on_nav_clicked(k))
            self.nav_buttons[key] = btn
            side_layout.addWidget(btn)

        side_layout.addStretch()

        # Footer controls (theme + collapse)
        self.footer_layout = QBoxLayout(QBoxLayout.LeftToRight)
        self.footer_layout.setContentsMargins(0, 8, 0, 0)
        self.footer_layout.setSpacing(8)

        self.theme_toggle_btn = QPushButton()
        self.theme_toggle_btn.setObjectName("iconButton")
        self.theme_toggle_btn.setFixedSize(32, 32)
        self.theme_toggle_btn.setToolTip("Alternar tema")
        self._refresh_theme_icon()
        self.theme_toggle_btn.clicked.connect(self._toggle_theme)
        self.footer_layout.addWidget(self.theme_toggle_btn)

        self.collapse_btn = QPushButton()
        self.collapse_btn.setObjectName("iconButton")
        self.collapse_btn.setFixedSize(32, 32)
        self.collapse_btn.setToolTip("Recolher sidebar")
        self._refresh_collapse_icon()
        self.collapse_btn.clicked.connect(self.toggle_sidebar)
        self.footer_layout.addWidget(self.collapse_btn)

        side_layout.addLayout(self.footer_layout)
        main_layout.addWidget(self.sidebar)

        # Content area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.stack = QStackedWidget()
        history_manager = self.history or self._empty_history_manager()
        self.home_page = HomePage(settings=self.settings, history_manager=history_manager)
        self.history_page = HistoryPage(history_manager)
        self.stats_page = StatsPage(history_manager, self.theme)
        self.settings_page = SettingsPage(self.settings, self._apply_theme, self) if self.settings else SettingsPage(None, self._apply_theme, self)
        if hasattr(self.settings_page, "settings_saved"):
            self.settings_page.settings_saved.connect(self.settings_saved.emit)
        if hasattr(self.settings_page, "logout_requested"):
            self.settings_page.logout_requested.connect(self._on_settings_logout_requested)
        if hasattr(self.settings_page, "login_page_requested"):
            self.settings_page.login_page_requested.connect(self._on_settings_login_page_requested)
        self.login_page = LoginPage()
        try:
            if hasattr(self.login_page, "login_requested"):
                self.login_page.login_requested.connect(self._on_login_requested)
            if hasattr(self.login_page, "password_reset_requested"):
                self.login_page.password_reset_requested.connect(self._on_password_reset_requested)
        except Exception:
            pass

        self.pages = {
            "home": self.home_page,
            "history": self.history_page,
            "settings": self.settings_page,
            "stats": self.stats_page,
            "login": self.login_page,
        }
        for page in self.pages.values():
            self.stack.addWidget(page)

        content_layout.addWidget(self.stack)
        main_layout.addWidget(content, 1)

        self.home_page.record_button.set_click_callback(self._toggle_recording)
        
        # Connect new premium actions
        if hasattr(self.home_page, "connect_actions"):
            self.home_page.connect_actions(
                self.home_page.open_mic_test
            )
            
        self._set_selected("home")
        self.stack.setCurrentWidget(self.home_page)

        if self.settings:
            if self.settings.get("sidebar_collapsed", False):
                self.set_sidebar_collapsed(True)
        QTimer.singleShot(0, self.maybe_show_onboarding)

    def _on_login_requested(self, auth_payload: dict):
        """Handle LoginPage submission (runs network in a thread, updates UI in main thread)."""
        if not self.settings:
            try:
                if hasattr(self.login_page, "set_status"):
                    self.login_page.set_status("Configuração indisponível.")
            except Exception:
                pass
            return

        email = (auth_payload.get("email") or "").strip()
        password = (auth_payload.get("password") or "").strip()
        remember_me = bool(auth_payload.get("remember_me", False))

        try:
            if hasattr(self.login_page, "set_loading"):
                self.login_page.set_loading(True)
        except Exception:
            pass

        def _worker():
            err = self._login_sync(email=email, password=password, remember_me=remember_me)
            self.login_finished.emit((err or "").strip())

        import threading

        threading.Thread(target=_worker, daemon=True).start()

    def _on_login_finished_ui(self, err: str):
        """Always executes in UI thread (Qt signal), safe to mutate widgets."""
        page = getattr(self, "login_page", None)
        if page is None:
            return
        try:
            if hasattr(page, "set_loading"):
                page.set_loading(False)
        except Exception:
            pass

        msg = str(err or "").strip()
        if msg:
            try:
                if hasattr(page, "set_status"):
                    page.set_status(msg)
            except Exception:
                pass
            return

        self._set_login_lock(False)
        try:
            if hasattr(page, "set_status"):
                page.set_status("")
            if hasattr(page, "set_reason"):
                page.set_reason("")
        except Exception:
            pass

        # Back to home and let main.py refresh backend state (quota, edge mode, etc).
        self.switch_page("home")
        try:
            # auth_session avoids full backend reinit that can drop in-memory sessions.
            self.settings_saved.emit(["auth_session"])
        except Exception:
            pass

    def _login_sync(self, *, email: str, password: str, remember_me: bool) -> str | None:
        """Single login path for LoginPage and onboarding.

        When available, delegates authentication to the app-level callback so the
        same AuthService/session is reused by the transcription backend.
        """
        mail = str(email or "").strip()
        pwd = str(password or "").strip()
        if not mail:
            return "Informe seu e-mail."
        if self._local_runtime:
            self.settings.set("auth_token", f"local:{mail.lower()}")
            self.settings.set("user_email", mail if remember_me else "")
            self.settings.set("remember_me", bool(remember_me))
            self.settings.save()
            return None
        if not pwd:
            return "Informe sua senha."

        try:
            if callable(self._login_callback):
                result = self._login_callback(mail, pwd, bool(remember_me))
                if isinstance(result, str) and result.strip():
                    return result.strip()
                return None

            from src.backend.auth_service import AuthService
            from src.backend.supabase_client import SupabaseClient, SupabaseError

            client = SupabaseClient.from_env()
            auth = AuthService(client, settings=self.settings)
            session = auth.login(email=mail, password=pwd, remember_me=bool(remember_me))
            if not (session.access_token or "").strip():
                return "Falha ao entrar. Verifique e tente novamente."
            try:
                client.auth_get_user((session.access_token or "").strip())
            except SupabaseError as exc:
                if getattr(exc, "status_code", None) == 401:
                    return "Falha de autenticação da sessão. Tente entrar novamente."
                # Non-401 post-check errors are usually transient; allow login to proceed.
            except Exception:
                # Network/transient issue after login; avoid forcing a second manual attempt.
                pass
            return None
        except Exception as exc:
            msg = "Falha ao entrar. Verifique seu e-mail e senha."
            try:
                from src.backend.supabase_client import SupabaseError

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
            logger.warning("Login failed: %s", type(exc).__name__)
            return msg

    def _on_settings_logout_requested(self):
        self.logout_requested.emit()

    def _on_settings_login_page_requested(self):
        try:
            if hasattr(self, "settings_page") and hasattr(self.settings_page, "refresh_account_state"):
                self.settings_page.refresh_account_state()
        except Exception:
            pass
        email = ""
        try:
            if self.settings:
                email = str(self.settings.get("user_email", "") or "").strip()
        except Exception:
            email = ""
        try:
            if hasattr(self, "login_page"):
                if hasattr(self.login_page, "set_reason"):
                    self.login_page.set_reason("Entre para continuar.")
                if hasattr(self.login_page, "set_prefill_email"):
                    self.login_page.set_prefill_email(email)
            self.switch_page("login")
        except Exception:
            self.switch_page("login")

    def _request_password_reset_sync(self, email: str) -> str | None:
        if self._local_runtime:
            return "Recuperação de senha não existe no modo local."
        mail = str(email or "").strip()
        if not mail:
            return "Informe seu e-mail para recuperar a senha."
        try:
            import requests
        except Exception:
            requests = None
        try:
            if callable(self._password_reset_callback):
                result = self._password_reset_callback(mail)
                if isinstance(result, str) and result.strip():
                    return result.strip()
                return None

            from src.backend.auth_service import AuthService
            from src.backend.supabase_client import SupabaseClient, SupabaseError

            client = SupabaseClient.from_env()
            auth = AuthService(client, settings=self.settings)
            auth.request_password_reset(email=mail, redirect_to=PASSWORD_RESET_REDIRECT_URL)
            return None
        except Exception as exc:
            msg = "Não foi possível enviar o e-mail de recuperação agora."
            if requests is not None and isinstance(exc, requests.exceptions.RequestException):
                msg = "Sem internet. Conecte-se e tente novamente."
            try:
                from src.backend.supabase_client import SupabaseError

                if isinstance(exc, SupabaseError):
                    if "SUPABASE_URL/SUPABASE_ANON_KEY" in str(exc):
                        msg = "Supabase não configurado (SUPABASE_URL/SUPABASE_ANON_KEY)."
            except Exception:
                pass
            return msg

    def _on_password_reset_requested(self, email: str):
        """Handle password reset from LoginPage asynchronously."""
        page = getattr(self, "login_page", None)
        if page is None:
            return

        try:
            if hasattr(page, "set_reset_loading"):
                page.set_reset_loading(True)
            if hasattr(page, "set_status"):
                page.set_status("Enviando e-mail de recuperação...")
        except Exception:
            pass

        def _worker():
            err = self._request_password_reset_sync(email)
            self.password_reset_finished.emit((err or "").strip())

        import threading

        threading.Thread(target=_worker, daemon=True).start()

    def _on_password_reset_finished_ui(self, err: str):
        """Always executes in UI thread (Qt signal), safe to mutate widgets."""
        page = getattr(self, "login_page", None)
        if page is None:
            return
        try:
            if hasattr(page, "set_reset_loading"):
                page.set_reset_loading(False)
            if hasattr(page, "set_status"):
                if err:
                    page.set_status(str(err).strip())
                else:
                    page.set_status("Enviamos um e-mail de recuperação. Verifique sua caixa de entrada.")
        except Exception:
            pass

    def maybe_show_onboarding(self):
        if not self.settings:
            return
        completed = self.settings.get("onboarding_completed", False)
        version = self.settings.get("onboarding_version", 0)
        auth_token = (self.settings.get("auth_token", "") or "").strip()
        # Local sessions are valid in the local-first runtime. The old switch
        # remains unnecessary because cloud mode is explicit.
        allow_local_auth = self._local_runtime
        if auth_token.startswith("local:") and not allow_local_auth:
            auth_token = ""
        # If we "remember" supabase:<user_id> but lost the real session tokens, require login again.
        if auth_token.startswith("supabase:"):
            has_access = False
            try:
                from src.security.secure_store import get_secure_store

                has_access = bool((get_secure_store().get_access_token() or "").strip())
            except Exception:
                has_access = False
            if not has_access:
                auth_token = ""
        if completed and version == ONBOARDING_VERSION:
            if auth_token:
                return
            # Onboarding already completed, but we don't have a valid session -> show Login page.
            try:
                initial_email = self.settings.get("user_email", "")
            except Exception:
                initial_email = ""
            try:
                self.show_login(reason="Sessão expirada. Faça login novamente.", prefill_email=initial_email)
            except Exception:
                self.switch_page("login")
            return

        hotkey = self.settings.get("hotkey", "ctrl+shift")
        initial_email = self.settings.get("user_email", "")

        def _finish_onboarding(auth_payload: dict | None = None):
            if not auth_payload:
                return "Dados de login ausentes."

            email = (auth_payload.get("email") or "").strip()
            password = (auth_payload.get("password") or "").strip()
            remember_me = bool(auth_payload.get("remember_me", False))
            local_mode = bool(auth_payload.get("local_mode", False))

            if not email:
                return "Informe seu e-mail."

            if local_mode or self._local_runtime:
                self.settings.set("auth_token", f"local:{email.lower()}")
                self.settings.set("user_email", email if remember_me else "")
                self.settings.set("remember_me", remember_me)
                self.settings.save()
            else:
                if not password:
                    return "Informe sua senha."
                err = self._login_sync(email=email, password=password, remember_me=remember_me)
                if err:
                    return err

            self.settings.set("onboarding_completed", True)
            self.settings.set("onboarding_version", ONBOARDING_VERSION)
            self.settings.save()
            self.switch_page("home")
            # Notify main.py so it can refresh backend/session-dependent state (quota, Edge mode, etc).
            try:
                self.settings_saved.emit(["auth_session"])
            except Exception:
                pass
            return None

        def _open_settings():
            self.switch_page("settings")

        def _request_reset_onboarding(email: str):
            result = self._request_password_reset_sync(email)
            return result or ""

        dialog = OnboardingDialog(
            hotkey=hotkey,
            on_complete=_finish_onboarding,
            on_open_settings=_open_settings,
            on_request_password_reset=_request_reset_onboarding,
            initial_email=initial_email,
            parent=self,
        )
        self._onboarding_dialog = dialog
        try:
            result = dialog.exec()
            if result != OnboardingDialog.Accepted:
                app = QApplication.instance()
                if app:
                    QTimer.singleShot(0, app.quit)
        finally:
            self._onboarding_dialog = None

    def show_login(self, *, reason: str = "", prefill_email: str = ""):
        """Open the Login page (used for session expiry)."""
        if self._local_runtime:
            self._set_login_lock(False)
            self.switch_page("home")
            return
        self._set_login_lock(True)
        try:
            self.showNormal()
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

        try:
            self.switch_page("login")
        except Exception:
            return

        page = getattr(self, "login_page", None)
        if page is None:
            return
        try:
            if hasattr(page, "set_reason"):
                page.set_reason(reason or "")
            if hasattr(page, "set_prefill_email"):
                page.set_prefill_email(prefill_email or "")
        except Exception:
            pass

    def _set_login_lock(self, locked: bool) -> None:
        """Lock navigation while authentication is required."""
        if self._local_runtime:
            locked = False
        self._login_required_lock = bool(locked)
        try:
            for key, btn in self.nav_buttons.items():
                btn.setEnabled(not locked)
        except Exception:
            pass
        try:
            if hasattr(self, "collapse_btn"):
                self.collapse_btn.setEnabled(not locked)
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = event.size().width()
        should_collapse = width < self._sidebar_breakpoint
        if should_collapse != self.sidebar_collapsed:
            self.set_sidebar_collapsed(should_collapse)

    def _empty_history_manager(self):
        class _EmptyHistory:
            history = []

            def get_all(self, limit=50):
                return []

        return _EmptyHistory()

    def _set_selected(self, key: str):
        for k, btn in self.nav_buttons.items():
            if btn.isCheckable():
                btn.setChecked(k == key)

    def _on_nav_clicked(self, key: str):
        self.switch_page(key)

    def switch_page(self, key: str):
        if self._login_required_lock and key != "login":
            key = "login"
        if key in self.pages:
            self.stack.setCurrentWidget(self.pages[key])
            if key == "settings":
                try:
                    if hasattr(self, "settings_page") and hasattr(self.settings_page, "refresh_account_state"):
                        self.settings_page.refresh_account_state()
                except Exception:
                    pass
            elif key == "history":
                try:
                    if hasattr(self, "history_page") and hasattr(self.history_page, "refresh"):
                        self.history_page.refresh()
                except Exception:
                    pass
            self._set_selected(key)
            try:
                if callable(self._page_changed_callback):
                    self._page_changed_callback(str(key))
            except Exception:
                logger.warning("Failed to run page changed callback", exc_info=True)
            return

    def _toggle_recording(self):
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        self.is_recording = True
        self.home_page.set_status("Gravando", "Capturando áudio", self.colors["recording"])
        self.record_requested.emit()

    def stop_recording(self):
        self.is_recording = False
        self.set_processing_ui()
        self.stop_requested.emit()

    def set_ready_status(self):
        self.home_page.set_status("Pronto", "Aguardando áudio", self.colors["success"])

    def set_processing_status(self):
        self.set_processing_ui()

    def set_error_status(self, error_msg: str):
        self.home_page.set_status("Erro", error_msg, self.colors["error"])

    def set_processing_ui(self):
        self.home_page.set_status("Processando", "Convertendo áudio", self.colors["processing"])

    def set_idle_ui(self):
        self.set_ready_status()

    def update_transcription(self, text: str):
        self.home_page.set_transcription(text)

    def append_transcription(self, text: str):
        self.home_page.append_transcription(text)

    def update_mode_info(self, mode: str, hotkey: str):
        self.home_page.update_mode_info(mode, hotkey)

    def set_page_changed_callback(self, callback: Callable):
        self._page_changed_callback = callback

    def set_update_callbacks(
        self,
        check_callback: Callable = None,
        open_callback: Callable = None,
        download_callback: Callable = None,
        install_callback: Callable = None,
    ):
        """Wire Settings -> Updates buttons to app callbacks."""
        try:
            if hasattr(self, "settings_page") and hasattr(self.settings_page, "set_update_callbacks"):
                self.settings_page.set_update_callbacks(check_callback, open_callback, download_callback, install_callback)
        except Exception:
            logger.warning("Failed to set update callbacks", exc_info=True)

    def _apply_theme(self, theme: str):
        if theme not in ("dark", "beige"):
            theme = "dark"
        if self.theme == theme:
            return

        self.theme = theme
        self.colors = get_colors(theme)
        stylesheet = get_stylesheet(theme)

        # Apply theme once at app level (fast path) and once for this window.
        app = QApplication.instance()
        if app:
            app.setStyleSheet(stylesheet)

        self._refresh_brand_logo()
        self._refresh_nav_icons()
        self._refresh_theme_icon()
        self._refresh_collapse_icon()

        if hasattr(self, "settings_page"):
            self.settings_page.set_theme(theme)
        if hasattr(self, "home_page"):
            self.home_page.set_theme(theme)
        if hasattr(self, "stats_page"):
            self.stats_page.set_theme(theme)

        if not self.is_recording:
            self.set_ready_status()


    def _animate_theme_transition(self):
        return

    def _refresh_nav_icons(self):
        if not qta:
            return
        icon_map = {
            "home": "fa5s.microphone",
            "history": "fa5s.history",
            "settings": "fa5s.cog",
            "stats": "fa5s.chart-bar",
        }
        for key, btn in self.nav_buttons.items():
            icon_name = icon_map.get(key)
            if icon_name:
                btn.setIcon(self._icon(icon_name))

    def _toggle_theme(self):
        theme = "beige" if self.theme == "dark" else "dark"
        self._apply_theme(theme)
        if self.settings:
            self.settings.set("theme", theme)
            # Persist after repaint to keep transition responsive.
            QTimer.singleShot(0, self.settings.save)

    def _refresh_theme_icon(self):
        if not hasattr(self, "theme_toggle_btn"):
            return
        if qta:
            icon_name = "fa5s.sun" if self.theme == "dark" else "fa5s.moon"
            self.theme_toggle_btn.setIcon(self._icon(icon_name))
            self.theme_toggle_btn.setIconSize(QSize(16, 16))
            self.theme_toggle_btn.setText("")
        else:
            self.theme_toggle_btn.setIcon(QIcon())
            self.theme_toggle_btn.setText("Tema")

    def _refresh_collapse_icon(self):
        if not hasattr(self, "collapse_btn"):
            return
        if qta:
            icon_name = "fa5s.angle-right" if self.sidebar_collapsed else "fa5s.angle-left"
            self.collapse_btn.setIcon(self._icon(icon_name))
            self.collapse_btn.setIconSize(QSize(16, 16))
            self.collapse_btn.setText("")
        else:
            self.collapse_btn.setIcon(QIcon())
            self.collapse_btn.setText(">" if self.sidebar_collapsed else "<")

    def toggle_sidebar(self):
        self.set_sidebar_collapsed(not self.sidebar_collapsed)

    def set_sidebar_collapsed(self, collapsed: bool):
        self.sidebar_collapsed = collapsed
        self.sidebar.setFixedWidth(64 if collapsed else 220)
        self.side_layout.setContentsMargins(10 if collapsed else 16, 16, 10 if collapsed else 16, 16)
        self.brand_text.setVisible(not collapsed)
        self._refresh_brand_logo()
        if hasattr(self, "footer_layout"):
            direction = QBoxLayout.TopToBottom if collapsed else QBoxLayout.LeftToRight
            self.footer_layout.setDirection(direction)
            self.footer_layout.setSpacing(6 if collapsed else 8)
            self.footer_layout.setAlignment(Qt.AlignHCenter if collapsed else Qt.AlignLeft)

        for key, btn in self.nav_buttons.items():
            full_text = btn.property("fullText") or btn.text()
            btn.setText("" if collapsed else full_text)
            btn.setToolTip(full_text)
            btn.setProperty("collapsed", collapsed)
            btn.setMinimumWidth(0 if collapsed else 180)
            btn.setIconSize(QSize(20, 20) if collapsed else QSize(18, 18))
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

        self.collapse_btn.setToolTip("Expandir sidebar" if collapsed else "Recolher sidebar")
        self._refresh_collapse_icon()

        if self.settings:
            self.settings.set("sidebar_collapsed", collapsed)
            self.settings.save()

    # Legacy callback setters for compatibility with main.py
    def set_record_callback(self, callback: Callable):
        self.record_requested.connect(callback)

    def set_stop_callback(self, callback: Callable):
        self.stop_requested.connect(callback)

    def set_settings_callback(self, callback: Callable):
        self.settings_requested.connect(callback)

    def set_history_callback(self, callback: Callable):
        self.history_requested.connect(callback)

    def set_stats_callback(self, callback: Callable):
        self.stats_requested.connect(callback)

    def set_logout_callback(self, callback: Callable):
        self.logout_requested.connect(callback)

    def set_settings_saved_callback(self, callback: Callable):
        self.settings_saved.connect(callback)

    def set_hotkey_enabled_callback(self, callback: Callable):
        self._hotkey_toggle_callback = callback

    def set_password_reset_callback(self, callback: Callable):
        self._password_reset_callback = callback

    def set_login_callback(self, callback: Callable):
        self._login_callback = callback

    def is_onboarding_active(self) -> bool:
        return bool(getattr(self, "_onboarding_dialog", None))

    def onboarding_transcription(self, text: str):
        dialog = getattr(self, "_onboarding_dialog", None)
        if dialog:
            dialog.set_transcription(text)

    def onboarding_error(self, message: str):
        dialog = getattr(self, "_onboarding_dialog", None)
        if dialog:
            dialog.set_error(message)

    def set_show_in_taskbar(self, show: bool):
        if getattr(self, "_show_in_taskbar", None) == show:
            return
        self._show_in_taskbar = show
        was_visible = self.isVisible()
        self.hide()
        flags = self.windowFlags()
        if show:
            flags = flags & ~Qt.Tool
            flags = flags | Qt.Window
            flags = flags | Qt.WindowSystemMenuHint | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint
        else:
            flags = flags | Qt.Tool
            flags = flags | Qt.WindowSystemMenuHint | Qt.WindowCloseButtonHint
        self.setWindowFlags(flags)
        if was_visible:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    # Qt window state methods (compatibility with tkinter-style calls)
    def deiconify(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def withdraw(self):
        self.hide()

    def lift(self):
        self.raise_()
        self.activateWindow()

    def winfo_exists(self):
        return self.isVisible() or not self.isHidden()
