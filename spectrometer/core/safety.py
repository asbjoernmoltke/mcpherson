"""SafetyManager -- single source of truth for "is it safe to X".

Responsibilities:

* **Emergency stop** (``estop``): immediately close the shutter and disable
  the laser (beam-blocking first), latch a global abort flag, then stop the
  grating and camera acquisition. The shutter-close and laser-off travel on
  channels independent of any in-progress grating serial transaction, so the
  E-stop is never queued behind a blocking grating move.
* **Vacuum/cooling interlock**: ``assert_can_cool`` refuses cooling unless the
  vacuum is sufficient; ``check_vacuum_while_cold`` raises an alarm if vacuum
  is lost while the camera is cold (warn-only -- software cannot control
  vacuum).
* **Acquisition interlock**: ``can_acquire`` gates scans only on the E-stop /
  abort latch -- cooling is NOT required (it only reduces shot noise).

The abort flag is a :class:`threading.Event` shared with the camera
controller and the (future) acquisition engine, which check it between steps.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from ..controllers.camera import CameraController
from ..controllers.grating import GratingController
from ..controllers.laser import LaserController
from ..controllers.shutter import ShutterController
from ..controllers.vacuum import VacuumController
from ..utilities import log
from .exceptions import EStopActive, InterlockError

AlarmListener = Callable[[str], None]


class SafetyManager:
    def __init__(self, *, camera: CameraController, grating: GratingController,
                 shutter: ShutterController, laser: LaserController,
                 vacuum: VacuumController,
                 abort: Optional[threading.Event] = None):
        self.camera = camera
        self.grating = grating
        self.shutter = shutter
        self.laser = laser
        self.vacuum = vacuum
        self.abort = abort or threading.Event()
        self._estopped = False
        self._alarm_listeners: list[AlarmListener] = []

    # --- alarms / banner ----------------------------------------------
    def add_alarm_listener(self, callback: AlarmListener) -> None:
        self._alarm_listeners.append(callback)

    def _alarm(self, message: str) -> None:
        log.error("SAFETY ALARM: %s" % message)
        for cb in self._alarm_listeners:
            try:
                cb(message)
            except Exception as exc:  # pragma: no cover
                log.error("Alarm listener raised: %s" % exc)

    # --- emergency stop -----------------------------------------------
    def estop(self) -> None:
        """Emergency stop. Beam-blocking actions first, then halt motion."""
        log.error("*** EMERGENCY STOP ***")
        self._estopped = True
        self.abort.set()
        # 1) Block the beam and kill the laser FIRST (fast, independent paths).
        try:
            self.shutter.close()
        except Exception as exc:  # pragma: no cover
            self._alarm("Shutter close failed during E-stop: %s" % exc)
        try:
            self.laser.disable()
        except Exception as exc:  # pragma: no cover
            self._alarm("Laser disable failed during E-stop: %s" % exc)
        # 2) Halt motion and acquisition.
        try:
            self.grating.stop()
        except Exception as exc:  # pragma: no cover
            self._alarm("Grating stop failed during E-stop: %s" % exc)
        try:
            self.camera.stop_acquisition()
        except Exception as exc:  # pragma: no cover
            self._alarm("Camera stop failed during E-stop: %s" % exc)
        self._alarm("Emergency stop engaged. Reset required to continue.")

    @property
    def is_estopped(self) -> bool:
        return self._estopped

    def reset_estop(self) -> None:
        """Explicit operator action to clear the latched E-stop."""
        log.warn("Resetting emergency stop.")
        self._estopped = False
        self.abort.clear()

    # --- interlocks ----------------------------------------------------
    def assert_not_estopped(self) -> None:
        if self._estopped:
            raise EStopActive("Emergency stop is engaged; reset to continue.")

    def assert_can_cool(self) -> None:
        """Raise unless it is safe to begin cooling the camera."""
        self.assert_not_estopped()
        if not self.vacuum.vacuum_ok:
            raise InterlockError(
                "Vacuum insufficient (%s); cooling is not permitted."
                % self.vacuum.status)

    def check_vacuum_while_cold(self) -> bool:
        """Call periodically. Returns True if a vacuum alarm was raised."""
        if self.camera.driver.is_cooler_on() and not self.vacuum.vacuum_ok:
            self._alarm("VACUUM LOST while camera is cold (%s). Warm up the "
                        "camera and investigate immediately." % self.vacuum.status)
            return True
        return False

    @property
    def can_acquire(self) -> bool:
        # Acquisition is allowed regardless of camera temperature -- cooling
        # only reduces shot noise, it is not a precondition for grabbing a
        # frame. Only the E-stop / abort latch blocks acquisition.
        return not self._estopped and not self.abort.is_set()
