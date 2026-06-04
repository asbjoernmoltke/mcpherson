"""Acquisition engine: single exposures and scan + stitch.

Replaces the buggy ``Spectrometer`` prototype. The engine is Qt-free and
interruptible: it checks the shared ``abort`` event between every step and
reports progress/data through plain callbacks, which the GUI adapts to Qt
signals while running the engine on a worker thread.

The stitch logic lives in the module-level :func:`stitch_segments` so it can
be unit-tested in isolation (this was the most bug-prone part of the original
code): overlapping ~200 nm windows are binned onto a uniform wavelength grid,
overlaps averaged, and any empty bins filled by interpolation.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from ..controllers.camera import CameraController
from ..controllers.grating import GratingController
from ..utilities import log
from .calibration import LinearCalibration
from .exceptions import EStopActive
from .safety import SafetyManager
from .sync import SyncController

Segment = tuple[np.ndarray, np.ndarray]  # (wavelength_nm, intensity)


def average_frames(frames: np.ndarray) -> np.ndarray:
    """Average a frame stack ``(n, H, W)`` over the n exposures -> a single 2-D
    image ``(H, W)`` (the 'shot'). A lone 2-D frame is returned unchanged."""
    arr = np.asarray(frames, dtype=np.float64)
    return arr.mean(axis=0) if arr.ndim == 3 else arr


def reduce_frames(frames: np.ndarray) -> np.ndarray:
    """Reduce a frame stack ``(n, H, W)`` (or ``(H, W)``) to a 1-D spectrum of
    length ``W`` by averaging over frames and vertical (spatial) rows."""
    arr = average_frames(frames)
    if arr.ndim == 2:
        arr = arr.mean(axis=0)
    return arr


def stitch_segments(segments: list[Segment], delta_nm: float) -> Segment:
    """Stitch overlapping (wavelength, intensity) segments onto a uniform grid.

    Samples falling in the same output bin are averaged (this is how the
    overlap between adjacent windows is combined); empty bins are filled by
    linear interpolation from neighbouring filled bins.
    """
    if not segments:
        raise ValueError("No segments to stitch.")
    all_wl = np.concatenate([np.asarray(w, dtype=np.float64) for w, _ in segments])
    all_int = np.concatenate([np.asarray(i, dtype=np.float64) for _, i in segments])

    order = np.argsort(all_wl)
    all_wl = all_wl[order]
    all_int = all_int[order]

    grid = np.arange(all_wl[0], all_wl[-1] + delta_nm, delta_nm)
    if grid.size == 0:
        grid = np.array([all_wl[0]])

    idx = np.clip(np.round((all_wl - grid[0]) / delta_nm).astype(int),
                  0, grid.size - 1)
    sums = np.zeros(grid.size)
    counts = np.zeros(grid.size)
    np.add.at(sums, idx, all_int)
    np.add.at(counts, idx, 1.0)

    out = np.full(grid.size, np.nan)
    filled = counts > 0
    out[filled] = sums[filled] / counts[filled]

    # Fill empty bins by interpolation from filled neighbours.
    if not filled.all():
        out[~filled] = np.interp(grid[~filled], grid[filled], out[filled])
    return grid, out


@dataclass
class AcquisitionEngine:
    camera: CameraController
    grating: GratingController
    sync: SyncController
    safety: SafetyManager
    calibration: LinearCalibration
    abort: threading.Event
    n_frames: int = 1
    delta_nm: float = 0.05
    overlap: float = 0.15

    # callbacks (GUI adapts these to Qt signals)
    on_frame: Optional[Callable[[np.ndarray], None]] = None
    on_spectrum: Optional[Callable[[np.ndarray, np.ndarray], None]] = None
    on_progress: Optional[Callable[[int, int], None]] = None
    on_finished: Optional[Callable[[], None]] = None
    on_aborted: Optional[Callable[[], None]] = None
    # per-shot hook: (shot_index, position, image2d, wavelength, intensity).
    # Used by the recorder to save raw 2-D images / 1-D spectra per shot.
    on_shot: Optional[Callable[[int, int, np.ndarray, np.ndarray, np.ndarray], None]] = None

    _emit_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # --- helpers -------------------------------------------------------
    def _guard(self) -> None:
        if self.abort.is_set() or self.safety.is_estopped:
            raise EStopActive("Acquisition blocked: emergency stop / abort active.")

    def _emit_frame(self, frame: np.ndarray) -> None:
        if self.on_frame:
            self.on_frame(frame)

    def _emit_spectrum(self, wl: np.ndarray, intensity: np.ndarray) -> None:
        if self.on_spectrum:
            self.on_spectrum(wl, intensity)

    # --- single exposure ----------------------------------------------
    def single(self) -> Segment:
        """One shutter-synced exposure at the current grating position."""
        self._guard()
        frames = self.sync.acquire(self.n_frames)
        self._emit_frame(frames[-1] if frames.ndim == 3 else frames)
        position = self.grating.position
        wl = self.calibration.wavelength_axis(position)
        intensity = reduce_frames(frames)
        if self.on_shot:
            self.on_shot(0, position, average_frames(frames), wl, intensity)
        self._emit_spectrum(wl, intensity)
        return wl, intensity

    # --- scan + stitch -------------------------------------------------
    def scan(self, wl_min: float, wl_max: float) -> Segment:
        """Scan the grating across ``[wl_min, wl_max]`` and return the
        stitched spectrum. Raises :class:`EStopActive` if aborted."""
        positions = self.calibration.scan_positions(
            wl_min, wl_max, overlap=self.overlap)
        log.info("AcquisitionEngine: scan %.1f-%.1f nm in %d windows."
                 % (wl_min, wl_max, len(positions)))
        segments: list[Segment] = []
        total = len(positions)
        try:
            for i, pos in enumerate(positions):
                self._guard()
                self.grating.move_to_position(int(pos))
                self._guard()
                frames = self.sync.acquire(self.n_frames)
                self._emit_frame(frames[-1] if frames.ndim == 3 else frames)
                wl = self.calibration.wavelength_axis(self.grating.position)
                intensity = reduce_frames(frames)
                if self.on_shot:
                    self.on_shot(i, int(self.grating.position),
                                 average_frames(frames), wl, intensity)
                segments.append((wl, intensity))
                if self.on_progress:
                    self.on_progress(i + 1, total)
        except EStopActive:
            if self.on_aborted:
                self.on_aborted()
            raise

        grid, stitched = stitch_segments(segments, self.delta_nm)
        self._emit_spectrum(grid, stitched)
        if self.on_finished:
            self.on_finished()
        return grid, stitched
