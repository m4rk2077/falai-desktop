"""
Statistics Window - View usage statistics
PySide6/Qt implementation - Premium UI/UX
"""
from datetime import datetime, timedelta
from typing import Dict, Any
from collections import defaultdict

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QGridLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPainter, QColor

from src.ui.theme import DARK_THEME, COLORS


class StatsWindow(QDialog):
    """Window to display usage statistics - Premium Design"""

    def __init__(self, parent, history_manager):
        super().__init__(parent)

        self.history_manager = history_manager

        # Configure window
        self.setWindowTitle("Estatísticas - FALAI")
        self.resize(750, 550)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        # Apply theme
        self.setStyleSheet(DARK_THEME)

        # Calculate stats
        self.stats = self._calculate_stats()

        # UI Layout
        self._create_ui()

    def _calculate_stats(self) -> Dict[str, Any]:
        """Calculate statistics from history"""
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

        # For daily graph (last 7 days)
        daily_usage = defaultdict(int)  # date_str -> word count
        today = datetime.now().date()
        last_7_days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
        prev_7_days = [(today - timedelta(days=i)).isoformat() for i in range(13, 6, -1)]

        for entry in history:
            # Get text (prefer corrected)
            text = entry.get("corrected") or entry.get("original", "")
            if not text:
                continue

            # Word count
            words = len(text.split())
            total_words += words

            # Duration
            duration = entry.get("duration_seconds", 0)
            total_time_seconds += duration

            # Daily usage
            try:
                timestamp = entry.get("timestamp")
                if timestamp:
                    date_str = datetime.fromisoformat(timestamp).date().isoformat()
                    daily_usage[date_str] += words
            except:
                pass

        # Calculate WPM (Words Per Minute)
        avg_wpm = 0
        if total_time_seconds > 0:
            avg_wpm = (total_words / total_time_seconds) * 60

        # Calculate Time Saved
        # Average typing speed: 40 WPM
        # Average speaking speed: 150 WPM
        # Time to type those words = total_words / 40 minutes
        # Time spent speaking = total_time_seconds / 60 minutes
        # Time saved = typing_time - speaking_time

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
            "avg_wpm": int(avg_wpm),
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
        """Create the UI components"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(20)

        # Header
        header_frame = QWidget()
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("📊 Estatísticas de Uso")
        title.setFont(QFont("Segoe UI", 22, QFont.Bold))
        header_layout.addWidget(title)

        header_layout.addStretch()

        close_btn = QPushButton("Fechar")
        close_btn.setFixedWidth(90)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['background_light']};
            }}
        """)
        close_btn.clicked.connect(self.close)
        header_layout.addWidget(close_btn)

        main_layout.addWidget(header_frame)

        # KPI Cards - 2x2 Grid
        cards_frame = QWidget()
        cards_layout = QGridLayout(cards_frame)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(12)

        # Row 1
        # 1. Total Words
        self._create_card(
            cards_layout,
            "Total de Palavras",
            f"{self.stats['total_words']:,}".replace(",", "."),
            "📝",
            COLORS['accent'],
            row=0, col=0
        )

        # 2. Total Transcriptions
        self._create_card(
            cards_layout,
            "Transcrições",
            f"{self.stats['total_transcriptions']}",
            "🎤",
            COLORS['accent'],
            row=0, col=1
        )

        # Row 2
        # 3. Time Saved (NOVO - destaque especial)
        time_saved = self.stats['time_saved_minutes']
        if time_saved >= 60:
            hours = int(time_saved // 60)
            mins = int(time_saved % 60)
            time_saved_str = f"{hours}h {mins}min"
        else:
            time_saved_str = f"{int(time_saved)} min"

        self._create_card(
            cards_layout,
            "Tempo Economizado",
            time_saved_str,
            "⏱️",
            "#2ed573",  # Green highlight
            row=1, col=0,
            highlight=True
        )

        # 4. Avg WPM
        self._create_card(
            cards_layout,
            "Velocidade Média",
            f"{self.stats['avg_wpm']} WPM",
            "⚡",
            COLORS['accent'],
            row=1, col=1
        )

        main_layout.addWidget(cards_frame)

        # Separator
        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background-color: {COLORS['border']};")
        main_layout.addWidget(separator)

        # Graph Title
        graph_header = QWidget()
        graph_header_layout = QHBoxLayout(graph_header)
        graph_header_layout.setContentsMargins(0, 0, 0, 0)

        graph_title = QLabel("Palavras nos Últimos 7 Dias")
        graph_title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        graph_header_layout.addWidget(graph_title)

        graph_header_layout.addStretch()

        # Total this week
        week_total = self.stats.get("week_total", 0)
        week_label = QLabel(f"Esta semana: {week_total:,} palavras".replace(",", "."))
        week_label.setFont(QFont("Segoe UI", 12))
        week_label.setStyleSheet(f"color: {COLORS['foreground_dim']};")
        graph_header_layout.addWidget(week_label)

        # Comparativo com semana anterior
        week_change_pct = self.stats.get("week_change_pct")
        if week_change_pct is None:
            change_text = "Sem dados da semana anterior"
        else:
            arrow = "↑" if week_change_pct >= 0 else "↓"
            change_text = f"{arrow} {abs(week_change_pct):.0f}% vs semana anterior"
        change_label = QLabel(change_text)
        change_label.setFont(QFont("Segoe UI", 11))
        change_label.setStyleSheet(f"color: {COLORS['foreground_dim']};")
        graph_header_layout.addWidget(change_label)

        main_layout.addWidget(graph_header)

        # Graph Area
        graph_frame = BarChartWidget(
            self.stats['last_7_days_dates'],
            self.stats['daily_usage']
        )
        graph_frame.setStyleSheet(f"""
            background-color: {COLORS['background_light']};
            border-radius: 12px;
        """)
        main_layout.addWidget(graph_frame, 1)

        # Footer info
        footer = QLabel("💡 Tempo economizado = tempo que levaria digitando - tempo falando")
        footer.setFont(QFont("Segoe UI", 10))
        footer.setStyleSheet(f"color: {COLORS['foreground_dim']};")
        footer.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(footer)

    def _create_card(
        self,
        layout: QGridLayout,
        title: str,
        value: str,
        icon: str,
        color: str,
        row: int,
        col: int,
        highlight: bool = False
    ):
        """Create a KPI card"""
        card = QFrame()

        # Special highlight style for "Tempo Economizado"
        if highlight:
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: rgba(46, 213, 115, 0.1);
                    border: 2px solid {color};
                    border-radius: 12px;
                }}
            """)
        else:
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {COLORS['background_light']};
                    border-radius: 12px;
                }}
            """)

        card_layout = QVBoxLayout(card)
        card_layout.setAlignment(Qt.AlignCenter)
        card_layout.setSpacing(8)
        card_layout.setContentsMargins(16, 16, 16, 16)

        # Icon + Title row
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        icon_label = QLabel(icon)
        icon_label.setFont(QFont("Segoe UI Emoji", 16))
        header_layout.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 12))
        title_label.setStyleSheet(f"color: {COLORS['foreground_dim']};")
        header_layout.addWidget(title_label)

        header_layout.addStretch()
        card_layout.addWidget(header_widget)

        # Value
        value_label = QLabel(value)
        value_label.setFont(QFont("Segoe UI", 26, QFont.Bold))
        value_label.setStyleSheet(f"color: {color};")
        value_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(value_label)

        layout.addWidget(card, row, col)


