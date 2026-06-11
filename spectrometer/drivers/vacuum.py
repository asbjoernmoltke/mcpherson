"""Vacuum-gauge drivers (read-only).

Vacuum is controlled manually on isolated hardware; software only *reads*
the pressure so the safety layer can gate camera cooling. Concrete gauge
hardware is TBD, so only :class:`DummyVacuum` exists -- its pressure is
settable so the cooling interlock can be exercised offline.
"""
from __future__ import annotations

from ..utilities import log
from .base import VacuumDriver


class DummyVacuum(VacuumDriver):
    """Simulated gauge with a settable pressure (default a poor vacuum, so
    the cooling interlock blocks until a test explicitly lowers it)."""

    def __init__(self, initial_pressure: float = 1.0e-2, units: str = "mbar"):
        self._pressure = initial_pressure
        self._units = units
        self._connected = False
        self._turbo_state = 0    # 0 stopped / 4 running (simulated, like the TIC)
        self._backing_state = 0

    def open(self) -> None:
        self._connected = True
        log.info("DummyVacuum connected.")

    def close(self) -> None:
        self._connected = False
        log.info("DummyVacuum disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_status(self) -> str:
        if not self._connected:
            return "Disconnected"
        return f"{self._pressure:.2e} {self._units}"

    def read_pressure(self) -> float:
        return self._pressure

    @property
    def units(self) -> str:
        return self._units

    # --- simulated pump status + control ------------------------------
    _STATE_NAMES = {0: "Stopped", 4: "Running", 5: "Accelerating"}

    def read_turbo_state(self) -> str:
        return self._STATE_NAMES.get(self._turbo_state, "state %d" % self._turbo_state)

    def read_backing_state(self) -> str:
        return self._STATE_NAMES.get(self._backing_state, "state %d" % self._backing_state)

    def supports_control(self) -> bool:
        return True

    def set_turbo(self, on: bool) -> None:
        self._turbo_state = 4 if on else 0

    def set_backing(self, on: bool) -> None:
        self._backing_state = 4 if on else 0

    def turbo_state_code(self) -> int:
        return self._turbo_state

    def backing_state_code(self) -> int:
        return self._backing_state

    # --- test/simulation helper (not part of the ABC) -----------------
    def set_pressure(self, pressure: float) -> None:
        """Simulate a pressure change (e.g. pump-down) for offline tests."""
        self._pressure = pressure
        log.info("DummyVacuum: pressure set to %.2e %s" % (pressure, self._units))
