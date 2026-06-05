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

# Newton DO920P is 16-bit (ADC max 65535); flag frames near full scale as
# saturated. The sensor full-well is ~457,768 e-/pixel, but the ADC saturates
# at/around this count, so this is the practical per-pixel saturation guard.
SATURATION_LEVEL = 65000

# Andor Newton DO920P cooling spec: rated -100..-20 C, typical operating -80 C.
MIN_SETPOINT_C = -100.0
MAX_SETPOINT_C = -20.0
DEFAULT_SETPOINT_C = -80.0

# Reference ambient for the cooldown-progress estimate (the sensor starts near
# room temperature). Only used to render a progress fraction; not a control.
AMBIENT_REF_C = 21.0


class CameraController(Controller):
    def __init__(self, driver: CameraDriver, *,
                 vacuum_ok: Callable[[], bool],
                 warm_target_c: float = 10.0,
                 stable_timeout_s: float = 300.0,
                 cooling_fan_mode: str = "full",
                 abort: Optional[threading.Event] = None):
        super().__init__("Camera")
        self.driver = driver
        self._vacuum_ok = vacuum_ok
        self.warm_target_c = warm_target_c
        self.stable_timeout_s = stable_timeout_s
        # Fan mode while cooling. Default 'full' (safe for air-cooled deep
        # cooling); set 'off' only if the head is water-cooled. CONFIRM.
        self.cooling_fan_mode = cooling_fan_mode
        self._abort = abort or threading.Event()
        self.last_frame_saturated = False

    # --- cooling lifecycle --------------------------------------------
    def cooldown(self, setpoint_c: float) -> None:
        """Begin cooling to ``setpoint_c`` -- gated on the vacuum interlock.
        Clamped to the camera's rated range and turns the fan on first."""
        if not self._vacuum_ok():
            raise InterlockError(
                "Refusing to cool the camera: vacuum is not sufficient.")
        setpoint_c = max(MIN_SETPOINT_C, min(MAX_SETPOINT_C, setpoint_c))
        # Fan on before cooling hard (dissipates heat from the TE cooler).
        try:
            self.driver.set_fan_mode(self.cooling_fan_mode)
        except Exception as exc:  # pragma: no cover - hardware dependent
            log.warn("CameraController: could not set fan mode: %s" % exc)
        log.info("CameraController: cooling to %.1f C (fan=%s)."
                 % (setpoint_c, self.cooling_fan_mode))
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

    def cooldown_progress(self) -> float:
        """0..1 estimate of cooldown completion toward the setpoint.

        Returns 1.0 once stable, 0.0 if the cooler is off. The estimate is
        referenced to a nominal ambient (the start of a cooldown), so it is
        only meaningful while cooling -- it drives a progress bar, nothing
        safety-critical."""
        if not self.driver.is_cooler_on():
            return 0.0
        if self.driver.is_temperature_stable():
            return 1.0
        setpoint = self.driver.get_temperature_setpoint()
        temp = self.driver.get_temperature()
        span = AMBIENT_REF_C - setpoint
        if abs(span) < 1e-6:
            return 1.0
        frac = (AMBIENT_REF_C - temp) / span
        return float(max(0.0, min(1.0, frac)))

    # --- warm-up / shutdown -------------------------------------------
    # The warm-up is split into begin/poll/finish phases so the GUI can drive
    # it from the (non-blocking) status poll without freezing the worker
    # thread. ``safe_shutdown`` keeps a blocking convenience for scripts and
    # the app-teardown path.
    def begin_warmup(self) -> None:
        """Raise the setpoint to ``warm_target_c`` so the sensor warms while
        the cooler still runs (controlled, not a sudden cooler-off shock)."""
        log.info("CameraController: warm-up to %.1f C (cooler stays on)."
                 % self.warm_target_c)
        self.driver.set_temperature(self.warm_target_c)
        self._notify(self.status)

    def is_warm_enough(self) -> bool:
        return self.driver.get_temperature() >= self.warm_target_c - 1.0

    def finish_shutdown(self) -> None:
        """Disable the cooler once warm. Safe to call repeatedly."""
        self.driver.set_cooler(False)
        log.info("CameraController: cooler off at %.1f C."
                 % self.driver.get_temperature())
        self._notify(self.status)

    def safe_shutdown(self) -> None:
        """Blocking controlled warm-up then cooler-off (scripts / teardown)."""
        log.info("CameraController: safe shutdown -- warming to %.1f C first."
                 % self.warm_target_c)
        try:
            self.begin_warmup()
            deadline = time.monotonic() + self.stable_timeout_s
            while time.monotonic() < deadline:
                self._notify(self.status)
                if self.is_warm_enough():
                    break
                time.sleep(0.5)
            else:
                log.warn("CameraController: warm-up timed out; disabling "
                         "cooler anyway at %.1f C." % self.driver.get_temperature())
        finally:
            self.finish_shutdown()

    # --- acquisition config -------------------------------------------
    def configure(self, *, exposure_s: Optional[float] = None,
                  trigger_mode: Optional[str] = None,
                  internal_shutter: Optional[str] = None,
                  readout_index: Optional[int] = None,
                  preamp_index: Optional[int] = None,
                  em_gain: Optional[int] = None) -> None:
        if exposure_s is not None:
            self.driver.set_exposure(exposure_s)
        if trigger_mode is not None:
            self.driver.set_trigger_mode(trigger_mode)
        if internal_shutter is not None:
            self.driver.set_internal_shutter(internal_shutter)
        if readout_index is not None:
            self.driver.set_readout_rate(readout_index)
        if preamp_index is not None:
            self.driver.set_preamp_gain(preamp_index)
        if em_gain is not None:
            self.driver.set_em_gain(em_gain)

    # --- capability discovery (read by the GUI to build its controls) --
    def capabilities(self) -> dict:
        """Static-ish option lists for the config controls. Queried once the
        camera is open so dropdowns reflect the real device."""
        d = self.driver
        return {
            "trigger_modes": d.get_trigger_modes(),
            "trigger_mode": d.get_trigger_mode(),
            "internal_shutter_modes": d.get_internal_shutter_modes(),
            "internal_shutter": d.get_internal_shutter(),
            "readout_rates": d.get_readout_rates(),
            "readout_rate": d.get_readout_rate(),
            "preamp_gains": d.get_preamp_gains(),
            "preamp_gain": d.get_preamp_gain(),
            "em_gain_range": d.get_em_gain_range(),
            "em_gain": d.get_em_gain(),
        }

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
