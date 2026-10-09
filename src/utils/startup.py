"""
Windows startup helper for FALAI.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)

APP_NAME = "FALAI"


def _startup_dir() -> Path:
    appdata = os.getenv("APPDATA", "")
    if not appdata:
        raise RuntimeError("APPDATA not found")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _startup_file() -> Path:
    return _startup_dir() / f"{APP_NAME}-startup.bat"


def _installed_executable() -> Path | None:
    """Return the per-user installed FALAI executable, when present."""
    local_app_data = os.getenv("LOCALAPPDATA", "")
    if not local_app_data:
        return None

    executable = Path(local_app_data) / "Programs" / APP_NAME / f"{APP_NAME}.exe"
    return executable if executable.exists() else None


_STARTUP_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"


def _clear_startup_disabled_flag() -> None:
    """Re-approve the startup entry if Windows (Task Manager) marked it disabled.

    Windows keeps a separate per-item flag; rewriting the .bat does not clear it,
    so the app would silently stop launching at boot.
    """
    if sys.platform != "win32":
        return
    try:
        import winreg

        name = _startup_file().name
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_APPROVED_KEY, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
            try:
                value, _ = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                return
            if value and value[0] != 0x02:
                winreg.SetValueEx(key, name, 0, winreg.REG_BINARY, bytes([2] + [0] * 11))
                logger.info("Startup entry re-approved in Windows: %s", name)
    except Exception:
        logger.warning("Could not clear Windows startup disabled flag", exc_info=True)


def is_startup_enabled() -> bool:
    try:
        return _startup_file().exists()
    except Exception:
        return False


def enable_startup(root_dir: Path, executable_path: Path | str | None = None, *, approve: bool = False):
    """
    Create startup .bat that launches the installed executable when available.
    Fallback to run_falai.bat / main.py for local dev runs.
    approve=True (explicit user toggle) also clears a Windows "disabled" flag.
    """
    try:
        startup_dir = _startup_dir()
        startup_dir.mkdir(parents=True, exist_ok=True)

        cmd = ""
        exe = Path(str(executable_path or "")).expanduser()

        # When running the source through Python, sys.executable is Python itself.
        # Prefer the installed app so Windows startup launches FALAI, not a blank
        # Python process.
        installed_exe = _installed_executable() if getattr(sys, "frozen", False) else None
        if installed_exe:
            cmd = f'start "" "{installed_exe.resolve()}"\n'

        if exe and exe.exists():
            # Installed app (PyInstaller onedir/onefile): open the executable directly.
            if not cmd and exe.suffix.lower() == ".exe" and exe.stem.lower() not in {"python", "pythonw"}:
                cmd = f'start "" "{exe.resolve()}"\n'
            elif not cmd:
                # Dev mode (python): run main.py through current interpreter.
                main_py = root_dir / "main.py"
                if main_py.exists():
                    pythonw = exe.with_name("pythonw.exe")
                    interpreter = pythonw if pythonw.is_file() else exe
                    cmd = f'start "" /D "{root_dir.resolve()}" "{interpreter.resolve()}" "{main_py.resolve()}"\n'

        if not cmd:
            target_bat = root_dir / "run_falai.bat"
            if target_bat.exists():
                cmd = f'start "" "{target_bat.resolve()}"\n'
            else:
                main_py = root_dir / "main.py"
                if not main_py.exists():
                    raise RuntimeError("startup target not found")
                py = Path(sys.executable).resolve()
                cmd = f'start "" "{py}" "{main_py.resolve()}"\n'

        content = "@echo off\nchcp 65001 >nul\n" + cmd
        _startup_file().write_text(content, encoding="utf-8")
        logger.info("Startup enabled: %s", _startup_file())
        if approve:
            _clear_startup_disabled_flag()
    except Exception:
        logger.error("Failed to enable startup", exc_info=True)
        raise


def disable_startup():
    try:
        startup_file = _startup_file()
        if startup_file.exists():
            startup_file.unlink()
            logger.info("Startup disabled: %s", startup_file)
    except Exception:
        logger.error("Failed to disable startup", exc_info=True)
        raise
