"""
Componentes reutilizaveis de UI (premium)
"""
import math
import random
from typing import Optional, List, Tuple

from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QCheckBox,
    QButtonGroup,
    QGridLayout,
)
from PySide6.QtCore import Qt, QSize, Signal, QTimer, QEvent
from PySide6.QtWidgets import QSizePolicy
from PySide6.QtGui import QPainter, QColor, QCursor, QPainterPath, QLinearGradient, QBrush, QPen
from PySide6.QtWidgets import QToolTip


class Card(QFrame):
    """Card premium com layout vertical"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 18, 20, 18)
        self.layout.setSpacing(10)


class SectionHeader(QLabel):
    """Titulo de secao padronizado"""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("sectionHeader")


class StatusPill(QWidget):
    """Pill de status premium"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusPill")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        self.dot = QFrame()
        self.dot.setFixedSize(10, 10)
        self.dot.setObjectName("statusDot")
        layout.addWidget(self.dot)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.primary = QLabel("Pronto")
        self.primary.setObjectName("statusPrimary")
        self.secondary = QLabel("Aguardando áudio")
        self.secondary.setObjectName("statusSecondary")
        text_col.addWidget(self.primary)
        text_col.addWidget(self.secondary)

        layout.addLayout(text_col)
        layout.addStretch()

    def set_status(self, primary: str, secondary: str, color: str):
        self.primary.setText(primary)
        self.secondary.setText(secondary)
        self.dot.setStyleSheet(f"background-color:{color}; border-radius:5px;")


