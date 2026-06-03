"""Laser controller.

Thin wrapper exposing enable/disable/status plus a fast ``disable`` used by
the E-stop.
"""
from __future__ import annotations

from ..drivers.base import LaserDriver
from ..utilities import log
from .base import Controller


class LaserController(Controller):
    def __init__(self, driver: LaserDriver):
        super().__init__("Laser")
        self.driver = driver

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
    def status(self) -> str:
        return self.driver.get_status()
