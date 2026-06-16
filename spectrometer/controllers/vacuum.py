"""Vacuum controller.

Reads the gauge and exposes ``pressure`` plus a ``vacuum_ok`` boolean used by
the cooling interlock in :class:`SafetyManager` and shown in the GUI. We only
read -- vacuum is controlled manually on isolated hardware.
"""
from __future__ import annotations

from ..core.exceptions import InterlockError
from ..drivers.base import VacuumDriver
from ..utilities import log
from .base import Controller

# Default safe threshold for permitting cooling. The real value + the gauge's
# units are an open item (see plan); make it explicit and configurable.
DEFAULT_COOLING_THRESHOLD = 1.0e-2  # Pa (gauge's native unit); PLACEHOLDER -- confirm spec

# Pump state codes (TIC manual 1.7.8): 0 Stopped, 4 Running, 5 Accelerating.
PUMP_STOPPED = 0
PUMP_RUNNING = 4


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

    # --- pump control (interlocked) -----------------------------------
    @property
    def supports_control(self) -> bool:
        return self.driver.supports_control()

    @property
    def turbo_running(self) -> bool:
        return self.driver.turbo_state_code() == PUMP_RUNNING

    @property
    def backing_running(self) -> bool:
        return self.driver.backing_state_code() == PUMP_RUNNING

    def turbo_on(self) -> None:
        """Start the turbo -- ONLY once the backing pump is running (the turbo
        must not run without its exhaust)."""
        if not self.backing_running:
            raise InterlockError(
                "Turbo can't start until the backing pump is running (normal "
                "mode). Start the backing pump first.")
        self.driver.set_turbo(True)
        self._notify(self.status)

    def turbo_off(self) -> None:
        self.driver.set_turbo(False)
        self._notify(self.status)

    @property
    def turbo_standby(self) -> bool:
        """True if the turbo is held at reduced (standby) speed."""
        return bool(self.driver.turbo_standby_active())

    def turbo_standby_on(self) -> None:
        """Decelerate the turbo to standby speed -- the gentle spin-down that
        stays under vacuum and (with auto-vent 'On stop') does NOT vent. Only
        meaningful while the turbo is spinning."""
        st = self.driver.turbo_state_code()
        if st == PUMP_STOPPED:
            raise InterlockError(
                "The turbo is stopped -- nothing to put into standby.")
        self.driver.set_turbo_standby(True)
        self._notify(self.status)

    def turbo_standby_off(self) -> None:
        """Return the turbo from standby to full speed."""
        self.driver.set_turbo_standby(False)
        self._notify(self.status)

    def backing_on(self) -> None:
        self.driver.set_backing(True)
        self._notify(self.status)

    def backing_off(self) -> None:
        """Stop the backing pump -- ONLY once the turbo is stopped (the turbo
        needs the backing pump to exhaust)."""
        st = self.driver.turbo_state_code()
        if st is not None and st != PUMP_STOPPED:
            raise InterlockError(
                "Stop the turbo before the backing pump (the turbo needs the "
                "backing pump to exhaust).")
        self.driver.set_backing(False)
        self._notify(self.status)

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
