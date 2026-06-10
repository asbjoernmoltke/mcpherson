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
        self._cam = AndorSDK2Camera(idx=self._idx)
        # SAFETY: pylablib/the SDK comes up with the cooler ENABLED at its last
        # setpoint (observed on hw 2026-06-10: cooler on, -35 C, on every open).
        # Cooling must only happen via the vacuum-gated CameraController.cooldown,
        # so if the sensor is WARM we force the cooler off on connect -- otherwise
        # merely opening the camera silently cools a warm sensor with no vacuum.
        # A genuinely COLD camera (<5 C) is left untouched so we never abruptly
        # warm it; the controller handles the cold-reconnect / vacuum-lost case.
        try:
            if self._cam.is_cooler_on() and float(self._cam.get_temperature()) > 5.0:
                self._cam.set_cooler(False)
                log.warn("AndorCamera: cooler was ON at open with a warm sensor "
                         "-> forced OFF (cooling is vacuum-gated via cooldown()).")
        except Exception as exc:  # pragma: no cover - hardware dependent
            log.error("AndorCamera: could not enforce cooler-off on open: %s" % exc)
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

    # --- config enumeration --------------------------------------------
    # Best-effort mappings onto pylablib's AndorSDK2Camera API. The Andor amp
    # mode is a (channel, oamp, hsspeed, preamp) tuple; we expose the A-D
    # readout rate (hsspeed) and pre-amp gain as independent dropdowns and set
    # them via ``set_amp_mode`` (leaving the other axes at their current/default
    # value). VERIFY ON BENCH: index<->mode mapping and available combinations.
    def _amp_modes(self):
        try:
            return list(self._require().get_all_amp_modes())
        except Exception as exc:  # pragma: no cover - hardware dependent
            log.warn("AndorCamera: get_all_amp_modes failed: %s" % exc)
            return []

    def get_trigger_modes(self) -> list[str]:
        try:
            return list(self._require().get_supported_trigger_modes())
        except Exception:  # pragma: no cover - hardware dependent
            return ["int", "ext", "ext_start", "ext_exposure"]

    def get_trigger_mode(self) -> str:
        try:
            return str(self._require().get_trigger_mode())
        except Exception:  # pragma: no cover
            return "int"

    def get_internal_shutter(self) -> str:
        try:
            return str(self._require().get_shutter())
        except Exception:  # pragma: no cover
            return "auto"

    def get_readout_rates(self) -> list[str]:
        seen, labels = {}, []
        for m in self._amp_modes():
            hz = getattr(m, "hsspeed", None)
            if hz is not None and hz not in seen:
                seen[hz] = True
                mhz = getattr(m, "hsspeed_MHz", None)
                labels.append("%.2f MHz" % mhz if mhz else "rate %d" % hz)
        return labels

    def set_readout_rate(self, index: int) -> None:
        try:
            self._require().set_amp_mode(hsspeed=index)
        except Exception as exc:  # pragma: no cover - hardware dependent
            log.warn("AndorCamera: set readout rate failed: %s" % exc)

    def get_readout_rate(self) -> int:
        try:
            return int(self._require().get_amp_mode().hsspeed)
        except Exception:  # pragma: no cover
            return 0

    def get_preamp_gains(self) -> list[str]:
        seen, labels = {}, []
        for m in self._amp_modes():
            pa = getattr(m, "preamp", None)
            if pa is not None and pa not in seen:
                seen[pa] = True
                gain = getattr(m, "preamp_gain", None)
                labels.append("%.1fx" % gain if gain else "preamp %d" % pa)
        return labels

    def set_preamp_gain(self, index: int) -> None:
        try:
            self._require().set_amp_mode(preamp=index)
        except Exception as exc:  # pragma: no cover - hardware dependent
            log.warn("AndorCamera: set preamp gain failed: %s" % exc)

    def get_preamp_gain(self) -> int:
        try:
            return int(self._require().get_amp_mode().preamp)
        except Exception:  # pragma: no cover
            return 0

    def get_em_gain_range(self) -> Optional[tuple[int, int]]:
        # Only EMCCD Newtons expose EM gain; DO920P is conventional. Probe and
        # return None if unsupported.
        try:
            lo, hi = self._require().get_EMCCD_gain_range()
            return int(lo), int(hi)
        except Exception:  # pragma: no cover - conventional CCD / unsupported
            return None

    def set_em_gain(self, value: int) -> None:
        self._require().set_EMCCD_gain(int(value))

    def get_em_gain(self) -> Optional[int]:
        try:
            return int(self._require().get_EMCCD_gain()[0])
        except Exception:  # pragma: no cover
            return None

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
        # Config enumerations mirror what a Newton DO920P (conventional CCD)
        # exposes: several A-D readout rates and pre-amp gains, no EM gain.
        self._trigger_modes = ["int", "ext", "ext_start", "ext_exposure"]
        self._shutter_modes = ["auto", "open", "closed"]
        self._readout_rates = ["3.0 MHz", "1.0 MHz", "0.05 MHz"]
        self._readout_index = 0
        self._preamp_gains = ["1.0x", "2.0x", "4.0x"]
        self._preamp_index = 0
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

    # --- config enumeration (offline-complete) ------------------------
    def get_trigger_modes(self) -> list[str]:
        return list(self._trigger_modes)

    def get_trigger_mode(self) -> str:
        return self._trigger

    def get_internal_shutter_modes(self) -> list[str]:
        return list(self._shutter_modes)

    def get_internal_shutter(self) -> str:
        return self._internal_shutter

    def get_readout_rates(self) -> list[str]:
        return list(self._readout_rates)

    def set_readout_rate(self, index: int) -> None:
        self._readout_index = int(np.clip(index, 0, len(self._readout_rates) - 1))

    def get_readout_rate(self) -> int:
        return self._readout_index

    def get_preamp_gains(self) -> list[str]:
        return list(self._preamp_gains)

    def set_preamp_gain(self, index: int) -> None:
        self._preamp_index = int(np.clip(index, 0, len(self._preamp_gains) - 1))

    def get_preamp_gain(self) -> int:
        return self._preamp_index

    # DO920P is a conventional CCD -> no EM gain (base default None applies).

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
