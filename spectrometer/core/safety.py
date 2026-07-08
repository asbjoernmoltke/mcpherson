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
        """Raise unless cooling may be initiated at all. The per-setpoint
        frost-point gate lives in ``CameraController.cooldown``; here we only
        block on the E-stop."""
        self.assert_not_estopped()

    def assert_can_stop_pumping(self) -> None:
        """Raise unless it is safe to stop/slow the turbo. Stopping the turbo
        auto-vents the chamber (vent is on the turbo port), so doing it while
        the camera is cold would frost the sensor. Warm the camera first.

        Reads the *cached* cold flag rather than the camera driver directly:
        this is called from the vacuum/laser worker thread, which doesn't own
        the (thread-confined) camera driver -- the acquisition thread
        refreshes the cache once per poll cycle instead."""
        if self.camera.is_cold_cached:
            raise InterlockError(
                "Camera is cold (cooler on, sensor below %.0f C). Stopping or "
                "standing-by the turbo auto-vents the chamber and would frost "
                "the sensor -- warm the camera up first."
                % self.camera.warm_target_c)

    def check_pump_health(self) -> list[str]:
        """Call periodically. Surfaces vacuum faults: a controller alert (pump
        over-temp/over-pressure, etc.) or the turbo spinning with no backing
        pump (it has lost its exhaust). Raises an alarm per issue and returns
        the list (for a dedicated GUI field)."""
        issues: list[str] = []
        try:
            if self.vacuum.turbo_running and not self.vacuum.backing_running:
                issues.append(
                    "Backing pump stopped while the turbo is spinning -- the "
                    "turbo has lost its exhaust. Restore backing or stop the turbo.")
            issues.extend(self.vacuum.alerts)
        except Exception as exc:  # pragma: no cover - hardware dependent
            log.error("Pump-health check failed: %s" % exc)
        for msg in issues:
            self._alarm(msg)
        return issues

    def check_frost_risk(self) -> bool:
        """Call periodically. Returns True (and raises an alarm) if the sensor
        is colder than the frost-point-safe minimum for the current pressure --
        e.g. vacuum degraded while the camera is cold."""
        if self.camera.is_at_frost_risk():
            self._alarm(
                "FROST RISK: sensor is colder than the safe minimum for the "
                "current pressure (frost point %.1f C, %s). Warm the camera / "
                "improve vacuum immediately."
                % (self.vacuum.frost_point_c, self.vacuum.status))
            return True
        return False

    @property
    def can_acquire(self) -> bool:
        # Acquisition is allowed regardless of camera temperature -- cooling
        # only reduces shot noise, it is not a precondition for grabbing a
        # frame. Only the E-stop / abort latch blocks acquisition.
        return not self._estopped and not self.abort.is_set()
