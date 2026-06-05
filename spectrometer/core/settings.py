"""Persistent application settings (the planned Layer-4 AppState).

A flat dataclass of user-facing parameters that survive between sessions
(ports, grating, cooling setpoint, exposure, scan range, save destination,
save-content choices). Stored as JSON at a per-user path. Loading is
forward/backward compatible: unknown keys are ignored and missing keys keep
their defaults, so the file format can grow without breaking old files.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields

from ..utilities import log


def _default_folder() -> str:
    return os.path.join(os.path.expanduser("~"), "Documents")


def default_settings_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".mcpherson", "settings.json")


@dataclass
class Settings:
    # --- device ports / interfaces ------------------------------------
    grating_port: str = "COM5"
    laser_port: str = "COM6"
    laser_interface: str = "cli"        # "cli" | "interbus"
    vacuum_port: str = "COM7"
    vacuum_gauge: int = 1
    vacuum_units: str = "mbar"
    cooling_threshold: float = 1.0e-4   # safe pressure for cooling

    # --- instrument ----------------------------------------------------
    grating_name: str = "1200g/mm"
    cooling_setpoint_c: float = -80.0
    exposure_s: float = 0.1

    # --- acquisition ---------------------------------------------------
    scan_wl_min: float = 350.0
    scan_wl_max: float = 500.0
    n_frames: int = 1

    # --- saving (defaults for the Save dialog) ------------------------
    save_folder: str = field(default_factory=_default_folder)
    save_filename: str = "spectrum"
    save_format: str = "auto"           # "auto" | "csv" | "hdf5"
    save_image_2d: bool = False
    save_spectrum_1d: bool = False
    save_stitched: bool = True

    # --- persistence ---------------------------------------------------
    @classmethod
    def load(cls, path: str | None = None) -> "Settings":
        path = path or default_settings_path()
        s = cls()
        if not os.path.isfile(path):
            return s
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            log.warn("Settings: could not read %s (%s); using defaults." % (path, exc))
            return s
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in known:
                setattr(s, key, value)
            else:
                log.debug("Settings: ignoring unknown key %r." % key)
        return s

    def update_from_save_options(self, opts) -> None:
        """Remember the Save dialog's choices for next time."""
        self.save_folder = opts.folder
        self.save_filename = opts.filename
        self.save_format = opts.fmt
        self.save_image_2d = opts.save_image_2d
        self.save_spectrum_1d = opts.save_spectrum_1d
        self.save_stitched = opts.save_stitched

    def save(self, path: str | None = None) -> None:
        path = path or default_settings_path()
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(asdict(self), fh, indent=2)
            log.info("Settings saved to %s." % path)
        except OSError as exc:  # pragma: no cover - filesystem dependent
            log.error("Settings: could not save to %s: %s" % (path, exc))