class WaveformWidget(QWidget):
    """Audio waveform visualization widget - animated bars"""

    def __init__(
        self,
        parent=None,
        num_bars: int = 7,
        min_size: Tuple[int, int] = (50, 20),
        max_size: Tuple[int, int] = (60, 24),
        bar_width: int = 4,
        bar_spacing: int = 3,
        min_bar_height: int = 3,
        expand_width: bool = False,
        fixed_height: Optional[int] = None,
        fill_width: bool = False,
        style: str = "random",
        corner_radius: Optional[int] = None,
    ):
        super().__init__(parent)

        self.num_bars = num_bars
        self.bar_heights = [0.3] * self.num_bars  # Normalized heights (0-1)
        self.target_heights = [0.3] * self.num_bars
        self.bar_color = QColor("#10B981")
        self.is_animating = False
        self.current_level = 0.0
        self._bar_width = bar_width
        self._bar_spacing = bar_spacing
        self._min_bar_height = min_bar_height
        self._expand_width = expand_width
        self._fill_width = fill_width
        self._style = style
        self._corner_radius = corner_radius
        self._phase = 0.0
        self._phase_step = 0.35

        # Animation timer
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._animate)

        if self._expand_width:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if fixed_height is not None:
            self.setFixedHeight(fixed_height)
        else:
            self.setMinimumSize(*min_size)
            self.setMaximumSize(*max_size)

    def start_animation(self):
        """Start waveform animation"""
        self.is_animating = True
        self._animation_timer.start(33)  # ~30 FPS

    def stop_animation(self):
        """Stop waveform animation"""
        self.is_animating = False
        self._animation_timer.stop()
        # Reset to flat line
        self.bar_heights = [0.2] * self.num_bars
        self.update()

    def set_color(self, color: str):
        """Set bar color"""
        self.bar_color = QColor(color)
        self.update()

    def set_level(self, level: float):
        """Atualiza o nivel de audio (0-1) para influenciar o waveform"""
        try:
            self.current_level = max(0.0, min(1.0, float(level)))
        except Exception:
            self.current_level = 0.0

    def _animate(self):
        """Animate the waveform bars with staggered sine ripple.

        Creates a Spotify-style bouncing-bars effect: each bar follows the same
        sine wave but offset in phase so the motion ripples left-to-right.
        A tiny random jitter keeps it organic.
        """
        if not self.is_animating:
            return

        # amplitude scales from nearly flat (0.08) to full (1.0) based on audio level
        # This creates a dramatic difference: silence = tiny nubs, speaking = big waves
        amplitude = 0.08 + (self.current_level * 0.92)

        if self._style == "sine":
            self._phase += self._phase_step
            base = 0.05  # minimum bar height (barely visible at rest)
            # Stagger: ~0.4 radians between bars creates a wave that ripples
            # across the full width smoothly
            stagger = 0.4
            for i in range(self.num_bars):
                wave = math.sin(self._phase + i * stagger)
                target = base + amplitude * (0.5 + 0.5 * wave)
                target += random.uniform(-0.03, 0.03)  # subtle organic jitter
                self.target_heights[i] = max(0.08, min(1.0, target))
        else:
            for i in range(self.num_bars):
                self.target_heights[i] = random.uniform(0.15, amplitude)

        # Fast interpolation (0.6 = snappy reaction to voice)
        for i in range(self.num_bars):
            diff = self.target_heights[i] - self.bar_heights[i]
            self.bar_heights[i] += diff * 0.6

        self.update()

    def paintEvent(self, event):
        """Paint waveform as Spotify-style bouncing bars (optimized for micro-size).

        Design: 5 wide bars with rounded caps, generous spacing, staggered sine
        animation. Looks premium at 120x28px — each bar is clearly distinct and
        the ripple motion unmistakably communicates 'audio'.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        if w < 4 or h < 4:
            return

        mid_y = h / 2.0
        n = len(self.bar_heights)
        if n < 1:
            return

        # --- Bar geometry (adapts to widget width) ---
        num_bars = n  # Use all configured bars to fill the width

        # Scale to fill entire width evenly
        margin_x = max(2.0, w * 0.04)
        avail = w - margin_x * 2
        # Each bar = 2px wide, gap fills the rest
        bar_w = 2.0
        gap = max(1.0, (avail - num_bars * bar_w) / max(num_bars - 1, 1))

        total_w = num_bars * bar_w + (num_bars - 1) * gap
        start_x = (w - total_w) / 2.0  # center the bar group

        color = QColor(self.bar_color)

        for i in range(num_bars):
            # Map bar index to data (spread evenly across available data points)
            data_idx = int(i * (n - 1) / max(num_bars - 1, 1))
            height_val = self.bar_heights[data_idx]

            # Amplitude: min 1px (tiny nub), max ~45% of widget height
            min_amp = 1.0
            max_amp = h * 0.45
            amp = min_amp + height_val * (max_amp - min_amp)

            x = start_x + i * (bar_w + gap)
            top = mid_y - amp
            bot = mid_y + amp

            # Alpha: brighter bars at higher amplitude, subtle at low
            alpha = 0.55 + height_val * 0.45
            bar_color_with_alpha = QColor(color)
            bar_color_with_alpha.setAlphaF(min(1.0, alpha))

            # Draw bar as a thick line with round caps — this creates the
            # "rounded cylinder" look without needing a QPainterPath
            pen = QPen(bar_color_with_alpha)
            pen.setWidthF(bar_w)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(
                int(x + bar_w / 2), int(top),
                int(x + bar_w / 2), int(bot),
            )


class StatusBadgeMini(QWidget):
    """Mini badge de status com waveform opcional"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusBadgeMini")
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._show_waveform = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 1, 8, 1)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignVCenter)

        self.waveform = WaveformWidget(
            num_bars=5,
            min_size=(28, 12),
            max_size=(32, 12),
            bar_width=2,
            bar_spacing=2,
            min_bar_height=2,
            )
        self.waveform.setVisible(False)
        layout.addWidget(self.waveform)

        self.label = QLabel("Pronto")
        self.label.setObjectName("statusBadgeText")
        layout.addWidget(self.label)

    def set_status(self, text: str, color: str, show_waveform: bool):
        self.label.setText(text)
        self.waveform.set_color(color)
        self._show_waveform = bool(show_waveform)
        self.waveform.setVisible(self._show_waveform)
        if self._show_waveform:
            self.waveform.start_animation()
        else:
            self.waveform.stop_animation()

    def set_level(self, level: float):
        if self._show_waveform:
            self.waveform.set_level(level)


