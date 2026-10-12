"""
Onboarding modal wizard (3 passos) para primeiro uso.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QProgressBar
)
from PySide6.QtGui import QPixmap, QTextOption
import os

from src.audio.recorder import AudioRecorder
from src.config.runtime_mode import is_local_runtime


ONBOARDING_VERSION = 2


def _has_saved_groq_key() -> bool:
    if os.getenv("GROQ_API_KEY"):
        return True
    try:
        from src.config.settings import Settings
        from src.security.secure_store import SecureStore

        return bool(SecureStore().get_secret(Settings.GROQ_SECRET_TARGET))
    except Exception:
        return False


class OnboardingDialog(QDialog):
    """Wizard modal compacto com 3 passos."""

    def __init__(
        self,
        hotkey: str = "ctrl+shift",
        on_complete: Callable | None = None,
        on_open_settings: Callable | None = None,
        on_request_password_reset: Callable | None = None,
        initial_email: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._on_complete = on_complete
        self._on_open_settings = on_open_settings
        self._on_request_password_reset = on_request_password_reset
        self._hotkey = hotkey.upper().replace("+", " + ")
        self._initial_email = (initial_email or "").strip()
        self._local_runtime = is_local_runtime()
        # Preserve the former switch for cloud-mode developer testing.
        self._allow_local_auth = self._local_runtime or (os.getenv("FALAI_ALLOW_LOCAL_AUTH", "") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        self._step_titles = [
            "Transcreva em segundos",
            "Sua chave Groq" if self._local_runtime else "Ative sua conta",
            "Teste rapido",
        ]
        self._has_transcription = False

        self.setWindowTitle("Bem-vindo ao FALAI")
        self.setModal(True)
        self.resize(QSize(760, 500))
        self.setMinimumSize(QSize(700, 460))

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        self.header = self._build_header()
        root.addWidget(self.header)

        self.stack = QStackedWidget()
        self.stack.setObjectName("onboardingContent")
        root.addWidget(self.stack, 1)

        self._add_steps()

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)

        self.back_btn = QPushButton("Voltar")
        self.back_btn.setObjectName("secondaryButton")
        self.back_btn.setMinimumHeight(42)
        self.back_btn.clicked.connect(self._prev_step)

        self.next_btn = QPushButton("Continuar")
        self.next_btn.setObjectName("primaryButton")
        self.next_btn.setMinimumHeight(42)
        self.next_btn.clicked.connect(self._next_step)

        footer.addWidget(self.back_btn)
        footer.addStretch()
        footer.addWidget(self.next_btn)
        footer.addStretch()
        root.addLayout(footer)
        self.footer = footer

        self._update_controls()

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("onboardingHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        # Cleaner header - Only the stepper
        self.stepper_row = QHBoxLayout()
        self.stepper_row.setContentsMargins(0, 0, 0, 0)
        self.stepper_row.setSpacing(6)

        self.step_indicators = []
        for _ in range(3):
            indicator = QFrame()
            indicator.setObjectName("onboardingStepIndicator")
            indicator.setFixedHeight(6) # Thicker premium bars
            self.stepper_row.addWidget(indicator)
            self.step_indicators.append(indicator)

        layout.addLayout(self.stepper_row)
        
        # Step label below progress bar
        self.step_counter = QLabel("")
        self.step_counter.setObjectName("sectionHeader")
        self.step_counter.setAlignment(Qt.AlignRight)
        layout.addWidget(self.step_counter)
        
        return header

    def _add_steps(self):
        self.stack.addWidget(self._build_intro_step())
        self.stack.addWidget(self._build_finish_step())
        self.stack.addWidget(self._build_test_step())
        self._refresh_mic_info()

    def _build_intro_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 40, 20, 40)
        layout.setSpacing(24)
        layout.setAlignment(Qt.AlignCenter)

        # Attempt to load icon
        icon_label = QLabel()
        icon_path = os.path.join(os.path.dirname(__file__), "../../assets/icons/app.png")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            scaled = pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label.setPixmap(scaled)
        else:
            icon_label.setText("✨")
            icon_label.setStyleSheet("font-size: 64px;")
        
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)

        title = QLabel("Bem-vindo ao FALAI")
        title.setObjectName("onboardingHeroTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("Transcreva falando, rapido e sem atrito.\nSua voz, agora em texto. Instantaneamente.")
        hint.setObjectName("onboardingHeroSubtitle")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()
        return page

    def _build_test_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 32, 20, 20)
        layout.setSpacing(20)

        # Title Section
        header = QVBoxLayout()
        header.setContentsMargins(0, 4, 0, 8)
        header.setSpacing(8)
        title = QLabel("Vamos testar seu audio")
        title.setObjectName("onboardingHeroTitle")
        # Smaller font for this step title
        title.setStyleSheet("font-size: 24px;") 
        header.addWidget(title)
        
        subtitle = QLabel("Certifique-se que podemos te ouvir com clareza.")
        subtitle.setObjectName("onboardingHeroSubtitle")
        subtitle.setWordWrap(True)
        header.addWidget(subtitle)
        layout.addLayout(header)

        layout.addSpacing(4)

        # Hotkey Instruction Card
        hotkey_card = QFrame()
        hotkey_card.setObjectName("card")
        hk_layout = QHBoxLayout(hotkey_card)
        hk_layout.setContentsMargins(16, 16, 16, 16)
        
        hk_label = QLabel("Segure para falar:")
        hk_label.setObjectName("settingTitle")
        hk_layout.addWidget(hk_label)
        
        hk_layout.addStretch()
        
        keys = self._hotkey.split("+")
        for key in keys:
            k = QLabel(key.strip())
            k.setObjectName("keycap")
            hk_layout.addWidget(k)
            
        layout.addWidget(hotkey_card)

        # Test Area (Transcription)
        self.test_area = QFrame()
        self.test_area.setObjectName("testArea")
        test_layout = QVBoxLayout(self.test_area)
        test_layout.setContentsMargins(16, 16, 16, 16)
        test_layout.setSpacing(10)

        status_row = QHBoxLayout()
        self.mic_label = QLabel("Microfone: detectando...")
        self.mic_label.setObjectName("statusSecondary")
        status_row.addWidget(self.mic_label)
        status_row.addStretch()
        self.test_status = QLabel("Aguardando...")
        self.test_status.setObjectName("statusBadgeText")
        status_row.addWidget(self.test_status)
        test_layout.addLayout(status_row)

        self.transcription_box = QPlainTextEdit()
        self.transcription_box.setReadOnly(True)
        self.transcription_box.setPlaceholderText("Segure o atalho e fale algo para testar...")
        self.transcription_box.setFrameShape(QFrame.NoFrame)
        self.transcription_box.setStyleSheet("background: transparent; border: none; font-size: 28px; font-weight: 500;")
        self.transcription_box.setMinimumHeight(120)
        
        # Center alignment
        doc = self.transcription_box.document()
        opt = doc.defaultTextOption()
        opt.setAlignment(Qt.AlignCenter)
        doc.setDefaultTextOption(opt)
        
        test_layout.addWidget(self.transcription_box)

        layout.addWidget(self.test_area, 1) # Provide expand

        self.mic_hint = QLabel("Se houver erro, ajuste o microfone no Windows > Som.")
        self.mic_hint.setObjectName("mutedLabel")
        self.mic_hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.mic_hint)

        return page

    def _build_finish_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(24)

        # Header
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        
        title = QLabel("Modo local" if self._local_runtime else "Ative sua conta")
        title.setObjectName("onboardingHeroTitle")
        title.setStyleSheet("font-size: 24px;")
        title.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(title)
        
        hint = QLabel(
            "Use sua chave Groq local para transcrever." if self._local_runtime
            else "Entre com sua conta FALAI para liberar o acesso."
        )
        hint.setObjectName("onboardingHeroSubtitle")
        hint.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(hint)
        
        layout.addLayout(header_layout)

        # Login Form Card
        form_card = QFrame()
        form_card.setObjectName("card")
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(24, 24, 24, 24)
        form_layout.setSpacing(16)

        # Local (BYOK) mode: the only thing we need is the user's own Groq key.
        self.groq_key_input = QLineEdit()
        self.groq_key_input.setEchoMode(QLineEdit.Password)
        self.groq_key_input.setPlaceholderText("Cole sua chave Groq (gsk_...)")
        groq_hint = QLabel(
            'Crie grátis em <a href="https://console.groq.com/keys">console.groq.com/keys</a>. '
            "A chave fica criptografada neste PC e só é usada para falar com o Groq."
        )
        groq_hint.setObjectName("onboardingHint")
        groq_hint.setWordWrap(True)
        groq_hint.setOpenExternalLinks(True)
        form_layout.addWidget(self.groq_key_input)
        form_layout.addWidget(groq_hint)
        self.groq_key_input.setVisible(self._local_runtime)
        groq_hint.setVisible(self._local_runtime)

        self.login_email = QLineEdit()
        self.login_email.setPlaceholderText("seu@email.com")
        self.login_email.setText(self._initial_email)
        form_layout.addWidget(self.login_email)

        self.login_password = QLineEdit()
        self.login_password.setPlaceholderText("Sua senha")
        self.login_password.setEchoMode(QLineEdit.Password)
        form_layout.addWidget(self.login_password)

        row_password_actions = QHBoxLayout()
        row_password_actions.setContentsMargins(0, 0, 0, 0)
        row_password_actions.setSpacing(10)

        self.login_show_password = QCheckBox("Mostrar senha")
        self.login_show_password.toggled.connect(self._toggle_show_password)
        row_password_actions.addWidget(self.login_show_password)
        row_password_actions.addStretch()

        self.forgot_password_btn = QPushButton("Esqueci minha senha")
        self.forgot_password_btn.setObjectName("ghostButton")
        self.forgot_password_btn.setMinimumHeight(34)
        self.forgot_password_btn.clicked.connect(self._request_password_reset)
        row_password_actions.addWidget(self.forgot_password_btn)
        form_layout.addLayout(row_password_actions)

        row_remember = QHBoxLayout()
        self.login_remember = QCheckBox("Lembrar de mim")
        row_remember.addWidget(self.login_remember)
        row_remember.addStretch()
        form_layout.addLayout(row_remember)

        if self._allow_local_auth:
            local_row = QHBoxLayout()
            local_row.addStretch()
            self.local_mode_btn = QPushButton("Usar modo local")
            self.local_mode_btn.setObjectName("ghostButton")
            self.local_mode_btn.setMinimumHeight(36)
            self.local_mode_btn.clicked.connect(self._continue_local_mode)
            local_row.addWidget(self.local_mode_btn)
            local_row.addStretch()
            form_layout.addLayout(local_row)

        if self._local_runtime:
            for w in (self.login_email, self.login_password, self.login_show_password,
                      self.forgot_password_btn, self.login_remember, getattr(self, "local_mode_btn", None)):
                if w is not None:
                    w.setVisible(False)

        self.login_status = QLabel("")
        self.login_status.setObjectName("onboardingHint")
        self.login_status.setWordWrap(True)
        self.login_status.setAlignment(Qt.AlignCenter)
        form_layout.addWidget(self.login_status)
        
        layout.addWidget(form_card)
        layout.addStretch()
        
        return page

    def _refresh_mic_info(self):
        if not hasattr(self, "mic_label"):
            return
        try:
            recorder = AudioRecorder(sample_rate=16000, channels=1)
            devices = recorder.get_available_devices()
            if not devices:
                self.mic_label.setText("Microfone: nenhum detectado")
                return
            try:
                import sounddevice as sd

                default_in = sd.default.device[0]
                if default_in is not None and default_in >= 0:
                    info = sd.query_devices(default_in)
                    self.mic_label.setText(f"Microfone: {info.get('name', 'Desconhecido')}")
                    return
            except Exception:
                pass
            self.mic_label.setText(f"Microfone: {devices[0]['name']}")
        except Exception:
            self.mic_label.setText("Microfone: nao foi possivel detectar")

    def set_transcription(self, text: str):
        if hasattr(self, "transcription_box"):
            self.transcription_box.setPlainText(text)
        if hasattr(self, "test_status"):
            self.test_status.setText("Teste concluido com sucesso.")
        self._has_transcription = True
        self._update_controls()

    def set_error(self, message: str):
        if hasattr(self, "test_status"):
            self.test_status.setText(f"Erro: {message}")

    def _update_controls(self):
        idx = self.stack.currentIndex()
        total = self.stack.count()

        if hasattr(self, "step_title"):
            self.step_title.setText(self._step_titles[idx])
        self.step_counter.setText(f"{idx + 1}/{total}")

        for i, indicator in enumerate(self.step_indicators):
            indicator.setProperty("active", i <= idx)
            indicator.style().unpolish(indicator)
            indicator.style().polish(indicator)
            indicator.update()

        hide_back = idx == 0
        self.back_btn.setVisible(not hide_back)
        self.back_btn.setEnabled(not hide_back)

        # Step 1: centralize CTA. Other steps: keep CTA to the right.
        if idx == 0:
            self.footer.setStretch(1, 1)
            self.footer.setStretch(3, 1)
        else:
            self.footer.setStretch(1, 1)
            self.footer.setStretch(3, 0)

        if idx == 0:
            self.next_btn.setText("Continuar")
        elif idx == 1:
            self.next_btn.setText("Continuar" if self._local_runtime else "Entrar")
        else:
            self.next_btn.setText("Finalizar")

    def _collect_login_payload(self) -> dict | None:
        email = self.login_email.text().strip()
        password = self.login_password.text().strip()
        remember_me = self.login_remember.isChecked()

        if not email:
            self.login_status.setText("Informe seu e-mail para continuar.")
            return None

        if not password:
            self.login_status.setText("Informe sua senha para continuar.")
            return None

        self.login_status.setText("")
        return {
            "email": email,
            "password": password,
            "remember_me": remember_me,
        }

    def _toggle_show_password(self, checked: bool):
        self.login_password.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def _request_password_reset(self):
        email = self.login_email.text().strip()
        if not email:
            self.login_status.setText("Informe seu e-mail para recuperar a senha.")
            self.login_email.setFocus()
            return
        if not self._on_request_password_reset:
            self.login_status.setText("Recuperação de senha indisponível no momento.")
            return
        try:
            result = self._on_request_password_reset(email)
        except Exception:
            self.login_status.setText("Não foi possível enviar o e-mail de recuperação.")
            return
        if isinstance(result, str) and result.strip():
            self.login_status.setText(result.strip())
            return
        self.login_status.setText("Enviamos um e-mail de recuperação. Verifique sua caixa de entrada.")

    def _continue_local_mode(self):
        if not self._allow_local_auth:
            self.login_status.setText("Modo local desativado.")
            return
        email = self.login_email.text().strip() or "owner@local"
        groq_key = self.groq_key_input.text().strip()
        if self._local_runtime:
            if groq_key and not groq_key.startswith("gsk_"):
                self.login_status.setText("Essa não parece uma chave Groq (começa com gsk_).")
                return
            if not groq_key and not _has_saved_groq_key():
                self.login_status.setText("Cole sua chave Groq para continuar.")
                return
        payload = {
            "email": email,
            "password": "local-auth",
            "remember_me": True,
            "local_mode": True,
            "groq_api_key": groq_key,
        }
        if self._on_complete:
            try:
                self._on_complete(payload)
            except TypeError:
                self._on_complete()
        self.accept()

    def _next_step(self):
        idx = self.stack.currentIndex()
        # Step 0 -> Step 1 (login)
        if idx == 0:
            self.stack.setCurrentIndex(1)
            self._update_controls()
            return

        # Step 1 (login) -> Step 2 (test), but only after successful auth.
        if idx == 1:
            if self._local_runtime:
                self._continue_local_mode()
                return
            payload = self._collect_login_payload()
            if payload is None:
                return

            result = None
            if self._on_complete:
                try:
                    result = self._on_complete(payload)
                except TypeError:
                    result = self._on_complete()

            # Callback contract:
            # - None / True: success
            # - False: generic failure
            # - str: show as error message
            if result is False:
                self.login_status.setText("Falha ao entrar. Verifique e tente novamente.")
                return
            if isinstance(result, str) and result.strip():
                self.login_status.setText(result.strip())
                return

            self.stack.setCurrentIndex(2)
            self._update_controls()
            return

        # Step 2 (test) -> finish
        if not self._has_transcription and hasattr(self, "test_status"):
            # We allow finishing without a transcription to avoid blocking if mic isn't available,
            # but we make it clear to the user.
            self.test_status.setText("Você pode finalizar agora, mas recomendamos testar o microfone.")
        self.accept()

    def _prev_step(self):
        idx = self.stack.currentIndex()
        if idx > 0:
            self.stack.setCurrentIndex(idx - 1)
            self._update_controls()

    def _open_settings(self):
        if self._on_open_settings:
            self._on_open_settings()
        # Nunca fecha o onboarding aqui para evitar bypass.
        if self.stack.currentIndex() != 1:
            self.stack.setCurrentIndex(1)
            self._update_controls()
