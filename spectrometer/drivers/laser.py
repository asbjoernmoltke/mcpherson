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
        self._full_scale_energy_uj = 40.0
        self._pulse_picker_ratio = 1
        self._rep_rate_hz = 50.0e3  # default 50 kHz

    def open(self) -> None:
        self._connected = True
        log.info("DummyLaser connected.")

    def close(self) -> None:
        # Passive: leave emission state unchanged on disconnect (matches the
        # real driver, so the connection can be handed off without disturbance).
        self._connected = False
        log.info("DummyLaser disconnected (state left unchanged).")

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

    supports_listen = True

    def listen(self) -> None:
        self._stage = "listen"
        log.info("DummyLaser: listen state.")

    @property
    def is_enabled(self) -> bool:
        return self._stage not in ("off", "listen")

    @property
    def emission_stage(self) -> str:
        return self._stage

    @property
    def emission_state(self) -> str:
        if self._stage == "listen":
            return "listen"
        return "on" if self.is_enabled else "standby"

    # --- power / pulse picker / rep rate ------------------------------
    def set_power_percent(self, percent: float) -> None:
        self._power_pct = max(0.0, min(100.0, percent))
        log.info("DummyLaser: power %.1f %%." % self._power_pct)

    def read_power_percent(self) -> Optional[float]:
        return self._power_pct

    @property
    def max_pulse_energy_uj(self) -> Optional[float]:
        return self._full_scale_energy_uj

    def set_pulse_energy_uj(self, energy_uj: float) -> None:
        energy_uj = max(0.0, min(self._full_scale_energy_uj, energy_uj))
        self._power_pct = energy_uj / self._full_scale_energy_uj * 100.0
        log.info("DummyLaser: pulse energy %.2f uJ." % energy_uj)

    def read_pulse_energy_uj(self) -> Optional[float]:
        return self._power_pct / 100.0 * self._full_scale_energy_uj

    def read_measured_pulse_energy_uj(self) -> Optional[float]:
        # Simulate a near-ideal measurement of the setpoint when emitting.
        if self._stage == "off":
            return 0.0
        return self._power_pct / 100.0 * self._full_scale_energy_uj

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
