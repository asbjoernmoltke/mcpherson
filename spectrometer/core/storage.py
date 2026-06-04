"""Data storage: flexible metadata + spectrum/frame writers (CSV / HDF5).

Design goals (per the saving spec):
* **Metadata is a plain dict** (`collect_metadata`) embedded as a CSV header or
  HDF5 attributes (or a sidecar info file). Adding a new parameter never
  requires touching the writers -- they serialise whatever keys are present.
* **Format is optional**, defaulting to **CSV for a single** spectrum/frame and
  **HDF5 for repeated** measurements.

The recording *loop* (stop/cadence modes) lives in the GUI worker; this module
provides the building blocks: `SaveOptions`, `collect_metadata`, the single-file
writers, and a `Recorder` for a series.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np


# --- time helpers -----------------------------------------------------
def parse_hms(text: str) -> float:
    """'hh:mm:ss' (or 'mm:ss' / 'ss') -> seconds."""
    parts = [p for p in str(text).strip().split(":") if p != ""]
    if not parts:
        return 0.0
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts[-3], parts[-2], parts[-1]
    return h * 3600.0 + m * 60.0 + s


def format_hms(seconds: float) -> str:
    seconds = int(round(max(0.0, seconds)))
    return "%02d:%02d:%02d" % (seconds // 3600, (seconds % 3600) // 60,
                               seconds % 60)


# --- save options -----------------------------------------------------
@dataclass
class SaveOptions:
    folder: str
    filename: str
    fmt: str = "auto"               # "auto" | "csv" | "hdf5"
    record_type: str = "scans"      # "scans" | "frames"
    # scans: stop after a count or a duration
    stop_mode: str = "count"        # "count" | "duration"
    stop_count: int = 1
    stop_duration_s: float = 0.0
    # frames: cadence = every Nth frame or one every interval (runs until stop)
    cadence_mode: str = "every_nth"  # "every_nth" | "every_interval"
    cadence_n: int = 1
    cadence_interval_s: float = 0.0
    # scan wavelength range (for record_type == "scans")
    wl_min: float = 350.0
    wl_max: float = 500.0
    # what to save (tickboxes):
    save_image_2d: bool = False      # (a) raw 2-D image per shot
    save_spectrum_1d: bool = False   # (b) raw 1-D spectrum per shot
    save_stitched: bool = True       # (c) stitched 1-D spectrum per scan
    save_metadata: bool = True
    metadata_separate: bool = False

    def content_selected(self) -> bool:
        return self.save_image_2d or self.save_spectrum_1d or self.save_stitched

    def is_single(self) -> bool:
        """A single scan with count==1 -> single-file (CSV by default)."""
        return (self.record_type == "scans"
                and self.stop_mode == "count" and self.stop_count == 1)

    def resolved_format(self) -> str:
        # 2-D image stacks can't go in CSV -> force HDF5.
        if self.save_image_2d:
            return "hdf5"
        if self.fmt != "auto":
            return self.fmt
        return "csv" if self.is_single() else "hdf5"

    def base_path(self) -> str:
        name = self.filename or "spectrum"
        return os.path.join(self.folder, name)


# --- metadata ---------------------------------------------------------
def collect_metadata(system, *, extra: Optional[dict] = None) -> dict:
    """Snapshot every relevant setting into a flat dict. Each read is guarded
    so a flaky device can't abort the capture."""
    def safe(fn):
        try:
            return fn()
        except Exception:
            return None

    cal = system.calibration
    meta: dict = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "instrument": "McPherson 234/302 + Andor Newton DO920P",
        "grating": cal.name,
        "nm_per_step": cal.nm_per_step,
        "nm_per_pixel": cal.nm_per_pixel,
        "home_wavelength_nm": cal.wl0_nm,
        "grating_position_steps": safe(lambda: system.grating.position),
        "exposure_s": safe(lambda: system.devices.camera.get_exposure()),
        "camera_temperature_c": safe(lambda: system.camera.temperature),
        "camera_cooler_on": safe(lambda: system.devices.camera.is_cooler_on()),
        "detector_size": safe(lambda: list(system.devices.camera.get_detector_size())),
        "laser_emission_stage": safe(lambda: system.laser.emission_stage),
        "laser_power_pct": safe(lambda: system.laser.read_power_percent()),
        "laser_rep_rate_hz": safe(lambda: system.laser.read_repetition_rate_hz()),
        "laser_pulse_picker": safe(lambda: system.laser.read_pulse_picker_ratio()),
        "vacuum_pressure": safe(lambda: system.vacuum.pressure),
        "vacuum_units": safe(lambda: system.vacuum.units),
        "shutter_open": safe(lambda: system.shutter.is_open),
    }
    if extra:
        meta.update(extra)
    return meta


def _metadata_header_lines(metadata: dict) -> list[str]:
    return ["# %s: %s" % (k, v) for k, v in metadata.items()]


