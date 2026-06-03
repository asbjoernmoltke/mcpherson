"""Shared controller infrastructure.

Controllers are deliberately **Qt-free**: they expose state and a simple
listener/callback mechanism rather than Qt signals, so the safety and control
logic can be unit-tested with no GUI. The GUI layer adapts these callbacks to
Qt signals.

Controllers are *thread-confined*: their device-touching methods are intended
to run on the hardware/worker thread, never the GUI thread. Status reads
(plain attribute access) are cheap and safe to poll from a GUI timer.
"""
from __future__ import annotations

from typing import Callable

from ..utilities import log

StatusListener = Callable[[str], None]


class Controller:
    """Base with a lightweight status-change notification mechanism."""

    def __init__(self, name: str):
        self.name = name
        self._listeners: list[StatusListener] = []

    def add_listener(self, callback: StatusListener) -> None:
        self._listeners.append(callback)

    def _notify(self, status: str) -> None:
        for cb in self._listeners:
            try:
                cb(status)
            except Exception as exc:  # pragma: no cover - listener bug
                log.error("Status listener for %s raised: %s" % (self.name, exc))
