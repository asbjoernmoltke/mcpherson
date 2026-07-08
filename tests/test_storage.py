"""Tests for data saving: metadata, CSV/HDF5 writers, options, record loop."""
from __future__ import annotations

import os

import numpy as np
import pytest

from spectrometer.core import storage
from spectrometer.core.storage import (Hdf5Recorder, SaveOptions,
                                       collect_metadata, format_hms, parse_hms,
                                       write_spectrum_csv)
from spectrometer.core.system import build_system


# --- time helpers -----------------------------------------------------
def test_parse_and_format_hms():
    assert parse_hms("01:02:03") == pytest.approx(3723)
    assert parse_hms("00:00:05") == pytest.approx(5)
    assert parse_hms("90") == pytest.approx(90)        # bare seconds
    assert format_hms(3723) == "01:02:03"


# --- options ----------------------------------------------------------
def test_options_resolved_format():
    assert SaveOptions("f", "n").is_single()
    assert SaveOptions("f", "n").resolved_format() == "csv"           # single
    assert SaveOptions("f", "n", stop_count=3).resolved_format() == "hdf5"
    assert SaveOptions("f", "n", record_type="frames").resolved_format() == "hdf5"
    assert SaveOptions("f", "n", fmt="hdf5").resolved_format() == "hdf5"
    assert SaveOptions("f", "n", stop_count=3, fmt="csv").resolved_format() == "csv"


# --- metadata ---------------------------------------------------------
def test_collect_metadata_has_expected_keys():
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        m = collect_metadata(sys)
        assert m["grating"] and "nm_per_step" in m
        assert m["detector_size"] == [1024, 256]
        assert "laser_power_pct" in m and "vacuum_pressure" in m
        assert "timestamp" in m
    finally:
        sys.close_all()


# --- CSV --------------------------------------------------------------
def test_write_spectrum_csv_with_header(tmp_path):
    p = str(tmp_path / "s.csv")
    wl = np.linspace(300.0, 400.0, 10)
    y = np.arange(10.0)
    write_spectrum_csv(p, wl, y, metadata={"grating": "1200g/mm", "exposure_s": 0.1})
    text = open(p, encoding="utf-8").read()
    assert "# grating: 1200g/mm" in text
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and not ln.startswith("#")]
    assert lines[0] == "wavelength_nm,intensity"
    data = np.array([[float(x) for x in ln.split(",")] for ln in lines[1:]])
    assert data.shape == (10, 2)
    assert data[-1, 1] == pytest.approx(9.0)


def test_csv_separate_metadata_sidecar(tmp_path):
    p = str(tmp_path / "s.csv")
    write_spectrum_csv(p, np.arange(3.0), np.arange(3.0),
                       metadata={"grating": "x"}, separate_metadata=True)
    assert os.path.exists(str(tmp_path / "s.info.json"))
    assert "# grating" not in open(p, encoding="utf-8").read()


# --- HDF5 -------------------------------------------------------------
def test_hdf5_recorder_series(tmp_path):
    h5py = pytest.importorskip("h5py")
    p = str(tmp_path / "r.h5")
    rec = Hdf5Recorder(p, {"grating": "g", "detector_size": [1024, 256],
                           "laser_power_pct": None}, save_metadata=True)
    rec.append_spectrum(np.arange(5.0), np.arange(5.0), {"index": 0})
    rec.append_spectrum(np.arange(5.0), np.arange(5.0) + 1, {"index": 1})
    rec.close()
    with h5py.File(p, "r") as f:
        assert f.attrs["grating"] == "g"
        assert list(f.attrs["detector_size"]) == [1024, 256]
        assert "scan_0000" in f and "scan_0001" in f
        assert f["scan_0001"].attrs["index"] == 1
        assert list(f["scan_0000"]["intensity"][:]) == [0, 1, 2, 3, 4]


# --- record loop via the worker (dummy) -------------------------------
@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _worker(system):
    from spectrometer.gui.worker import AcquisitionWorker
    return AcquisitionWorker(system)


def test_record_single_scan_writes_csv(qapp, tmp_path):
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _worker(sys)
        sys.grating.home()                 # scans need a homed reference
        opts = SaveOptions(folder=str(tmp_path), filename="run", fmt="auto",
                           record_type="scans", stop_mode="count", stop_count=1,
                           wl_min=350.0, wl_max=450.0)
        path = w._run_recording(opts)
        assert path.endswith(".csv") and os.path.exists(path)
    finally:
        sys.close_all()


def test_options_force_hdf5_for_2d_image():
    o = SaveOptions("f", "n", fmt="csv", save_image_2d=True)
    assert o.resolved_format() == "hdf5"          # 2-D forces HDF5


def test_record_nothing_selected_raises(qapp, tmp_path):
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _worker(sys)
        opts = SaveOptions(folder=str(tmp_path), filename="x", save_stitched=False)
        with pytest.raises(Exception):
            w._run_recording(opts)
    finally:
        sys.close_all()


def test_record_scan_with_shots_image_and_spectrum(qapp, tmp_path):
    h5py = pytest.importorskip("h5py")
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _worker(sys)
        sys.grating.home()                 # scans need a homed reference
        opts = SaveOptions(folder=str(tmp_path), filename="shots", fmt="hdf5",
                           record_type="scans", stop_mode="count", stop_count=1,
                           wl_min=350.0, wl_max=420.0, save_image_2d=True,
                           save_spectrum_1d=True, save_stitched=True)
        path = w._run_recording(opts)
        with h5py.File(path, "r") as f:
            g = f["scan_0000"]
            assert "stitched_intensity" in g
            shots = [k for k in g.keys() if k.startswith("shot_")]
            assert shots
            sg = g[shots[0]]
            assert sg["image"].ndim == 2 and "spectrum" in sg and "wavelength_nm" in sg
    finally:
        sys.close_all()


def test_record_scan_series_writes_hdf5(qapp, tmp_path):
    h5py = pytest.importorskip("h5py")
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _worker(sys)
        sys.grating.home()                 # scans need a homed reference
        opts = SaveOptions(folder=str(tmp_path), filename="series", fmt="auto",
                           record_type="scans", stop_mode="count", stop_count=3,
                           wl_min=350.0, wl_max=450.0)
        path = w._run_recording(opts)
        assert path.endswith(".h5")
        with h5py.File(path, "r") as f:
            scans = [k for k in f.keys() if k.startswith("scan_")]
            assert len(scans) == 3
    finally:
        sys.close_all()
