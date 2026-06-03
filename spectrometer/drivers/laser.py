"""Laser drivers.

``DummyLaser`` simulates the full NKT-style control surface (emission,
power, pulse-picker ratio, repetition rate) so the GUI is fully exercisable
offline. The real NKT driver lives in ``laser_nkt.py``.
"""
from __future__ import annotations

from typing import Optional

from ..utilities import log
from .base import STANDARD_REP_RATES_HZ, LaserDriver


class DummyLaser(LaserDriver):
    """Simulated laser. ``disable()`` is the E-stop hook and is instantaneous.

    Mirrors the NKT/Origami control surface: staged emission, power %, a
    discrete amplifier repetition rate (50-1000 kHz), and an independent
    pulse-picker ratio (1/1 .. 1/1,000,000).
    """

    def __init__(self):
        self._connected = False
        self._stage = "off"
        self._power_pct = 0.0
        self._pulse_picker_ratio = 1
        self._rep_rate_hz = 50.0e3  # default 50 kHz

    def open(self) -> None:
        self._connected = True
        log.info("DummyLaser connected.")

    def close(self) -> None:
        # Fail safe: standby on disconnect.
        self._stage = "off"
        self._connected = False
        log.info("DummyLaser disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_status(self) -> str:
        if not self._connected:
            return "Disconnected"
        return f"{self._stage}, {self._power_pct:.0f}%, PP 1/{self._pulse_picker_ratio}"

    # --- emission -----------------------------------------------------
    def enable(self) -> None:
        self._stage = "booster"
        log.info("DummyLaser: emission ON (booster).")

    def disable(self) -> None:
        self._stage = "off"
        log.info("DummyLaser: DISABLED (standby).")

    @property
    def is_enabled(self) -> bool:
        return self._stage != "off"

    @property
    def emission_stage(self) -> str:
        return self._stage

    # --- power / pulse picker / rep rate ------------------------------
    def set_power_percent(self, percent: float) -> None:
        self._power_pct = max(0.0, min(100.0, percent))
        log.info("DummyLaser: power %.1f %%." % self._power_pct)

    def read_power_percent(self) -> Optional[float]:
        return self._power_pct

    def set_pulse_picker_ratio(self, ratio: int) -> None:
        if ratio < 1:
            raise ValueError("Pulse-picker ratio must be >= 1.")
        self._pulse_picker_ratio = int(ratio)
        log.info("DummyLaser: pulse-picker ratio 1/%d." % self._pulse_picker_ratio)

    def read_pulse_picker_ratio(self) -> Optional[int]:
        return self._pulse_picker_ratio

    def set_repetition_rate_hz(self, target_hz: float) -> float:
        """Snap to the nearest allowed discrete rate and apply it."""
        if target_hz <= 0:
            raise ValueError("Target repetition rate must be positive.")
        self._rep_rate_hz = min(STANDARD_REP_RATES_HZ,
                                key=lambda r: abs(r - target_hz))
        log.info("DummyLaser: rep rate %.0f kHz." % (self._rep_rate_hz / 1e3))
        return self._rep_rate_hz

    def read_repetition_rate_hz(self) -> Optional[float]:
        return self._rep_rate_hz

    def allowed_rep_rates_hz(self) -> Optional[tuple[float, ...]]:
        return STANDARD_REP_RATES_HZ
