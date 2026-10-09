import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.ui_state import UiStateController, UiStateMachine, UiState


class _Handle:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class ManualScheduler:
    """Scheduler manual para controlar callbacks em testes"""

    def __init__(self):
        self.tasks = []

    def schedule(self, delay_ms, callback):
        handle = _Handle()

        def _wrapped():
            if not handle.cancelled:
                callback()

        self.tasks.append((handle, _wrapped))
        return handle

    def run_next(self):
        while self.tasks:
            handle, cb = self.tasks.pop(0)
            if not handle.cancelled:
                cb()
                return


def test_state_machine_transitions():
    machine = UiStateMachine()
    machine.transition(UiState.PROCESSING)
    assert machine.state == UiState.PROCESSING
    machine.transition(UiState.DONE)
    assert machine.state == UiState.DONE
    machine.transition(UiState.IDLE)
    assert machine.state == UiState.IDLE


def test_controller_success_auto_reset():
    events = []
    scheduler = ManualScheduler()

    def dispatch(state, message=None):
        events.append((state, message))

    controller = UiStateController(
        dispatch=dispatch,
        auto_reset_ms=10,
        error_auto_reset_ms=10,
        watchdog_ms=1000,
        schedule=scheduler.schedule,
    )

    controller.start_processing()
    controller.finish_success()

    # Deve ter ido para PROCESSING e DONE
    assert events[0][0] == UiState.PROCESSING.value
    assert events[1][0] == UiState.DONE.value

    # Executa reset automatico
    scheduler.run_next()
    assert events[-1][0] == UiState.IDLE.value


def test_controller_watchdog_timeout():
    events = []
    scheduler = ManualScheduler()

    def dispatch(state, message=None):
        events.append((state, message))

    controller = UiStateController(
        dispatch=dispatch,
        auto_reset_ms=10,
        error_auto_reset_ms=10,
        watchdog_ms=10,
        schedule=scheduler.schedule,
    )

    controller.start_processing()
    # Dispara watchdog
    scheduler.run_next()
    assert events[-1][0] == UiState.ERROR.value

    # Reset apos erro
    scheduler.run_next()
    assert events[-1][0] == UiState.IDLE.value
