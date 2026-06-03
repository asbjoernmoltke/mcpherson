"""Camera controller -- the safety-critical subsystem.

Owns the cooling *policy* (the driver only exposes mechanism):

* ``cooldown`` refuses to start unless the vacuum interlock passes.
* ``safe_shutdown`` performs a controlled warm-up to near-ambient *before*
  the cooler/fan is switched off, preventing thermal shock / condensation on
  an expensive sensor.
* ``grab`` runs a saturation guard on every frame.

All long waits are interruptible via an ``abort`` event so the E-stop and
scan-abort paths stay responsive.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import numpy as np

from ..drivers.base import CameraDriver
from ..utilities import log
from .base import Controller
from ..core.exceptions import InterlockError

# 16-bit sensor full scale; flag frames at/above this fraction as saturated.
SATURATION_LEVEL = 65000


class CameraController(Controller):
    def __init__(self, driver: CameraDriver, *,
                 vacuum_ok: Callable[[], bool],
                 warm_target_c: float = 10.0,
                 stable_timeout_s: float = 300.0,
                 abort: Optional[threading.Event] = None):
        super().__init__("Camera")
        self.driver = driver
        self._vacuum_ok = vacuum_ok
        self.warm_target_c = warm_target_c
        self.stable_timeout_s = stable_timeout_s
        self._abort = abort or threading.Event()
        self.last_frame_saturated = False

    # --- cooling lifecycle --------------------------------------------
    def cooldown(self, setpoint_c: float) -> None:
        """Begin cooling to ``setpoint_c`` -- gated on the vacuum interlock."""
        if not self._vacuum_ok():
            raise InterlockError(
                "Refusing to cool the camera: vacuum is not sufficient.")
        log.info("CameraController: cooling to %.1f C." % setpoint_c)
        self.driver.set_temperature(setpoint_c)
        self._notify(self.status)

    def wait_until_stable(self, timeout: Optional[float] = None) -> bool:
        """Block until the sensor temperature stabilises, the timeout
        elapses, or an abort is requested. Returns True if stabilised."""
        timeout = self.stable_timeout_s if timeout is None else timeout
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._abort.is_set():
                log.warn("CameraController: stabilise wait aborted.")
                return False
            if self.driver.is_temperature_stable():
                log.info("CameraController: temperature stable at %.1f C."
                         % self.driver.get_temperature())
                return True
            self._notify(self.status)
            time.sleep(0.5)
        log.warn("CameraController: temperature did not stabilise in %.0fs."
                 % timeout)
        return False

    def safe_shutdown(self) -> None:
        """Controlled warm-up to ``warm_target_c`` before the cooler is
        turned off. Always attempt to disable the cooler at the end."""
        log.info("CameraController: safe shutdown -- warming to %.1f C first."
                 % self.warm_target_c)
        try:
            # Raise the setpoint so the sensor warms while the cooler still
            # runs (controlled, not a sudden cooler-off thermal shock).
            self.driver.set_temperature(self.warm_target_c)
            deadline = time.monotonic() + self.stable_timeout_s
            while time.monotonic() < deadline:
                temp = self.driver.get_temperature()
                self._notify(self.status)
                if temp >= self.warm_target_c - 1.0:
                    break
                time.sleep(0.5)
            else:
                log.warn("CameraController: warm-up timed out; disabling "
                         "cooler anyway at %.1f C." % self.driver.get_temperature())
        finally:
            self.driver.set_cooler(False)
            log.info("CameraController: cooler off at %.1f C."
                     % self.driver.get_temperature())
            self._notify(self.status)

    # --- acquisition config -------------------------------------------
    def configure(self, *, exposure_s: Optional[float] = None,
                  trigger_mode: Optional[str] = None,
                  internal_shutter: Optional[str] = None) -> None:
        if exposure_s is not None:
            self.driver.set_exposure(exposure_s)
        if trigger_mode is not None:
            self.driver.set_trigger_mode(trigger_mode)
        if internal_shutter is not None:
            self.driver.set_internal_shutter(internal_shutter)

    @property
    def is_cooled(self) -> bool:
        """Informational: True when cooled and temperature-stable (low-noise
        regime). NOT required to acquire -- cooling only reduces shot noise."""
        return self.driver.is_cooler_on() and self.driver.is_temperature_stable()

    def grab(self, n_frames: int = 1, timeout: float = 5.0) -> np.ndarray:
        frames = self.driver.grab(n_frames, timeout=timeout)
        self._check_saturation(frames)
        return frames

    def _check_saturation(self, frames: np.ndarray) -> None:
        peak = int(np.max(frames)) if frames.size else 0
        self.last_frame_saturated = peak >= SATURATION_LEVEL
        if self.last_frame_saturated:
            log.warn("CameraController: SATURATION detected (peak=%d). "
                     "Reduce exposure/gain." % peak)

    def stop_acquisition(self) -> None:
        """Fast path used by the E-stop."""
        self.driver.stop_acquisition()

    # --- status -------------------------------------------------------
    @property
    def temperature(self) -> float:
        return self.driver.get_temperature()

    @property
    def status(self) -> str:
        if not self.driver.is_connected:
            return "Disconnected"
        cooler = "cooler on" if self.driver.is_cooler_on() else "cooler off"
        stable = "stable" if self.driver.is_temperature_stable() else "ramping"
        return f"{self.driver.get_temperature():.1f} C, {cooler}, {stable}"
