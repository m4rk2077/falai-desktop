"""
Window Manager - Handle window focus and activation
Cross-platform implementation with fallbacks
"""
import time
import platform
from typing import Optional

SW_RESTORE = 9
SW_SHOW = 5


class WindowManager:
    """Manages window focus and activation (cross-platform)"""
    
    def __init__(self):
        self.system = platform.system()
        self.user32 = None
        self.kernel32 = None
        
        if self.system == 'Windows':
            import ctypes
            self.user32 = ctypes.windll.user32
            self.kernel32 = ctypes.windll.kernel32
        
    def get_active_window(self) -> int:
        """Get the handle of the currently active window"""
        if self.system == 'Windows' and self.user32:
            return self.user32.GetForegroundWindow()
        return 0
    
    def set_foreground_window(self, hwnd: int) -> bool:
        """
        Bring the specified window to the foreground and give it focus.
        
        Args:
            hwnd: Window handle to activate
            
        Returns:
            True if successful, False otherwise
        """
        if self.system != 'Windows' or not self.user32:
            return True
            
        if not hwnd:
            return False
            
        if not self.user32.IsWindow(hwnd):
            return False
            
        if self.user32.IsIconic(hwnd):
            self.user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            self.user32.ShowWindow(hwnd, SW_SHOW)
            
        current_thread_id = self.kernel32.GetCurrentThreadId()
        window_thread_id = self.user32.GetWindowThreadProcessId(hwnd, None)
        
        if current_thread_id != window_thread_id:
            self.user32.AttachThreadInput(current_thread_id, window_thread_id, True)
            
        result = self.user32.SetForegroundWindow(hwnd)
        
        if current_thread_id != window_thread_id:
            self.user32.AttachThreadInput(current_thread_id, window_thread_id, False)
            
        time.sleep(0.05)  # Allow window manager to complete focus switch

        return bool(result)
