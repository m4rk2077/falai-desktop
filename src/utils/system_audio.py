"""
Windows system volume ducking (best-effort).
"""
from __future__ import annotations

import os
import sys
import ctypes
from ctypes import wintypes
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class SystemAudioDucker:
    def __init__(self, duck_level: float = 0.0):
        self.duck_level = max(0.0, min(1.0, duck_level))
        self._saved_volume: Optional[float] = None
        self._session_volumes: dict[int, float] = {}
        self._endpoint = None
        self._pycaw_ready = False
        self._warned_no_pycaw = False
        self._init_pycaw()

    def _init_pycaw(self):
        if sys.platform != "win32":
            return
        try:
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            self._endpoint = cast(interface, POINTER(IAudioEndpointVolume))
            self._pycaw_ready = True
        except Exception:
            self._pycaw_ready = False
            logger.debug("Pycaw not available for volume ducking", exc_info=True)

    def _get_volume(self) -> float | None:
        if sys.platform != "win32":
            return None
        if self._pycaw_ready and self._endpoint:
            try:
                return float(self._endpoint.GetMasterVolumeLevelScalar())
            except Exception:
                logger.debug("Failed to get master volume via pycaw", exc_info=True)
        try:
            vol = wintypes.DWORD()
            ctypes.windll.winmm.waveOutGetVolume(0, ctypes.byref(vol))
            left = vol.value & 0xFFFF
            right = (vol.value >> 16) & 0xFFFF
            avg = (left + right) / 2
            return avg / 0xFFFF
        except Exception:
            logger.debug("Failed to get system volume", exc_info=True)
            return None

    def _set_volume(self, value: float):
        if sys.platform != "win32":
            return
        value = max(0.0, min(1.0, value))
        if self._pycaw_ready and self._endpoint:
            try:
                self._endpoint.SetMasterVolumeLevelScalar(value, None)
                return
            except Exception:
                logger.debug("Failed to set master volume via pycaw", exc_info=True)
        try:
            v = int(value * 0xFFFF)
            packed = v | (v << 16)
            ctypes.windll.winmm.waveOutSetVolume(0, packed)
        except Exception:
            logger.debug("Failed to set system volume", exc_info=True)

    def duck(self):
        if sys.platform != "win32":
            return
        if self._pycaw_ready:
            try:
                from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume

                sessions = AudioUtilities.GetAllSessions()
                if not sessions:
                    logger.debug("No audio sessions found for ducking")
                    return
                self._session_volumes = {}
                skipped = 0
                for session in sessions:
                    process = session.Process
                    if not process:
                        skipped += 1
                        continue
                    pid = process.pid
                    if pid == os.getpid():
                        skipped += 1
                        continue
                    volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                    current = float(volume.GetMasterVolume())
                    self._session_volumes[pid] = current
                    volume.SetMasterVolume(self.duck_level, None)
                logger.info(
                    "Audio ducking applied to %d session(s) (skipped %d)",
                    len(self._session_volumes),
                    skipped,
                )
                return
            except Exception:
                logger.warning("Session ducking failed, falling back to master volume", exc_info=True)

        if not self._warned_no_pycaw and not self._pycaw_ready:
            logger.warning("Pycaw not available, using master volume ducking")
            self._warned_no_pycaw = True

        if self._saved_volume is None:
            self._saved_volume = self._get_volume()
        if self._saved_volume is not None:
            self._set_volume(self.duck_level)

    def restore(self):
        if sys.platform != "win32":
            return
        if self._pycaw_ready and self._session_volumes:
            try:
                from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume

                sessions = AudioUtilities.GetAllSessions()
                restored = 0
                for session in sessions:
                    process = session.Process
                    if not process:
                        continue
                    pid = process.pid
                    if pid not in self._session_volumes:
                        continue
                    volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                    volume.SetMasterVolume(self._session_volumes[pid], None)
                    restored += 1
                logger.info("Audio ducking restored for %d session(s)", restored)
                self._session_volumes = {}
            except Exception:
                logger.warning("Failed to restore session volumes", exc_info=True)

        if self._saved_volume is not None:
            self._set_volume(self._saved_volume)
            self._saved_volume = None
