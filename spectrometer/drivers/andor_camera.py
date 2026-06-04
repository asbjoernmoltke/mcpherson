"""Andor camera drivers.

``AndorCamera`` wraps pylablib's ``AndorSDK2Camera``. pylablib (and the Andor
SDK DLLs) are imported lazily inside the class so this module loads cleanly on
machines without the SDK -- essential for offline development against
``DummyCamera``.

``DummyCamera`` simulates cooling dynamics (a temperature ramp toward the
setpoint and a stabilisation flag) and produces synthetic frames, so the full
acquisition path and the cooling/vacuum interlocks can be exercised with no
hardware.
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from ..utilities import log
from .base import CameraDriver

# Where the Andor SDK2 DLLs live; override via configuration if needed.
DEFAULT_ANDOR_SDK2_PATH = "C:/Program Files/Andor Driver Pack 2"

# --- This system's camera: Andor Newton DO920P-BEN-995 (SDK2) -------------
# Sensor: e2v CCD30-11, 1024 x 256 px, 26 um square pixels, 16-bit.
# Full-well ~457,768 e-/pixel; read noise ~5-30 e- (A/D rate + preamp dependent).
# Cooling: spec -100..-20 C, typical operating -80 C.
NEWTON_WIDTH = 1024
NEWTON_HEIGHT = 256
NEWTON_PIXEL_UM = 26.0
NEWTON_FULL_WELL_E = 457_768


class AndorCamera(CameraDriver):
    """Thin wrapper over pylablib ``AndorSDK2Camera``.

    Only the verbs the rest of the system needs are exposed; the cooling
    *policy* (vacuum interlock, controlled warm-up) lives in
    ``CameraController``, not here.
    """

    def __init__(self, *, sdk2_path: str = DEFAULT_ANDOR_SDK2_PATH,
                 idx: int = 0):
        self._sdk2_path = sdk2_path
        self._idx = idx
        self._cam = None  # type: ignore[var-annotated]

    def open(self) -> None:
        if self._cam is not None:
            return
        import pylablib as pll
        from pylablib.devices.Andor import AndorSDK2Camera

        pll.par["devices/dlls/andor_sdk2"] = self._sdk2_path
        # NOTE: do not force a warm setpoint / fan-off here. Cooling is driven
        # deliberately by CameraController after the vacuum interlock passes.
        self._cam = AndorSDK2Camera(idx=self._idx)
        log.info("AndorCamera opened.")

    def close(self) -> None:
        if self._cam is not None:
            self._cam.close()
            self._cam = None
            log.info("AndorCamera closed.")

    @property
    def is_connected(self) -> bool:
        return self._cam is not None

    def _require(self):
        if self._cam is None:
            raise RuntimeError("AndorCamera is not open.")
        return self._cam

    def get_status(self) -> str:
        if self._cam is None:
            return "Disconnected"
        try:
            return str(self._cam.get_status())
        except Exception as exc:  # pragma: no cover - hardware dependent
            return f"Error: {exc}"

    # --- cooling -------------------------------------------------------
    def set_temperature(self, setpoint_c: float) -> None:
        self._require().set_temperature(setpoint_c, enable_cooler=True)

    def get_temperature(self) -> float:
        return float(self._require().get_temperature())

    def get_temperature_setpoint(self) -> float:
        return float(self._require().get_temperature_setpoint())

    def is_temperature_stable(self) -> bool:
        return self._require().get_temperature_status() == "stabilized"

    def set_cooler(self, on: bool) -> None:
        self._require().set_cooler(on)

    def is_cooler_on(self) -> bool:
        return bool(self._require().is_cooler_on())

    def set_fan_mode(self, mode: str) -> None:
        self._require().set_fan_mode(mode)

    def get_fan_mode(self) -> str:
        return str(self._require().get_fan_mode())

    # --- acquisition config -------------------------------------------
    def set_exposure(self, seconds: float) -> None:
        self._require().set_exposure(seconds)

    def get_exposure(self) -> float:
        return float(self._require().get_exposure())

    def set_trigger_mode(self, mode: str) -> None:
        self._require().set_trigger_mode(mode)

    def set_internal_shutter(self, mode: str) -> None:
        self._require().set_shutter(mode)

    def get_detector_size(self) -> tuple[int, int]:
        w, h = self._require().get_detector_size()
        return int(w), int(h)

    # --- acquisition ---------------------------------------------------
    def grab(self, n_frames: int = 1, timeout: float = 5.0) -> np.ndarray:
        frames = self._require().grab(n_frames, frame_timeout=timeout)
        return np.asarray(frames)

    def start_acquisition(self) -> None:
        self._require().start_acquisition()

    def read_newest_image(self) -> Optional[np.ndarray]:
        img = self._require().read_newest_image()
        return None if img is None else np.asarray(img)

    def stop_acquisition(self) -> None:
        if self._cam is not None:
            self._cam.stop_acquisition()


class DummyCamera(CameraDriver):
    """Synthetic camera for offline development.

    Models a first-order temperature ramp toward the setpoint and a
    stabilisation flag, and produces frames with a few Gaussian emission
    peaks plus shot/dark noise (dark level rises with temperature).
    """

    AMBIENT_C = 21.0
    STABLE_TOL_C = 1.0
    RAMP_RATE_C_PER_S = 8.0  # simulated cooling/warming rate

    def __init__(self, *, width: int = NEWTON_WIDTH, height: int = NEWTON_HEIGHT):
        self._w = width
        self._h = height
        self._connected = False
        self._cooler_on = False
        self._fan_mode = "full"
        self._setpoint = self.AMBIENT_C
        self._temp = self.AMBIENT_C
        self._last_t = time.monotonic()
        self._exposure = 0.1
        self._trigger = "int"
        self._internal_shutter = "auto"
        self._acquiring = False
        self._rng = np.random.default_rng(0)
        # fixed synthetic peak positions (pixels) and amplitudes
        self._peaks = [(int(0.25 * width), 30000.0, 12.0),
                       (int(0.55 * width), 18000.0, 20.0),
                       (int(0.80 * width), 24000.0, 8.0)]

    # --- Driver lifecycle ---------------------------------------------
    def open(self) -> None:
        self._connected = True
        self._last_t = time.monotonic()
        log.info("DummyCamera opened.")

    def close(self) -> None:
        self._acquiring = False
        self._connected = False
        log.info("DummyCamera closed.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_status(self) -> str:
        if not self._connected:
            return "Disconnected"
        return "Acquiring" if self._acquiring else "Idle"

    # --- cooling simulation -------------------------------------------
    def _update_temp(self) -> None:
        now = time.monotonic()
        dt = now - self._last_t
        self._last_t = now
        target = self._setpoint if self._cooler_on else self.AMBIENT_C
        step = self.RAMP_RATE_C_PER_S * dt
        if abs(target - self._temp) <= step:
            self._temp = target
        else:
            self._temp += step if target > self._temp else -step

    def set_temperature(self, setpoint_c: float) -> None:
        self._setpoint = setpoint_c
        self._cooler_on = True
        log.info("DummyCamera: setpoint %.1f C, cooler on." % setpoint_c)

    def get_temperature(self) -> float:
        self._update_temp()
        return round(self._temp, 2)

    def get_temperature_setpoint(self) -> float:
        return self._setpoint

    def is_temperature_stable(self) -> bool:
        self._update_temp()
        return self._cooler_on and abs(self._temp - self._setpoint) <= self.STABLE_TOL_C

    def set_cooler(self, on: bool) -> None:
        self._cooler_on = on
        log.info("DummyCamera: cooler %s." % ("on" if on else "off"))

    def is_cooler_on(self) -> bool:
        return self._cooler_on

    def set_fan_mode(self, mode: str) -> None:
        self._fan_mode = mode

    def get_fan_mode(self) -> str:
        return self._fan_mode

    # --- acquisition config -------------------------------------------
    def set_exposure(self, seconds: float) -> None:
        self._exposure = max(1e-4, seconds)

    def get_exposure(self) -> float:
        return self._exposure

    def set_trigger_mode(self, mode: str) -> None:
        self._trigger = mode

    def set_internal_shutter(self, mode: str) -> None:
        self._internal_shutter = mode

    def get_detector_size(self) -> tuple[int, int]:
        return self._w, self._h

    # --- frame synthesis ----------------------------------------------
    def _synth_frame(self) -> np.ndarray:
        x = np.arange(self._w)
        spectrum = np.zeros(self._w, dtype=np.float64)
        for center, amp, sigma in self._peaks:
            spectrum += amp * np.exp(-0.5 * ((x - center) / sigma) ** 2)
        # dark level grows with temperature; cold camera = low background
        dark = 200.0 + 40.0 * max(0.0, self._temp)
        frame = np.tile(spectrum + dark, (self._h, 1))
        frame += self._rng.normal(0.0, np.sqrt(np.abs(frame) + 1.0))
        return np.clip(frame, 0, 65535).astype(np.uint16)

    def grab(self, n_frames: int = 1, timeout: float = 5.0) -> np.ndarray:
        time.sleep(min(self._exposure * n_frames, 0.2))
        return np.stack([self._synth_frame() for _ in range(n_frames)])

    def start_acquisition(self) -> None:
        self._acquiring = True

    def read_newest_image(self) -> Optional[np.ndarray]:
        if not self._acquiring:
            return None
        return self._synth_frame()

    def stop_acquisition(self) -> None:
        self._acquiring = False
