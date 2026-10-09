"""
System Tray Manager for FALAI
Runs the app in the system tray with context menu
"""
import os
import threading
from pathlib import Path
from typing import Callable, Optional
from PIL import Image
import pystray
from pystray import MenuItem as item

from src.utils.logger import get_logger

logger = get_logger(__name__)


class TrayManager:
    """Manages the system tray icon and menu"""

    def __init__(self, icon_path: str = None):
        self.icon: Optional[pystray.Icon] = None
        self.is_running = False

        # Callbacks
        self.on_settings: Optional[Callable] = None
        self.on_history: Optional[Callable] = None
        self.on_stats: Optional[Callable] = None
        self.on_quit: Optional[Callable] = None
        self.on_click: Optional[Callable] = None
        self.on_update: Optional[Callable] = None

        # Load icon
        if icon_path and os.path.exists(icon_path):
            self.icon_image = Image.open(icon_path)
            # Resize to appropriate tray icon size
            self.icon_image = self.icon_image.resize((64, 64), Image.Resampling.LANCZOS)
        else:
            # Create a simple fallback icon (red circle)
            self.icon_image = self._create_fallback_icon()

    def _create_fallback_icon(self) -> Image.Image:
        """Create a simple fallback icon if logo not found"""
        from PIL import ImageDraw

        size = 64
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # Draw a red circle (microphone indicator)
        padding = 8
        draw.ellipse(
            [padding, padding, size - padding, size - padding],
            fill=(220, 53, 69, 255)  # Bootstrap red
        )

        return image

    def _create_menu(self) -> pystray.Menu:
        """Create the context menu for the tray icon"""
        return pystray.Menu(
            # "Abrir" is the default action (double-click on Windows)
            item('🎤 Abrir FALAI', self._on_open_click),
            pystray.Menu.SEPARATOR,
            item('⬆️ Atualizações', self._on_update_click),
            item('⚙️ Configurações', self._on_settings_click),
            item('📋 Histórico', self._on_history_click),
            item('📊 Estatísticas', self._on_stats_click),
            pystray.Menu.SEPARATOR,
            item('❌ Sair', self._on_quit_click)
        )

    def _on_update_click(self, icon, item):
        """Handle update menu click"""
        if self.on_update:
            threading.Thread(target=self.on_update, daemon=True).start()

    def _on_open_click(self, icon, item):
        """Handle open/double-click"""
        if self.on_click:
            threading.Thread(target=self.on_click, daemon=True).start()
        elif self.on_settings:
            threading.Thread(target=self.on_settings, daemon=True).start()

    def _on_settings_click(self, icon, item):
        """Handle settings menu click"""
        if self.on_settings:
            # Run in main thread
            threading.Thread(target=self.on_settings, daemon=True).start()

    def _on_history_click(self, icon, item):
        """Handle history menu click"""
        if self.on_history:
            threading.Thread(target=self.on_history, daemon=True).start()

    def _on_stats_click(self, icon, item):
        """Handle stats menu click"""
        if self.on_stats:
            threading.Thread(target=self.on_stats, daemon=True).start()

    def _on_quit_click(self, icon, item):
        """Handle quit menu click"""
        self.stop()
        if self.on_quit:
            self.on_quit()

    def set_callbacks(
        self,
        on_settings: Callable = None,
        on_history: Callable = None,
        on_stats: Callable = None,
        on_quit: Callable = None,
        on_click: Callable = None,
        on_update: Callable = None,
    ):
        """Set callback functions for menu items"""
        self.on_settings = on_settings
        self.on_history = on_history
        self.on_stats = on_stats
        self.on_quit = on_quit
        self.on_click = on_click
        self.on_update = on_update

    def start(self):
        """Start the system tray icon"""
        if self.is_running:
            return

        self.icon = pystray.Icon(
            name="FALAI",
            icon=self.icon_image,
            title="FALAI - Voice Transcription",
            menu=self._create_menu()
        )

        self.is_running = True

        # Run in separate thread so it doesn't block
        def run_tray():
            self.icon.run()

        self.tray_thread = threading.Thread(target=run_tray, daemon=True)
        self.tray_thread.start()

        logger.info("System tray started")

    def stop(self):
        """Stop the system tray icon"""
        if self.icon:
            self.icon.stop()
            self.is_running = False
            logger.info("System tray stopped")

    def update_icon(self, recording: bool = False):
        """Update tray icon to show recording state"""
        # Could be extended to show different icons when recording
        pass

    def show_notification(self, title: str, message: str):
        """Show a system notification"""
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception as e:
                logger.error("Could not show notification", exc_info=True)
