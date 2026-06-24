"""Laser controller.

Exposes enable/disable/status (the fast ``disable`` is the E-stop path) plus
pass-throughs for the optional power / pulse-picker / repetition-rate controls.
Capability flags let the GUI grey-out controls the connected laser doesn't
support.
"""
from __future__ import annotations

from typing import Optional

from ..drivers.base import LaserDriver
from ..utilities import log
from .base import Controller


class LaserController(Controller):
    def __init__(self, driver: LaserDriver):
        super().__init__("Laser")
        self.driver = driver

    # --- emission -----------------------------------------------------
    def enable(self) -> None:
        self.driver.enable()
        self._notify(self.status)

    def disable(self) -> None:
        """Also the E-stop fast path -- command the laser off immediately."""
        self.driver.disable()
        self._notify(self.status)

    @property
    def is_enabled(self) -> bool:
        return self.driver.is_enabled

    @property
    def emission_stage(self) -> str:
        return self.driver.emission_stage

    # --- power / pulse picker / rep rate (pass-throughs) --------------
    def set_power_percent(self, percent: float) -> None:
        self.driver.set_power_percent(percent)
        self._notify(self.status)

    def read_power_percent(self) -> Optional[float]:
        return self.driver.read_power_percent()

    # --- pulse energy (uJ) --------------------------------------------
    def set_pulse_energy_uj(self, energy_uj: float) -> None:
        self.driver.set_pulse_energy_uj(energy_uj)
        self._notify(self.status)

    def read_pulse_energy_uj(self) -> Optional[float]:
        return self.driver.read_pulse_energy_uj()

    def read_measured_pulse_energy_uj(self) -> Optional[float]:
        return self.driver.read_measured_pulse_energy_uj()

    @property
    def max_pulse_energy_uj(self) -> Optional[float]:
        return self.driver.max_pulse_energy_uj

    def set_pulse_picker_ratio(self, ratio: int) -> None:
        self.driver.set_pulse_picker_ratio(ratio)
        self._notify(self.status)

    def read_pulse_picker_ratio(self) -> Optional[int]:
        return self.driver.read_pulse_picker_ratio()

    def set_repetition_rate_hz(self, target_hz: float) -> int:
        ratio = self.driver.set_repetition_rate_hz(target_hz)
        self._notify(self.status)
        return ratio

    def read_repetition_rate_hz(self) -> Optional[float]:
        return self.driver.read_repetition_rate_hz()

    def allowed_rep_rates_hz(self) -> Optional[tuple[float, ...]]:
        return self.driver.allowed_rep_rates_hz()

    # --- capabilities (for GUI enable/disable) ------------------------
    @property
    def supports_power(self) -> bool:
        return self.driver.read_power_percent() is not None

    @property
    def supports_energy(self) -> bool:
        return self.driver.max_pulse_energy_uj is not None

    @property
    def supports_pulse_picker(self) -> bool:
        return self.driver.read_pulse_picker_ratio() is not None

    @property
    def supports_rep_rate(self) -> bool:
        return self.driver.read_repetition_rate_hz() is not None

    @property
    def status(self) -> str:
        return self.driver.get_status()
