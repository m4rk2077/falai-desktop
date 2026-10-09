"""
History Window - View and manage transcription history
PySide6/Qt implementation
"""
from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLabel, QLineEdit, QPushButton, QFrame, QFileDialog,
    QInputDialog, QMessageBox, QDateEdit, QCheckBox
)
from PySide6.QtCore import Qt, QTimer, QDate
from PySide6.QtGui import QFont

from src.ui.theme import DARK_THEME, COLORS
from src.utils.clipboard import ClipboardManager
from src.utils.logger import get_logger

logger = get_logger(__name__)


class HistoryWindow(QDialog):
    """Window to view and manage transcription history"""

    def __init__(self, parent, history_manager):
        super().__init__(parent)

        self.history_manager = history_manager
        self.clipboard = ClipboardManager()
        self.page_size = 20
        self.current_page = 1

        # Window setup
        self.setWindowTitle("📋 Histórico de Transcrições")
        self.resize(600, 500)
        self.setMinimumSize(500, 400)
        self.setModal(True)

        # Apply theme
        self.setStyleSheet(DARK_THEME)

        self._create_widgets()
        self._load_history()

    def _create_widgets(self):
        """Create UI components"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(10)

        # Header
        header_frame = QWidget()
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)

        title_label = QLabel("📋 Histórico")
        title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # Search
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("🔍 Buscar...")
        self.search_entry.setFixedWidth(200)
        self.search_entry.textChanged.connect(self._on_search)
        header_layout.addWidget(self.search_entry)

        main_layout.addWidget(header_frame)

        # Filters
        filters_frame = QWidget()
        filters_layout = QHBoxLayout(filters_frame)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        filters_layout.setSpacing(10)

        self.date_filter_checkbox = QCheckBox("Filtrar por data")
        self.date_filter_checkbox.toggled.connect(self._on_filter_changed)
        filters_layout.addWidget(self.date_filter_checkbox)

        today = QDate.currentDate()
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_from.setDate(today.addDays(-7))
        self.date_from.dateChanged.connect(self._on_filter_changed)
        filters_layout.addWidget(QLabel("De:"))
        filters_layout.addWidget(self.date_from)

        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setDate(today)
        self.date_to.dateChanged.connect(self._on_filter_changed)
        filters_layout.addWidget(QLabel("Até:"))
        filters_layout.addWidget(self.date_to)

        self.corrected_only_checkbox = QCheckBox("Apenas corrigidos")
        self.corrected_only_checkbox.toggled.connect(self._on_filter_changed)
        filters_layout.addWidget(self.corrected_only_checkbox)

        filters_layout.addStretch()
        main_layout.addWidget(filters_frame)

        # History list container (scroll area)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch()

        scroll_area.setWidget(self.list_container)
        main_layout.addWidget(scroll_area, 1)

        # Footer
        footer_frame = QWidget()
        footer_layout = QHBoxLayout(footer_frame)
        footer_layout.setContentsMargins(0, 0, 0, 0)

        self.count_label = QLabel("0 transcrições")
        self.count_label.setFont(QFont("Segoe UI", 11))
        self.count_label.setStyleSheet(f"color: {COLORS['foreground_dim']};")
        footer_layout.addWidget(self.count_label)

        footer_layout.addStretch()

        clear_btn = QPushButton("🗑️ Limpar")
        clear_btn.setFixedWidth(100)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['danger']};
            }}
            QPushButton:hover {{
                background-color: {COLORS['danger_hover']};
            }}
        """)
        clear_btn.clicked.connect(self._clear_history)
        footer_layout.addWidget(clear_btn)

        self.load_more_btn = QPushButton("Carregar mais")
        self.load_more_btn.setFixedWidth(140)
        self.load_more_btn.clicked.connect(self._load_more)
        footer_layout.addWidget(self.load_more_btn)

        export_btn = QPushButton("📥 Exportar")
        export_btn.setFixedWidth(120)
        export_btn.clicked.connect(self._export_history)
        footer_layout.addWidget(export_btn)

        main_layout.addWidget(footer_frame)

        # Message label
        self.message_label = QLabel()
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.message_label.hide()
        main_layout.addWidget(self.message_label)

    def _load_history(self, query: str = ""):
        """Load and display history items"""
        # Clear existing items (except the stretch at the end)
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Get history with filters and pagination
        entries = self._get_filtered_entries(query)
        total_entries = len(entries)
        visible_limit = self.page_size * self.current_page
        entries = entries[:visible_limit]

        if not entries:
            empty_label = QLabel("Nenhuma transcrição encontrada")
            empty_label.setFont(QFont("Segoe UI", 12))
            empty_label.setStyleSheet(f"color: {COLORS['foreground_dim']};")
            empty_label.setAlignment(Qt.AlignCenter)
            self.list_layout.insertWidget(0, empty_label)
            self.count_label.setText("0 transcrições")
            self.load_more_btn.setVisible(False)
            return

        # Display entries (in reverse so newest are at top, before stretch)
        for i, entry in enumerate(entries):
            widget = self._create_entry_widget(entry)
            self.list_layout.insertWidget(i, widget)

        self.count_label.setText(f"{len(entries)} de {total_entries} transcrições")
        self.load_more_btn.setVisible(len(entries) < total_entries)

    def _get_filtered_entries(self, query: str = ""):
        """Aplica filtros, busca e retorna lista ordenada (mais recentes primeiro)"""
        entries = list(reversed(self.history_manager.history))

        # Busca por texto
        if query:
            query_lower = query.lower()
            filtered = []
            for entry in entries:
                original = entry.get("original", "").lower()
                corrected = (entry.get("corrected") or "").lower()
                if query_lower in original or query_lower in corrected:
                    filtered.append(entry)
            entries = filtered

        # Apenas corrigidos
        if self.corrected_only_checkbox.isChecked():
            entries = [e for e in entries if e.get("corrected")]

        # Filtro por data
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

    def _on_filter_changed(self):
        """Reseta paginação e recarrega"""
        self.current_page = 1
        self._load_history(self.search_entry.text())

    def _load_more(self):
        """Carrega mais itens mantendo filtros"""
        self.current_page += 1
        self._load_history(self.search_entry.text())

    def _create_entry_widget(self, entry: dict) -> QFrame:
        """Create a widget for a history entry"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['background_light']};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(8)

        # Header with timestamp and copy button
        header_frame = QWidget()
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)

        # Timestamp
        try:
            dt = datetime.fromisoformat(entry["timestamp"])
            time_str = dt.strftime("%d/%m/%Y %H:%M")
        except:
            time_str = entry.get("timestamp", "")

        time_label = QLabel(f"🕐 {time_str}")
        time_label.setFont(QFont("Segoe UI", 10))
        time_label.setStyleSheet(f"color: {COLORS['foreground_dim']};")
        header_layout.addWidget(time_label)

        duration = entry.get("duration_seconds", 0)
        if duration:
            duration_label = QLabel(f"⏱️ {duration:.1f}s")
            duration_label.setFont(QFont("Segoe UI", 10))
            duration_label.setStyleSheet(f"color: {COLORS['foreground_dim']};")
            header_layout.addWidget(duration_label)

        header_layout.addStretch()

        # Get text for copy button
        text = self.history_manager.get_text(entry)

        copy_btn = QPushButton("📋 Copiar")
        copy_btn.setFixedSize(80, 28)
        copy_btn.setFont(QFont("Segoe UI", 10))
        copy_btn.clicked.connect(lambda checked, t=text: self._copy_text(t))
        header_layout.addWidget(copy_btn)

        layout.addWidget(header_frame)

        # Text content
        display_text = text[:150] + "..." if len(text) > 150 else text

        text_label = QLabel(display_text)
        text_label.setFont(QFont("Segoe UI", 12))
        text_label.setWordWrap(True)
        layout.addWidget(text_label)

        # Show if corrected
        if entry.get("corrected"):
            corrected_label = QLabel("✨ Corrigido com GPT")
            corrected_label.setFont(QFont("Segoe UI", 9))
            corrected_label.setStyleSheet(f"color: {COLORS['accent']};")
            layout.addWidget(corrected_label)

        return frame

    def _copy_text(self, text: str):
        """Copy text to clipboard"""
        self.clipboard.copy(text)
        logger.info("Copied from history")
        logger.debug("History copy preview: %s...", text[:50])

        # Show feedback
        self.message_label.setText("📋 Copiado!")
        self.message_label.setStyleSheet(f"color: {COLORS['accent']};")
        self.message_label.show()
        QTimer.singleShot(1500, self.message_label.hide)

    def _on_search(self, text: str):
        """Handle search input"""
        self.current_page = 1
        self._load_history(text)

    def _clear_history(self):
        """Clear all history after confirmation"""
        text, ok = QInputDialog.getText(
            self,
            "Confirmar Exclusão",
            "Digite 'LIMPAR' para confirmar:"
        )

        if ok and text.upper() == "LIMPAR":
            self.history_manager.clear()
            self._load_history()

            self.message_label.setText("🗑️ Histórico limpo!")
            self.message_label.setStyleSheet(f"color: {COLORS['warning']};")
            self.message_label.show()
            QTimer.singleShot(2000, self.message_label.hide)

    def _export_history(self):
        """Export history to a nicely formatted TXT file"""
        entries = self.history_manager.get_all(limit=1000)

        if not entries:
            QMessageBox.information(self, "Exportar", "Nenhuma transcrição para exportar.")
            return

        # Ask user where to save
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Histórico",
            f"transcricoes_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            "Text files (*.txt);;All files (*.*)"
        )

        if not file_path:
            return

        # Generate formatted content
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
            except:
                date_str = entry.get("timestamp", "Data desconhecida")

            duration = entry.get("duration_seconds", 0)
            text = self.history_manager.get_text(entry)

            lines.append("-" * 60)
            lines.append(f"📅 {date_str}  |  ⏱️ {duration:.1f}s")
            lines.append("-" * 60)
            lines.append(text)
            lines.append("")

        # Write file
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines))

            logger.info("History exported to: %s", file_path)

            self.message_label.setText("✅ Exportado com sucesso!")
            self.message_label.setStyleSheet(f"color: {COLORS['accent']};")
            self.message_label.show()
            QTimer.singleShot(2000, self.message_label.hide)

        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao exportar: {e}")
