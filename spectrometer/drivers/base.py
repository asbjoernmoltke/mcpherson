"""Abstract base classes for every hardware driver.

Each concrete driver (real or dummy) implements one of these interfaces. The
controllers (Layer 2) depend only on these ABCs, never on a concrete device,
so a ``Dummy*`` twin can be swapped in for fully offline development -- which
is mandatory before the expensive Andor camera is ever connected.

The interfaces are intentionally thin and synchronous: blocking I/O is fine
here because controllers/the acquisition engine run device calls on a
dedicated hardware thread, never on the GUI thread.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

# Discrete repetition rates (Hz) selectable on the Origami XP amplifier:
# 50 kHz, then 100..1000 kHz in 100 kHz steps. Default 50 kHz.
STANDARD_REP_RATES_HZ: tuple[float, ...] = tuple(
    r * 1e3 for r in (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000))


class Driver(ABC):
    """Common lifecycle shared by all drivers."""

    @abstractmethod
    def open(self) -> None:
        """Open/connect to the device. Idempotent where possible."""

    @abstractmethod
    def close(self) -> None:
        """Release the device. Must be safe to call multiple times."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    def get_status(self) -> str:
        """Short human-readable status string for the GUI."""

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class CameraDriver(Driver):
    """Andor-style scientific camera.

    Note the distinction between the camera's *internal* shutter
    (``set_internal_shutter``) and the external beam shutter handled by
    :class:`ShutterDriver`.
    """

    # --- cooling / safety-critical -------------------------------------
    @abstractmethod
    def set_temperature(self, setpoint_c: float) -> None:
        ...

    @abstractmethod
    def get_temperature(self) -> float:
        ...

    @abstractmethod
    def get_temperature_setpoint(self) -> float:
        ...

    @abstractmethod
    def is_temperature_stable(self) -> bool:
        ...

    @abstractmethod
    def set_cooler(self, on: bool) -> None:
        ...

    @abstractmethod
    def is_cooler_on(self) -> bool:
        ...

    @abstractmethod
    def set_fan_mode(self, mode: str) -> None:
        ...

    @abstractmethod
    def get_fan_mode(self) -> str:
        ...

    # --- acquisition config --------------------------------------------
    @abstractmethod
    def set_exposure(self, seconds: float) -> None:
        ...

    @abstractmethod
    def get_exposure(self) -> float:
        ...

    @abstractmethod
    def set_trigger_mode(self, mode: str) -> None:
        ...

    @abstractmethod
    def set_internal_shutter(self, mode: str) -> None:
        ...

    @abstractmethod
    def get_detector_size(self) -> tuple[int, int]:
        """(width, height) in pixels."""

    # --- acquisition ---------------------------------------------------
    @abstractmethod
    def grab(self, n_frames: int = 1, timeout: float = 5.0) -> np.ndarray:
        """Blocking acquisition of ``n_frames`` frames -> stacked ndarray."""

    @abstractmethod
    def start_acquisition(self) -> None:
        ...

    @abstractmethod
    def read_newest_image(self) -> Optional[np.ndarray]:
        """Latest frame from a running acquisition, or None if none ready."""

    @abstractmethod
    def stop_acquisition(self) -> None:
        ...

    # --- optional config enumeration (overridden where supported) -------
    # Concrete defaults report "no choices / unsupported" so simple cameras
    # and the offline path need not implement them; the GUI greys-out a
    # control whose option list is empty / range is None. Mirrors the
    # optional-capability pattern on LaserDriver.
    def get_trigger_modes(self) -> list[str]:
        """Selectable trigger modes (first = default)."""
        return ["int"]

    def get_trigger_mode(self) -> str:
        return "int"

    def get_internal_shutter_modes(self) -> list[str]:
        """Selectable internal-shutter modes."""
        return ["auto", "open", "closed"]

    def get_internal_shutter(self) -> str:
        return "auto"

    def get_readout_rates(self) -> list[str]:
        """A-D / horizontal readout-rate labels, fastest first. Empty if N/A."""
        return []

    def set_readout_rate(self, index: int) -> None:
        raise NotImplementedError("Readout-rate selection not supported.")

    def get_readout_rate(self) -> int:
        return 0

    def get_preamp_gains(self) -> list[str]:
        """Pre-amplifier gain labels. Empty if N/A."""
        return []

    def set_preamp_gain(self, index: int) -> None:
        raise NotImplementedError("Pre-amp gain selection not supported.")

    def get_preamp_gain(self) -> int:
        return 0

    def get_em_gain_range(self) -> Optional[tuple[int, int]]:
        """(min, max) EMCCD gain, or None on a conventional (non-EM) sensor."""
        return None

    def set_em_gain(self, value: int) -> None:
        raise NotImplementedError("EM gain not supported by this sensor.")

    def get_em_gain(self) -> Optional[int]:
        return None


