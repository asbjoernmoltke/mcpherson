"""Grating calibration: position (motor steps) <-> wavelength (nm).

At any grating position the detector sees a ~200 nm window; as the position
scans, the window shifts. The calibration provides, per grating:

* ``center_wavelength(position)``  -- wavelength at the detector centre
* ``wavelength_axis(position)``    -- wavelength at every pixel (length = width)
* ``position_to_wavelength_range`` -- (min, max) seen at a position
* ``wavelength_to_position``       -- inverse of ``center_wavelength``
* ``scan_positions``               -- tile positions to cover a wavelength span

This replaces the hard-coded example splines in the old ``spectrometer.py``.
A linear model is provided (and used for the dummy/offline path); real
calibrations can be loaded from JSON via :meth:`LinearCalibration.from_file`,
and a spline-based subclass can be added later without touching callers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np


@dataclass
class LinearCalibration:
    """Linear-dispersion calibration for one grating.

    ``center_wavelength(pos) = wl0_nm + nm_per_step * pos``
    ``wavelength(pixel)      = center + (pixel - (N-1)/2) * nm_per_pixel``
    """
    name: str
    n_pixels: int
    wl0_nm: float           # centre wavelength at position 0
    nm_per_step: float      # dispersion of the scan mechanism
    nm_per_pixel: float     # dispersion across the detector
    position_limits: tuple[int, int] = (0, 1_000_000)

    # --- forward maps --------------------------------------------------
    def center_wavelength(self, position: float) -> float:
        return self.wl0_nm + self.nm_per_step * position

    def wavelength_axis(self, position: float) -> np.ndarray:
        pixels = np.arange(self.n_pixels)
        offset = (pixels - (self.n_pixels - 1) / 2.0) * self.nm_per_pixel
        return self.center_wavelength(position) + offset

    @property
    def window_width_nm(self) -> float:
        return self.n_pixels * self.nm_per_pixel

    def position_to_wavelength_range(self, position: float) -> tuple[float, float]:
        axis = self.wavelength_axis(position)
        return float(axis.min()), float(axis.max())

    def wavelength_limits(self) -> tuple[float, float]:
        """(min, max) centre wavelength reachable within ``position_limits``.

        ``center_wavelength`` is monotonic in position, so the limits are the
        centre wavelengths at the two ends (ordered, since ``nm_per_step`` may
        be negative)."""
        lo, hi = self.position_limits
        a = self.center_wavelength(lo)
        b = self.center_wavelength(hi)
        return (min(a, b), max(a, b))

    # --- inverse map ---------------------------------------------------
    def wavelength_to_position(self, wavelength_nm: float) -> int:
        if self.nm_per_step == 0:
            raise ValueError("nm_per_step is zero; calibration is degenerate.")
        pos = (wavelength_nm - self.wl0_nm) / self.nm_per_step
        lo, hi = self.position_limits
        return int(round(min(max(pos, lo), hi)))

    # --- scan planning -------------------------------------------------
    def scan_positions(self, wl_min: float, wl_max: float, *,
                       overlap: float = 0.15) -> np.ndarray:
        """Positions whose ~200 nm windows tile ``[wl_min, wl_max]`` with the
        given fractional ``overlap`` (0..1) between adjacent windows."""
        if wl_max < wl_min:
            wl_min, wl_max = wl_max, wl_min
        # Use the *actual* wavelength span of the detector (pixel 0..N-1),
        # not the nominal N*nm_per_pixel, so the window edges line up with
        # real pixels and the requested span is fully covered.
        covered = (self.n_pixels - 1) * self.nm_per_pixel
        half = covered / 2.0
        step_nm = covered * (1.0 - overlap)
        if step_nm <= 0:
            raise ValueError("overlap too large; non-positive step.")
        # Centre the first/last windows so the requested span is fully covered.
        centers = np.arange(wl_min + half, wl_max - half + step_nm, step_nm)
        if centers.size == 0:  # span narrower than one window
            centers = np.array([(wl_min + wl_max) / 2.0])
        positions = np.array([self.wavelength_to_position(c) for c in centers])
        return np.unique(positions)

    # --- persistence ---------------------------------------------------
    def to_file(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.__dict__ | {"position_limits": list(self.position_limits)},
                      fh, indent=2)

    @classmethod
    def from_file(cls, path: str) -> "LinearCalibration":
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["position_limits"] = tuple(data["position_limits"])
        return cls(**data)


# --- McPherson 234/302 monochromator (200 mm f.l., f/4.5) ----------------
# Derived from the instrument's grating table + the 789A-4 scan drive:
#   nm_per_step   = nm_per_motor_rev / STEPS_PER_MOTOR_REV
#   nm_per_pixel  = dispersion_nm_per_mm * PIXEL_MM   (Newton 26 um pixels)
# Home wavelength sits at position 0 after homing. Two factors are still to be
# verified with a calibration lamp (configurable here, not assumed in stone):
#   STEPS_PER_MOTOR_REV: the homing arithmetic (-108000 = "3 rev", +72000 =
#       "2 rev") implies 36000 controller-steps/rev (half-stepping of the
#       18000 motor-step/rev drive). A 2x error here scales wavelength.
#   DIRECTION: sign of nm per +step (does +steps raise or lower wavelength).
STEPS_PER_MOTOR_REV = 36000
DIRECTION = +1
PIXEL_MM = 0.026  # Newton DO920P 26 um pixels

# grating -> (nm/motor-rev, dispersion nm/mm, home wavelength nm, (wl_min, wl_max))
MCPHERSON_234_302 = {
    "2400g/mm": (1.0, 2.0, 279.70, (30.0, 275.0)),
    "1200g/mm": (2.0, 4.0, 279.70, (30.0, 550.0)),
    "599.45g/mm": (4.0, 8.0, 279.82, (30.0, 1100.0)),
}


def mcpherson_234_302(grating: str = "1200g/mm", *, n_pixels: int = 1024,
                      steps_per_motor_rev: int = STEPS_PER_MOTOR_REV,
                      direction: int = DIRECTION) -> LinearCalibration:
    """Calibration for the McPherson 234/302 (s/n 302438) from its spec sheet."""
    if grating not in MCPHERSON_234_302:
        raise ValueError(f"Unknown grating: {grating}")
    nm_per_rev, disp_nm_per_mm, home_wl, (wl_lo, wl_hi) = MCPHERSON_234_302[grating]
    nm_per_step = direction * nm_per_rev / steps_per_motor_rev
    nm_per_pixel = disp_nm_per_mm * PIXEL_MM
    # Step positions for the wavelength range (home at position 0).
    p_lo = int((wl_lo - home_wl) / nm_per_step)
    p_hi = int((wl_hi - home_wl) / nm_per_step)
    return LinearCalibration(
        name=f"234/302 {grating}", n_pixels=n_pixels, wl0_nm=home_wl,
        nm_per_step=nm_per_step, nm_per_pixel=nm_per_pixel,
        position_limits=(min(p_lo, p_hi), max(p_lo, p_hi)))


# Default calibration entry point (used by the system builder).
def default_calibration(grating: str = "1200g/mm", n_pixels: int = 1024) -> LinearCalibration:
    return mcpherson_234_302(grating, n_pixels=n_pixels)


def available_gratings() -> list[str]:
    """Installed-grating choices for the 234/302 (for the GUI selector)."""
    return list(MCPHERSON_234_302.keys())
