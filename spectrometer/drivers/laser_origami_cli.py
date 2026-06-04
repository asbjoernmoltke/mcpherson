"""NKT Origami XPS laser driver via the vendor CLI protocol (ASCII serial).

The Origami exposes its RS-232 port as either CLI mode (38400 baud, ASCII
``ly_oxp2_*`` / ``e_*`` commands) or NKTPBus/Interbus mode (115200 baud, binary
telegrams -- see :mod:`spectrometer.drivers.laser_nkt`). The two are mutually
exclusive; mode is selected by Interbus register ``0x39`` (0=NKTPBus, 1=CLI).
Helpers to detect/switch live in :mod:`spectrometer.drivers.origami_mode`.

The CLI is unambiguous (no FSM-state or rep-index guessing) and DLL-free, so it
is the preferred interface. Command set (NKT-owned, from the vendor CLI ref):

* ``ly_oxp2_standby`` / ``ly_oxp2_enabled``   emission off / on
* ``ly_oxp2_output_disable`` / ``..._enable``  AOM (fast electronic gate)
* ``ly_oxp2_output?``                          AOM state
* ``ly_oxp2_power=<W>`` / ``ly_oxp2_power?``    IR pump power in Watts
* ``e_power=<0-4000>`` / ``e_power?``           AOM relative output power
* ``e_freq=<Hz>`` / ``e_freq?`` / ``e_freq_available?``  rep rate + allowed list
* ``e_div=<n>`` / ``e_div?``                    pulse-picker division
* ``e_mlp?``                                    measured average laser power
* ``ly_oxp2_dev_status`` / ``ly_oxp2_mode?``    status

SAFETY: ``disable()`` (the E-stop fast path) disables the AOM output AND sets
standby -- belt and suspenders, retried, never raises. ``open()``/``close()``
force standby so attaching/detaching never leaves the beam on.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Optional

import serial

from ..utilities import log
from .base import LaserDriver

CLI_BAUD = 38400


def _first_number(text: str) -> Optional[float]:
    m = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text)
    return float(m.group()) if m else None


def _all_numbers(text: str) -> list[float]:
    return [float(x) for x in
            re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text)]


class OrigamiCLI(LaserDriver):
    def __init__(self, port: str = "COM6", *, max_pump_power_w: float = 5.0,
                 aom_full_scale: int = 4000, timeout: float = 0.6):
        self.port = port
        self.max_pump_power_w = max_pump_power_w
        self.aom_full_scale = aom_full_scale
        self.timeout = timeout
        self._ser: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._allowed_rep_rates: Optional[tuple[float, ...]] = None

    # --- serial transaction -------------------------------------------
    def _txn(self, cmd: str) -> str:
        """Send an ASCII command, return the laser's reply text (stripped)."""
        if self._ser is None:
            raise RuntimeError("OrigamiCLI port not open.")
        with self._lock:
            self._ser.reset_input_buffer()
            self._ser.write((cmd + "\n").encode("ascii"))
            deadline = time.time() + self.timeout
            buf = b""
            time.sleep(0.08)
            while time.time() < deadline:
                n = self._ser.in_waiting
                if n:
                    buf += self._ser.read(n)
                    time.sleep(0.03)
                elif buf:
                    break
                else:
                    time.sleep(0.02)
        reply = buf.decode("ascii", errors="replace").strip()
        log.debug("OrigamiCLI %s -> %r" % (cmd, reply))
        return reply

    def _set(self, cmd: str, *, what: str) -> None:
        reply = self._txn(cmd)
        if reply == "":
            log.warn("OrigamiCLI %s: no reply." % what)

    def _query_number(self, cmd: str) -> Optional[float]:
        return _first_number(self._txn(cmd))

    # --- lifecycle ----------------------------------------------------
    def open(self) -> None:
        self._ser = serial.Serial(
            port=self.port, baudrate=CLI_BAUD, bytesize=serial.EIGHTBITS,
            stopbits=serial.STOPBITS_ONE, rtscts=False, timeout=self.timeout)
        reply = self._txn("ly_oxp2_dev_status")
        if "ly_oxp2" not in reply:
            log.warn("OrigamiCLI: unexpected status reply %r -- is the laser "
                     "in CLI mode (reg 0x39=1)?" % reply)
        self.disable()  # safety: standby + AOM off on attach
        log.info("OrigamiCLI connected on %s; forced to standby." % self.port)

    def close(self) -> None:
        if self._ser is not None:
            try:
                self.disable()
            finally:
                self._ser.close()
                self._ser = None
        log.info("OrigamiCLI closed.")

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # --- emission -----------------------------------------------------
    def enable(self) -> None:
        self._set("ly_oxp2_enabled", what="enable")
        self._set("ly_oxp2_output_enable", what="AOM enable")
        log.info("OrigamiCLI: emission enabled + AOM open.")

    def disable(self) -> None:
        """E-stop fast path: AOM off first, then standby. Retried; never raises."""
        for attempt in range(3):
            try:
                self._txn("ly_oxp2_output_disable")
                self._txn("ly_oxp2_standby")
                log.info("OrigamiCLI: AOM disabled + standby.")
                return
            except Exception as exc:  # pragma: no cover
                log.error("OrigamiCLI disable attempt %d failed: %s"
                          % (attempt + 1, exc))
                time.sleep(0.02)
        log.fatal("OrigamiCLI: FAILED to confirm standby after retries!")

    @property
    def is_enabled(self) -> bool:
        reply = self._txn("ly_oxp2_mode?").lower()
        # "enabled"/"emission" => emitting; "standby"/"listen"/"off" => not.
        if "enabl" in reply or "emiss" in reply:
            return True
        if "standby" in reply or "listen" in reply or "off" in reply:
            return False
        # Fall back to AOM state: ly_oxp2_output? (0=open/emitting, 1=closed).
        out = _first_number(self._txn("ly_oxp2_output?"))
        return out == 0

    @property
    def emission_stage(self) -> str:
        reply = self._txn("ly_oxp2_mode?").strip()
        return reply or "unknown"

    # --- power --------------------------------------------------------
    def set_power_percent(self, percent: float) -> None:
        """GUI power knob -> AOM relative output power (0..aom_full_scale)."""
        percent = max(0.0, min(100.0, percent))
        raw = int(round(percent / 100.0 * self.aom_full_scale))
        self._set("e_power=%d" % raw, what="set AOM power")
        log.info("OrigamiCLI: AOM power %.1f %% (raw %d)." % (percent, raw))

    def read_power_percent(self) -> Optional[float]:
        raw = self._query_number("e_power?")
        return None if raw is None else raw / self.aom_full_scale * 100.0

    def set_pump_power_watts(self, watts: float) -> None:
        watts = max(0.0, min(self.max_pump_power_w, watts))
        self._set("ly_oxp2_power=%g" % watts, what="set pump power")

    def read_pump_power_watts(self) -> Optional[float]:
        return self._query_number("ly_oxp2_power?")

    def read_average_power_watts(self) -> Optional[float]:
        return self._query_number("e_mlp?")

    # --- pulse picker -------------------------------------------------
    def set_pulse_picker_ratio(self, ratio: int) -> None:
        if not 1 <= ratio <= 1_000_000:
            raise ValueError("Pulse-picker ratio must be in 1..1,000,000.")
        self._set("e_div=%d" % int(ratio), what="set pulse picker")

    def read_pulse_picker_ratio(self) -> Optional[int]:
        val = self._query_number("e_div?")
        return None if val is None else int(val)

    # --- repetition rate ----------------------------------------------
    def allowed_rep_rates_hz(self) -> Optional[tuple[float, ...]]:
        if self._allowed_rep_rates is None:
            nums = _all_numbers(self._txn("e_freq_available?"))
            # Keep plausible rep-rate values (Hz); ignore stray small ints.
            rates = sorted({n for n in nums if n >= 1000.0})
            self._allowed_rep_rates = tuple(rates) if rates else None
        return self._allowed_rep_rates

    def set_repetition_rate_hz(self, target_hz: float) -> float:
        allowed = self.allowed_rep_rates_hz()
        applied = (min(allowed, key=lambda r: abs(r - target_hz))
                   if allowed else float(target_hz))
        self._set("e_freq=%d" % int(round(applied)), what="set rep rate")
        return applied

    def read_repetition_rate_hz(self) -> Optional[float]:
        return self._query_number("e_freq?")

    # --- status -------------------------------------------------------
    def get_status(self) -> str:
        if not self.is_connected:
            return "Disconnected"
        try:
            parts = [self.emission_stage]
            power = self.read_power_percent()
            if power is not None:
                parts.append("AOM %.0f%%" % power)
            rate = self.read_repetition_rate_hz()
            if rate:
                parts.append("%.0f kHz" % (rate / 1e3))
            ratio = self.read_pulse_picker_ratio()
            if ratio:
                parts.append("PP 1/%d" % ratio)
            return ", ".join(parts)
        except Exception as exc:  # pragma: no cover
            return f"Error: {exc}"
