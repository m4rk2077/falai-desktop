"""
Paginas principais do app (UI mock / premium)
"""
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from typing import Dict, Any, Callable
import math

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QPlainTextEdit, QCheckBox, QScrollArea, QFrame, QDateEdit,
    QInputDialog, QMessageBox, QFileDialog, QGraphicsDropShadowEffect, QSizePolicy,
    QDialog, QProgressBar, QCalendarWidget, QGraphicsOpacityEffect
)
from PySide6.QtCore import Qt, QDate, QTimer, QPropertyAnimation, QEasingCurve, Property, QSize, Signal
from PySide6.QtGui import QFont, QPainter, QColor, QPen, QBrush, QPainterPath, QRadialGradient

from src.ui.components import Card, StatusPill, SectionHeader, SettingRow, SegmentedControl, StatusBadgeMini, HistoryPreviewItem, StatCard, KPIItem, KPIBand
from src.utils.clipboard import ClipboardManager
from src.config.plan_rules import effective_message_format_mode
from src.ui.theme import get_colors
from src.audio.recorder import AudioRecorder


class RecordButton(QWidget):
    """Premium animated record button with classic podcast microphone"""
    
    STATE_IDLE = "idle"
    STATE_RECORDING = "recording"
    STATE_PROCESSING = "processing"
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = self.STATE_IDLE
        self._pulse_value = 0.0
        self._spinner_angle = 0
        self._idle_pulse = 0.0  # For subtle idle animation
        self._size = 150
        self.setFixedSize(self._size, self._size)
        self.setCursor(Qt.PointingHandCursor)
        
        # Colors
        self._idle_color = QColor("#10B981")
        self._recording_color = QColor("#EF4444")
        self._processing_color = QColor("#10B981")
        self._icon_color = QColor("#FFFFFF")
        self._glow_color = QColor("#10B981")
        
        # Pulse animation for recording
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._update_pulse)
        self._pulse_direction = 1
        
        # Spinner animation for processing
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._update_spinner)
        
        # Idle pulse animation (subtle breathing) — only runs when visible
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._update_idle_pulse)
        
        self._click_callback = None
    
    def set_click_callback(self, callback):
        self._click_callback = callback
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._click_callback:
            self._click_callback()
        super().mousePressEvent(event)
    
    def set_state(self, state: str):
        self._state = state
        self._pulse_timer.stop()
        self._spinner_timer.stop()
        self._idle_timer.stop()
        self._pulse_value = 0.0

        if state == self.STATE_RECORDING:
            self._pulse_timer.start(30)
            self._glow_color = QColor(self._recording_color)
        elif state == self.STATE_PROCESSING:
            self._spinner_timer.start(20)
            self._glow_color = QColor(self._processing_color)
        else:
            self._glow_color = QColor(self._idle_color)
            if self.isVisible():
                self._idle_timer.start(40)

        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self._state == self.STATE_IDLE and not self._idle_timer.isActive():
            self._idle_timer.start(40)

    def hideEvent(self, event):
        self._idle_timer.stop()
        super().hideEvent(event)

    def set_glow_color(self, color: QColor):
        self._glow_color = QColor(color)
        self.update()
    
    def _update_pulse(self):
        self._pulse_value += 0.05 * self._pulse_direction
        if self._pulse_value >= 1.0:
            self._pulse_direction = -1
        elif self._pulse_value <= 0.0:
            self._pulse_direction = 1
        self.update()
    
    def _update_spinner(self):
        self._spinner_angle = (self._spinner_angle + 8) % 360
        self.update()
    
    def _update_idle_pulse(self):
        # Subtle breathing animation only in idle state
        if self._state == self.STATE_IDLE:
            self._idle_pulse = (self._idle_pulse + 0.04) % 6.28  # 2*pi
            self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        center_x = self.width() / 2
        center_y = self.height() / 2
        radius = min(self.width(), self.height()) / 2 - 14
        
        if self._state == self.STATE_IDLE:
            self._draw_idle(painter, center_x, center_y, radius)
        elif self._state == self.STATE_RECORDING:
            self._draw_recording(painter, center_x, center_y, radius)
        elif self._state == self.STATE_PROCESSING:
            self._draw_processing(painter, center_x, center_y, radius)
    
    def _draw_idle(self, painter, cx, cy, r):
        import math
        # Subtle scale pulse
        scale = 1.0 + 0.045 * math.sin(self._idle_pulse)
        r_scaled = r * scale
        glow_alpha = 90 + int(35 * math.sin(self._idle_pulse))
        
        # Glow
        self._draw_glow(painter, cx, cy, r_scaled + 14, self._glow_color, glow_alpha)
        
        # Main circle
        painter.setBrush(QBrush(self._idle_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(int(cx - r_scaled), int(cy - r_scaled), int(r_scaled * 2), int(r_scaled * 2))
        
        # Podcast microphone icon
        self._draw_podcast_mic(painter, cx, cy, self._icon_color, self._idle_color)
    
    def _draw_recording(self, painter, cx, cy, r):
        # Pulsing outer glow ring
        pulse_r = r + 6 + (self._pulse_value * 10)
        self._draw_glow(painter, cx, cy, pulse_r + 10, self._recording_color, 150)
        
        # Main red circle
        painter.setBrush(QBrush(self._recording_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
        
        # Stop square icon
        sq_size = 28
        painter.setBrush(QBrush(self._icon_color))
        painter.drawRoundedRect(int(cx - sq_size/2), int(cy - sq_size/2), sq_size, sq_size, 8, 8)
    
    def _draw_processing(self, painter, cx, cy, r):
        # Subtle processing glow
        self._draw_glow(painter, cx, cy, r + 14, self._processing_color, 110)

        # Main circle
        painter.setBrush(QBrush(self._processing_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
        
        # Spinning arc
        pen = QPen(self._icon_color)
        pen.setWidth(4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        
        arc_r = 26
        rect = (int(cx - arc_r), int(cy - arc_r), int(arc_r * 2), int(arc_r * 2))
        painter.drawArc(rect[0], rect[1], rect[2], rect[3], 
                       int(self._spinner_angle * 16), int(270 * 16))
    
    def _draw_podcast_mic(self, painter, cx, cy, color, accent_color=None):
        """Draw a premium studio mic icon"""
        scale = max(0.7, min(self.width(), self.height()) / 140.0)
        accent = QColor(accent_color or color)
        accent.setAlpha(140)

        # Outer head
        head_w = 32 * scale
        head_h = 40 * scale
        head_x = cx - head_w / 2
        head_y = cy - 30 * scale
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(int(head_x), int(head_y), int(head_w), int(head_h), int(12 * scale), int(12 * scale))

        # Inner capsule groove
        inner_w = 16 * scale
        inner_h = 26 * scale
        inner_x = cx - inner_w / 2
        inner_y = head_y + (7 * scale)
        painter.setBrush(QBrush(accent))
        painter.drawRoundedRect(int(inner_x), int(inner_y), int(inner_w), int(inner_h), int(7 * scale), int(7 * scale))

        # Grille lines inside groove
        grille = QPen(color)
        grille.setWidthF(1.8 * scale)
        grille.setCapStyle(Qt.RoundCap)
        painter.setPen(grille)
        for offset in (6, 12, 18):
            y = inner_y + offset * scale
            painter.drawLine(int(inner_x + 3 * scale), int(y), int(inner_x + inner_w - 3 * scale), int(y))

        # Collar
        collar_w = 16 * scale
        collar_h = 5 * scale
        collar_x = cx - collar_w / 2
        collar_y = head_y + head_h + (2 * scale)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(int(collar_x), int(collar_y), int(collar_w), int(collar_h),
                                int(2.5 * scale), int(2.5 * scale))

        # Stem
        stem_top = collar_y + collar_h + (2 * scale)
        stem_bottom = stem_top + (10 * scale)
        painter.setPen(QPen(color, 3.0 * scale, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(int(cx), int(stem_top), int(cx), int(stem_bottom))

        # Base
        base_w = 34 * scale
        base_h = 7 * scale
        base_x = cx - base_w / 2
        base_y = stem_bottom + (3 * scale)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(int(base_x), int(base_y), int(base_w), int(base_h),
                                int(3 * scale), int(3 * scale))

    def _draw_glow(self, painter, cx, cy, radius, color, alpha):
        max_radius = min(self.width(), self.height()) / 2 - 1
        radius = min(radius, max_radius)
        glow = QRadialGradient(cx, cy, radius)
        c0 = QColor(color)
        c0.setAlpha(0)
        c1 = QColor(color)
        c1.setAlpha(alpha)
        c2 = QColor(color)
        c2.setAlpha(0)
        glow.setColorAt(0.0, c0)
        glow.setColorAt(0.65, c1)
        glow.setColorAt(1.0, c2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))


class QuickActionCard(QFrame):
    """Small action card for quick actions"""
    
    def __init__(self, icon_char: str, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("quickActionCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(72)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)
        
        icon = QLabel(icon_char)
        icon.setObjectName("quickActionIcon")
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)
        
        label = QLabel(title)
        label.setObjectName("quickActionLabel")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)


try:
    import qtawesome as qta
except ImportError:
    qta = None

class PremiumActionButton(QPushButton):
    """Botão de ação rápida estilo premium - OUTLINE CARD"""
    def __init__(self, icon_name: str, text: str, subtitle: str = "", colors: dict = None, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(64)
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setObjectName("premiumActionBtn")

        self.colors = colors or get_colors("dark")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        # Icon bubble
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(32, 32)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self._bubble_style = ""
        if qta:
            pixmap = qta.icon(icon_name, color=self.colors["foreground_dim"]).pixmap(QSize(18, 18))
            self.icon_label.setPixmap(pixmap)
        else:
            self.icon_label.setText("◉")
        self.icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.icon_label)

        # Text column
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.text_label = QLabel(text)
        self.text_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_col.addWidget(self.text_label)

        self.subtitle_label = None
        if subtitle:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setAttribute(Qt.WA_TransparentForMouseEvents)
            text_col.addWidget(self.subtitle_label)

        layout.addLayout(text_col, 1)

        self._apply_theme()

    def _is_light(self) -> bool:
        bg = self.colors.get("background", "#111827").lstrip("#")
        if len(bg) != 6:
            return False
        r = int(bg[0:2], 16)
        g = int(bg[2:4], 16)
        b = int(bg[4:6], 16)
        luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
        return luminance > 0.6

    def _apply_theme(self):
        is_light = self._is_light()

        if is_light:
            bg = "#FFFFFF"
            border = "#D9DDE3"
            hover_bg = "#F5F7FA"
            pressed_bg = "#EEF2F7"
            title_color = "#0F172A"
            subtitle_color = "#6B7280"
            icon_color = "#6B7280"
            bubble_bg = "#F3F4F6"
            bubble_border = "#E5E7EB"
        else:
            bg = self.colors["card_bg"]
            border = self.colors["border_hover"]
            hover_bg = self.colors["hover_bg"]
            pressed_bg = self.colors["background_light"]
            title_color = self.colors["foreground"]
            subtitle_color = "#9CA3AF"
            icon_color = subtitle_color
            bubble_bg = self.colors["background"]
            bubble_border = self.colors["border"]

        self.setStyleSheet(f"""
            QPushButton#premiumActionBtn {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 12px;
                padding: 0px;
            }}
            QPushButton#premiumActionBtn:hover {{
                background-color: {hover_bg};
                border-color: {self.colors["accent"]};
            }}
            QPushButton#premiumActionBtn:pressed {{
                background-color: {pressed_bg};
                border-color: {self.colors["accent"]};
            }}
        """)

        self.text_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {title_color};"
        )
        if self.subtitle_label:
            self.subtitle_label.setStyleSheet(
                f"font-size: 11px; font-weight: 500; color: {subtitle_color};"
            )

        self._bubble_style = (
            f"background-color: {bubble_bg}; "
            f"border: 1px solid {bubble_border}; "
            "border-radius: 16px;"
        )
        if qta:
            pixmap = qta.icon(self._icon_name, color=icon_color).pixmap(QSize(18, 18))
            self.icon_label.setPixmap(pixmap)
            self.icon_label.setStyleSheet(self._bubble_style)
        else:
            self.icon_label.setStyleSheet(
                self._bubble_style + f"font-size: 16px; color: {icon_color};"
            )

    def set_colors(self, colors: dict):
        self.colors = colors
        self._apply_theme()

class HomePage(QWidget):
    """Pagina Home premium - SaaS style (Redesigned Round 2 - Minimalist)"""

    def __init__(self, parent=None, settings=None, history_manager=None):
        super().__init__(parent)
        self.settings = settings
        self.history_manager = history_manager
        self._has_transcription = False
        self.colors = get_colors(self.settings.get("theme", "dark") if self.settings else "dark")
        self._transcription_action_buttons = []
        self._last_transcription_time = None
        self._is_light_theme = (self.settings.get("theme", "dark") == "beige") if self.settings else False
        self._content_layout = None
        self._hero_layout = None
        
        # Scrollable content to avoid overlap on small windows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("homeScroll")

        content = QWidget()
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(32)
        self._content_layout = layout

        # ===== A) HERO CENTRAL =====
        hero_widget = QWidget()
        hero_layout = QVBoxLayout(hero_widget)
        hero_layout.setContentsMargins(0, 20, 0, 20)
        hero_layout.setSpacing(28) # Tighter hierarchy between button and hints
        hero_layout.setAlignment(Qt.AlignCenter)
        self._hero_layout = hero_layout

        # Status badge - same centered column as microphone button
        self.status_badge = StatusBadgeMini()
        self.status_badge.set_status("Pronto", "#10B981", False)
        hero_layout.addWidget(self.status_badge, 0, Qt.AlignCenter)

        # Record button (Larger Focus)
        self.record_button = RecordButton()
        self.record_button.setFixedSize(150, 150)
        self.record_button._size = 150
        
        hero_layout.addWidget(self.record_button, 0, Qt.AlignCenter)
        
        # Action + hotkey (clear hierarchy)
        hint_widget = QWidget()
        hint_layout = QVBoxLayout(hint_widget)
        hint_layout.setContentsMargins(0, 0, 0, 0)
        hint_layout.setSpacing(8)
        hint_layout.setAlignment(Qt.AlignCenter)

        self.action_label = QLabel("Clique para gravar")
        self.action_label.setAlignment(Qt.AlignCenter)
        self.action_label.setStyleSheet(
            "font-family: \"Manrope\", \"Inter\", \"Segoe UI\", sans-serif; "
            "color: #10B981; font-size: 15px; font-weight: 700; letter-spacing: 0.4px;"
        )
        hint_layout.addWidget(self.action_label)

        hotkey_row = QHBoxLayout()
        hotkey_row.setContentsMargins(0, 0, 0, 0)
        hotkey_row.setSpacing(10)
        hotkey_row.setAlignment(Qt.AlignCenter)

        self.hotkey_label = QLabel("ATALHO")
        self.hotkey_label.setStyleSheet(
            "color: #6B7280; font-size: 11px; font-weight: 700; letter-spacing: 1.5px;"
        )
        hotkey_row.addWidget(self.hotkey_label)

        self.hotkey_pill = QLabel("CTRL + SHIFT")
        self.hotkey_pill.setStyleSheet(
            "padding: 4px 10px; border-radius: 10px; "
            "background-color: rgba(16, 185, 129, 0.12); "
            "border: 1px solid rgba(16, 185, 129, 0.35); "
            "color: #10B981; font-size: 12px; font-weight: 700; letter-spacing: 0.8px;"
        )
        hotkey_row.addWidget(self.hotkey_pill)

        hint_layout.addLayout(hotkey_row)
        hero_layout.addWidget(hint_widget, 0, Qt.AlignCenter)
        
        layout.addWidget(hero_widget)

        # ===== C) AÇÕES RÁPIDAS (Ghost Buttons) =====
        actions_row = QHBoxLayout()
        actions_row.setSpacing(16)
        actions_row.setAlignment(Qt.AlignCenter)
        
        self.btn_mic = PremiumActionButton(
            "fa5s.microphone-alt",
            "Testar microfone",
            "Verificar entrada de áudio",
            colors=self.colors,
        )

        actions_row.addStretch()
        actions_row.addWidget(self.btn_mic)
        actions_row.addStretch()
        layout.addLayout(actions_row)

        # ===== D) HISTÓRICO RECENTE (Timeline + Card) =====
        trans_card = Card()
        trans_card.layout.setContentsMargins(0, 0, 0, 0) # Remove padding for clean look
        trans_card.setStyleSheet("#card { background: transparent; border: none; }") # Invisible card container
        
        # Custom content container with minimal styling
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(24, 0, 24, 0)
        content_layout.setSpacing(12)
        
        # Header row: title + counter + actions
        card_header = QHBoxLayout()
        card_header.setContentsMargins(0, 0, 0, 0)
        card_header.setSpacing(10)

        title = QLabel("Histórico recente")
        title.setObjectName("homeHistoryTitle")
        card_header.addWidget(title)

        self.home_history_count = QLabel("")
        self.home_history_count.setObjectName("homeHistoryCount")
        card_header.addWidget(self.home_history_count)
        card_header.addStretch()

        for label, callback in [
            ("LIMPAR", self._clear_transcription),
            ("HISTÓRICO", self._open_history),
        ]:
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            self._apply_action_btn_style(btn)
            btn.clicked.connect(callback)
            self._transcription_action_buttons.append(btn)
            card_header.addWidget(btn)

        content_layout.addLayout(card_header)

        # Empty state
        self.history_empty = QWidget()
        self.history_empty.setObjectName("homeHistoryEmpty")
        empty_layout = QVBoxLayout(self.history_empty)
        empty_layout.setContentsMargins(0, 14, 0, 14)
        empty_layout.setSpacing(6)
        empty_layout.setAlignment(Qt.AlignCenter)

        self.empty_title = QLabel("Nenhuma transcrição ainda")
        self.empty_title.setObjectName("homeHistoryEmptyTitle")
        self.empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_title)

        self.empty_subtitle = QLabel("Grave uma frase para aparecer aqui.")
        self.empty_subtitle.setObjectName("homeHistoryEmptySubtitle")
        self.empty_subtitle.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_subtitle)

        content_layout.addWidget(self.history_empty)

        # List of recent items
        self.history_list = QWidget()
        self.history_list.setObjectName("homeHistoryList")
        self.history_list_layout = QVBoxLayout(self.history_list)
        self.history_list_layout.setContentsMargins(0, 6, 0, 6)
        self.history_list_layout.setSpacing(12)
        content_layout.addWidget(self.history_list)

        self._recent_items = []
        self._latest_text = ""
        self._refresh_recent_history()
        
        trans_card.layout.addWidget(content_container)
        layout.addWidget(trans_card, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = event.size().width()
        if width < 860:
            if self._content_layout:
                self._content_layout.setContentsMargins(24, 20, 24, 20)
                self._content_layout.setSpacing(20)
            if self._hero_layout:
                self._hero_layout.setContentsMargins(0, 12, 0, 12)
                self._hero_layout.setSpacing(20)
            self.record_button.setFixedSize(120, 120)
            self.record_button._size = 120
        else:
            if self._content_layout:
                self._content_layout.setContentsMargins(40, 40, 40, 40)
                self._content_layout.setSpacing(32)
            if self._hero_layout:
                self._hero_layout.setContentsMargins(0, 20, 0, 20)
                self._hero_layout.setSpacing(28)
            self.record_button.setFixedSize(150, 150)
            self.record_button._size = 150

        # Connect buttons
        # (Already connected in loop above relative to this scope, but let's keep references if needed)
        
        # Ensure the record button draws slightly larger icons
        # We need to monkey-patch or update the RecordButton paint event if it was not updated.
        # Ideally, we should have updated the RecordButton class too. 
        # For now, we assume the class was updated or we rely on the large size.

    def _copy_transcription(self):
        if self._latest_text:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(self._latest_text)

    def _clear_transcription(self):
        if not self.history_manager or not hasattr(self.history_manager, "clear"):
            return
        text, ok = QInputDialog.getText(self, "Confirmar", "Digite 'LIMPAR' para apagar o histórico:")
        if ok and text.strip().upper() == "LIMPAR":
            self.history_manager.clear()
            self._refresh_recent_history()

    def _open_history(self):
        window = self.window()
        if hasattr(window, "switch_page"):
            window.switch_page("history")

    def _update_empty_state(self):
        has_items = bool(self._recent_items)
        self.history_empty.setVisible(not has_items)
        self.history_list.setVisible(has_items)

    def _apply_transcription_styles(self):
        # Kept for compatibility with existing calls (theme switch).
        # Recent history preview is styled via theme.qss using objectNames.
        pass

    def _copy_recent_item(self, text: str):
        if not text:
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)

    def _refresh_recent_history(self):
        # Clear existing items
        while self.history_list_layout.count():
            item = self.history_list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._recent_items = []
        self._latest_text = ""

        entries = []
        if self.history_manager and hasattr(self.history_manager, "get_all"):
            try:
                entries = self.history_manager.get_all(limit=4)
            except Exception:
                entries = []

        total = len(getattr(self.history_manager, "history", []) or []) if self.history_manager else 0
        if entries:
            self._latest_text = (entries[0].get("corrected") or entries[0].get("original") or "").strip()
        shown = len(entries)
        if total:
            self.home_history_count.setText(f"{shown} de {total}")
        else:
            self.home_history_count.setText("")

        for idx, entry in enumerate(entries):
            is_last = (idx == shown - 1)
            item = HistoryPreviewItem(entry, copy_callback=self._copy_recent_item)
            item.set_entry(entry, is_last=is_last)
            self.history_list_layout.addWidget(item)
            self._recent_items.append(item)

        self._update_empty_state()

    def _apply_action_btn_style(self, btn: QPushButton):
        base = self.colors["foreground_dim"]
        hover = self.colors["foreground"]
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {base};
                border: none;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.5px;
                padding: 4px 8px;
            }}
            QPushButton:hover {{ color: {hover}; }}
        """)

    def set_status(self, primary: str, secondary: str, color: str):
        if "Gravando" in primary:
            self.record_button.set_state(RecordButton.STATE_RECORDING)
            self.status_badge.set_status(primary, "#EF4444", True)
            
            self.action_label.setText("Solte para parar")
            self.action_label.setStyleSheet(
                "font-family: \"Manrope\", \"Inter\", \"Segoe UI\", sans-serif; "
                "color: #EF4444; font-size: 15px; font-weight: 700; letter-spacing: 0.4px;"
            )

        elif "Processando" in primary or "Transcrevendo" in primary:
            self.record_button.set_state(RecordButton.STATE_PROCESSING)
            self.status_badge.set_status(primary, "#F59E0B", False)
            
            self.action_label.setText("Transcrevendo...")
            self.action_label.setStyleSheet(
                "font-family: \"Manrope\", \"Inter\", \"Segoe UI\", sans-serif; "
                "color: #F59E0B; font-size: 15px; font-weight: 700; letter-spacing: 0.4px;"
            )
        elif "Erro" in primary:
            self.record_button.set_state(RecordButton.STATE_IDLE)
            self.status_badge.set_status(primary, "#EF4444", False)

            self.action_label.setText("Clique para gravar")
            self.action_label.setStyleSheet(
                "font-family: \"Manrope\", \"Inter\", \"Segoe UI\", sans-serif; "
                "color: #10B981; font-size: 15px; font-weight: 700; letter-spacing: 0.4px;"
            )
        else:
            self.record_button.set_state(RecordButton.STATE_IDLE)
            self.status_badge.set_status(primary, "#10B981", False)
            
            self.action_label.setText("Clique para gravar")
            self.action_label.setStyleSheet(
                "font-family: \"Manrope\", \"Inter\", \"Segoe UI\", sans-serif; "
                "color: #10B981; font-size: 15px; font-weight: 700; letter-spacing: 0.4px;"
            )

    def set_transcription(self, text: str):
        # History is persisted by TranscriptionHistory; refresh preview.
        self._refresh_recent_history()

    def append_transcription(self, text: str):
        self._refresh_recent_history()

    def update_mode_info(self, mode: str, hotkey: str):
        display_hotkey = hotkey.upper().replace("+", " + ")
        self.hotkey_pill.setText(display_hotkey)

    def connect_actions(self, mic_callback):
        self.btn_mic.clicked.connect(mic_callback)

    def set_theme(self, theme: str):
        self.colors = get_colors(theme)
        self._is_light_theme = theme == "beige"
        self.btn_mic.set_colors(self.colors)
        for btn in self._transcription_action_buttons:
            self._apply_action_btn_style(btn)
        self._apply_transcription_styles()

    def open_mic_test(self):
        window = self.window()
        if hasattr(window, "is_recording") and window.is_recording:
            try:
                from src.utils.logger import get_logger
                get_logger(__name__).info("Mic test blocked: app is_recording=True (window=%s)", type(window).__name__)
            except Exception:
                pass
            QMessageBox.information(self, "Microfone", "Pare a gravação antes de testar o microfone.")
            return
        dialog = MicTestDialog(self)
        dialog.exec()

class MicTestDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Testar microfone")
        self.setMinimumWidth(360)
        self.recorder = AudioRecorder(sample_rate=16000, channels=1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_level)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Fale para testar")
        title.setObjectName("settingTitle")
        layout.addWidget(title)

        subtitle = QLabel("Verifique se o nível reage à sua voz.")
        subtitle.setObjectName("mutedLabel")
        layout.addWidget(subtitle)

        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.level.setFixedHeight(10)
        layout.addWidget(self.level)

        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close, 0, Qt.AlignRight)

        QTimer.singleShot(0, self._start)

    def _start(self):
        if not self.recorder.is_microphone_available():
            QMessageBox.warning(self, "Microfone", "Nenhum microfone encontrado.")
            return
        try:
            self.recorder.start_recording()
            self.timer.start(50)
        except Exception:
            QMessageBox.warning(self, "Microfone", "Falha ao iniciar o microfone.")

    def _update_level(self):
        value = int(self.recorder.get_level() * 100)
        self.level.setValue(value)

    def closeEvent(self, event):
        if self.timer.isActive():
            self.timer.stop()
        if self.recorder and self.recorder.is_recording:
            self.recorder.stop_recording()
        super().closeEvent(event)


class HotkeyDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Configurar atalho")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Atalho de teclado")
        title.setObjectName("settingTitle")
        layout.addWidget(title)

        subtitle = QLabel("Exemplos: ctrl+shift, ctrl+alt+g")
        subtitle.setObjectName("mutedLabel")
        layout.addWidget(subtitle)

        self.input = QLineEdit()
        self.input.setPlaceholderText("ctrl+shift")
        if self.settings:
            self.input.setText(self.settings.get("hotkey", "ctrl+shift"))
        layout.addWidget(self.input)

        self.error = QLabel("")
        self.error.setObjectName("mutedLabel")
        layout.addWidget(self.error)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_save = QPushButton("Salvar")
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

        self._value = None

    def _on_save(self):
        raw = self.input.text().strip().lower()
        if not raw:
            self.error.setText("Informe um atalho.")
            return
        parts = [p.strip() for p in raw.split("+") if p.strip()]
        modifiers = {"ctrl", "shift", "alt", "win", "cmd"}
        has_modifier = any(p in modifiers for p in parts)
        modifier_count = sum(1 for p in parts if p in modifiers)
        has_key = any((len(p) == 1) or (p not in modifiers) for p in parts)
        if not has_modifier:
            self.error.setText("Use pelo menos um modificador.")
            return
        if not has_key and modifier_count < 2:
            self.error.setText("Use pelo menos dois modificadores ou uma tecla.")
            return
        self._value = "+".join(parts)
        self.accept()

    def value(self):
        return self._value



class LoginPage(QWidget):
    """Pagina de login premium"""

    login_requested = Signal(dict)
    password_reset_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(20)

        title = QLabel("Login")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        layout.addStretch()

        self.reason_label = QLabel("")
        self.reason_label.setObjectName("mutedLabel")
        self.reason_label.setWordWrap(True)
        self.reason_label.setAlignment(Qt.AlignCenter)
        self.reason_label.setVisible(False)
        layout.addWidget(self.reason_label)

        card = Card()
        card.setFixedWidth(420)
        card.layout.setContentsMargins(28, 28, 28, 28)
        card.layout.setSpacing(16)

        email_label = QLabel("Email")
        email_label.setObjectName("settingTitle")
        card.layout.addWidget(email_label)
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("seu@email.com")
        self.email_input.setMinimumHeight(48)
        card.layout.addWidget(self.email_input)

        senha_label = QLabel("Senha")
        senha_label.setObjectName("settingTitle")
        card.layout.addWidget(senha_label)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("••••••••")
        self.password_input.setMinimumHeight(48)
        card.layout.addWidget(self.password_input)

        row_password_actions = QHBoxLayout()
        row_password_actions.setContentsMargins(0, 0, 0, 0)
        row_password_actions.setSpacing(10)

        self.show_password_checkbox = QCheckBox("Mostrar senha")
        row_password_actions.addWidget(self.show_password_checkbox)

        row_password_actions.addStretch()
        self.btn_forgot_password = QPushButton("Esqueci minha senha")
        self.btn_forgot_password.setObjectName("ghostButton")
        self.btn_forgot_password.setCursor(Qt.PointingHandCursor)
        self.btn_forgot_password.setMinimumHeight(34)
        row_password_actions.addWidget(self.btn_forgot_password)
        card.layout.addLayout(row_password_actions)

        self.remember_checkbox = QCheckBox("Lembrar de mim")
        card.layout.addWidget(self.remember_checkbox)

        card.layout.addSpacing(8)

        self.btn_login = QPushButton("Entrar")
        self.btn_login.setObjectName("primaryButton")
        self.btn_login.setMinimumHeight(52)
        self.btn_login.setCursor(Qt.PointingHandCursor)
        card.layout.addWidget(self.btn_login)

        self.status_label = QLabel("")
        self.status_label.setObjectName("mutedLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setVisible(False)
        card.layout.addWidget(self.status_label)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setObjectName("divider")
        divider.setMaximumHeight(1)
        card.layout.addWidget(divider)

        ghost = QPushButton("Entrar com Google (em breve)")
        ghost.setObjectName("secondaryButton")
        ghost.setMinimumHeight(48)
        ghost.setCursor(Qt.PointingHandCursor)
        ghost.setEnabled(False)
        ghost.setVisible(False)
        card.layout.addWidget(ghost)

        center_layout = QHBoxLayout()
        center_layout.addStretch()
        center_layout.addWidget(card)
        center_layout.addStretch()
        layout.addLayout(center_layout)

        layout.addStretch()

        # Events
        self.btn_login.clicked.connect(self._on_submit)
        self.password_input.returnPressed.connect(self._on_submit)
        self.show_password_checkbox.toggled.connect(self._on_toggle_show_password)
        self.btn_forgot_password.clicked.connect(self._on_request_password_reset)

    def set_reason(self, text: str):
        msg = str(text or "").strip()
        self.reason_label.setText(msg)
        self.reason_label.setVisible(bool(msg))

    def set_prefill_email(self, email: str):
        v = str(email or "").strip()
        if v:
            self.email_input.setText(v)
            self.password_input.setFocus()
        else:
            self.email_input.setFocus()

    def set_status(self, text: str):
        msg = str(text or "").strip()
        self.status_label.setText(msg)
        self.status_label.setVisible(bool(msg))

    def set_loading(self, loading: bool):
        self.btn_login.setEnabled(not loading)
        self.email_input.setEnabled(not loading)
        self.password_input.setEnabled(not loading)
        self.remember_checkbox.setEnabled(not loading)
        self.show_password_checkbox.setEnabled(not loading)
        self.btn_forgot_password.setEnabled(not loading)
        self.btn_login.setText("Entrando..." if loading else "Entrar")

    def set_reset_loading(self, loading: bool):
        self.btn_forgot_password.setEnabled(not loading)
        self.btn_forgot_password.setText("Enviando..." if loading else "Esqueci minha senha")

    def _on_toggle_show_password(self, checked: bool):
        self.password_input.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def _on_submit(self):
        email = (self.email_input.text() or "").strip()
        password = (self.password_input.text() or "").strip()
        remember = bool(self.remember_checkbox.isChecked())

        if not email:
            self.set_status("Informe seu e-mail.")
            self.email_input.setFocus()
            return
        if not password:
            self.set_status("Informe sua senha.")
            self.password_input.setFocus()
            return

        self.set_status("")
        self.login_requested.emit({"email": email, "password": password, "remember_me": remember})

    def _on_request_password_reset(self):
        email = (self.email_input.text() or "").strip()
        if not email:
            self.set_status("Informe seu e-mail para recuperar a senha.")
            self.email_input.setFocus()
            return
        self.set_status("")
        self.password_reset_requested.emit(email)


class SettingsPage(QWidget):
    """Pagina de configuracoes (estilo SaaS)"""

    settings_saved = Signal(object)
    logout_requested = Signal()
    login_page_requested = Signal()

    def __init__(self, settings, on_theme_change=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.on_theme_change = on_theme_change
        self.colors = get_colors(self.settings.get("theme", "dark") if self.settings else "dark")
        self._rows = []
        self._update_check_callback = None
        self._update_open_callback = None
        self._update_download_callback = None
        self._update_install_callback = None
        self._update_download_in_progress = False

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setObjectName("settingsScroll")
        
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        title = QLabel("Configurações")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        account_card = Card()
        account_card.setObjectName("settingsSection")
        account_card.layout.setContentsMargins(0, 4, 0, 6)
        account_card.layout.setSpacing(4)
        account_card.layout.addWidget(SectionHeader("CONTA"))

        account_row = QWidget()
        account_row.setObjectName("settingRow")
        account_row.setProperty("last", True)
        account_row.setAttribute(Qt.WA_StyledBackground, True)
        account_layout = QHBoxLayout(account_row)
        account_layout.setContentsMargins(0, 4, 0, 4)
        account_layout.setSpacing(12)

        account_text = QVBoxLayout()
        account_text.setContentsMargins(0, 0, 0, 0)
        account_text.setSpacing(2)
        account_title = QLabel("Sessao atual")
        account_title.setObjectName("settingTitle")
        self._account_email_label = QLabel("--")
        self._account_email_label.setObjectName("mutedLabel")
        account_text.addWidget(account_title)
        account_text.addWidget(self._account_email_label)
        account_layout.addLayout(account_text, 1)

        self._btn_open_login = QPushButton("Entrar")
        self._btn_open_login.setObjectName("secondaryButton")
        self._btn_open_login.setMinimumHeight(36)
        self._btn_open_login.clicked.connect(self._on_open_login_clicked)
        account_layout.addWidget(self._btn_open_login)

        self._btn_logout = QPushButton("Sair da conta")
        self._btn_logout.setObjectName("ghostButton")
        self._btn_logout.setMinimumHeight(36)
        self._btn_logout.clicked.connect(self._on_logout_clicked)
        account_layout.addWidget(self._btn_logout)

        account_card.layout.addWidget(account_row)
        layout.addWidget(account_card)

        system_card = Card()
        system_card.setObjectName("settingsSection")
        system_card.layout.setContentsMargins(0, 4, 0, 6)
        system_card.layout.setSpacing(4)
        system_card.layout.addWidget(SectionHeader("SISTEMA"))
        self.launch_login = SettingRow(
            "Iniciar com o sistema",
            "Abre ao ligar o PC",
            self.settings.get("launch_login", False) if self.settings else False,
            colors=self.colors,
        )
        self.show_floating = SettingRow(
            "Barra flutuante visível",
            "Mantém barra de status",
            self.settings.get("show_floating", True) if self.settings else True,
            last=False,
            colors=self.colors,
        )
        system_card.layout.addWidget(self.launch_login)
        system_card.layout.addWidget(self.show_floating)

        # Hotkey editor (helps when ctrl+shift conflicts with Windows shortcuts).
        self._hotkey_row = QWidget()
        self._hotkey_row.setObjectName("settingRow")
        self._hotkey_row.setProperty("last", True)
        self._hotkey_row.setAttribute(Qt.WA_StyledBackground, True)
        hk_layout = QHBoxLayout(self._hotkey_row)
        hk_layout.setContentsMargins(0, 4, 0, 4)
        hk_layout.setSpacing(12)

        hk_text = QVBoxLayout()
        hk_text.setContentsMargins(0, 0, 0, 0)
        hk_text.setSpacing(2)
        hk_title = QLabel("Atalho")
        hk_title.setObjectName("settingTitle")
        hk_sub = QLabel("Tecla para falar (ex: ctrl+alt).")
        hk_sub.setObjectName("mutedLabel")
        hk_text.addWidget(hk_title)
        hk_text.addWidget(hk_sub)
        hk_layout.addLayout(hk_text, 1)

        raw_hotkey = self.settings.get("hotkey", "ctrl+shift") if self.settings else "ctrl+shift"
        self._hotkey_pill = QLabel(raw_hotkey.upper().replace("+", " + "))
        self._hotkey_pill.setAlignment(Qt.AlignCenter)
        self._hotkey_pill.setMinimumWidth(140)
        hk_layout.addWidget(self._hotkey_pill)

        self._hotkey_btn = QPushButton("Alterar")
        self._hotkey_btn.setObjectName("secondaryButton")
        self._hotkey_btn.setMinimumHeight(36)
        self._hotkey_btn.clicked.connect(self._on_change_hotkey)
        hk_layout.addWidget(self._hotkey_btn)

        system_card.layout.addWidget(self._hotkey_row)
        layout.addWidget(system_card)
        self._rows.extend([self.launch_login, self.show_floating])

        sound_card = Card()
        sound_card.setObjectName("settingsSection")
        sound_card.layout.setContentsMargins(0, 4, 0, 6)
        sound_card.layout.setSpacing(4)
        sound_card.layout.addWidget(SectionHeader("SOM"))
        self.dictation_fx = SettingRow(
            "Efeitos sonoros",
            "Sons ao gravar",
            self.settings.get("dictation_fx", True) if self.settings else True,
            colors=self.colors,
        )
        self.mute_music = SettingRow(
            "Silenciar música",
            "Pausa músicas ao falar",
            self.settings.get("mute_music", False) if self.settings else False,
            last=True,
            colors=self.colors,
        )
        sound_card.layout.addWidget(self.dictation_fx)
        sound_card.layout.addWidget(self.mute_music)
        layout.addWidget(sound_card)
        self._rows.extend([self.dictation_fx, self.mute_music])

        correction_card = Card()
        correction_card.setObjectName("settingsSection")
        correction_card.layout.setContentsMargins(0, 4, 0, 6)
        correction_card.layout.setSpacing(4)
        correction_card.layout.addWidget(SectionHeader("CORREÇÃO"))
        self.correction_toggle = SettingRow(
            "Correção automática",
            "Pontuação, capitalização e ortografia",
            self.settings.get("gpt_correction", True) if self.settings else True,
            colors=self.colors,
        )
        correction_card.layout.addWidget(self.correction_toggle)
        self._rows.append(self.correction_toggle)

        style_row = QWidget()
        style_row.setObjectName("settingRow")
        style_row.setProperty("last", True)
        style_row.setAttribute(Qt.WA_StyledBackground, True)
        style_layout = QHBoxLayout(style_row)
        style_layout.setContentsMargins(0, 4, 0, 4)
        style_layout.setSpacing(12)

        style_text = QVBoxLayout()
        style_text.setContentsMargins(0, 0, 0, 0)
        style_text.setSpacing(2)
        style_title = QLabel("Estilo de correção")
        style_title.setObjectName("settingTitle")
        style_sub = QLabel("Pontual, Casual ou Formal")
        style_sub.setObjectName("mutedLabel")
        style_text.addWidget(style_title)
        style_text.addWidget(style_sub)
        style_layout.addLayout(style_text, 1)

        current_style = self.settings.get("correction_style", "neutro") if self.settings else "neutro"
        self.style_segment = SegmentedControl(
            [("Pontual", "neutro"), ("Casual", "casual"), ("Formal", "formal")],
            value=current_style,
        )
        style_layout.addWidget(self.style_segment)
        style_row.setProperty("last", False)
        correction_card.layout.addWidget(style_row)

        format_row = QWidget()
        format_row.setObjectName("settingRow")
        format_row.setProperty("last", True)
        format_row.setAttribute(Qt.WA_StyledBackground, True)
        format_layout = QHBoxLayout(format_row)
        format_layout.setContentsMargins(0, 4, 0, 4)
        format_layout.setSpacing(12)

        format_text = QVBoxLayout()
        format_text.setContentsMargins(0, 0, 0, 0)
        format_text.setSpacing(2)
        format_title = QLabel("Formato de saída")
        format_title.setObjectName("settingTitle")
        format_sub = QLabel("Padrão ou Mensagem com quebras automáticas")
        format_sub.setObjectName("mutedLabel")
        format_text.addWidget(format_title)
        format_text.addWidget(format_sub)
        format_layout.addLayout(format_text, 1)

        current_format = self.settings.get("message_format_mode", "balanced") if self.settings else "balanced"
        self.format_segment = SegmentedControl(
            [("Padrão", "balanced"), ("Mensagem", "message")],
            value=current_format,
        )
        format_layout.addWidget(self.format_segment)
        correction_card.layout.addWidget(format_row)
        layout.addWidget(correction_card)

        extras_card = Card()
        extras_card.setObjectName("settingsSection")
        extras_card.layout.setContentsMargins(0, 4, 0, 6)
        extras_card.layout.setSpacing(4)
        extras_card.layout.addWidget(SectionHeader("FUNCIONALIDADES"))
        self.auto_paste = SettingRow(
            "Colar automaticamente",
            "Cola texto onde você digitava",
            self.settings.get("auto_paste", True) if self.settings else True,
            last=True,
            colors=self.colors,
        )
        extras_card.layout.addWidget(self.auto_paste)
        layout.addWidget(extras_card)
        self._rows.append(self.auto_paste)

        appearance_card = Card()
        appearance_card.setObjectName("settingsSection")
        appearance_card.setProperty("last", True)
        appearance_card.layout.setContentsMargins(0, 4, 0, 6)
        appearance_card.layout.setSpacing(4)
        appearance_card.layout.addWidget(SectionHeader("APARÊNCIA"))
        is_beige = (self.settings.get("theme", "dark") == "beige") if self.settings else False
        self.theme_toggle = SettingRow(
            "Tema Claro",
            "Alterna tema escuro/claro",
            is_beige,
            last=True,
            colors=self.colors,
        )
        appearance_card.layout.addWidget(self.theme_toggle)
        layout.addWidget(appearance_card)
        self._rows.append(self.theme_toggle)

        # Updates (GitHub Releases) - Option A: notify + open download link.
        updates_card = Card()
        updates_card.setObjectName("settingsSection")
        updates_card.setProperty("last", True)
        updates_card.layout.setContentsMargins(0, 4, 0, 6)
        updates_card.layout.setSpacing(4)
        updates_card.layout.addWidget(SectionHeader("ATUALIZAÇÕES"))

        try:
            from src import __version__ as _APP_VERSION
            app_version = str(_APP_VERSION or "").strip() or "?"
        except Exception:
            app_version = "?"

        self._update_current_label = QLabel(f"Versão instalada: {app_version}")
        self._update_current_label.setObjectName("mutedLabel")
        updates_card.layout.addWidget(self._update_current_label)

        actions = QWidget()
        actions.setObjectName("settingRow")
        actions.setProperty("last", True)
        actions.setAttribute(Qt.WA_StyledBackground, True)
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 4, 0, 4)
        actions_layout.setSpacing(12)

        actions_text = QVBoxLayout()
        actions_text.setContentsMargins(0, 0, 0, 0)
        actions_text.setSpacing(0)
        actions_title = QLabel("Verificar atualizações")
        actions_title.setObjectName("settingTitle")
        actions_text.addWidget(actions_title)
        actions_layout.addLayout(actions_text, 1)

        self._btn_check_updates = QPushButton("Verificar")
        self._btn_check_updates.setObjectName("secondaryButton")
        self._btn_check_updates.setMinimumHeight(36)
        self._btn_check_updates.clicked.connect(self._on_check_updates)
        actions_layout.addWidget(self._btn_check_updates)

        self._btn_download_update = QPushButton("Baixar")
        self._btn_download_update.setObjectName("primaryButton")
        self._btn_download_update.setMinimumHeight(36)
        self._btn_download_update.setVisible(False)
        self._btn_download_update.clicked.connect(self._on_download_update)
        actions_layout.addWidget(self._btn_download_update)

        self._btn_install_update = QPushButton("Instalar agora")
        self._btn_install_update.setObjectName("primaryButton")
        self._btn_install_update.setMinimumHeight(36)
        self._btn_install_update.setVisible(False)
        self._btn_install_update.clicked.connect(self._on_install_update)
        actions_layout.addWidget(self._btn_install_update)

        updates_card.layout.addWidget(actions)

        self._update_progress = QProgressBar()
        self._update_progress.setTextVisible(False)
        self._update_progress.setMinimumHeight(10)
        self._update_progress.setMaximumHeight(10)
        self._update_progress.setRange(0, 100)
        self._update_progress.setValue(0)
        self._update_progress.setVisible(False)
        updates_card.layout.addWidget(self._update_progress)

        self._update_status_label = QLabel("")
        self._update_status_label.setObjectName("mutedLabel")
        self._update_status_label.setWordWrap(True)
        updates_card.layout.addWidget(self._update_status_label)

        layout.addWidget(updates_card)

        layout.addStretch()
        
        scroll_area.setWidget(scroll_content)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll_area)

        # Bind actions
        self.auto_paste.toggle.toggled.connect(self._on_auto_paste)
        self.correction_toggle.toggle.toggled.connect(self._on_correction_toggle)
        self.style_segment.valueChanged.connect(self._on_correction_style)
        self.format_segment.valueChanged.connect(self._on_message_format_mode)
        self.theme_toggle.toggle.toggled.connect(self._on_theme_toggle)
        self.launch_login.toggle.toggled.connect(self._on_launch_login)
        self.show_floating.toggle.toggled.connect(self._on_show_floating)
        self.dictation_fx.toggle.toggled.connect(self._on_dictation_fx)
        self.mute_music.toggle.toggled.connect(self._on_mute_music)
        if self._set_correction_enabled(self.correction_toggle.is_checked()) and self.settings:
            self.settings.save()
        self._apply_hotkey_pill_style()
        self._refresh_update_info()
        self.refresh_account_state()

    def set_update_callbacks(
        self,
        check_callback: Callable | None,
        open_callback: Callable | None,
        download_callback: Callable | None = None,
        install_callback: Callable | None = None,
    ):
        """Wire update buttons to the main app logic (non-blocking)."""
        self._update_check_callback = check_callback
        self._update_open_callback = open_callback
        self._update_download_callback = download_callback
        self._update_install_callback = install_callback
        self._refresh_update_info()

    def _on_check_updates(self):
        if not self.settings:
            return
        if not self._update_check_callback:
            self._update_status_label.setText("Atualizações não configuradas.")
            return
        self._update_status_label.setText("Verificando...")
        try:
            self._update_check_callback()
        except Exception:
            self._update_status_label.setText("Não consegui verificar agora.")
            return
        # Refresh UI after the background check finishes (best-effort).
        QTimer.singleShot(2500, self._refresh_update_info)

    def _on_download_update(self):
        # Prefer in-app download (progress bar) when available.
        if self._update_download_callback:
            try:
                self._update_status_label.setText("Baixando...")
                self._update_download_callback()
            except Exception:
                self._update_status_label.setText("Não consegui baixar agora.")
            return

        # Fallback: open browser (older builds / safe path).
        if not self._update_open_callback:
            self._update_status_label.setText("Link de atualização indisponível.")
            return
        try:
            self._update_open_callback()
        except Exception:
            self._update_status_label.setText("Não consegui abrir o link.")

    def _on_install_update(self):
        if not self._update_install_callback:
            self._update_status_label.setText("Instalação indisponível.")
            return
        try:
            self._update_status_label.setText("Abrindo instalador...")
            self._update_install_callback()
        except Exception:
            self._update_status_label.setText("Não consegui iniciar a instalação.")

    def on_update_download_started(self, version: str = "") -> None:
        """Called by the main app (Qt thread) when a download starts."""
        self._update_download_in_progress = True
        if hasattr(self, "_btn_check_updates"):
            self._btn_check_updates.setEnabled(False)
        if hasattr(self, "_btn_download_update"):
            self._btn_download_update.setEnabled(False)
        if hasattr(self, "_btn_install_update"):
            self._btn_install_update.setEnabled(False)
            self._btn_install_update.setVisible(False)
        if hasattr(self, "_update_progress"):
            self._update_progress.setVisible(True)
            # Indeterminate until we receive real percent.
            self._update_progress.setRange(0, 0)
        if hasattr(self, "_update_status_label"):
            v = str(version or "").strip()
            self._update_status_label.setText("Baixando atualização..." if not v else f"Baixando atualização {v}...")

    def on_update_download_progress(self, percent: int) -> None:
        """Called by the main app (Qt thread) to update progress (0-100)."""
        if not hasattr(self, "_update_progress"):
            return
        try:
            p = int(percent)
        except Exception:
            p = -1
        if p < 0:
            self._update_progress.setRange(0, 0)
            return
        # Switch to determinate mode.
        if self._update_progress.maximum() == 0:
            self._update_progress.setRange(0, 100)
        self._update_progress.setValue(max(0, min(100, p)))

    def on_update_download_completed(self, path: str = "") -> None:
        """Called by the main app (Qt thread) when download finishes."""
        self._update_download_in_progress = False
        if hasattr(self, "_btn_check_updates"):
            self._btn_check_updates.setEnabled(True)
        if hasattr(self, "_btn_download_update"):
            self._btn_download_update.setEnabled(True)
        if hasattr(self, "_btn_install_update"):
            self._btn_install_update.setEnabled(True)
        if hasattr(self, "_update_progress"):
            self._update_progress.setRange(0, 100)
            self._update_progress.setValue(100)
            self._update_progress.setVisible(False)
        if hasattr(self, "_update_status_label"):
            self._update_status_label.setText("Atualização baixada. Clique em Instalar agora.")
        self._refresh_update_info()

    def on_update_download_failed(self, message: str = "") -> None:
        """Called by the main app (Qt thread) when download fails."""
        self._update_download_in_progress = False
        if hasattr(self, "_btn_check_updates"):
            self._btn_check_updates.setEnabled(True)
        if hasattr(self, "_btn_download_update"):
            self._btn_download_update.setEnabled(True)
        if hasattr(self, "_btn_install_update"):
            self._btn_install_update.setEnabled(True)
        if hasattr(self, "_update_progress"):
            self._update_progress.setVisible(False)
            self._update_progress.setRange(0, 100)
            self._update_progress.setValue(0)
        msg = str(message or "").strip() or "Falha ao baixar. Verifique sua internet e tente novamente."
        if hasattr(self, "_update_status_label"):
            self._update_status_label.setText(msg)
        self._refresh_update_info()

    def _refresh_update_info(self):
        if not self.settings:
            return
        try:
            from src.backend.update_service import is_newer_version
        except Exception:
            is_newer_version = None

        try:
            from src import __version__ as _APP_VERSION
            current = str(_APP_VERSION or "").strip()
        except Exception:
            current = ""

        latest = str(self.settings.get("update_available_version", "") or "").strip()
        last_checked = float(self.settings.get("update_last_checked_at", 0.0) or 0.0)
        last_error = str(self.settings.get("update_last_error", "") or "").strip()
        downloaded_version = str(self.settings.get("update_downloaded_version", "") or "").strip()
        downloaded_path = str(self.settings.get("update_downloaded_path", "") or "").strip()
        downloaded_valid_raw = self.settings.get("update_downloaded_valid", True)
        downloaded_valid = bool(downloaded_valid_raw) if isinstance(downloaded_valid_raw, bool) else True
        downloaded_ok = False
        if downloaded_version and downloaded_path:
            try:
                downloaded_ok = Path(downloaded_path).exists()
            except Exception:
                downloaded_ok = False

        suffix = ""
        if last_checked:
            try:
                dt = datetime.fromtimestamp(last_checked)
                suffix = f" (última verificação: {dt.strftime('%d/%m %H:%M')})"
            except Exception:
                suffix = ""

        has_update = False
        if latest and is_newer_version and current:
            try:
                has_update = bool(is_newer_version(latest, current))
            except Exception:
                has_update = False

        if self._update_download_in_progress:
            # Keep UI stable during download; progress callbacks will update visuals.
            return

        if has_update:
            # Reset default label unless we detect an invalid cached file.
            self._btn_download_update.setText("Baixar")

            same_version_cached = bool(downloaded_ok and downloaded_version and downloaded_version == latest)
            if same_version_cached and not downloaded_valid:
                self._update_status_label.setText(f"Arquivo de atualização inválido. Baixe novamente.{suffix}")
            else:
                self._update_status_label.setText(f"Nova versão {latest} disponível.{suffix}")

            # If we already downloaded this exact and valid version, prefer "Install now".
            can_install = bool(same_version_cached and downloaded_valid)
            self._btn_install_update.setVisible(can_install)
            self._btn_download_update.setVisible(not can_install)
            if not can_install and same_version_cached and not downloaded_valid:
                self._btn_download_update.setText("Baixar novamente")
        else:
            self._btn_download_update.setText("Baixar")
            self._btn_download_update.setVisible(False)
            self._btn_install_update.setVisible(False)
            if latest:
                self._update_status_label.setText(f"Você está na última versão.{suffix}")
            else:
                if last_error:
                    self._update_status_label.setText(f"Não consegui verificar atualizações.{suffix}")
                else:
                    self._update_status_label.setText(f"Clique em Verificar para checar atualizações.{suffix}")

    def _apply_hotkey_pill_style(self):
        if not hasattr(self, "_hotkey_pill"):
            return
        pill_bg = self.colors.get("pill_bg", "#1F2937")
        border = self.colors.get("border", "#2F3442")
        fg = self.colors.get("foreground", "#F8FAFC")
        self._hotkey_pill.setStyleSheet(
            f"background: {pill_bg}; color: {fg}; border: 1px solid {border};"
            "border-radius: 10px; padding: 6px 10px; font-weight: 700;"
        )

    def refresh_account_state(self):
        if not self.settings:
            if hasattr(self, "_account_email_label"):
                self._account_email_label.setText("Conta indisponivel")
            if hasattr(self, "_btn_logout"):
                self._btn_logout.setEnabled(False)
            return

        email = str(self.settings.get("user_email", "") or "").strip()
        auth_token = str(self.settings.get("auth_token", "") or "").strip()
        has_session = bool(auth_token)

        if hasattr(self, "_account_email_label"):
            if email:
                self._account_email_label.setText(email)
            elif has_session:
                self._account_email_label.setText("Sessao ativa")
            else:
                self._account_email_label.setText("Nao conectado")

        if hasattr(self, "_btn_logout"):
            self._btn_logout.setEnabled(has_session)

    def _on_open_login_clicked(self):
        self.login_page_requested.emit()

    def _on_logout_clicked(self):
        if hasattr(self, "_btn_logout") and not self._btn_logout.isEnabled():
            return
        self.logout_requested.emit()

    def _on_change_hotkey(self):
        if not self.settings:
            return
        dlg = HotkeyDialog(self.settings, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        value = dlg.value()
        if not value:
            return
        self.settings.set("hotkey", value)
        self.settings.save()
        if hasattr(self, "_hotkey_pill"):
            self._hotkey_pill.setText(value.upper().replace("+", " + "))
        self.settings_saved.emit(["hotkey"])

    def _on_auto_paste(self, checked: bool):
        if not self.settings:
            return
        self.settings.set("auto_paste", checked)
        self.settings.save()
        self.settings_saved.emit(["auto_paste"])

    def _on_correction_toggle(self, checked: bool):
        if not self.settings:
            return
        self.settings.set("gpt_correction", checked)
        format_reset = self._set_correction_enabled(checked)
        self.settings.save()
        changed_keys = ["gpt_correction"]
        if format_reset:
            changed_keys.append("message_format_mode")
        self.settings_saved.emit(changed_keys)

    def _on_correction_style(self, style: str):
        if not self.settings:
            return
        self.settings.set("correction_style", style)
        self.settings.save()
        self.settings_saved.emit(["correction_style"])

    def _on_message_format_mode(self, mode: str):
        if not self.settings:
            return
        normalized = effective_message_format_mode(mode, self.correction_toggle.is_checked())
        if normalized == "balanced" and str(self.format_segment.value() or "").strip().lower() != "balanced":
            self.format_segment.set_value("balanced")
        self.settings.set("message_format_mode", normalized)
        self.settings.save()
        self.settings_saved.emit(["message_format_mode"])

    def _on_theme_toggle(self, checked: bool):
        if not self.settings:
            return
        theme = "beige" if checked else "dark"
        if self.on_theme_change:
            self.on_theme_change(theme)
        else:
            self.set_theme(theme)
        self.settings.set("theme", theme)
        # Persist after repaint to keep theme switch instant.
        QTimer.singleShot(0, self.settings.save)

    def _on_launch_login(self, checked: bool):
        if not self.settings:
            return
        self.settings.set("launch_login", checked)
        self.settings.save()
        self.settings_saved.emit(["launch_login"])

    def _on_show_floating(self, checked: bool):
        if not self.settings:
            return
        self.settings.set("show_floating", checked)
        self.settings.save()
        self.settings_saved.emit(["show_floating"])

    def _on_dictation_fx(self, checked: bool):
        if not self.settings:
            return
        self.settings.set("dictation_fx", checked)
        self.settings.save()
        self.settings_saved.emit(["dictation_fx"])

    def _on_mute_music(self, checked: bool):
        if not self.settings:
            return
        self.settings.set("mute_music", checked)
        self.settings.save()
        self.settings_saved.emit(["mute_music"])

    def _set_correction_enabled(self, enabled: bool):
        format_reset = False
        if not enabled:
            if self.format_segment.value() != "balanced":
                self.format_segment.set_value("balanced")
            if self.settings:
                current_saved = str(self.settings.get("message_format_mode", "balanced") or "").strip().lower()
                if current_saved != "balanced":
                    self.settings.set("message_format_mode", "balanced")
                    format_reset = True
        self.style_segment.setEnabled(enabled)
        self.format_segment.setEnabled(enabled)
        return format_reset

    def set_theme(self, theme: str):
        self.colors = get_colors(theme)
        is_beige = theme == "beige"
        self.theme_toggle.toggle.blockSignals(True)
        self.theme_toggle.toggle.setChecked(is_beige)
        self.theme_toggle.toggle.blockSignals(False)
        for row in self._rows:
            row.set_colors(self.colors)
        self._apply_hotkey_pill_style()


class HistoryEntryCard(QFrame):
    def __init__(self, entry: dict, copy_callback, parent=None):
        super().__init__(parent)
        self.setObjectName("historyEntry")
        self.entry = entry
        self._copy_callback = copy_callback
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        self.select_box = QCheckBox()
        self.select_box.setObjectName("historySelect")
        header_row.addWidget(self.select_box)

        meta_col = QVBoxLayout()
        meta_col.setContentsMargins(0, 0, 0, 0)
        meta_col.setSpacing(4)

        time_str = entry.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(entry.get("timestamp", ""))
            time_str = dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass

        time_label = QLabel(time_str)
        time_label.setObjectName("historyMeta")
        meta_col.addWidget(time_label)

        badges_row = QHBoxLayout()
        badges_row.setContentsMargins(0, 0, 0, 0)
        badges_row.setSpacing(6)

        duration = entry.get("duration_seconds", 0)
        if duration:
            duration_label = QLabel(f"{duration:.1f}s")
            duration_label.setObjectName("historyBadge")
            duration_label.setProperty("variant", "duration")
            badges_row.addWidget(duration_label)

        corrected = bool(entry.get("corrected"))
        status_label = QLabel("Corrigido" if corrected else "Original")
        status_label.setObjectName("historyBadge")
        status_label.setProperty("variant", "corrected" if corrected else "original")
        badges_row.addWidget(status_label)

        badges_row.addStretch()
        meta_col.addLayout(badges_row)
        header_row.addLayout(meta_col, 1)

        header_row.addStretch()

        self.copy_btn = QPushButton("Copiar")
        self.copy_btn.setObjectName("historyAction")
        self.copy_btn.clicked.connect(self._on_copy)
        header_row.addWidget(self.copy_btn)

        self.expand_btn = QPushButton("Ver mais")
        self.expand_btn.setObjectName("historyAction")
        self.expand_btn.clicked.connect(self.toggle_expand)
        header_row.addWidget(self.expand_btn)

        layout.addLayout(header_row)

        self.full_text = entry.get("corrected") or entry.get("original", "")
        self.preview_text = self._truncate(self.full_text)

        self.text_label = QLabel(self.preview_text)
        self.text_label.setObjectName("historyText")
        self.text_label.setWordWrap(True)
        layout.addWidget(self.text_label)

        self.toast = QLabel("Copiado")
        self.toast.setObjectName("historyToast")
        self.toast.hide()
        layout.addWidget(self.toast, 0, Qt.AlignRight)

        if len(self.full_text) <= len(self.preview_text):
            self.expand_btn.hide()

    def _truncate(self, text: str) -> str:
        if len(text) <= 220:
            return text
        return text[:220].rstrip() + "..."

    def _on_copy(self):
        if self._copy_callback:
            self._copy_callback(self.full_text, False)
        self.toast.show()
        QTimer.singleShot(900, self.toast.hide)

    def toggle_expand(self):
        self._expanded = not self._expanded
        if self._expanded:
            self.text_label.setText(self.full_text)
            self.expand_btn.setText("Ver menos")
        else:
            self.text_label.setText(self.preview_text)
            self.expand_btn.setText("Ver mais")

    def is_selected(self) -> bool:
        return self.select_box.isChecked()

    def get_text(self) -> str:
        return self.full_text


class HistoryPage(QWidget):
    """Pagina de historico premium"""

    def __init__(self, history_manager, parent=None):
        super().__init__(parent)
        self.history_manager = history_manager
        self.clipboard = ClipboardManager()
        self.page_size = 20
        self.current_page = 1
        self._entry_cards = []

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_search)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(32, 28, 32, 28)
        main_layout.setSpacing(14)

        header = QWidget()
        header.setObjectName("historyHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)

        title = QLabel("Histórico")
        title.setObjectName("pageTitle")
        title_col.addWidget(title)

        self.count_label = QLabel("0 transcrições")
        self.count_label.setObjectName("historyCount")
        title_col.addWidget(self.count_label)

        top_row.addLayout(title_col)
        top_row.addStretch()

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Buscar...")
        self.search_entry.setObjectName("historySearch")
        self.search_entry.setFixedWidth(240)
        self.search_entry.textChanged.connect(self._on_search)
        top_row.addWidget(self.search_entry)

        header_layout.addLayout(top_row)

        self.actions_row_main = QHBoxLayout()
        self.actions_row_main.setContentsMargins(0, 0, 0, 0)
        self.actions_row_main.setSpacing(8)
        self.actions_row_main.addStretch()

        self.copy_selected_btn = QPushButton("Copiar selecionadas")
        self.copy_selected_btn.setObjectName("ghostButton")
        self.copy_selected_btn.setMinimumWidth(140)
        self.copy_selected_btn.clicked.connect(self._copy_selected)
        self.actions_row_main.addWidget(self.copy_selected_btn)

        self.clear_btn = QPushButton("Limpar")
        self.clear_btn.setObjectName("ghostButton")
        self.clear_btn.setMinimumWidth(80)
        self.clear_btn.clicked.connect(self._clear_history)
        self.actions_row_main.addWidget(self.clear_btn)

        self.export_btn = QPushButton("Exportar")
        self.export_btn.setObjectName("primaryButton")
        self.export_btn.setMinimumWidth(110)
        self.export_btn.clicked.connect(self._export_history)
        self.actions_row_main.addWidget(self.export_btn)

        self.actions_row_secondary = QHBoxLayout()
        self.actions_row_secondary.setContentsMargins(0, 0, 0, 0)
        self.actions_row_secondary.setSpacing(8)
        self.actions_row_secondary.addStretch()

        header_layout.addLayout(self.actions_row_main)
        header_layout.addLayout(self.actions_row_secondary)

        filters_row = QHBoxLayout()
        filters_row.setContentsMargins(0, 0, 0, 0)
        filters_row.setSpacing(10)

        self.toggle_filters_btn = QPushButton("Filtros")
        self.toggle_filters_btn.setCheckable(True)
        self.toggle_filters_btn.setObjectName("historyFilterToggle")
        self.toggle_filters_btn.clicked.connect(self._toggle_filters)
        filters_row.addWidget(self.toggle_filters_btn)

        self.chips_container = QWidget()
        self.chips_layout = QHBoxLayout(self.chips_container)
        self.chips_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_layout.setSpacing(6)
        filters_row.addWidget(self.chips_container)
        filters_row.addStretch()
        header_layout.addLayout(filters_row)

        self.filters_panel = QWidget()
        self.filters_panel.setObjectName("historyFilters")
        panel_layout = QHBoxLayout(self.filters_panel)
        panel_layout.setContentsMargins(0, 6, 0, 0)
        panel_layout.setSpacing(12)

        self.date_filter_checkbox = QCheckBox("Filtrar por data")
        self.date_filter_checkbox.toggled.connect(self._on_filter_changed)
        panel_layout.addWidget(self.date_filter_checkbox)

        today = QDate.currentDate()
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_from.setDate(today.addDays(-7))
        self.date_from.setFixedWidth(130)
        self.date_from.dateChanged.connect(self._on_filter_changed)
        panel_layout.addWidget(QLabel("De:"))
        panel_layout.addWidget(self.date_from)

        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setDate(today)
        self.date_to.setFixedWidth(130)
        self.date_to.dateChanged.connect(self._on_filter_changed)
        panel_layout.addWidget(QLabel("Até:"))
        panel_layout.addWidget(self.date_to)

        self.corrected_only_checkbox = QCheckBox("Apenas corrigidos")
        self.corrected_only_checkbox.toggled.connect(self._on_filter_changed)
        panel_layout.addWidget(self.corrected_only_checkbox)

        panel_layout.addStretch()
        self.filters_panel.setVisible(False)
        header_layout.addWidget(self.filters_panel)

        for picker in (self.date_from, self.date_to):
            cal = QCalendarWidget()
            cal.setGridVisible(True)
            cal.setFirstDayOfWeek(Qt.Monday)
            cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
            cal.setMinimumSize(320, 240)
            picker.setCalendarWidget(cal)

        main_layout.addWidget(header)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area = scroll_area

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(12)
        self.list_layout.addStretch()
        scroll_area.setWidget(self.list_container)
        main_layout.addWidget(scroll_area, 1)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(10)
        footer_row.addStretch()
        self.load_more_btn = QPushButton("Carregar mais")
        self.load_more_btn.setFixedWidth(180)
        self.load_more_btn.setObjectName("primaryButton")
        self.load_more_btn.clicked.connect(self._load_more)
        footer_row.addWidget(self.load_more_btn)
        main_layout.addLayout(footer_row)

        self.message_label = QLabel()
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setObjectName("mutedLabel")
        self.message_label.hide()
        main_layout.addWidget(self.message_label)

        self._compact_header = False
        self._set_header_compact(self.width() < 980)
        self._last_history_count = 0
        self._load_history()

    def showEvent(self, event):
        """Refresh history whenever the page becomes visible."""
        super().showEvent(event)
        current_count = len(self.history_manager.history) if self.history_manager else 0
        if current_count != self._last_history_count:
            self.current_page = 1
            self._load_history(self.search_entry.text().strip())

    def refresh(self):
        """Public method to force a history reload."""
        self.current_page = 1
        self._load_history(self.search_entry.text().strip())

    def _load_history(self, query: str = ""):
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._entry_cards = []
        all_entries = list(reversed(self.history_manager.history))
        self._last_history_count = len(all_entries)
        entries = self._get_filtered_entries(query)
        total_entries = len(entries)
        visible_limit = self.page_size * self.current_page
        entries = entries[:visible_limit]

        self._update_filter_chips()

        if not all_entries:
            empty_box = QWidget()
            empty_layout = QVBoxLayout(empty_box)
            empty_layout.setContentsMargins(0, 40, 0, 40)
            empty_layout.setSpacing(10)
            empty_label = QLabel("Nenhuma transcrição ainda")
            empty_label.setObjectName("mutedLabel")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_layout.addWidget(empty_label)
            cta = QPushButton("Gravar agora")
            cta.setObjectName("primaryButton")
            cta.setFixedWidth(160)
            cta.clicked.connect(self._go_to_record)
            empty_layout.addWidget(cta, 0, Qt.AlignCenter)
            self.list_layout.insertWidget(0, empty_box)
            self.count_label.setText("0 transcrições")
            self.load_more_btn.setVisible(False)
            return

        if not entries:
            empty_box = QWidget()
            empty_layout = QVBoxLayout(empty_box)
            empty_layout.setContentsMargins(0, 40, 0, 40)
            empty_layout.setSpacing(10)
            empty_label = QLabel("Nenhum resultado para os filtros atuais")
            empty_label.setObjectName("mutedLabel")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_layout.addWidget(empty_label)
            clear_filters = QPushButton("Limpar filtros")
            clear_filters.setObjectName("ghostButton")
            clear_filters.setFixedWidth(160)
            clear_filters.clicked.connect(self._reset_filters)
            empty_layout.addWidget(clear_filters, 0, Qt.AlignCenter)
            self.list_layout.insertWidget(0, empty_box)
            self.count_label.setText("0 transcrições")
            self.load_more_btn.setVisible(False)
            return

        for i, entry in enumerate(entries):
            widget = HistoryEntryCard(entry, self._copy_text)
            self._entry_cards.append(widget)
            self.list_layout.insertWidget(i, widget)

        self.count_label.setText(f"{len(entries)} de {total_entries} transcrições")
        self.load_more_btn.setVisible(len(entries) < total_entries)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._set_header_compact(event.size().width() < 980)

    def _set_header_compact(self, compact: bool):
        if compact == self._compact_header:
            return
        self._compact_header = compact
        if compact:
            self.search_entry.setFixedWidth(180)
            self.copy_selected_btn.setText("Copiar seleção")
            if self.export_btn.parent() is not None:
                self.actions_row_main.removeWidget(self.export_btn)
                self.actions_row_secondary.addWidget(self.export_btn)
        else:
            self.search_entry.setFixedWidth(240)
            self.copy_selected_btn.setText("Copiar selecionadas")
            if self.export_btn.parent() is not None:
                self.actions_row_secondary.removeWidget(self.export_btn)
                self.actions_row_main.addWidget(self.export_btn)

    def _get_filtered_entries(self, query: str = ""):
        entries = list(reversed(self.history_manager.history))

        if query:
            query_lower = query.lower()
            filtered = []
            for entry in entries:
                original = entry.get("original", "").lower()
                corrected = (entry.get("corrected") or "").lower()
                if query_lower in original or query_lower in corrected:
                    filtered.append(entry)
            entries = filtered

        if self.corrected_only_checkbox.isChecked():
            entries = [e for e in entries if e.get("corrected")]

        if self.date_filter_checkbox.isChecked():
            start_date = self.date_from.date().toPython()
            end_date = self.date_to.date().toPython()
            filtered = []
            for entry in entries:
                try:
                    dt = datetime.fromisoformat(entry.get("timestamp", "")).date()
                    if start_date <= dt <= end_date:
                        filtered.append(entry)
                except Exception:
                    pass
            entries = filtered

        return entries

    def _on_search(self, text: str):
        self.current_page = 1
        self._search_timer.start(250)

    def _apply_search(self):
        self._load_history(self.search_entry.text())

    def _on_filter_changed(self):
        self.current_page = 1
        self._load_history(self.search_entry.text())

    def _load_more(self):
        # Incremental append to avoid UI "blink" and keep scroll position stable.
        self.current_page += 1
        self._append_more()

    def _append_more(self):
        query = self.search_entry.text()
        entries = self._get_filtered_entries(query)
        total_entries = len(entries)
        already_visible = len(self._entry_cards)
        if already_visible >= total_entries:
            self.load_more_btn.setVisible(False)
            return

        # Button feedback
        self.load_more_btn.setEnabled(False)
        old_text = self.load_more_btn.text()
        self.load_more_btn.setText("Carregando...")

        start = already_visible
        end = min(already_visible + self.page_size, total_entries)

        new_widgets = []
        insert_at = max(0, self.list_layout.count() - 1)  # before stretch
        for i in range(start, end):
            widget = HistoryEntryCard(entries[i], self._copy_text)
            self._entry_cards.append(widget)
            self.list_layout.insertWidget(insert_at + len(new_widgets), widget)
            new_widgets.append(widget)

        self.count_label.setText(f"{end} de {total_entries} transcrições")
        self.load_more_btn.setVisible(end < total_entries)

        # Animate new items so the user can "feel" the load
        self._animate_loaded_items(new_widgets)

        # Restore button state
        def _restore():
            self.load_more_btn.setEnabled(True)
            self.load_more_btn.setText(old_text)

        QTimer.singleShot(450, _restore)

    def _animate_loaded_items(self, widgets):
        # Keep animations alive
        if not hasattr(self, "_load_more_anims"):
            self._load_more_anims = []
        self._load_more_anims = []

        # Animate only first few to stay lightweight
        widgets = widgets[:8]
        for w in widgets:
            eff = QGraphicsOpacityEffect(w)
            eff.setOpacity(0.0)
            w.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b"opacity", self)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setDuration(220)
            anim.setEasingCurve(QEasingCurve.OutCubic)

            def _cleanup(effect=eff, widget=w):
                # remove effect after animation (keeps text crisp and avoids extra paint cost)
                if widget.graphicsEffect() is effect:
                    widget.setGraphicsEffect(None)

            anim.finished.connect(_cleanup)
            self._load_more_anims.append(anim)
            anim.start()

    def _toggle_filters(self):
        is_open = self.toggle_filters_btn.isChecked()
        self.filters_panel.setVisible(is_open)

    def _reset_filters(self):
        self.search_entry.setText("")
        self.date_filter_checkbox.setChecked(False)
        self.corrected_only_checkbox.setChecked(False)
        today = QDate.currentDate()
        self.date_from.setDate(today.addDays(-7))
        self.date_to.setDate(today)
        self.current_page = 1
        self._load_history("")

    def _update_filter_chips(self):
        while self.chips_layout.count():
            item = self.chips_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        query = self.search_entry.text().strip()
        if query:
            chip = QLabel(f"Busca: {query}")
            chip.setObjectName("historyChip")
            self.chips_layout.addWidget(chip)

        if self.corrected_only_checkbox.isChecked():
            chip = QLabel("Corrigidos")
            chip.setObjectName("historyChip")
            self.chips_layout.addWidget(chip)

        if self.date_filter_checkbox.isChecked():
            chip = QLabel(
                f"{self.date_from.date().toString('dd/MM')} - {self.date_to.date().toString('dd/MM')}"
            )
            chip.setObjectName("historyChip")
            self.chips_layout.addWidget(chip)

        self.chips_layout.addStretch()

    def _copy_selected(self):
        selected = [c.get_text() for c in self._entry_cards if c.is_selected()]
        if not selected:
            self.message_label.setText("Selecione pelo menos uma transcrição.")
            self.message_label.show()
            QTimer.singleShot(1200, self.message_label.hide)
            return
        self.clipboard.copy_to_clipboard("\n\n".join(selected))
        self.message_label.setText("Copiadas!")
        self.message_label.show()
        QTimer.singleShot(1200, self.message_label.hide)

    def _go_to_record(self):
        window = self.window()
        if hasattr(window, "switch_page"):
            window.switch_page("home")

    def _export_history(self):
        entries = self.history_manager.get_all(limit=1000)
        if not entries:
            QMessageBox.information(self, "Exportar", "Nenhuma transcrição para exportar.")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Histórico",
            f"transcricoes_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            "Text files (*.txt);;All files (*.*)"
        )
        if not file_path:
            return

        lines = []
        lines.append("=" * 60)
        lines.append("  FALAI - Histórico de Transcrições")
        lines.append(f"  Exportado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        lines.append(f"  Total: {len(entries)} transcrições")
        lines.append("=" * 60)
        lines.append("")

        for entry in entries:
            try:
                dt = datetime.fromisoformat(entry["timestamp"])
                date_str = dt.strftime("%d/%m/%Y às %H:%M")
            except Exception:
                date_str = entry.get("timestamp", "Data desconhecida")

            duration = entry.get("duration_seconds", 0)
            text = entry.get("corrected") or entry.get("original", "")

            lines.append("-" * 60)
            lines.append(f"{date_str}  |  {duration:.1f}s")
            lines.append("-" * 60)
            lines.append(text)
            lines.append("")

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\\n".join(lines))
            self.message_label.setText("Exportado com sucesso!")
            self.message_label.show()
            QTimer.singleShot(1500, self.message_label.hide)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao exportar: {e}")

    def _clear_history(self):
        text, ok = QInputDialog.getText(self, "Confirmar Exclusão", "Digite 'LIMPAR' para confirmar:")
        if ok and text.upper() == "LIMPAR":
            if hasattr(self.history_manager, "clear"):
                self.history_manager.clear()
            self.current_page = 1
            self._load_history()
            self.message_label.setText("Histórico limpo!")
            self.message_label.show()
            QTimer.singleShot(1500, self.message_label.hide)

    def _copy_text(self, text: str, show_message: bool = True):
        self.clipboard.copy_to_clipboard(text)
        if show_message:
            self.message_label.setText("Copiado!")
            self.message_label.show()
            QTimer.singleShot(1200, self.message_label.hide)


class StatsPage(QWidget):
    """Pagina de estatisticas (interna)"""

    def __init__(self, history_manager, theme: str = "dark", parent=None):
        super().__init__(parent)
        self.history_manager = history_manager
        self.theme = theme
        self.colors = get_colors(theme)
        self.stats = self._calculate_stats()
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._apply_resize)
        self._create_ui()

    def _calculate_stats(self) -> Dict[str, Any]:
        history = self.history_manager.history

        if not history:
            return {
                "total_words": 0,
                "total_time": 0,
                "avg_wpm": 0,
                "time_saved_minutes": 0,
                "total_transcriptions": 0,
                "daily_usage": {},
                "last_7_days_dates": [],
                "prev_7_days_dates": [],
                "week_total": 0,
                "prev_week_total": 0,
                "week_change_pct": None,
            }

        total_words = 0
        total_time_seconds = 0
        total_transcriptions = len(history)

        daily_usage = defaultdict(int)
        today = datetime.now().date()
        last_7_days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
        prev_7_days = [(today - timedelta(days=i)).isoformat() for i in range(13, 6, -1)]

        for entry in history:
            text = entry.get("corrected") or entry.get("original", "")
            if not text:
                continue

            words = len(text.split())
            total_words += words
            duration = entry.get("duration_seconds", 0)
            total_time_seconds += duration

            try:
                timestamp = entry.get("timestamp")
                if timestamp:
                    date_str = datetime.fromisoformat(timestamp).date().isoformat()
                    daily_usage[date_str] += words
            except Exception:
                pass

        avg_wpm = int((total_words / total_time_seconds) * 60) if total_time_seconds > 0 else 0

        typing_time_minutes = total_words / 40 if total_words > 0 else 0
        speaking_time_minutes = total_time_seconds / 60
        time_saved_minutes = max(0, typing_time_minutes - speaking_time_minutes)

        week_total = sum(daily_usage.get(d, 0) for d in last_7_days)
        prev_week_total = sum(daily_usage.get(d, 0) for d in prev_7_days)
        if prev_week_total > 0:
            week_change_pct = ((week_total - prev_week_total) / prev_week_total) * 100
        else:
            week_change_pct = None if week_total == 0 else 100.0

        return {
            "total_words": total_words,
            "total_time": total_time_seconds,
            "avg_wpm": avg_wpm,
            "time_saved_minutes": time_saved_minutes,
            "total_transcriptions": total_transcriptions,
            "daily_usage": daily_usage,
            "last_7_days_dates": last_7_days,
            "prev_7_days_dates": prev_7_days,
            "week_total": week_total,
            "prev_week_total": prev_week_total,
            "week_change_pct": week_change_pct,
        }

    def _create_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        scroll.setWidget(content)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(24, 22, 24, 22)
        main_layout.setSpacing(16)

        root.addWidget(scroll)
        self._scroll = scroll
        self._scroll_content = content

        title = QLabel("Estatísticas")
        title.setObjectName("pageTitle")
        main_layout.addWidget(title)

        subtitle = QLabel("Visão geral do seu desempenho")
        subtitle.setObjectName("statsMeta")
        main_layout.addWidget(subtitle)

        main_layout.addSpacing(8)

        if self.stats.get("total_transcriptions", 0) == 0:
            empty = QLabel("Sem estatísticas ainda")
            empty.setObjectName("mutedLabel")
            empty.setAlignment(Qt.AlignCenter)
            main_layout.addStretch()
            main_layout.addWidget(empty)
            main_layout.addStretch()
            return

        accent = self.colors.get("accent", "#10B981")
        kpi_items = [
            KPIItem(
                "Total de Palavras",
                f"{self.stats['total_words']:,}".replace(",", "."),
                "Soma total das transcrições",
                "Soma de todas as palavras transcritas.",
                icon="📝",
                accent_color=accent,
            ),
            KPIItem(
                "Transcrições",
                f"{self.stats['total_transcriptions']}",
                "Quantidade total de registros",
                "Quantidade total de registros.",
                icon="🎙️",
                accent_color="#6366F1",
            ),
            KPIItem(
                "Tempo Economizado",
                self._format_time_saved(),
                "Tempo digitando − tempo falando",
                "Tempo economizado = tempo digitando − tempo falando.",
                icon="⏱️",
                accent_color="#F59E0B",
            ),
            KPIItem(
                "Velocidade Média",
                f"{self.stats['avg_wpm']} WPM",
                "Palavras por minuto",
                "WPM = palavras ÷ tempo falando (min).",
                icon="⚡",
                accent_color="#EC4899",
            ),
        ]

        self.kpi_band = KPIBand(kpi_items)
        self.kpi_band.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        main_layout.addWidget(self.kpi_band)
        self._arrange_kpis()

        main_layout.addSpacing(8)

        # --- Chart card container ---
        chart_card = QFrame()
        chart_card.setObjectName("statCard")
        chart_card_layout = QVBoxLayout(chart_card)
        chart_card_layout.setContentsMargins(20, 18, 20, 18)
        chart_card_layout.setSpacing(12)

        graph_header = QHBoxLayout()
        chart_title = QLabel("Últimos 7 dias")
        chart_title.setObjectName("statTitle")
        chart_title.setFont(QFont("Manrope", 13, QFont.Bold))
        graph_header.addWidget(chart_title)
        graph_header.addStretch()

        week_total = self.stats.get("week_total", 0)
        week_label = QLabel(f"Esta semana: {week_total:,} palavras".replace(",", "."))
        week_label.setObjectName("statsMeta")
        graph_header.addWidget(week_label)

        chart_card_layout.addLayout(graph_header)

        self.chart_widget = BarChartWidget(self.stats["last_7_days_dates"], self.stats["daily_usage"], self.colors)
        self.chart_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        chart_card_layout.addWidget(self.chart_widget)

        # Week-over-week comparison badge
        week_change_pct = self.stats.get("week_change_pct")
        change_row = QHBoxLayout()
        change_row.addStretch()
        if week_change_pct is None:
            change_text = "Sem dados da semana anterior"
            change_color = self.colors.get("foreground_dim", "#6B6B7B")
        elif week_change_pct >= 0:
            change_text = f"↑ {abs(week_change_pct):.0f}% vs semana anterior"
            change_color = self.colors.get("accent", "#10B981")
        else:
            change_text = f"↓ {abs(week_change_pct):.0f}% vs semana anterior"
            change_color = self.colors.get("danger", "#DC2626")

        change_label = QLabel(change_text)
        change_label.setStyleSheet(
            f"QLabel {{ color: {change_color}; font-size: 12px; font-weight: 600;"
            f" background-color: {change_color}18; border-radius: 10px;"
            f" padding: 4px 12px; }}"
        )
        change_row.addWidget(change_label)
        change_row.addStretch()
        chart_card_layout.addLayout(change_row)

        main_layout.addWidget(chart_card)

        footer = QLabel("WPM = palavras por minuto")
        footer.setObjectName("statsMeta")
        footer.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(footer)

    def _format_time_saved(self) -> str:
        time_saved = self.stats["time_saved_minutes"]
        if time_saved >= 60:
            hours = int(time_saved // 60)
            mins = int(time_saved % 60)
            return f"{hours}h {mins}min"
        return f"{int(time_saved)} min"

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start(120)

    def _apply_resize(self):
        self._sync_scroll_width()
        self._arrange_kpis()

    def _sync_scroll_width(self):
        if hasattr(self, "_scroll") and hasattr(self, "_scroll_content"):
            viewport_width = self._scroll.viewport().width()
            if viewport_width > 0:
                self._scroll_content.setMinimumWidth(viewport_width)

    def _arrange_kpis(self):
        if not hasattr(self, "kpi_band"):
            return
        available_width = self.kpi_band.width() or self.width()
        if available_width >= 900:
            columns = 4
        elif available_width >= 500:
            columns = 2
        else:
            columns = 1
        self.kpi_band.setUpdatesEnabled(False)
        self.kpi_band.arrange(columns)
        self.kpi_band.setUpdatesEnabled(True)

    def set_theme(self, theme: str):
        self.theme = theme
        self.colors = get_colors(theme)
        if hasattr(self, "chart_widget"):
            self.chart_widget.set_colors(self.colors)
        self.update()


class BarChartWidget(QWidget):
    """Simple bar chart widget"""

    def __init__(self, dates: list, daily_usage: dict, colors: dict, parent=None):
        super().__init__(parent)
        self.dates = dates
        self.data = [daily_usage.get(d, 0) for d in dates]
        self.max_val = max(self.data) if self.data and max(self.data) > 0 else 1
        self.colors = colors
        self.setFixedHeight(260)
        self._create_ui()

    def _create_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        today = datetime.now().date().isoformat()

        for i, val in enumerate(self.data):
            is_today = self.dates[i] == today

            col_widget = QWidget()
            if is_today:
                col_widget.setObjectName("chartColumnToday")
            else:
                col_widget.setObjectName("chartColumn")
            col_layout = QVBoxLayout(col_widget)
            col_layout.setContentsMargins(0, 0, 0, 0)
            col_layout.setSpacing(6)

            val_label = QLabel(str(val) if val > 0 else "")
            val_label.setFont(QFont("Manrope", 10, QFont.Bold if is_today else QFont.Normal))
            val_label.setObjectName("chartValueLabel")
            val_label.setAlignment(Qt.AlignCenter)
            col_layout.addWidget(val_label)

            bar_container = QWidget()
            bar_container.setMinimumHeight(100)
            col_layout.addWidget(bar_container, 1)

            bar = BarWidget(val, self.max_val, is_today, self.colors, bar_container)
            bar.setParent(bar_container)

            date_label = QLabel(self._format_date(self.dates[i], is_today))
            date_label.setFont(QFont("Manrope", 10, QFont.Bold if is_today else QFont.Normal))
            date_label.setObjectName("chartDateLabel")
            date_label.setAlignment(Qt.AlignCenter)
            col_layout.addWidget(date_label)

            layout.addWidget(col_widget)

    def set_colors(self, colors: dict):
        self.colors = colors
        for bar in self.findChildren(BarWidget):
            bar.set_colors(colors)
        self.update()

    def _format_date(self, date_iso: str, is_today: bool) -> str:
        if is_today:
            return "Hoje"
        try:
            dt = datetime.fromisoformat(date_iso)
            days = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
            return days[dt.weekday()]
        except Exception:
            return date_iso[:5]


class BarWidget(QWidget):
    """Barra individual do grafico"""

    def __init__(self, value: int, max_value: int, is_today: bool, colors: dict, parent=None):
        super().__init__(parent)
        self.value = value
        self.max_value = max_value
        self.is_today = is_today
        self.colors = colors
        self.setMinimumWidth(35)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        parent_height = self.parent().height() if self.parent() else 100
        parent_width = self.parent().width() if self.parent() else 35

        height_pct = self.value / self.max_value if self.max_value > 0 else 0
        if height_pct < 0.08:
            height_pct = 0.08

        bar_height = int(parent_height * height_pct)
        bar_width = min(35, parent_width - 6)

        x = (parent_width - bar_width) // 2
        y = parent_height - bar_height
        self.setGeometry(x, y, bar_width, bar_height)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.value > 0:
            color = QColor(self.colors["accent"])
            if not self.is_today:
                color.setAlpha(180)
        else:
            color = QColor(self.colors["border"])
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 6, 6)

    def set_colors(self, colors: dict):
        self.colors = colors
        self.update()
