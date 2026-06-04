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

    def __init__(self, **kwargs):
        self.is_open = True
        self.writes: list[str] = []
        self._out = b""
        # remembered setpoints so queries echo them back
        self._state = {"e_power": 0, "e_freq": 50000, "e_div": 1,
                       "mode": "standby"}

    def reset_input_buffer(self):
        self._out = b""

    def write(self, data: bytes):
        cmd = data.decode("ascii").strip()
        self.writes.append(cmd)
        self._out = (self._reply(cmd) + "\n").encode("ascii")

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
            return "ly_oxp2_dev_status OK"
        if cmd == "ly_oxp2_enabled":
            self._state["mode"] = "enabled"
            return "ly_oxp2_enabled"
        if cmd == "ly_oxp2_standby":
            self._state["mode"] = "standby"
            return "ly_oxp2_standby"
        if cmd in ("ly_oxp2_output_enable", "ly_oxp2_output_disable"):
            return cmd
        if cmd == "ly_oxp2_mode?":
            return self._state["mode"]
        if cmd == "e_freq_available?":
            return "e_freq_available 50000 100000 200000 300000 1000000"
        if cmd.startswith("e_power="):
            self._state["e_power"] = int(cmd.split("=")[1])
            return "e_power %d" % self._state["e_power"]
        if cmd == "e_power?":
            return "e_power %d" % self._state["e_power"]
        if cmd.startswith("e_freq="):
            self._state["e_freq"] = int(cmd.split("=")[1])
            return "e_freq %d" % self._state["e_freq"]
        if cmd == "e_freq?":
            return "%d" % self._state["e_freq"]
        if cmd.startswith("e_div="):
            self._state["e_div"] = int(cmd.split("=")[1])
            return "e_div %d" % self._state["e_div"]
        if cmd == "e_div?":
            return "e_div %d" % self._state["e_div"]
        return ""


@pytest.fixture
def laser(monkeypatch):
    monkeypatch.setattr(cli_mod.serial, "Serial", FakeSerial)
    dev = OrigamiCLI("COMX", timeout=0.2)
    dev.open()
    yield dev
    dev.close()


def test_open_forces_standby(laser):
    fake = laser._ser
    # open() must have queried status and then disabled (AOM off + standby)
    assert "ly_oxp2_dev_status" in fake.writes
    assert "ly_oxp2_output_disable" in fake.writes
    assert "ly_oxp2_standby" in fake.writes


def test_power_percent_maps_to_aom(laser):
    laser.set_power_percent(40.0)
    assert "e_power=1600" in laser._ser.writes      # 40% of 4000
    assert laser.read_power_percent() == pytest.approx(40.0)


def test_pulse_picker(laser):
    laser.set_pulse_picker_ratio(8)
    assert "e_div=8" in laser._ser.writes
    assert laser.read_pulse_picker_ratio() == 8


def test_rep_rate_uses_queried_allowed_list(laser):
    allowed = laser.allowed_rep_rates_hz()
    assert allowed == (50000, 100000, 200000, 300000, 1000000)
    applied = laser.set_repetition_rate_hz(95000)   # nearest -> 100000
    assert applied == 100000
    assert "e_freq=100000" in laser._ser.writes
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