class BarChartWidget(QWidget):
    """Simple bar chart widget with improved styling"""

    def __init__(self, dates: list, daily_usage: dict, parent=None):
        super().__init__(parent)

        self.dates = dates
        self.data = [daily_usage.get(d, 0) for d in dates]
        self.max_val = max(self.data) if self.data and max(self.data) > 0 else 1

        self.setMinimumHeight(180)
        self._create_ui()

    def _create_ui(self):
        """Create bar chart using widgets"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        today = datetime.now().date().isoformat()

        for i, val in enumerate(self.data):
            is_today = self.dates[i] == today

            # Column container
            col_widget = QWidget()
            col_layout = QVBoxLayout(col_widget)
            col_layout.setContentsMargins(0, 0, 0, 0)
            col_layout.setSpacing(6)

            # Value label at top
            val_label = QLabel(str(val) if val > 0 else "")
            val_label.setFont(QFont("Segoe UI", 10, QFont.Bold if is_today else QFont.Normal))
            val_label.setStyleSheet(f"color: {COLORS['accent'] if is_today else COLORS['foreground_dim']};")
            val_label.setAlignment(Qt.AlignCenter)
            col_layout.addWidget(val_label)

            # Bar container
            bar_container = QWidget()
            bar_container.setMinimumHeight(100)
            col_layout.addWidget(bar_container, 1)

            # Create bar inside container
            bar = BarWidget(val, self.max_val, is_today, bar_container)
            bar.setParent(bar_container)
            tooltip_date = self._format_date(self.dates[i], is_today)
            bar.setToolTip(f"{tooltip_date}: {val} palavras")

            # Date label at bottom
            date_label = QLabel(self._format_date(self.dates[i], is_today))
            date_label.setFont(QFont("Segoe UI", 11, QFont.Bold if is_today else QFont.Normal))
            date_label.setStyleSheet(f"color: {COLORS['accent'] if is_today else COLORS['foreground']};")
            date_label.setAlignment(Qt.AlignCenter)
            col_layout.addWidget(date_label)

            layout.addWidget(col_widget)

    def _format_date(self, date_iso: str, is_today: bool) -> str:
        """Format date for label"""
        if is_today:
            return "Hoje"
        try:
            dt = datetime.fromisoformat(date_iso)
            # Short day name in Portuguese
            days = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
            return days[dt.weekday()]
        except:
            return date_iso[:5]


class BarWidget(QWidget):
    """A single bar in the chart"""

    def __init__(self, value: int, max_value: int, is_today: bool = False, parent=None):
        super().__init__(parent)

        self.value = value
        self.max_value = max_value
        self.is_today = is_today
        self.setMinimumWidth(35)

    def resizeEvent(self, event):
        """Position and resize bar on parent resize"""
        super().resizeEvent(event)

        parent_height = self.parent().height() if self.parent() else 100
        parent_width = self.parent().width() if self.parent() else 35

        # Calculate bar height
        height_pct = self.value / self.max_value if self.max_value > 0 else 0
        if height_pct < 0.08:
            height_pct = 0.08  # Minimum height

        bar_height = int(parent_height * height_pct)
        bar_width = min(35, parent_width - 6)

        # Position at bottom center
        x = (parent_width - bar_width) // 2
        y = parent_height - bar_height

        self.setGeometry(x, y, bar_width, bar_height)

    def paintEvent(self, event):
        """Paint the bar"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.value > 0:
            if self.is_today:
                color = QColor(COLORS['accent'])
            else:
                color = QColor(COLORS['accent'])
                color.setAlpha(180)  # Slightly transparent for non-today
        else:
            color = QColor(COLORS['border'])

        painter.setBrush(color)
        painter.setPen(Qt.NoPen)

        # Draw rounded rectangle
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 6, 6)
