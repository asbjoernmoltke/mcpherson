"""Beam-shutter drivers.

Concrete hardware is not yet chosen, so only :class:`DummyShutter` exists.
When the real shutter is selected (e.g. a Thorlabs SC10 over serial, or a
TTL/digital line), add a sibling class implementing
:class:`~spectrometer.drivers.base.ShutterDriver` -- the controllers depend
only on the ABC, so nothing else changes.
"""
from __future__ import annotations

import time

from ..utilities import log
from .base import ShutterDriver


class DummyShutter(ShutterDriver):
    """Simulated shutter with a configurable open/close travel time."""

    def __init__(self, travel_time: float = 0.05):
        self._is_open = False
        self._connected = False
        self.travel_time = travel_time

    def open(self) -> None:
        self._connected = True
        log.info("DummyShutter connected.")

    def close(self) -> None:
        # Driver-level disconnect; fail safe by closing the beam path first.
        self._is_open = False
        self._connected = False
        log.info("DummyShutter disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_status(self) -> str:
        if not self._connected:
            return "Disconnected"
        return "Open" if self._is_open else "Closed"

    def open_shutter(self) -> None:
        time.sleep(self.travel_time)
        self._is_open = True
        log.info("DummyShutter: open.")

    def close_shutter(self) -> None:
        time.sleep(self.travel_time)
        self._is_open = False
        log.info("DummyShutter: closed.")

    @property
    def is_open(self) -> bool:
        return self._is_open