def write_metadata_sidecar(path: str, metadata: dict) -> str:
    """Write metadata to a sibling JSON file; returns its path."""
    sidecar = os.path.splitext(path)[0] + ".info.json"
    with open(sidecar, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2, default=str)
    return sidecar


# --- single-file CSV writers -----------------------------------------
def write_spectrum_csv(path: str, wavelength: np.ndarray, intensity: np.ndarray,
                       *, metadata: Optional[dict] = None,
                       separate_metadata: bool = False) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    header_lines = []
    if metadata and not separate_metadata:
        header_lines = _metadata_header_lines(metadata)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        for line in header_lines:
            fh.write(line + "\n")
        fh.write("wavelength_nm,intensity\n")
        for w, i in zip(np.asarray(wavelength), np.asarray(intensity)):
            fh.write("%.6f,%.6f\n" % (w, i))
    if metadata and separate_metadata:
        write_metadata_sidecar(path, metadata)


def write_frame_csv(path: str, frame: np.ndarray, *,
                    metadata: Optional[dict] = None,
                    separate_metadata: bool = False) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    header = "\n".join(_metadata_header_lines(metadata)) if (
        metadata and not separate_metadata) else ""
    np.savetxt(path, np.asarray(frame), fmt="%d", delimiter=",", header=header)
    if metadata and separate_metadata:
        write_metadata_sidecar(path, metadata)


# --- HDF5 series recorder --------------------------------------------
def _attr_value(v):
    if v is None:
        return ""
    if isinstance(v, (int, float, str, bool)):
        return v
    if isinstance(v, (list, tuple)) and all(isinstance(x, (int, float)) for x in v):
        return np.asarray(v)
    return json.dumps(v, default=str)


class Hdf5Recorder:
    """Append spectra/frames to one HDF5 file; metadata -> attributes."""

    def __init__(self, path: str, run_metadata: Optional[dict] = None,
                 save_metadata: bool = True):
        import h5py
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._f = h5py.File(path, "w")
        if save_metadata and run_metadata:
            for k, v in run_metadata.items():
                self._f.attrs[k] = _attr_value(v)
        self._n = 0

    def append_spectrum(self, wavelength, intensity,
                        item_meta: Optional[dict] = None) -> None:
        g = self._f.create_group("scan_%04d" % self._n)
        g.create_dataset("wavelength_nm", data=np.asarray(wavelength))
        g.create_dataset("intensity", data=np.asarray(intensity))
        self._attrs(g, item_meta)
        self._n += 1
        self._f.flush()

    def append_frame(self, image=None, spectrum=None, wavelength=None,
                     item_meta: Optional[dict] = None) -> None:
        """A 'shot' in a flat frame series: optional 2-D image and/or 1-D
        spectrum, plus the wavelength axis."""
        g = self._f.create_group("frame_%04d" % self._n)
        if image is not None:
            g.create_dataset("image", data=np.asarray(image))
        if spectrum is not None:
            g.create_dataset("spectrum", data=np.asarray(spectrum))
        if wavelength is not None:
            g.create_dataset("wavelength_nm", data=np.asarray(wavelength))
        self._attrs(g, item_meta)
        self._n += 1
        self._f.flush()

    def new_scan(self, scan_meta: Optional[dict] = None) -> "_Hdf5ScanGroup":
        """Begin a scan group that holds per-shot data and/or the stitched
        spectrum."""
        g = self._f.create_group("scan_%04d" % self._n)
        self._attrs(g, scan_meta)
        self._n += 1
        return _Hdf5ScanGroup(g, self._f)

    @staticmethod
    def _attrs(group, item_meta):
        if item_meta:
            for k, v in item_meta.items():
                group.attrs[k] = _attr_value(v)

    @property
    def count(self) -> int:
        return self._n

    def close(self) -> None:
        self._f.close()


class _Hdf5ScanGroup:
    """One scan's group: per-shot data under ``shot_NNNN`` + optional stitched."""

    def __init__(self, group, file):
        self._g = group
        self._f = file
        self._shot = 0

    def add_shot(self, *, image=None, spectrum=None, wavelength=None,
                 item_meta: Optional[dict] = None) -> None:
        sg = self._g.create_group("shot_%04d" % self._shot)
        if image is not None:
            sg.create_dataset("image", data=np.asarray(image))
        if spectrum is not None:
            sg.create_dataset("spectrum", data=np.asarray(spectrum))
        if wavelength is not None:
            sg.create_dataset("wavelength_nm", data=np.asarray(wavelength))
        if item_meta:
            for k, v in item_meta.items():
                sg.attrs[k] = _attr_value(v)
        self._shot += 1

    def set_stitched(self, wavelength, intensity) -> None:
        self._g.create_dataset("stitched_wavelength_nm", data=np.asarray(wavelength))
        self._g.create_dataset("stitched_intensity", data=np.asarray(intensity))
        self._f.flush()
