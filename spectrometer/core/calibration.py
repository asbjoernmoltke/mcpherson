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


# Default offline calibrations per grating: ~200 nm window over 2048 pixels.
# These are placeholders for development; replace with measured calibrations.
def default_calibration(grating: str = "1200g/mm", n_pixels: int = 2048) -> LinearCalibration:
    presets = {
        "1200g/mm": dict(wl0_nm=200.0, nm_per_step=1.0e-3, nm_per_pixel=200.0 / n_pixels),
        "2400g/mm": dict(wl0_nm=200.0, nm_per_step=0.5e-3, nm_per_pixel=100.0 / n_pixels),
        "599.45g/mm": dict(wl0_nm=200.0, nm_per_step=2.0e-3, nm_per_pixel=400.0 / n_pixels),
    }
    if grating not in presets:
        raise ValueError(f"Unknown grating: {grating}")
    return LinearCalibration(name=grating, n_pixels=n_pixels, **presets[grating])
