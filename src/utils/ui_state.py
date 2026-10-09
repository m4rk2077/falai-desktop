"""
Maquina de estados de UI e controlador para transicoes seguras (thread-safe)
"""
from enum import Enum
import threading
from typing import Callable, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class UiState(str, Enum):
    """Estados possiveis da UI"""

    IDLE = "idle"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class UiStateMachine:
    """Valida transicoes de estado de forma explicita"""

    _allowed = {
        UiState.IDLE: {UiState.PROCESSING},
        UiState.PROCESSING: {UiState.DONE, UiState.ERROR},
        UiState.DONE: {UiState.IDLE, UiState.PROCESSING},
        UiState.ERROR: {UiState.IDLE, UiState.PROCESSING},
    }

    def __init__(self):
        self.state = UiState.IDLE

    def can_transition(self, new_state: UiState) -> bool:
        if new_state == self.state:
            return True
        return new_state in self._allowed.get(self.state, set())

    def transition(self, new_state: UiState):
        if new_state == self.state:
            return
        if not self.can_transition(new_state):
            raise ValueError(f"Transicao invalida: {self.state} -> {new_state}")
        self.state = new_state


def _default_schedule(delay_ms: int, callback: Callable):
    """Agenda callback em thread separada usando Timer"""
    timer = threading.Timer(delay_ms / 1000.0, callback)
    timer.daemon = True
    timer.start()
    return timer


class UiStateController:
    """Controlador de estados com reset automatico e watchdog"""

    def __init__(
        self,
        dispatch: Callable[[str, Optional[str]], None],
        auto_reset_ms: int = 1200,
        error_auto_reset_ms: int = 2000,
        watchdog_ms: int = 15000,
        schedule: Optional[Callable[[int, Callable], object]] = None,
    ):
        self._dispatch_fn = dispatch
        self._auto_reset_ms = auto_reset_ms
        self._error_auto_reset_ms = error_auto_reset_ms
        self._watchdog_ms = watchdog_ms
        self._schedule = schedule or _default_schedule
        self._machine = UiStateMachine()
        self._reset_handle = None
        self._watchdog_handle = None
        self._lock = threading.Lock()

    @property
    def state(self) -> UiState:
        return self._machine.state

    def start_processing(self):
        """Inicia o estado de processamento"""
        with self._lock:
            if self._machine.state == UiState.PROCESSING:
                return
            self._cancel_reset()
            self._transition(UiState.PROCESSING)
            self._start_watchdog()

    def finish_success(self):
        """Finaliza com sucesso e agenda reset"""
        with self._lock:
            if self._machine.state != UiState.PROCESSING:
                return
            self._stop_watchdog()
            self._transition(UiState.DONE)
            self._schedule_reset(self._auto_reset_ms)

    def finish_error(self, message: str):
        """Finaliza com erro e agenda reset"""
        with self._lock:
            if self._machine.state != UiState.PROCESSING:
                return
            self._stop_watchdog()
            self._transition(UiState.ERROR, message)
            self._schedule_reset(self._error_auto_reset_ms)

    def force_reset(self):
        """Forca retorno ao estado idle"""
        with self._lock:
            self._stop_watchdog()
            self._cancel_reset()
            # Reset forçado ignora validação de transicao
            self._machine.state = UiState.IDLE
            self._dispatch_fn(UiState.IDLE.value, None)
            logger.debug("UI state forced reset to idle")

    def _transition(self, new_state: UiState, message: Optional[str] = None):
        prev = self._machine.state
        self._machine.transition(new_state)
        self._dispatch_fn(new_state.value, message)
        logger.debug("UI state transition: %s -> %s", prev.value, new_state.value)

    def _schedule_reset(self, delay_ms: int):
        self._cancel_reset()
        if delay_ms <= 0:
            self._transition(UiState.IDLE)
            return

        def _reset():
            with self._lock:
                if self._machine.state in (UiState.DONE, UiState.ERROR):
                    self._transition(UiState.IDLE)

        self._reset_handle = self._schedule(delay_ms, _reset)

    def _start_watchdog(self):
        self._stop_watchdog()
        if self._watchdog_ms <= 0:
            return

        def _watchdog():
            with self._lock:
                if self._machine.state == UiState.PROCESSING:
                    logger.warning("UI watchdog timeout exceeded")
                    self._transition(UiState.ERROR, "Tempo excedido")
                    self._schedule_reset(self._error_auto_reset_ms)

        self._watchdog_handle = self._schedule(self._watchdog_ms, _watchdog)

    def _stop_watchdog(self):
        if self._watchdog_handle and hasattr(self._watchdog_handle, "cancel"):
            self._watchdog_handle.cancel()
        self._watchdog_handle = None

    def _cancel_reset(self):
        if self._reset_handle and hasattr(self._reset_handle, "cancel"):
            self._reset_handle.cancel()
        self._reset_handle = None
