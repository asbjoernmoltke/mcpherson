"""Laser drivers.

Concrete hardware is not yet chosen, so only :class:`DummyLaser` exists.
The real laser only needs enable/disable + status for the emergency-stop
path; the analog sync channel is a documented future hook (``read_sync``).
"""
from __future__ import annotations

from ..utilities import log
from .base import LaserDriver


class DummyLaser(LaserDriver):
    """Simulated laser. ``disable()`` is the E-stop hook and is instantaneous."""

    def __init__(self):
        self._enabled = False
        self._connected = False

    def open(self) -> None:
        self._connected = True
        log.info("DummyLaser connected.")

    def close(self) -> None:
        # Fail safe: disable on disconnect.
        self._enabled = False
        self._connected = False
        log.info("DummyLaser disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_status(self) -> str:
        if not self._connected:
            return "Disconnected"
        return "Enabled" if self._enabled else "Disabled"

    def enable(self) -> None:
        self._enabled = True
        log.info("DummyLaser: enabled.")

    def disable(self) -> None:
        self._enabled = False
        log.info("DummyLaser: DISABLED.")

    @property
    def is_enabled(self) -> bool:
        return self._enabled
