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

    # --- simulated read-only pump status (display only) ---------------
    def read_turbo_state(self) -> str:
        # Pretend the turbo is at full speed once the pressure is low.
        return "Normal" if self._pressure < 1.0 else "Accelerating"

    def read_backing_state(self) -> str:
        return "Running"

    # --- test/simulation helper (not part of the ABC) -----------------
    def set_pressure(self, pressure: float) -> None:
        """Simulate a pressure change (e.g. pump-down) for offline tests."""
        self._pressure = pressure
        log.info("DummyVacuum: pressure set to %.2e %s" % (pressure, self._units))
