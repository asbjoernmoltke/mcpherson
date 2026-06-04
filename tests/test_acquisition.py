"""Tests for calibration, the stitch math, and an end-to-end dummy scan."""
from __future__ import annotations

import numpy as np
import pytest

from spectrometer.core.acquisition import reduce_frames, stitch_segments
from spectrometer.core.calibration import LinearCalibration, default_calibration
from spectrometer.core.system import build_system


# --- calibration ------------------------------------------------------
def test_linear_calibration_roundtrip():
    # Real McPherson 234/302 1200 g/mm calibration (1024 px Newton).
    cal = default_calibration("1200g/mm")
    assert cal.n_pixels == 1024
    pos = 50_000
    wl = cal.center_wavelength(pos)
    assert cal.wavelength_to_position(wl) == pytest.approx(pos, abs=1)
    assert cal.wavelength_axis(pos).size == 1024
    lo, hi = cal.position_to_wavelength_range(pos)
    assert lo < wl < hi
    # 1200 g/mm: 4 nm/mm * 0.026 mm/px * 1024 px ~= 106.5 nm window.
    assert cal.window_width_nm == pytest.approx(0.104 * 1024, rel=1e-6)
    # Home wavelength sits at position 0.
    assert cal.center_wavelength(0) == pytest.approx(279.70)


def test_scan_positions_cover_range_with_overlap():
    cal = default_calibration("1200g/mm")
    # Within the 1200 g/mm physical range (30-550 nm).
    positions = cal.scan_positions(300.0, 500.0, overlap=0.2)
    assert positions.size >= 2
    ranges = [cal.position_to_wavelength_range(p) for p in positions]
    assert min(r[0] for r in ranges) <= 300.0
    assert max(r[1] for r in ranges) >= 500.0


# --- frame reduction --------------------------------------------------
def test_reduce_frames_shapes():
    frames = np.ones((3, 512, 2048), dtype=np.uint16) * 7
    spec = reduce_frames(frames)
    assert spec.shape == (2048,)
    assert spec == pytest.approx(7.0)


# --- stitch math (the bug-prone part) ---------------------------------
def test_stitch_recovers_known_function_across_overlapping_windows():
    """Two overlapping windows sampling the same f(wl) must stitch back to
    f on the output grid (overlap averaged, no discontinuity)."""
    def f(wl):
        return 1000.0 + 500.0 * np.sin(wl / 10.0)

    wl_a = np.linspace(300.0, 500.0, 2048)
    wl_b = np.linspace(450.0, 650.0, 2048)  # overlaps a in [450, 500]
    segments = [(wl_a, f(wl_a)), (wl_b, f(wl_b))]

    grid, stitched = stitch_segments(segments, delta_nm=0.1)

    assert grid[0] == pytest.approx(300.0, abs=0.2)
    assert grid[-1] == pytest.approx(650.0, abs=0.2)
    assert np.all(np.diff(grid) > 0)
    assert np.isfinite(stitched).all()
    # values match the underlying function
    assert np.allclose(stitched, f(grid), atol=5.0)


def test_stitch_averages_overlap():
    # Same wavelengths, different intensities -> average in the shared bins.
    wl = np.linspace(400.0, 401.0, 11)
    seg1 = (wl, np.full_like(wl, 100.0))
    seg2 = (wl, np.full_like(wl, 300.0))
    grid, stitched = stitch_segments([seg1, seg2], delta_nm=0.1)
    assert np.allclose(stitched, 200.0, atol=1e-6)


# --- end-to-end dummy scan -------------------------------------------
def test_dummy_scan_runs_uncooled_and_covers_range():
    # Cooling is NOT required to acquire (it only reduces shot noise); the
    # scan must run with the camera at ambient.
    sys = build_system(dummy=True, cooling_threshold=1.0e-4)
    sys.open_all()
    try:
        assert not sys.camera.is_cooled       # camera is warm
        assert sys.safety.can_acquire         # ...but acquisition is allowed

        progress = []
        sys.engine.on_progress = lambda i, n: progress.append((i, n))
        sys.engine.n_frames = 1

        grid, spectrum = sys.engine.scan(350.0, 500.0)   # within 1200 g/mm range

        assert grid[0] <= 360.0 and grid[-1] >= 490.0
        assert np.isfinite(spectrum).all()
        assert progress and progress[-1][0] == progress[-1][1]
        assert not sys.shutter.is_open  # shutter closed after scan
    finally:
        sys.close_all()


def test_single_grab_works_without_cooling():
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        assert not sys.camera.is_cooled
        wl, intensity = sys.engine.single()
        assert intensity.size == 1024 and np.isfinite(intensity).all()  # Newton width
    finally:
        sys.close_all()
