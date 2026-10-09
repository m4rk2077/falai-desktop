"""
Floating Bar UI for FALAI
Minimalist pill-shaped overlay with audio waveform visualization
PySide6/Qt implementation - Premium UI/UX
"""
from typing import Optional, List

from PySide6.QtWidgets import QWidget, QHBoxLayout, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QTimer, Signal, QRect, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QScreen, QColor, QPainter, QPen, QLinearGradient, QBrush

from src.utils.logger import get_logger

logger = get_logger(__name__)

from src.ui.theme import COLORS
from src.ui.components import WaveformWidget


class FloatingPill(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._border_color = QColor(COLORS["success"])
        self._bg_start = QColor(15, 15, 20, 245)
        self._bg_end = QColor(22, 22, 30, 238)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def set_border_color(self, color: str):
        self._border_color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0.5, 0.5, -0.5, -0.5)
        radius = rect.height() / 2
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, self._bg_start)
        gradient.setColorAt(1, self._bg_end)
        painter.setBrush(QBrush(gradient))
        painter.setPen(QPen(self._border_color, 1.0))
        painter.drawRoundedRect(rect, radius, radius)


class FloatingBar(QWidget):
    """
    A minimalist floating bar that appears during voice recording.
    Premium design: small, positioned at bottom right, with waveform visualization.
    Size: 200x40px
    """

    # States
    STATE_HIDDEN = "hidden"
    STATE_IDLE = "idle"
    STATE_RECORDING = "recording"
    STATE_PROCESSING = "processing"
    STATE_SUCCESS = "success"
    STATE_ERROR = "error"

    # Signals
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.state = self.STATE_HIDDEN
        self._is_hiding = False
        self._hovered = False
        self._expanded = False
        self._current_color = COLORS['recording']
        self._collapsed_size = (44, 6)
        self._expanded_size = (72, 16)
        # availableGeometry() already excludes the taskbar on Windows, so keep this low.
        # This is the extra gap from the bottom edge (in px).
        self._margin_bottom = 18
        self._size_anim = QPropertyAnimation(self, b"geometry", self)
        self._size_anim.setDuration(120)
        self._size_anim.setEasingCurve(QEasingCurve.OutQuart)

        # Configure window
        self._configure_window()

        # Create UI
        self._create_ui()

        # Fade animation (200ms)
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.0)
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(140)

        # Start hidden
        self.hide()

    def _configure_window(self):
        """Configure window properties for floating overlay"""
        # Remove window decorations (title bar, borders) and always on top
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool  # Don't show in taskbar
        )

        # Enable transparency
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        # Size - reduced (collapsed by default)
        self.setMinimumSize(*self._collapsed_size)
        self.setMaximumSize(*self._expanded_size)
        self.resize(*self._collapsed_size)

        # Position - bottom center
        self._position_bottom_right()

    def _position_bottom_right(self):
        """Position the bar at the bottom center of the screen"""
        screen = QScreen.availableGeometry(self.screen())

        # Offset from edges
        margin_bottom = self._margin_bottom

        x = (screen.width() - self.width()) // 2
        y = screen.height() - self.height() - margin_bottom

        self.move(x, y)

    def _create_ui(self):
        """Create the floating bar UI elements"""
        # Main layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Main container (the pill shape)
        self.container = FloatingPill()
        self.container.setObjectName("floatingBar")
        self._update_container_style(COLORS['recording'])

        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(3, 1, 3, 1)
        container_layout.setSpacing(2)

        # Waveform visualization — fills entire pill width
        self.waveform = WaveformWidget(
            num_bars=16,
            bar_width=2,
            bar_spacing=1,
            min_bar_height=2,
            expand_width=True,
            fixed_height=10,
            fill_width=True,
            style="sine",
        )
        container_layout.addWidget(self.waveform, 1)
        self.waveform.setVisible(False)

        layout.addWidget(self.container)

    def _update_container_style(self, border_color: str):
        """Update the container style with border color and premium gradient"""
        if hasattr(self.container, "set_border_color"):
            self.container.set_border_color(border_color)

    def _muted_border(self, color: str, alpha: float = 0.7) -> str:
        qcolor = QColor(color)
        qcolor.setAlphaF(max(0.0, min(1.0, alpha)))
        return f"rgba({qcolor.red()}, {qcolor.green()}, {qcolor.blue()}, {qcolor.alpha()})"

    def _target_geometry(self, width: int, height: int) -> QRect:
        screen = QScreen.availableGeometry(self.screen())
        margin_bottom = self._margin_bottom
        x = (screen.width() - width) // 2
        y = screen.height() - height - margin_bottom
        return QRect(x, y, width, height)

    def _apply_size(self, width: int, height: int):
        self.resize(width, height)
        self._position_bottom_right()
        self._update_container_style(self._current_color)

    def _animate_to_size(self, width: int, height: int):
        target = self._target_geometry(width, height)
        self._size_anim.stop()
        self._size_anim.setStartValue(self.geometry())
        self._size_anim.setEndValue(target)
        self._size_anim.start()
        self._update_container_style(self._current_color)

    def _update_expanded_state(self):
        should_expand = self._hovered or self.state in {
            self.STATE_RECORDING,
            self.STATE_PROCESSING,
            self.STATE_ERROR,
        }
        if should_expand == self._expanded:
            return
        self._expanded = should_expand
        if self._expanded:
            self._animate_to_size(*self._expanded_size)
            self.waveform.setVisible(self.state in {self.STATE_RECORDING, self.STATE_PROCESSING} or self._hovered)
        else:
            self.waveform.setVisible(False)
            self._animate_to_size(*self._collapsed_size)

    def _show_with_fade(self):
        """Mostra com fade in"""
        self._is_hiding = False
        if not self.isVisible():
            self._position_bottom_right()
            super().show()
        self.raise_()
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def _hide_with_fade(self):
        """Esconde com fade out"""
        if self._is_hiding:
            return
        self._is_hiding = True
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(0.0)

        def _finalize_hide():
            if not self._is_hiding:
                return
            self._is_hiding = False
            super(FloatingBar, self).hide()
            self.closed.emit()

        try:
            self._fade_anim.finished.disconnect()
        except Exception:
            pass
        self._fade_anim.finished.connect(_finalize_hide)
        self._fade_anim.start()

    def set_audio_level(self, level: float):
        """Atualiza o nivel do waveform"""
        boosted = max(0.0, min(1.0, level * 5.0))
        self.waveform.set_level(boosted)

    def show_recording(self):
        """Show the bar in recording state"""
        self.state = self.STATE_RECORDING

        # Update visuals
        self._current_color = COLORS['recording']
        self.waveform.set_color(self._current_color)
        self.waveform.start_animation()
        self.waveform.setVisible(True)
        self._update_container_style(self._current_color)
        self._update_expanded_state()

        # Position and show window
        self._show_with_fade()

        logger.info("Floating bar: Recording")

    def show_processing(self):
        """Show the bar in processing state with gentle pulse animation"""
        self.state = self.STATE_PROCESSING

        self._current_color = COLORS['processing']
        self.waveform.set_color(self._current_color)
        # Keep waveform animating with low level for subtle pulse effect
        self.waveform.set_level(0.15)
        self.waveform.start_animation()
        self.waveform.setVisible(True)

        # Update visuals
        self._update_container_style(self._current_color)
        self._update_expanded_state()
        self._show_with_fade()

        logger.info("Floating bar: Processing")

    def show_success(self, auto_hide_ms: int = 900):
        """Show success state and auto-hide"""
        self.state = self.STATE_SUCCESS

        # Stop waveform animation
        self.waveform.stop_animation()
        self._current_color = COLORS['success']
        self.waveform.set_color(self._current_color)

        # Update visuals
        self._update_container_style(self._current_color)
        self._update_expanded_state()
        self._show_with_fade()

        logger.info("Floating bar: Success")

        # Auto-hide after delay
        if auto_hide_ms > 0:
            QTimer.singleShot(auto_hide_ms, self.hide)

    def show_idle(self):
        """Show idle state (persistent)"""
        self.state = self.STATE_IDLE
        self.waveform.stop_animation()
        self._current_color = self._muted_border(COLORS['success'])
        self.waveform.set_color(COLORS['success'])
        self.waveform.setVisible(False)
        self._update_container_style(self._current_color)
        self._update_expanded_state()
        self._show_with_fade()
        logger.info("Floating bar: Idle")

    def show_error(self, message: str = "Erro", auto_hide_ms: int = 2000):
        """Show error state"""
        self.state = self.STATE_ERROR

        # Stop waveform animation
        self.waveform.stop_animation()
        self._current_color = COLORS['error']
        self.waveform.set_color(self._current_color)

        # Show window if hidden
        self._show_with_fade()
        self._update_container_style(self._current_color)
        self._update_expanded_state()

        logger.warning("Floating bar: Error - %s", message)

        # Auto-hide after delay
        if auto_hide_ms > 0:
            QTimer.singleShot(auto_hide_ms, self.hide)

    def hide(self):
        """Hide the floating bar"""
        self.waveform.stop_animation()
        self.state = self.STATE_HIDDEN
        self._hide_with_fade()
        logger.info("Floating bar: Hidden")

    def enterEvent(self, event):
        self._hovered = True
        self._update_expanded_state()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._update_expanded_state()
        super().leaveEvent(event)


# Test the floating bar standalone
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    bar = FloatingBar()

    def test_sequence():
        bar.show_recording()
        QTimer.singleShot(3000, bar.show_processing)
        QTimer.singleShot(5000, bar.show_success)
        QTimer.singleShot(7500, app.quit)

    QTimer.singleShot(100, test_sequence)
    sys.exit(app.exec())
