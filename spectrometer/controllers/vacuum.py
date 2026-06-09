"""Vacuum controller.

Reads the gauge and exposes ``pressure`` plus a ``vacuum_ok`` boolean used by
the cooling interlock in :class:`SafetyManager` and shown in the GUI. We only
read -- vacuum is controlled manually on isolated hardware.
"""
from __future__ import annotations

from ..drivers.base import VacuumDriver
from ..utilities import log
from .base import Controller

# Default safe threshold for permitting cooling. The real value + the gauge's
# units are an open item (see plan); make it explicit and configurable.
DEFAULT_COOLING_THRESHOLD = 1.0e-4  # in the gauge's native units


class VacuumController(Controller):
    def __init__(self, driver: VacuumDriver,
                 cooling_threshold: float = DEFAULT_COOLING_THRESHOLD):
        super().__init__("Vacuum")
        self.driver = driver
        self.cooling_threshold = cooling_threshold
        self._pressure = float("inf")

    def poll(self) -> float:
        """Read the gauge; updates cached pressure and notifies listeners.
        On a read error the cached pressure is set to +inf (fail-safe)."""
        try:
            self._pressure = self.driver.read_pressure()
        except Exception as exc:
            self._pressure = float("inf")
            log.error("Vacuum read failed: %s (treating as unsafe)." % exc)
        self._notify(self.status)
        return self._pressure

    @property
    def pressure(self) -> float:
        return self._pressure

    @property
    def units(self) -> str:
        return self.driver.units

    # --- read-only pump status (display only; never commands the pumps) ---
    @property
    def turbo_state(self) -> str | None:
        try:
            return self.driver.read_turbo_state()
        except Exception:
            return None

    @property
    def backing_state(self) -> str | None:
        try:
            return self.driver.read_backing_state()
        except Exception:
            return None

    @property
    def vacuum_ok(self) -> bool:
        """True when pressure is at/below the safe cooling threshold. A read
        error is fail-safe: returns False (cannot confirm vacuum => not safe)."""
        try:
            return self.driver.read_pressure() <= self.cooling_threshold
        except Exception as exc:
            log.error("Vacuum read failed in vacuum_ok: %s (=> not ok)." % exc)
            return False

    @property
    def status(self) -> str:
        if not self.driver.is_connected:
            return "Disconnected"
        ok = "OK" if self.vacuum_ok else "TOO HIGH"
        return f"{self._pressure:.2e} {self.units} ({ok})"
