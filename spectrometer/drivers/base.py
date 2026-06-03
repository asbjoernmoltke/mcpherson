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