class GratingDriver(Driver):
    """Grating scan controller (e.g. McPherson 789A-4).

    Positions are in motor steps; wavelength conversion lives in the
    calibration layer, not here.
    """

    @abstractmethod
    def home(self) -> bool:
        ...

    @abstractmethod
    def move_to(self, position: int, backlash: int = 0) -> None:
        ...

    @abstractmethod
    def move_relative(self, steps: int) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        """Immediate halt -- used by the E-stop path; must be fast."""

    @abstractmethod
    def get_position(self) -> int:
        ...

    @abstractmethod
    def is_moving(self) -> bool:
        ...

    @abstractmethod
    def is_homing(self) -> bool:
        ...


class ShutterDriver(Driver):
    """Beam shutter. Software-coordinated with the camera; concrete
    hardware is TBD, so only :class:`DummyShutter` exists for now."""

    @abstractmethod
    def open_shutter(self) -> None:
        ...

    @abstractmethod
    def close_shutter(self) -> None:
        ...

    @property
    @abstractmethod
    def is_open(self) -> bool:
        ...


class LaserDriver(Driver):
    """Pulsed laser. We only need enable/disable + status for the E-stop;
    the analog sync channel is a documented future hook (``read_sync``)."""

    @abstractmethod
    def enable(self) -> None:
        ...

    @abstractmethod
    def disable(self) -> None:
        """Used by the E-stop path; must be fast and independent of other
        device transactions."""

    @property
    @abstractmethod
    def is_enabled(self) -> bool:
        ...

    def read_sync(self) -> Optional[float]:
        """Future hook for the analog sync channel. Unused for now."""
        return None

    # --- optional capabilities (overridden by lasers that support them) ---
    # Defaults report "unsupported" so the GUI can grey-out controls and the
    # dummy/simple lasers need not implement them. The NKT driver overrides
    # all of these.
    @property
    def emission_stage(self) -> str:
        """'off' | 'seed' | 'preamp' | 'booster' (default: on/off only)."""
        return "booster" if self.is_enabled else "off"

    def set_power_percent(self, percent: float) -> None:
        raise NotImplementedError("Power control not supported by this laser.")

    def read_power_percent(self) -> Optional[float]:
        return None

    # Energy control (relative AOM scale expressed as pulse energy in uJ).
    @property
    def max_pulse_energy_uj(self) -> Optional[float]:
        """Full-scale pulse energy in uJ, or None if energy control is N/A."""
        return None

    def set_pulse_energy_uj(self, energy_uj: float) -> None:
        raise NotImplementedError("Energy control not supported by this laser.")

    def read_pulse_energy_uj(self) -> Optional[float]:
        """Energy setpoint (uJ) implied by the current relative AOM value."""
        return None

    def read_measured_pulse_energy_uj(self) -> Optional[float]:
        """Measured pulse energy (uJ) = measured avg power / rep rate."""
        return None

    def set_pulse_picker_ratio(self, ratio: int) -> None:
        raise NotImplementedError("Pulse picker not supported by this laser.")

    def read_pulse_picker_ratio(self) -> Optional[int]:
        return None

    def set_repetition_rate_hz(self, target_hz: float) -> float:
        raise NotImplementedError("Repetition-rate control not supported.")

    def read_repetition_rate_hz(self) -> Optional[float]:
        return None

    def allowed_rep_rates_hz(self) -> Optional[tuple[float, ...]]:
        """Discrete selectable repetition rates, or None if continuous/N/A."""
        return None


class VacuumDriver(Driver):
    """Read-only vacuum gauge.

    Vacuum is controlled manually on isolated hardware; software only reads
    the pressure to gate camera cooling. A control hook is intentionally
    omitted -- see ``read_pressure`` as the single source of truth.
    """

    @abstractmethod
    def read_pressure(self) -> float:
        """Current pressure in the gauge's native units (see ``units``)."""

    @property
    @abstractmethod
    def units(self) -> str:
        ...

    # --- optional read-only pump status (display only) ----------------
    def read_alerts(self) -> list[str]:
        """Active fault/alert strings from the controller (e.g. a pump
        over-temperature or over-pressure), or [] if all clear/unsupported."""
        return []

    def read_turbo_state(self) -> Optional[str]:
        """Turbo-pump status string for display, or None if unavailable."""
        return None

    def read_backing_state(self) -> Optional[str]:
        """Backing-pump status string for display, or None if unavailable."""
        return None

    # --- optional pump CONTROL (overridden by controllers that allow it) ---
    # Default: control unsupported. A controller that supports it implements
    # set_turbo/set_backing (raising on rejection) and the state-code reads.
    def supports_control(self) -> bool:
        return False

    def set_turbo(self, on: bool) -> None:
        raise NotImplementedError("Pump control not supported by this driver.")

    def set_backing(self, on: bool) -> None:
        raise NotImplementedError("Pump control not supported by this driver.")

    def set_turbo_standby(self, on: bool) -> None:
        """Put the turbo into standby (reduced set speed, still under vacuum)
        or back to full speed -- the gentle spin-down that does NOT vent."""
        raise NotImplementedError("Standby not supported by this driver.")

    def turbo_standby_active(self) -> Optional[bool]:
        """True if the turbo is in standby, False if not, None if unknown."""
        return None

    def turbo_state_code(self) -> Optional[int]:
        """Turbo pump state code (0 Stopped, 4 Running, 5 Accelerating, ...)."""
        return None

    def backing_state_code(self) -> Optional[int]:
        return None