class HistoryPreviewItem(QWidget):
    """Timeline + card item for recent history preview (Home tab)."""

    def __init__(self, entry: dict, copy_callback=None, parent=None):
        super().__init__(parent)
        self.setObjectName("historyPreviewItem")
        self._copy_callback = copy_callback
        self._expanded = False
        self._full_text = ""
        self._preview_text = ""

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # Left timeline column
        self.left = QWidget()
        self.left.setFixedWidth(84)
        left_layout = QVBoxLayout(self.left)
        left_layout.setContentsMargins(0, 2, 0, 2)
        left_layout.setSpacing(2)

        self.date_label = QLabel("--/--")
        self.date_label.setObjectName("historyPreviewDate")
        self.time_label = QLabel("--:--")
        self.time_label.setObjectName("historyPreviewTime")
        left_layout.addWidget(self.date_label)
        left_layout.addWidget(self.time_label)

        self.dot = QFrame()
        self.dot.setObjectName("historyPreviewDot")
        self.dot.setFixedSize(8, 8)
        left_layout.addWidget(self.dot, 0, Qt.AlignLeft)

        self.guide = QFrame()
        self.guide.setObjectName("historyPreviewGuide")
        self.guide.setFixedWidth(2)
        self.guide.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        left_layout.addWidget(self.guide, 1, Qt.AlignLeft)

        root.addWidget(self.left)

        # Right card
        self.card = QFrame()
        self.card.setObjectName("historyPreviewCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(8)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(6)

        self.duration_badge = QLabel("")
        self.duration_badge.setObjectName("historyPreviewBadge")
        self.duration_badge.setProperty("variant", "duration")
        self.duration_badge.hide()
        meta_row.addWidget(self.duration_badge)

        self.status_badge = QLabel("")
        self.status_badge.setObjectName("historyPreviewBadge")
        self.status_badge.setProperty("variant", "original")
        self.status_badge.hide()
        meta_row.addWidget(self.status_badge)

        meta_row.addStretch()

        self.toast = QLabel("Copiado!")
        self.toast.setObjectName("historyPreviewToast")
        self.toast.hide()
        meta_row.addWidget(self.toast)

        card_layout.addLayout(meta_row)

        self.text_label = QLabel("")
        self.text_label.setObjectName("historyPreviewText")
        self.text_label.setWordWrap(True)
        card_layout.addWidget(self.text_label)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(8)
        actions_row.addStretch()

        self.btn_more = QPushButton("Ver mais")
        self.btn_more.setObjectName("historyPreviewAction")
        self.btn_more.clicked.connect(self.toggle_expand)
        self.btn_more.hide()
        actions_row.addWidget(self.btn_more)

        self.btn_copy = QPushButton("Copiar")
        self.btn_copy.setObjectName("historyPreviewActionPrimary")
        self.btn_copy.clicked.connect(self._on_copy)
        actions_row.addWidget(self.btn_copy)

        card_layout.addLayout(actions_row)

        root.addWidget(self.card, 1)

        self.set_entry(entry)

    def set_entry(self, entry: dict, is_last: bool = False):
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(entry.get("timestamp", ""))
            self.date_label.setText(dt.strftime("%d/%m"))
            self.time_label.setText(dt.strftime("%H:%M"))
        except Exception:
            ts = entry.get("timestamp", "")
            self.date_label.setText(ts[:5] or "--/--")
            self.time_label.setText(ts[11:16] or "--:--")

        duration = float(entry.get("duration_seconds") or 0.0)
        if duration > 0:
            self.duration_badge.setText(f"{duration:.1f}s")
            self.duration_badge.show()
        else:
            self.duration_badge.hide()

        corrected = bool(entry.get("corrected"))
        if corrected:
            self.status_badge.setText("Corrigido")
            self.status_badge.setProperty("variant", "corrected")
            self.status_badge.show()
        else:
            self.status_badge.hide()

        self._full_text = entry.get("corrected") or entry.get("original", "") or ""
        self._preview_text = self._truncate(self._full_text)
        self._expanded = False
        self.text_label.setText(self._preview_text)

        if self._preview_text != self._full_text:
            self.btn_more.show()
        else:
            self.btn_more.hide()

        # Hide guide line for the last item (visual end of timeline)
        self.guide.setVisible(not is_last)

    def _truncate(self, text: str) -> str:
        if len(text) <= 260:
            return text
        return text[:260].rstrip() + "..."

    def toggle_expand(self):
        self._expanded = not self._expanded
        if self._expanded:
            self.text_label.setText(self._full_text)
            self.btn_more.setText("Ver menos")
        else:
            self.text_label.setText(self._preview_text)
            self.btn_more.setText("Ver mais")

    def _on_copy(self):
        if self._copy_callback:
            self._copy_callback(self._full_text)
        self.toast.show()
        QTimer.singleShot(900, self.toast.hide)


class StatCard(QFrame):
    """Stats card with title, value, hint and optional info tooltip."""

    def __init__(self, title: str, value: str, hint: str, info_text: str = "", icon: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("statTitle")
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        top_row.addWidget(self.title_label)

        top_row.addStretch()

        if icon:
            icon_label = QLabel(icon)
            icon_label.setObjectName("statIcon")
            top_row.addWidget(icon_label)

        self.info_badge = QPushButton("ⓘ")
        self.info_badge.setObjectName("statInfoBadge")
        self.info_badge.setCursor(Qt.PointingHandCursor)
        self.info_badge.setFlat(True)
        if info_text:
            self.info_badge.setToolTip(info_text)
            top_row.addWidget(self.info_badge)
        else:
            self.info_badge.setVisible(False)

        layout.addLayout(top_row)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("statValue")
        self.value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.value_label)

        self.subtitle_label = QLabel(hint)
        self.subtitle_label.setObjectName("statSubtitle")
        self.subtitle_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout.addWidget(self.subtitle_label)


class KPIItem(QWidget):
    """Item de KPI para faixa superior de estatisticas."""

    def __init__(self, title: str, value: str, subtext: str, info_text: str = "", icon: str = "", accent_color: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("kpiItem")
        self.setProperty("divider", False)
        self._info_text = info_text

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("statsKpiCard")
        if accent_color:
            card.setStyleSheet(
                f"QFrame#statsKpiCard {{ border-left: 3px solid {accent_color}; }}"
            )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)

        if icon:
            icon_label = QLabel(icon)
            icon_label.setObjectName("statIcon")
            top.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setObjectName("kpiTitle")
        top.addWidget(title_label)
        top.addStretch()

        info_badge = QPushButton("ⓘ")
        info_badge.setObjectName("kpiInfoBadge")
        info_badge.setCursor(Qt.PointingHandCursor)
        info_badge.setFlat(True)
        info_badge.setFixedSize(16, 16)
        info_badge.setFocusPolicy(Qt.NoFocus)
        info_badge.setAttribute(Qt.WA_AlwaysShowToolTips, True)
        info_badge.setToolTipDuration(4000)
        if info_text:
            info_badge.setToolTip(info_text)
            info_badge.installEventFilter(self)
            info_badge.clicked.connect(self._show_tooltip)
        else:
            info_badge.setVisible(False)
        top.addWidget(info_badge)
        self._info_badge = info_badge

        layout.addLayout(top)

        value_label = QLabel(value)
        value_label.setObjectName("kpiValue")
        layout.addWidget(value_label)

        sub_label = QLabel(subtext)
        sub_label.setObjectName("kpiSubtext")
        layout.addWidget(sub_label)

        outer.addWidget(card)

    def _show_tooltip(self):
        if self._info_text:
            QToolTip.showText(QCursor.pos(), self._info_text, self._info_badge)

    def eventFilter(self, obj, event):
        if obj is getattr(self, "_info_badge", None) and self._info_text:
            if event.type() == QEvent.Enter:
                QToolTip.showText(QCursor.pos(), self._info_text, self._info_badge)
            elif event.type() == QEvent.Leave:
                QToolTip.hideText()
        return super().eventFilter(obj, event)


class KPIBand(QWidget):
    """Faixa de KPIs responsiva."""

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.setObjectName("kpiBand")
        self._items = items

        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(14)
        self._layout.setVerticalSpacing(14)

        for item in self._items:
            item.setParent(self)

        self.arrange(4)

    def arrange(self, columns: int):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        columns = max(1, columns)
        for col_idx in range(columns):
            self._layout.setColumnStretch(col_idx, 1)

        row = 0
        col = 0
        for item in self._items:
            item.setProperty("divider", col != 0)
            item.style().unpolish(item)
            item.style().polish(item)
            self._layout.addWidget(item, row, col)
            col += 1
            if col >= columns:
                col = 0
                row += 1

class IconNavButton(QPushButton):
    """Botao de navegacao premium"""

    def __init__(self, text: str, icon=None, parent=None, checkable: bool = True):
        super().__init__(text, parent)
        self.setObjectName("navButton")
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        if icon:
            self.setIcon(icon)
            self.setIconSize(QSize(18, 18))
        self.setMinimumHeight(40)
        self.setMinimumWidth(180)


class ToggleSwitch(QCheckBox):
    """Toggle premium para Settings"""

    def __init__(self, checked: bool = False, colors: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("switch")
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 22)
        self.setText("")
        self._colors = colors or {
            "accent": "#10B981",
            "switch_off": "#3A3A48",
            "border": "#2A2A35",
            "background_light": "#ffffff",
        }

    def set_colors(self, colors: dict):
        self._colors = colors
        self.update()

    def paintEvent(self, event):
        radius = self.height() / 2
        track_rect = self.rect().adjusted(1, 1, -1, -1)
        knob_size = self.height() - 6
        knob_y = (self.height() - knob_size) / 2
        knob_x = self.width() - knob_size - 3 if self.isChecked() else 3

        track_color = self._colors["accent"] if self.isChecked() else self._colors["switch_off"]
        border_color = self._colors.get("border", track_color)
        knob_color = "#ffffff"

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(border_color))
        painter.setBrush(QColor(track_color))
        painter.drawRoundedRect(track_rect, radius, radius)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(knob_color))
        painter.drawEllipse(int(knob_x), int(knob_y), int(knob_size), int(knob_size))


