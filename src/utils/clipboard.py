"""
Clipboard utilities - Copy and paste text
"""
import pyperclip
import time
from pynput.keyboard import Controller, Key

from src.utils.logger import get_logger

logger = get_logger(__name__)


class ClipboardManager:
    """Manages clipboard operations and automatic pasting"""
    
    def __init__(self):
        self.keyboard = Controller()
    
    def copy_to_clipboard(self, text: str):
        """
        Copy text to clipboard
        
        Args:
            text: Text to copy
        """
        try:
            pyperclip.copy(text)
            logger.info("Copied to clipboard")
            logger.debug("Clipboard preview: %s...", text[:50])
        except Exception as e:
            logger.error("Error copying to clipboard", exc_info=True)
    
    def paste_to_active_field(self, text: str):
        """
        Paste text to the currently active field
        
        Args:
            text: Text to paste
        """
        try:
            # First, copy to clipboard
            pyperclip.copy(text)
            
            # Small delay to ensure clipboard is updated (50ms: safe minimum for Win32 clipboard API)
            time.sleep(0.05)
            
            # Simulate Ctrl+V to paste
            self.keyboard.press(Key.ctrl)
            self.keyboard.press('v')
            self.keyboard.release('v')
            self.keyboard.release(Key.ctrl)
            
            logger.info("Pasted text to active field")
            logger.debug("Paste preview: %s...", text[:50])
            
        except Exception as e:
            logger.error("Error pasting text", exc_info=True)
    
    def type_text(self, text: str, delay: float = 0.01):
        """
        Type text character by character (alternative to paste)
        
        Args:
            text: Text to type
            delay: Delay between characters in seconds
        """
        try:
            for char in text:
                self.keyboard.type(char)
                time.sleep(delay)
            
            logger.info("Typed text")
            logger.debug("Typed preview: %s...", text[:50])
            
        except Exception as e:
            logger.error("Error typing text", exc_info=True)
