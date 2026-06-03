"""Grating controller.

Wraps the grating driver and enforces step limits + backlash. Wavelength
<-> position conversion is delegated to the calibration layer (Phase 3);
until a calibration is attached, only step-based moves are available.
"""
from __future__ import annotations

from typing import Optional

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

    def home(self) -> bool:
        log.info("GratingController: homing.")
        ok = self.driver.home()
        self._notify(self.status)
        return ok

    def move_to_position(self, steps: int) -> None:
        self.driver.move_to(steps, self.backlash)
        self._notify(self.status)

    def move_to_wavelength(self, wavelength_nm: float) -> None:
        if self.calibration is None:
            raise RuntimeError("No calibration attached; cannot map wavelength.")
        steps = self.calibration.wavelength_to_position(wavelength_nm)
        self.move_to_position(steps)

    def stop(self) -> None:
        """Fast path used by the E-stop."""
        self.driver.stop()
        self._notify(self.status)

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
        return self.driver.get_status()