class SettingRow(QWidget):
    """Linha de configuracao com titulo, subtitulo e toggle"""

    def __init__(self, title: str, subtitle: str, checked: bool = False, parent=None, last: bool = False, colors: Optional[dict] = None):
        super().__init__(parent)
        self.setObjectName("settingRow")
        self.setProperty("last", last)
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(3)

        title_label = QLabel(title)
        title_label.setObjectName("settingTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("mutedLabel")

        text_col.addWidget(title_label)
        text_col.addWidget(subtitle_label)

        layout.addLayout(text_col, 1)

        self.toggle = ToggleSwitch(checked, colors=colors)
        self.toggle.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.toggle)
        layout.setAlignment(self.toggle, Qt.AlignVCenter)

    def is_checked(self) -> bool:
        return self.toggle.isChecked()

    def set_colors(self, colors: dict):
        self.toggle.set_colors(colors)


class SegmentedControl(QWidget):
    """Segmented buttons (Neutro/Casual/Formal)"""

    valueChanged = Signal(str)

    def __init__(self, options: List[Tuple[str, str]], value: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("segmentGroup")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)

        count = len(options)
        for index, (label, option_value) in enumerate(options):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setObjectName("segmentButton")
            btn.setProperty("value", option_value)
            if index == 0:
                btn.setProperty("segment", "left")
            elif index == count - 1:
                btn.setProperty("segment", "right")
            else:
                btn.setProperty("segment", "middle")
            if value == option_value:
                btn.setChecked(True)
            self.group.addButton(btn)
            layout.addWidget(btn)

        self.group.buttonClicked.connect(self._emit_value)

    def _emit_value(self, _button=None):
        button = self.group.checkedButton()
        if button:
            self.valueChanged.emit(button.property("value"))

    def set_value(self, value: str):
        for button in self.group.buttons():
            if button.property("value") == value:
                button.setChecked(True)
                return

    def value(self) -> Optional[str]:
        button = self.group.checkedButton()
        return button.property("value") if button else None
