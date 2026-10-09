"""
Settings window UI - Configuration interface
PySide6/Qt implementation
"""
import os
from typing import Callable, Optional

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLabel, QLineEdit, QPushButton, QCheckBox, QRadioButton,
    QButtonGroup, QFrame, QMessageBox, QComboBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from src.ui.theme import DARK_THEME, COLORS


class SettingsWindow(QDialog):
    """Settings configuration window"""

    def __init__(self, parent, settings, on_save_callback: Optional[Callable] = None):
        super().__init__(parent)

        self.settings = settings
        self.on_save_callback = on_save_callback

        # Configure window
        self.setWindowTitle("⚙️ Configurações - FALAI")
        self.setFixedSize(550, 650)
        self.setModal(True)

        # Apply theme
        self.setStyleSheet(DARK_THEME)

        # Create UI
        self._create_ui()

        # Load current settings
        self._load_current_settings()

    def _create_ui(self):
        """Create the settings interface"""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Content widget
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(15)

        # Title
        title_label = QLabel("⚙️ Configurações")
        title_label.setFont(QFont("Segoe UI", 20, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(title_label)

        # === TRANSCRIPTION (GROQ) SECTION ===
        provider_frame = self._create_section_frame()
        provider_layout = QVBoxLayout(provider_frame)

        provider_title = QLabel("🚀 Transcrição (Groq)")
        provider_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        provider_title.setStyleSheet(f"color: {COLORS['accent']};")
        provider_layout.addWidget(provider_title)

        provider_subtitle = QLabel("Whisper ultra rápido pela Groq")
        provider_subtitle.setFont(QFont("Segoe UI", 10))
        provider_subtitle.setStyleSheet(f"color: {COLORS['foreground_dim']};")
        provider_layout.addWidget(provider_subtitle)

        stt_label = QLabel("Modelo de transcrição:")
        stt_label.setFont(QFont("Segoe UI", 11))
        provider_layout.addWidget(stt_label)

        self.stt_model_combo = QComboBox()
        self.stt_model_combo.addItems([
            "whisper-large-v3-turbo",
            "whisper-large-v3",
            "Outro...",
        ])
        provider_layout.addWidget(self.stt_model_combo)

        self.stt_model_custom = QLineEdit()
        self.stt_model_custom.setPlaceholderText("Digite o modelo (ex: whisper-large-v3-turbo)")
        self.stt_model_custom.hide()
        provider_layout.addWidget(self.stt_model_custom)

        self.stt_model_combo.currentIndexChanged.connect(self._on_stt_model_change)

        content_layout.addWidget(provider_frame)

        # === API KEY SECTION ===
        api_frame = self._create_section_frame()
        api_layout = QVBoxLayout(api_frame)

        groq_label = QLabel("🔑 Groq API Key")
        groq_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        groq_label.setStyleSheet(f"color: {COLORS['accent']};")
        api_layout.addWidget(groq_label)

        groq_subtitle = QLabel("Obtenha em: console.groq.com")
        groq_subtitle.setFont(QFont("Segoe UI", 10))
        groq_subtitle.setStyleSheet(f"color: {COLORS['foreground_dim']};")
        api_layout.addWidget(groq_subtitle)

        self.groq_key_entry = QLineEdit()
        self.groq_key_entry.setPlaceholderText("gsk_...")
        self.groq_key_entry.setEchoMode(QLineEdit.Password)
        groq_row = QWidget()
        groq_row_layout = QHBoxLayout(groq_row)
        groq_row_layout.setContentsMargins(0, 0, 0, 0)
        groq_row_layout.setSpacing(8)
        groq_row_layout.addWidget(self.groq_key_entry, 1)

        self.test_groq_btn = QPushButton("Testar")
        self.test_groq_btn.setFixedWidth(80)
        self.test_groq_btn.clicked.connect(self._test_groq_key)
        groq_row_layout.addWidget(self.test_groq_btn)

        self.groq_test_label = QLabel("")
        self.groq_test_label.setFixedWidth(20)
        self.groq_test_label.setAlignment(Qt.AlignCenter)
        groq_row_layout.addWidget(self.groq_test_label)

        api_layout.addWidget(groq_row)

        self.show_key_checkbox = QCheckBox("Mostrar chave")
        self.show_key_checkbox.toggled.connect(self._toggle_api_key_visibility)
        api_layout.addWidget(self.show_key_checkbox)

        content_layout.addWidget(api_frame)

        # === LANGUAGE SECTION ===
        lang_frame = self._create_section_frame()
        lang_layout = QVBoxLayout(lang_frame)

        lang_title = QLabel("🌍 Idioma da Transcrição")
        lang_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        lang_title.setStyleSheet(f"color: {COLORS['accent']};")
        lang_layout.addWidget(lang_title)

        self.language_group = QButtonGroup(self)
        languages = [
            ("🇧🇷 Português (pt)", "pt"),
            ("🇺🇸 English (en)", "en"),
            ("🇪🇸 Español (es)", "es"),
            ("🇫🇷 Français (fr)", "fr"),
            ("🇩🇪 Deutsch (de)", "de"),
            ("🇮🇹 Italiano (it)", "it"),
        ]

        for lang_label, lang_code in languages:
            radio = QRadioButton(lang_label)
            radio.setProperty("value", lang_code)
            self.language_group.addButton(radio)
            lang_layout.addWidget(radio)

        content_layout.addWidget(lang_frame)

        # === ACTIVATION MODE SECTION ===
        mode_frame = self._create_section_frame()
        mode_layout = QVBoxLayout(mode_frame)

        mode_title = QLabel("🎯 Modo de Ativação")
        mode_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        mode_title.setStyleSheet(f"color: {COLORS['accent']};")
        mode_layout.addWidget(mode_title)

        self.mode_group = QButtonGroup(self)
        modes = [
            ("Push-to-talk (Segurar tecla)", "push_to_talk"),
            ("Toggle (Apertar para iniciar/parar)", "toggle"),
            ("Sempre ativo (Microfone sempre ligado)", "always_on"),
        ]

        for mode_label, mode_value in modes:
            radio = QRadioButton(mode_label)
            radio.setProperty("value", mode_value)
            self.mode_group.addButton(radio)
            mode_layout.addWidget(radio)

        content_layout.addWidget(mode_frame)

        # === HOTKEY SECTION ===
        hotkey_frame = self._create_section_frame()
        hotkey_layout = QVBoxLayout(hotkey_frame)

        hotkey_title = QLabel("⌨️ Atalho de Teclado")
        hotkey_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        hotkey_title.setStyleSheet(f"color: {COLORS['accent']};")
        hotkey_layout.addWidget(hotkey_title)

        hotkey_subtitle = QLabel("Exemplos: ctrl+win, ctrl+shift+r, alt+space")
        hotkey_subtitle.setFont(QFont("Segoe UI", 10))
        hotkey_subtitle.setStyleSheet(f"color: {COLORS['foreground_dim']};")
        hotkey_layout.addWidget(hotkey_subtitle)

        self.hotkey_entry = QLineEdit()
        self.hotkey_entry.setPlaceholderText("ctrl+win")
        hotkey_layout.addWidget(self.hotkey_entry)

        content_layout.addWidget(hotkey_frame)

        # === AUTO-PASTE SECTION ===
        paste_frame = self._create_section_frame()
        paste_layout = QVBoxLayout(paste_frame)

        paste_title = QLabel("📋 Comportamento após Transcrição")
        paste_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        paste_title.setStyleSheet(f"color: {COLORS['accent']};")
        paste_layout.addWidget(paste_title)

        self.auto_paste_checkbox = QCheckBox("Colar automaticamente no campo ativo")
        paste_layout.addWidget(self.auto_paste_checkbox)

        content_layout.addWidget(paste_frame)

        # === CORRECTION SECTION ===
        gpt_frame = self._create_section_frame()
        gpt_layout = QVBoxLayout(gpt_frame)

        gpt_title = QLabel("✨ Correção automática (Llama/Groq)")
        gpt_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        gpt_title.setStyleSheet(f"color: {COLORS['accent']};")
        gpt_layout.addWidget(gpt_title)

        gpt_subtitle = QLabel("Corrige pontuação, capitalização e ortografia automaticamente")
        gpt_subtitle.setFont(QFont("Segoe UI", 10))
        gpt_subtitle.setStyleSheet(f"color: {COLORS['foreground_dim']};")
        gpt_layout.addWidget(gpt_subtitle)

        self.gpt_correction_checkbox = QCheckBox("Ativar correção automática")
        self.gpt_correction_checkbox.toggled.connect(self._toggle_style_options)
        gpt_layout.addWidget(self.gpt_correction_checkbox)

        # Corrector model selection
        corrector_label = QLabel("Modelo Llama:")
        corrector_label.setFont(QFont("Segoe UI", 11))
        gpt_layout.addWidget(corrector_label)

        self.corrector_model_combo = QComboBox()
        self.corrector_model_combo.addItems([
            "openai/gpt-oss-120b",
            "qwen/qwen3.8-27b",
            "openai/gpt-oss-20b",
            "Outro...",
        ])
        gpt_layout.addWidget(self.corrector_model_combo)

        self.corrector_model_custom = QLineEdit()
        self.corrector_model_custom.setPlaceholderText("Digite o modelo (ex: openai/gpt-oss-120b)")
        self.corrector_model_custom.hide()
        gpt_layout.addWidget(self.corrector_model_custom)

        self.corrector_model_combo.currentIndexChanged.connect(self._on_corrector_model_change)

        # Style selection
        style_label = QLabel("Estilo de correção:")
        style_label.setFont(QFont("Segoe UI", 11))
        gpt_layout.addWidget(style_label)

        self.style_group = QButtonGroup(self)
        self.style_radios = []
        styles = [
            ("Pontual (só pontuação)", "neutro"),
            ("Casual (mantém gírias)", "casual"),
            ("Formal (profissional)", "formal"),
        ]

        for style_label_text, style_value in styles:
            radio = QRadioButton(style_label_text)
            radio.setProperty("value", style_value)
            self.style_group.addButton(radio)
            self.style_radios.append(radio)
            gpt_layout.addWidget(radio)

        format_label = QLabel("Formato de saída:")
        format_label.setFont(QFont("Segoe UI", 11))
        gpt_layout.addWidget(format_label)

        self.format_group = QButtonGroup(self)
        self.format_radios = []
        formats = [
            ("Padrão (parágrafos equilibrados)", "balanced"),
            ("Mensagem (quebras automáticas)", "message"),
        ]

        for format_label_text, format_value in formats:
            radio = QRadioButton(format_label_text)
            radio.setProperty("value", format_value)
            self.format_group.addButton(radio)
            self.format_radios.append(radio)
            gpt_layout.addWidget(radio)

        content_layout.addWidget(gpt_frame)

        # === BUTTONS ===
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 10, 0, 0)

        self.save_button = QPushButton("💾 Salvar Configurações")
        self.save_button.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.save_button.setMinimumHeight(40)
        self.save_button.clicked.connect(self._save_settings)
        button_layout.addWidget(self.save_button)

        self.cancel_button = QPushButton("❌ Cancelar")
        self.cancel_button.setFont(QFont("Segoe UI", 12))
        self.cancel_button.setMinimumHeight(40)
        self.cancel_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #666666;
            }}
            QPushButton:hover {{
                background-color: #888888;
            }}
        """)
        self.cancel_button.clicked.connect(self.close)
        button_layout.addWidget(self.cancel_button)

        content_layout.addWidget(button_frame)

        # Add stretch to push content up
        content_layout.addStretch()

        # Set scroll area content
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

        # Message label for error/success
        self.message_label = QLabel()
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setFont(QFont("Segoe UI", 11))
        self.message_label.hide()
        main_layout.addWidget(self.message_label)

    def _create_section_frame(self) -> QFrame:
        """Create a styled section frame"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['background_light']};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        return frame

    def _toggle_api_key_visibility(self, checked: bool):
        """Toggle API key visibility"""
        mode = QLineEdit.Normal if checked else QLineEdit.Password
        self.groq_key_entry.setEchoMode(mode)

    def _toggle_style_options(self, checked: bool):
        """Enable/disable corrector and style options based on correction toggle"""
        self.corrector_model_combo.setEnabled(checked)
        self.corrector_model_custom.setEnabled(checked and self.corrector_model_combo.currentText() == "Outro...")
        for radio in self.style_radios:
            radio.setEnabled(checked)
        for radio in getattr(self, "format_radios", []):
            radio.setEnabled(checked)
        self._on_corrector_model_change()

    def _get_selected_value(self, group: QButtonGroup) -> Optional[str]:
        """Get the selected value from a button group"""
        checked = group.checkedButton()
        if checked:
            return checked.property("value")
        return None

    def _set_selected_value(self, group: QButtonGroup, value: str):
        """Set the selected value in a button group"""
        for button in group.buttons():
            if button.property("value") == value:
                button.setChecked(True)
                return

    def _set_combo_or_custom(self, combo: QComboBox, custom_input: QLineEdit, value: str):
        index = combo.findText(value)
        if index != -1:
            combo.setCurrentIndex(index)
            custom_input.hide()
            custom_input.setText("")
        else:
            combo.setCurrentText("Outro...")
            custom_input.setText(value)
            custom_input.show()

    def _get_combo_or_custom(self, combo: QComboBox, custom_input: QLineEdit) -> str:
        if combo.currentText() == "Outro...":
            return custom_input.text().strip()
        return combo.currentText().strip()

    def _on_stt_model_change(self, *_args):
        is_custom = self.stt_model_combo.currentText() == "Outro..."
        self.stt_model_custom.setVisible(is_custom)
        self.stt_model_custom.setEnabled(is_custom)

    def _on_corrector_model_change(self, *_args):
        is_custom = self.corrector_model_combo.currentText() == "Outro..."
        self.corrector_model_custom.setVisible(is_custom)
        self.corrector_model_custom.setEnabled(is_custom and self.gpt_correction_checkbox.isChecked())

    def _load_current_settings(self):
        """Load current settings into the form"""
        # API Keys
        current_groq_key = os.getenv("GROQ_API_KEY", "")
        if current_groq_key:
            self.groq_key_entry.setText(current_groq_key)
        self._set_test_result(self.groq_test_label, None)

        # STT model
        stt_model = self.settings.get("groq_stt_model", "whisper-large-v3-turbo")
        self._set_combo_or_custom(self.stt_model_combo, self.stt_model_custom, stt_model)

        # Language
        language = self.settings.get("language", "pt")
        self._set_selected_value(self.language_group, language)

        # Mode
        mode = self.settings.get("activation_mode", "push_to_talk")
        self._set_selected_value(self.mode_group, mode)

        # Hotkey
        hotkey = self.settings.get("hotkey", "ctrl+win")
        self.hotkey_entry.setText(hotkey)

        # Auto-paste
        auto_paste = self.settings.get("auto_paste", True)
        self.auto_paste_checkbox.setChecked(auto_paste)

        # GPT Correction
        gpt_correction = self.settings.get("gpt_correction", True)
        self.gpt_correction_checkbox.setChecked(gpt_correction)

        correction_style = self.settings.get("correction_style", "neutro")
        self._set_selected_value(self.style_group, correction_style)

        message_format_mode = self.settings.get("message_format_mode", "balanced")
        self._set_selected_value(self.format_group, message_format_mode)

        # Corrector model
        corrector_model = self.settings.get("groq_corrector_model", "openai/gpt-oss-120b")
        self._set_combo_or_custom(self.corrector_model_combo, self.corrector_model_custom, corrector_model)

        # Update style options visibility
        self._toggle_style_options(gpt_correction)
        self._on_stt_model_change()
        self._on_corrector_model_change()

    def _save_settings(self):
        """Save settings"""
        groq_key = self.groq_key_entry.text().strip()
        if not groq_key:
            self._show_error("Groq API Key é obrigatória para este provedor!")
            return
        if not groq_key.startswith("gsk_"):
            self._show_error("Groq API Key inválida!")
            return

        stt_model = self._get_combo_or_custom(self.stt_model_combo, self.stt_model_custom)
        if not stt_model:
            self._show_error("Informe o modelo de transcrição.")
            return

        corrector_model = self._get_combo_or_custom(self.corrector_model_combo, self.corrector_model_custom)
        if self.gpt_correction_checkbox.isChecked() and not corrector_model:
            self._show_error("Informe o modelo de correção.")
            return

        # Update .env file
        env_path = ".env"
        try:
            self._update_env_file(env_path, groq_key, self._get_selected_value(self.language_group))
        except Exception as e:
            self._show_error(f"Erro ao salvar .env: {e}")
            return

        # Update environment variable
        os.environ["GROQ_API_KEY"] = groq_key

        # Update settings
        self.settings.set("transcription_provider", "groq")
        self.settings.set("language", self._get_selected_value(self.language_group))
        self.settings.set("activation_mode", self._get_selected_value(self.mode_group))
        self.settings.set("hotkey", self.hotkey_entry.text().strip())
        self.settings.set("auto_paste", self.auto_paste_checkbox.isChecked())
        self.settings.set("gpt_correction", self.gpt_correction_checkbox.isChecked())
        self.settings.set("correction_style", self._get_selected_value(self.style_group))
        self.settings.set("message_format_mode", self._get_selected_value(self.format_group))
        self.settings.set("corrector_provider", "groq")
        self.settings.set("groq_stt_model", stt_model)
        self.settings.set("groq_corrector_model", corrector_model)

        # Save settings to file
        self.settings.save()

        # Show success
        self._show_success()

        # Call callback if set
        if self.on_save_callback:
            self.on_save_callback()

        # Close window after delay
        QTimer.singleShot(1500, self.close)

    def _show_error(self, message: str):
        """Show error message"""
        self.message_label.setText(f"❌ {message}")
        self.message_label.setStyleSheet(f"color: {COLORS['danger']};")
        self.message_label.show()
        QTimer.singleShot(3000, self.message_label.hide)

    def _show_success(self):
        """Show success message"""
        self.message_label.setText("✅ Configurações salvas com sucesso!")
        self.message_label.setStyleSheet(f"color: {COLORS['accent']};")
        self.message_label.show()

    def _set_test_result(self, label: QLabel, ok: Optional[bool]):
        """Atualiza feedback visual do teste de chave"""
        if ok is None:
            label.setText("")
            return
        if ok:
            label.setText("✓")
            label.setStyleSheet(f"color: {COLORS['success']}; font-weight: bold;")
        else:
            label.setText("✗")
            label.setStyleSheet(f"color: {COLORS['danger']}; font-weight: bold;")

    def _validate_groq_key(self, key: str) -> bool:
        """Valida formato basico da Groq API Key (sem rede)"""
        return bool(key) and key.startswith("gsk_") and len(key) > 10

    def _test_groq_key(self):
        """Testa Groq API Key localmente"""
        key = self.groq_key_entry.text().strip()
        self._set_test_result(self.groq_test_label, self._validate_groq_key(key))

    def _update_env_file(self, env_path: str, groq_key: str, language: str):
        """Atualiza .env preservando OPENAI_API_KEY caso exista"""
        lines = []
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()

        updated_lines = []
        seen_groq = False
        seen_lang = False

        for line in lines:
            if line.startswith("GROQ_API_KEY="):
                updated_lines.append(f"GROQ_API_KEY={groq_key}")
                seen_groq = True
            elif line.startswith("DEFAULT_LANGUAGE="):
                updated_lines.append(f"DEFAULT_LANGUAGE={language}")
                seen_lang = True
            else:
                updated_lines.append(line)

        if not seen_groq:
            updated_lines.append(f"GROQ_API_KEY={groq_key}")
        if not seen_lang:
            updated_lines.append(f"DEFAULT_LANGUAGE={language}")

        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(updated_lines) + "\n")
