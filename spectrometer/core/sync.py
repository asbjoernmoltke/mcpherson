"""Shutter <-> camera synchronisation.

At 10-100 kHz the laser is effectively quasi-continuous relative to the ms
exposure, so there is no per-pulse phase-locking problem. The requirement is
simply that the (slow, mechanical) shutter is open exactly around the camera
exposure -- the camera "decides" the window, the shutter brackets it.

``SoftwareSync`` implements this in software now. ``HardwareTriggerSync`` is a
documented future seam (camera in external-trigger mode, laser sync wired in)
with the same ``acquire`` interface, so the acquisition engine never changes.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

from ..controllers.camera import CameraController
from ..controllers.shutter import ShutterController
from ..utilities import log
from .exceptions import EStopActive


class SyncController(ABC):
    @abstractmethod
    def acquire(self, n_frames: int = 1, timeout: float = 5.0) -> np.ndarray:
        """Acquire frames with the beam shutter correctly bracketed."""


class SoftwareSync(SyncController):
    def __init__(self, shutter: ShutterController, camera: CameraController, *,
                 open_settle_s: float = 0.05, close_settle_s: float = 0.05,
                 abort: Optional[threading.Event] = None):
        self.shutter = shutter
        self.camera = camera
        self.open_settle_s = open_settle_s
        self.close_settle_s = close_settle_s
        self._abort = abort or threading.Event()

    def acquire(self, n_frames: int = 1, timeout: float = 5.0) -> np.ndarray:
        if self._abort.is_set():
            raise EStopActive("Acquisition refused: abort is set.")
        try:
            self.shutter.open()
            if self._wait(self.open_settle_s):
                raise EStopActive("Aborted during shutter-open settle.")
            frames = self.camera.grab(n_frames, timeout=timeout)
        finally:
            # Always close the beam path, even on error/abort.
            self.shutter.close()
            self._wait(self.close_settle_s)
        return frames

    def _wait(self, seconds: float) -> bool:
        """Interruptible settle. Returns True if aborted during the wait."""
        return self._abort.wait(seconds)
