"""Unit tests for the Origami CLI driver, using a fake serial port.

Verifies the ASCII command/response transaction layer and the LaserDriver
mappings (power -> e_power, rep rate -> e_freq with the queried allowed list,
pulse picker -> e_div, E-stop -> output_disable + standby) without hardware.
"""
from __future__ import annotations

import pytest

import spectrometer.drivers.laser_origami_cli as cli_mod
from spectrometer.drivers.laser_origami_cli import OrigamiCLI


class FakeSerial:
    """Minimal serial stand-in that canned-replies to OXPS CLI commands."""

    # Index -> Hz, mirroring the real e_freq_available? reply.
    RATES = {0: 50000, 1: 100000, 2: 200000, 3: 300000, 4: 1000000}

    def __init__(self, **kwargs):
        self.is_open = True
        self.writes: list[str] = []
        self._out = b""
        # remembered setpoints so queries echo them back (e_freq is an INDEX)
        self._state = {"e_power": 0, "e_freq": 0, "e_div": 1, "mode": "standby"}

    def reset_input_buffer(self):
        self._out = b""

    def write(self, data: bytes):
        cmd = data.decode("ascii").strip()
        self.writes.append(cmd)
        # The real firmware echoes the command, then the verbose answer.
        self._out = (cmd + "\n" + self._reply(cmd) + "\n").encode("ascii")

    @property
    def in_waiting(self) -> int:
        return len(self._out)

    def read(self, n: int) -> bytes:
        chunk, self._out = self._out[:n], self._out[n:]
        return chunk

    def close(self):
        self.is_open = False

    def _reply(self, cmd: str) -> str:
        if cmd == "ly_oxp2_dev_status":
            return "ly_oxp2_dev_status 129"
        if cmd == "ly_oxp2_enabled":
            self._state["mode"] = "enabled"
            return "OK"
        if cmd == "ly_oxp2_standby":
            self._state["mode"] = "standby"
            return "OK"
        if cmd in ("ly_oxp2_output_enable", "ly_oxp2_output_disable"):
            return "OK"
        if cmd == "ly_oxp2_mode?":
            return ("Laser status: ON enabled state"
                    if self._state["mode"] == "enabled"
                    else "Laser status: standby")
        if cmd == "e_freq_available?":
            lines = ["Available repetition rates:"]
            for i in sorted(self.RATES):
                lines.append("\t e_freq=%d\t--> %d Hz" % (i, self.RATES[i]))
            return "\n".join(lines)
        if cmd.startswith("e_power="):
            self._state["e_power"] = int(cmd.split("=")[1])
            return "OK"
        if cmd == "e_power?":
            return "Setted laser power in relative unit: %d" % self._state["e_power"]
        if cmd.startswith("e_freq="):
            self._state["e_freq"] = int(cmd.split("=")[1])
            return "OK"
        if cmd == "e_freq?":
            return "Frequency index parameter: %d" % self._state["e_freq"]
        if cmd.startswith("e_div="):
            self._state["e_div"] = int(cmd.split("=")[1])
            return "OK"
        if cmd == "e_div?":
            return "Notice: Division factor is %d" % self._state["e_div"]
        if cmd == "e_mlp?":
            # Measured average power in mW; full AOM scale -> 4000 mW (4 W).
            return "%d mW" % self._state["e_power"]
        return ""


@pytest.fixture
def laser(monkeypatch):
    monkeypatch.setattr(cli_mod.serial, "Serial", FakeSerial)
    dev = OrigamiCLI("COMX", timeout=0.2)
    dev.open()
    yield dev
    dev.close()


def test_open_is_passive(laser):
    fake = laser._ser
    # open() confirms CLI via a status query but must NOT touch emission/state,
    # so the connection can be handed off to the vendor software untouched.
    assert "ly_oxp2_dev_status" in fake.writes
    assert "ly_oxp2_output_disable" not in fake.writes
    assert "ly_oxp2_standby" not in fake.writes
    assert "ly_oxp2_enabled" not in fake.writes


def test_close_is_passive(laser):
    laser.enable()
    laser._ser.writes.clear()
    laser.close()
    # close() just releases the port -- it must not standby/disable.
    assert laser._ser is None  # port released


def test_power_percent_maps_to_aom(laser):
    laser.set_power_percent(40.0)
    assert "e_power=1600" in laser._ser.writes      # 40% of 4000
    assert laser.read_power_percent() == pytest.approx(40.0)


def test_pulse_energy_maps_to_aom(laser):
    # Provisional cal: full scale 40 uJ at e_power=4000 -> 10 uJ = raw 1000.
    laser.set_pulse_energy_uj(10.0)
    assert "e_power=1000" in laser._ser.writes
    assert laser.read_pulse_energy_uj() == pytest.approx(10.0)
    assert laser.max_pulse_energy_uj == pytest.approx(40.0)
    # Over-range is clamped to full scale.
    laser.set_pulse_energy_uj(999.0)
    assert "e_power=4000" in laser._ser.writes


def test_measured_pulse_energy_from_power_and_rep(laser):
    # e_power=2000 -> e_mlp 2.0 W; at 50 kHz that's 2.0/50000 = 40 uJ.
    laser.set_pulse_energy_uj(20.0)                 # raw 2000
    laser.set_repetition_rate_hz(50000)
    assert laser.read_measured_pulse_energy_uj() == pytest.approx(40.0, rel=1e-3)


def test_pulse_picker(laser):
    laser.set_pulse_picker_ratio(8)
    assert "e_div=8" in laser._ser.writes
    assert laser.read_pulse_picker_ratio() == 8


def test_rep_rate_uses_queried_index_map(laser):
    allowed = laser.allowed_rep_rates_hz()
    assert allowed == (50000, 100000, 200000, 300000, 1000000)
    applied = laser.set_repetition_rate_hz(95000)   # nearest -> 100000 (index 1)
    assert applied == 100000
    assert "e_freq=1" in laser._ser.writes          # sends the INDEX, not Hz
    assert laser.read_repetition_rate_hz() == 100000


def test_enable_then_estop_disable(laser):
    laser.enable()
    assert laser.is_enabled
    laser._ser.writes.clear()
    laser.disable()
    # E-stop order: AOM output disabled, then standby.
    assert laser._ser.writes.index("ly_oxp2_output_disable") < \
        laser._ser.writes.index("ly_oxp2_standby")
    assert not laser.is_enabled
