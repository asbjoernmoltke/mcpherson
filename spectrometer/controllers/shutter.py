"""Shutter controller.

Thin wrapper exposing open/close/status plus a fast ``close`` used by the
E-stop. The shutter↔camera *timing* lives in the SyncController, not here.
"""
from __future__ import annotations

from ..drivers.base import ShutterDriver
from ..utilities import log
from .base import Controller


class ShutterController(Controller):
    def __init__(self, driver: ShutterDriver):
        super().__init__("Shutter")
        self.driver = driver

    def open(self) -> None:
        self.driver.open_shutter()
        self._notify(self.status)

    def close(self) -> None:
        """Also the E-stop fast path -- block the beam immediately."""
        self.driver.close_shutter()
        self._notify(self.status)

    @property
    def is_open(self) -> bool:
        return self.driver.is_open

    @property
    def status(self) -> str:
        return self.driver.get_status()
