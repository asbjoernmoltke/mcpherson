"""Tests for persistent settings (load/save round-trip, defaults, wiring)."""
from __future__ import annotations

import json

from spectrometer.core.settings import Settings
from spectrometer.core.storage import SaveOptions
from spectrometer.core.system import build_system_from_settings


def test_defaults():
    s = Settings()
    assert s.grating_name == "1200g/mm"
    assert s.cooling_setpoint_c == -80.0
    assert s.save_stitched is True
    assert s.save_format == "auto"


def test_save_load_roundtrip(tmp_path):
    p = str(tmp_path / "settings.json")
    s = Settings(grating_port="COM9", cooling_setpoint_c=-90.0,
                 scan_wl_min=300.0, scan_wl_max=420.0, n_frames=5,
                 save_filename="run", save_format="hdf5")
    s.save(p)
    loaded = Settings.load(p)
    assert loaded.grating_port == "COM9"
    assert loaded.cooling_setpoint_c == -90.0
    assert loaded.scan_wl_min == 300.0 and loaded.scan_wl_max == 420.0
    assert loaded.n_frames == 5
    assert loaded.save_filename == "run" and loaded.save_format == "hdf5"


def test_load_missing_file_returns_defaults(tmp_path):
    loaded = Settings.load(str(tmp_path / "nope.json"))
    assert loaded.grating_name == "1200g/mm"


def test_load_ignores_unknown_and_keeps_missing(tmp_path):
    p = str(tmp_path / "s.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"grating_port": "COM12", "obsolete_key": 123}, fh)
    loaded = Settings.load(p)
    assert loaded.grating_port == "COM12"        # known key applied
    assert loaded.exposure_s == 0.1              # missing key keeps default
    assert not hasattr(loaded, "obsolete_key")   # unknown ignored


def test_update_from_save_options():
    s = Settings()
    opts = SaveOptions(folder="/tmp/x", filename="abc", fmt="csv",
                       save_image_2d=True, save_spectrum_1d=False,
                       save_stitched=True)
    s.update_from_save_options(opts)
    assert s.save_folder == "/tmp/x" and s.save_filename == "abc"
    assert s.save_format == "csv" and s.save_image_2d is True


def test_build_system_from_settings_dummy():
    s = Settings(grating_name="2400g/mm", cooling_threshold=5e-5)
    sysm = build_system_from_settings(s, dummy=True)
    sysm.open_all()
    try:
        assert "2400" in sysm.calibration.name
        assert sysm.vacuum.cooling_threshold == 5e-5
    finally:
        sysm.close_all()
