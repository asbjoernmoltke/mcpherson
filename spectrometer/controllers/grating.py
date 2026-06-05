"""Grating controller.

Wraps the grating driver and enforces the safety/consistency rules that the
thin driver does not:

* **Homed-state tracking** -- absolute step positions are only meaningful
  relative to the home flag, so absolute moves (and therefore wavelength
  moves and scans) are refused until the grating has been homed.
* **Calibrated position limits** -- moves are validated against the active
  calibration's ``position_limits`` (tighter than the driver's own soft
  clamp), so a bad target is rejected with a clear error instead of silently
  clamped.
* **Validated go-to-wavelength** -- the requested wavelength is checked
  against the grating's reachable range before it is mapped to steps.

Wavelength <-> position conversion itself is delegated to the calibration
layer; until a calibration is attached only step-based moves are available
(and then without calibrated limits).
"""
from __future__ import annotations

from ..core.exceptions import NotHomedError, OutOfRangeError
from ..drivers.base import GratingDriver
from ..utilities import log
from .base import Controller


class GratingController(Controller):
    def __init__(self, driver: GratingDriver, *, backlash: int = 0,
                 calibration=None):
        super().__init__("Grating")
        self.driver = driver
        self.backlash = backlash
        self.calibration = calibration  # attached in Phase 3
        self._homed = False

    # --- state --------------------------------------------------------
    @property
    def is_homed(self) -> bool:
        """True once a successful home has established the position reference.

        Cleared by a ``stop`` (the home reference is lost if motion is
        interrupted, since the controller no longer knows where it ended up)."""
        return self._homed

    def home(self) -> bool:
        log.info("GratingController: homing.")
        ok = bool(self.driver.home())
        self._homed = ok
        self._notify(self.status)
        return ok

    # --- moves --------------------------------------------------------
    def move_to_position(self, steps: int) -> None:
        if not self._homed:
            raise NotHomedError(
                "Grating is not homed; home before any absolute move.")
        lo, hi = self.position_limits
        if not (lo <= steps <= hi):
            raise OutOfRangeError(
                "Target %d steps is outside the calibrated limits "
                "[%d, %d]." % (steps, lo, hi))
        self.driver.move_to(steps, self.backlash)
        self._notify(self.status)

    def move_to_wavelength(self, wavelength_nm: float) -> None:
        if self.calibration is None:
            raise RuntimeError("No calibration attached; cannot map wavelength.")
        lo, hi = self.calibration.wavelength_limits()
        if not (lo <= wavelength_nm <= hi):
            raise OutOfRangeError(
                "Wavelength %.2f nm is outside this grating's reachable range "
                "[%.2f, %.2f] nm." % (wavelength_nm, lo, hi))
        steps = self.calibration.wavelength_to_position(wavelength_nm)
        self.move_to_position(steps)

    def stop(self) -> None:
        """Fast path used by the E-stop. Invalidates the homed reference, since
        an interrupted move leaves the true position unknown."""
        self.driver.stop()
        self._homed = False
        self._notify(self.status)

    # --- limits -------------------------------------------------------
    @property
    def position_limits(self) -> tuple[int, int]:
        """Allowed absolute step range. Uses the calibration when attached;
        otherwise unbounded (validation is effectively disabled)."""
        if self.calibration is not None:
            lo, hi = self.calibration.position_limits
            return int(lo), int(hi)
        return (-(2 ** 31), 2 ** 31 - 1)

    @property
    def position(self) -> int:
        return self.driver.get_position()

    @property
    def is_moving(self) -> bool:
        return self.driver.is_moving()

    @property
    def is_homing(self) -> bool:
        return self.driver.is_homing()

    @property
    def status(self) -> str:
        base = self.driver.get_status()
        if base == "Idle" and not self._homed:
            return "Idle (not homed)"
        return base
