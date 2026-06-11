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
DEFAULT_COOLING_THRESHOLD = 1.0e-2  # Pa (gauge's native unit); PLACEHOLDER -- confirm spec


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

    # --- frost-point interlock support --------------------------------
    _UNIT_TO_PA = {"pa": 1.0, "mbar": 100.0, "torr": 133.322}

    @property
    def pressure_pa(self) -> float:
        """Cached pressure converted to Pa (the frost-point math works in Pa).
        Unknown units pass through unscaled."""
        return self._pressure * self._UNIT_TO_PA.get(self.units.lower(), 1.0)

    @property
    def frost_point_c(self) -> float:
        """Frost point (deg C) at the current pressure -- the temperature below
        which the sensor risks condensation. A read failure leaves the cached
        pressure at +inf, so this returns a high value (cooling blocked)."""
        from ..core.thermo import frost_point_c
        return frost_point_c(self.pressure_pa)

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
