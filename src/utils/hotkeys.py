"""
Hotkey management - Global keyboard shortcuts
With proper debouncing to prevent infinite loops
"""
from pynput import keyboard
from typing import Callable, Optional, Set
import time
import threading

from src.utils.logger import get_logger

logger = get_logger(__name__)


class HotkeyManager:
    """Manages global keyboard shortcuts with debouncing"""
    
    def __init__(self):
        self.listener: Optional[keyboard.Listener] = None
        self.current_keys: Set = set()
        self.hotkey_callback: Optional[Callable] = None
        self.hotkey_combination = {keyboard.Key.ctrl_l, keyboard.Key.cmd}  # Ctrl+Win default
        self.required_groups = []
        self.required_keys: Set = set()
        self.is_active = False
        
        # Debouncing - prevent rapid firing
        self._last_press_time = 0
        self._last_release_time = 0
        self._debounce_delay = 0.3  # 300ms minimum between events
        self._lock = threading.Lock()
        self._callback_in_progress = False
    
    def set_hotkey(self, hotkey_string: str):
        """
        Set hotkey combination from string (e.g., 'ctrl+win', 'ctrl+shift+r')
        
        Args:
            hotkey_string: Hotkey combination as string
        """
        def _parse(value: str):
            keys = value.lower().split('+')
            hotkey_combination = set()
            required_groups = []
            required_keys = set()
            unknown_parts = []

            def _mod_group(*names):
                group = set()
                for name in names:
                    k = getattr(keyboard.Key, name, None)
                    if k is not None:
                        group.add(k)
                return group

            key_mapping = {
                'ctrl': _mod_group('ctrl_l', 'ctrl_r', 'ctrl'),
                'shift': _mod_group('shift_l', 'shift_r', 'shift'),
                'alt': _mod_group('alt_l', 'alt_r', 'alt'),
                'win': _mod_group('cmd', 'cmd_l', 'cmd_r'),
                'cmd': _mod_group('cmd', 'cmd_l', 'cmd_r'),
                'space': keyboard.Key.space,
                'enter': keyboard.Key.enter,
                'tab': keyboard.Key.tab,
                'esc': keyboard.Key.esc,
            }

            for key in keys:
                key = key.strip()
                if not key:
                    continue
                if key in key_mapping:
                    mapped = key_mapping[key]
                    if isinstance(mapped, set):
                        if mapped:
                            required_groups.append(mapped)
                            hotkey_combination.update(mapped)
                    else:
                        required_keys.add(mapped)
                        hotkey_combination.add(mapped)
                elif len(key) == 1:
                    k = keyboard.KeyCode.from_char(key)
                    required_keys.add(k)
                    hotkey_combination.add(k)
                else:
                    unknown_parts.append(key)

            return required_groups, required_keys, hotkey_combination, unknown_parts

        required_groups, required_keys, hotkey_combination, unknown_parts = _parse(hotkey_string)
        if (not required_groups and not required_keys) or (unknown_parts and (len(required_groups) + len(required_keys) <= 1)):
            logger.warning("Invalid hotkey '%s' (parts: %s). Falling back to ctrl+shift.", hotkey_string, unknown_parts)
            hotkey_string = "ctrl+shift"
            required_groups, required_keys, hotkey_combination, unknown_parts = _parse(hotkey_string)

        self.hotkey_combination = hotkey_combination
        self.required_groups = required_groups
        self.required_keys = required_keys
        
        logger.info("Hotkey set to: %s", hotkey_string)

    def _combo_active(self) -> bool:
        if self.required_keys and not self.required_keys.issubset(self.current_keys):
            return False
        for group in self.required_groups:
            if not any(k in self.current_keys for k in group):
                return False
        return True
    
    def on_press(self, key):
        """Handle key press event with debouncing"""
        self.current_keys.add(key)
        
        # Check if hotkey combination is pressed
        if not self._combo_active():
            return
        
        # Debounce: check if enough time has passed since last press
        current_time = time.time()
        if current_time - self._last_press_time < self._debounce_delay:
            return
        
        # Use lock to prevent concurrent callback execution
        with self._lock:
            if self.is_active or self._callback_in_progress:
                return
            
            self._callback_in_progress = True
            self.is_active = True
            self._last_press_time = current_time
        
        # Call callback outside of lock
        if self.hotkey_callback:
            try:
                self.hotkey_callback(True)  # Hotkey pressed
            except Exception as e:
                logger.error("Error in hotkey callback (press)", exc_info=True)
        
        with self._lock:
            self._callback_in_progress = False
    
    def on_release(self, key):
        """Handle key release event with debouncing"""
        try:
            self.current_keys.discard(key)
        except:
            pass
        
        # Only trigger release if we were active and a hotkey key was released
        if not self.is_active:
            return

        if self._combo_active():
            return
        
        # Debounce: check if enough time has passed since last release
        current_time = time.time()
        if current_time - self._last_release_time < self._debounce_delay:
            return
        
        # Use lock to prevent concurrent callback execution
        with self._lock:
            if not self.is_active or self._callback_in_progress:
                return
            
            self._callback_in_progress = True
            self.is_active = False
            self._last_release_time = current_time
        
        # Call callback outside of lock
        if self.hotkey_callback:
            try:
                self.hotkey_callback(False)  # Hotkey released
            except Exception as e:
                logger.error("Error in hotkey callback (release)", exc_info=True)
        
        with self._lock:
            self._callback_in_progress = False
    
    def start_listening(self, callback: Callable):
        """
        Start listening for hotkey
        
        Args:
            callback: Function to call when hotkey is pressed/released
                     Receives bool: True when pressed, False when released
        """
        self.hotkey_callback = callback
        
        # Reset state
        self.is_active = False
        self._callback_in_progress = False
        self.current_keys.clear()
        self._last_press_time = 0
        self._last_release_time = 0
        
        # Stop existing listener if any
        self.stop_listening()
        
        # Start new listener
        self.listener = keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release
        )
        self.listener.start()
        logger.info("Hotkey listener started")
    
    def stop_listening(self):
        """Stop listening for hotkey"""
        if self.listener:
            self.listener.stop()
            self.listener = None
            logger.info("Hotkey listener stopped")
