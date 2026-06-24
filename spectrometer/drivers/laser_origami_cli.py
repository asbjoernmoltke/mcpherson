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
standby -- belt and suspenders, retried, never raises.

``open()``/``close()`` are deliberately PASSIVE: they only open/close the serial
port (open also reads status to confirm CLI mode). They do NOT change emission,
power, or the interface mode, so the connection can be handed off to the vendor
software without disturbing the laser's running state. Use the explicit
enable/disable controls (or the E-stop) to change emission.
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


def _last_number(text: str) -> Optional[float]:
    """The firmware answers are verbose ('... is 4', 'relative unit: 0', '20
    mW') -- the value is the LAST number, which avoids label/echo digits."""
    nums = _all_numbers(text)
    return nums[-1] if nums else None


class OrigamiCLI(LaserDriver):
    def __init__(self, port: str = "COM6", *, max_pump_power_w: float = 5.0,
                 aom_full_scale: int = 4000,
                 full_scale_energy_uj: float = 40.0, timeout: float = 0.6):
        self.port = port
        self.max_pump_power_w = max_pump_power_w
        self.aom_full_scale = aom_full_scale
        # Pulse energy (uJ) at e_power == aom_full_scale. PROVISIONAL: the AOM
        # scale is relative; this is the rep-rate-dependent spec ceiling
        # (~40 uJ at <=100 kHz) until the power-meter calibration replaces it.
        # The measured-energy readout (e_mlp / rep-rate) is always truthful.
        self.full_scale_energy_uj = full_scale_energy_uj
        self.timeout = timeout
        self._ser: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._allowed_rep_rates: Optional[tuple[float, ...]] = None
        self._rep_rate_index_hz: Optional[dict[int, float]] = None

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
        # The firmware echoes the command on the first line; drop it so callers
        # parse only the answer (e.g. 'e_freq?\nFrequency index parameter: 0').
        lines = reply.split("\n")
        if lines and lines[0].strip() == cmd.strip():
            reply = "\n".join(lines[1:]).strip()
        log.debug("OrigamiCLI %s -> %r" % (cmd, reply))
        return reply

    def _set(self, cmd: str, *, what: str) -> None:
        reply = self._txn(cmd)
        if reply == "":
            log.warn("OrigamiCLI %s: no reply." % what)

    def _query_number(self, cmd: str) -> Optional[float]:
        return _last_number(self._txn(cmd))

    # --- lifecycle ----------------------------------------------------
    def open(self) -> None:
        if self.is_connected:
            return
        # Passive connect: open the CLI port and confirm the laser answers in
        # CLI mode. We do NOT switch the interface mode or touch emission, so a
        # running laser is left exactly as-is (and can be handed to the vendor
        # software). If it does not answer CLI, raise rather than silently
        # half-connecting or flipping it out of NKTPBus mode.
        self._ser = serial.Serial(
            port=self.port, baudrate=CLI_BAUD, bytesize=serial.EIGHTBITS,
            stopbits=serial.STOPBITS_ONE, rtscts=False, timeout=self.timeout)
        reply = self._txn("ly_oxp2_dev_status")
        if "ly_oxp2" not in reply:
            self._ser.close()
            self._ser = None
            raise RuntimeError(
                "Origami did not answer CLI on %s (reply %r). It may be in "
                "NKTPBus mode or in use by the vendor software. Switch it to "
                "CLI mode (reg 0x39=1) before connecting." % (self.port, reply))
        log.info("OrigamiCLI connected on %s (state left unchanged)." % self.port)

    def close(self) -> None:
        # Passive: leave emission/power as-is; just release the port.
        if self._ser is not None:
            self._ser.close()
            self._ser = None
        log.info("OrigamiCLI closed (state left unchanged).")

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # --- emission -----------------------------------------------------
    def enable(self) -> None:
        self._set("ly_oxp2_enabled", what="enable")
        self._set("ly_oxp2_output_enable", what="AOM enable")
        log.info("OrigamiCLI: emission enabled + AOM open.")

    supports_listen = True

    def listen(self) -> None:
        """Return to the 'listen' state (seed running, not emitting)."""
        self._set("ly_oxp2_listen", what="listen")
        log.info("OrigamiCLI: listen state requested.")

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
        # Reply e.g. 'Laser status: ON enabled state' -> 'ON enabled state'.
        reply = self._txn("ly_oxp2_mode?").replace("Laser status:", "").strip()
        return reply or "unknown"

    @property
    def emission_state(self) -> str:
        """Normalised state for the GUI: 'on' | 'standby' | 'listen'."""
        r = self._txn("ly_oxp2_mode?").lower()
        if "listen" in r:
            return "listen"
        if "standby" in r:
            return "standby"
        if "enabl" in r or "emiss" in r or " on" in r or r.startswith("on"):
            return "on"
        return "unknown"

    # --- power / energy -----------------------------------------------
    def set_power_percent(self, percent: float) -> None:
        """Low-level relative AOM setter (0..100 %% -> 0..aom_full_scale)."""
        percent = max(0.0, min(100.0, percent))
        raw = int(round(percent / 100.0 * self.aom_full_scale))
        self._set("e_power=%d" % raw, what="set AOM power")
        log.info("OrigamiCLI: AOM power %.1f %% (raw %d)." % (percent, raw))

    def read_power_percent(self) -> Optional[float]:
        raw = self._query_number("e_power?")
        return None if raw is None else raw / self.aom_full_scale * 100.0

    @property
    def max_pulse_energy_uj(self) -> Optional[float]:
        return self.full_scale_energy_uj

    def set_pulse_energy_uj(self, energy_uj: float) -> None:
        """GUI energy knob -> AOM raw via the provisional full-scale mapping."""
        energy_uj = max(0.0, min(self.full_scale_energy_uj, energy_uj))
        scale = self.full_scale_energy_uj or 1.0
        raw = int(round(energy_uj / scale * self.aom_full_scale))
        self._set("e_power=%d" % raw, what="set pulse energy")
        log.info("OrigamiCLI: pulse energy %.2f uJ (raw %d, provisional cal)."
                 % (energy_uj, raw))

    def read_pulse_energy_uj(self) -> Optional[float]:
        """Energy *setpoint* implied by the AOM raw value (provisional cal)."""
        raw = self._query_number("e_power?")
        if raw is None:
            return None
        return raw / self.aom_full_scale * self.full_scale_energy_uj

    def read_measured_pulse_energy_uj(self) -> Optional[float]:
        """Measured pulse energy = measured avg power / rep rate (truthful)."""
        watts = self.read_average_power_watts()      # e_mlp, W
        freq = self.read_repetition_rate_hz()        # Hz
        if watts is None or not freq:
            return None
        return watts / freq * 1e6                    # J -> uJ

    def set_pump_power_watts(self, watts: float) -> None:
        watts = max(0.0, min(self.max_pump_power_w, watts))
        self._set("ly_oxp2_power=%g" % watts, what="set pump power")

    @staticmethod
    def _watts_from_reply(reply: str) -> Optional[float]:
        """Parse a power reply, honouring its unit ('20 mW' -> 0.020 W)."""
        val = _last_number(reply)
        if val is None:
            return None
        return val / 1000.0 if "mw" in reply.lower() else val

    def read_pump_power_watts(self) -> Optional[float]:
        return self._watts_from_reply(self._txn("ly_oxp2_power?"))

    def read_average_power_watts(self) -> Optional[float]:
        return self._watts_from_reply(self._txn("e_mlp?"))

    # --- pulse picker -------------------------------------------------
    def set_pulse_picker_ratio(self, ratio: int) -> None:
        if not 1 <= ratio <= 1_000_000:
            raise ValueError("Pulse-picker ratio must be in 1..1,000,000.")
        self._set("e_div=%d" % int(ratio), what="set pulse picker")

    def read_pulse_picker_ratio(self) -> Optional[int]:
        val = self._query_number("e_div?")
        return None if val is None else int(val)

    # --- repetition rate ----------------------------------------------
    # e_freq is a discrete INDEX, not a Hz value. e_freq_available? returns the
    # index->Hz map, e.g. 'e_freq=0\t--> 50000 Hz'. e_freq? returns the current
    # index; set e_freq=<index>.
    def _rep_rate_map(self) -> dict[int, float]:
        if self._rep_rate_index_hz is None:
            reply = self._txn("e_freq_available?")
            pairs = re.findall(r"e_freq\s*=\s*(\d+)\s*-+>\s*(\d+)\s*Hz", reply)
            self._rep_rate_index_hz = {int(i): float(hz) for i, hz in pairs}
        return self._rep_rate_index_hz

    def allowed_rep_rates_hz(self) -> Optional[tuple[float, ...]]:
        if self._allowed_rep_rates is None:
            rates = sorted(self._rep_rate_map().values())
            self._allowed_rep_rates = tuple(rates) if rates else None
        return self._allowed_rep_rates

    def set_repetition_rate_hz(self, target_hz: float) -> float:
        rate_map = self._rep_rate_map()
        if not rate_map:
            self._set("e_freq=%d" % int(round(target_hz)), what="set rep rate")
            return float(target_hz)
        index = min(rate_map, key=lambda i: abs(rate_map[i] - target_hz))
        self._set("e_freq=%d" % index, what="set rep rate")
        return rate_map[index]

    def read_repetition_rate_hz(self) -> Optional[float]:
        index = self._query_number("e_freq?")     # current index, not Hz
        if index is None:
            return None
        return self._rep_rate_map().get(int(index))

    # --- status -------------------------------------------------------
    def get_status(self) -> str:
        if not self.is_connected:
            return "Disconnected"
        try:
            parts = [self.emission_stage]
            energy = self.read_pulse_energy_uj()
            if energy is not None:
                parts.append("%.1f µJ" % energy)
            rate = self.read_repetition_rate_hz()
            if rate:
                parts.append("%.0f kHz" % (rate / 1e3))
            ratio = self.read_pulse_picker_ratio()
            if ratio:
                parts.append("PP 1/%d" % ratio)
            return ", ".join(parts)
        except Exception as exc:  # pragma: no cover
            return f"Error: {exc}"
