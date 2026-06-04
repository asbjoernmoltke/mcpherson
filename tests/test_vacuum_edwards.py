"""Unit tests for the Edwards TIC vacuum driver (fake serial, no hardware)."""
from __future__ import annotations

import pytest

import spectrometer.drivers.vacuum_edwards as ev
from spectrometer.drivers.vacuum_edwards import EdwardsTIC


# --- pure parsing -----------------------------------------------------
def test_parse_pressure_semicolon_fields():
    assert EdwardsTIC.parse_pressure("=V913 1.23E-5;59;0") == pytest.approx(1.23e-5)


def test_parse_value_fields():
    assert EdwardsTIC.parse_value_reply("=V913 1.0E+3;66;0") == ["1.0E+3", "66", "0"]


def test_parse_pressure_no_echo():
    assert EdwardsTIC.parse_pressure("9.9E-7") == pytest.approx(9.9e-7)


def test_parse_error_reply_raises():
    with pytest.raises(ValueError):
        EdwardsTIC.parse_value_reply("*V913 5")
    with pytest.raises(ValueError):
        EdwardsTIC.parse_value_reply("")


# --- driver over a fake serial ---------------------------------------
class FakeSerial:
    def __init__(self, **kwargs):
        self.is_open = True
        self.writes: list[str] = []
        self._out = b""

    def reset_input_buffer(self):
        self._out = b""

    def write(self, data: bytes):
        cmd = data.decode("ascii").strip()
        self.writes.append(cmd)
        self._out = (self._reply(cmd) + "\r").encode("ascii")

    def read_until(self, expected=b"\r"):
        idx = self._out.find(expected)
        if idx == -1:
            chunk, self._out = self._out, b""
            return chunk
        end = idx + len(expected)
        chunk, self._out = self._out[:end], self._out[end:]
        return chunk

    def readline(self):
        return self.read_until(b"\n")

    def close(self):
        self.is_open = False

    def _reply(self, cmd: str) -> str:
        if cmd == "?V913":
            return "=V913 2.50E-6;59;0"
        if cmd == "?V904":
            return "=V904 1;0;0"   # turbo running (made up for test)
        return "*V000 1"


@pytest.fixture
def tic(monkeypatch):
    monkeypatch.setattr(ev.serial, "Serial", FakeSerial)
    dev = EdwardsTIC("COMX", gauge=1, units="mbar")
    dev.open()
    yield dev
    dev.close()


def test_read_pressure(tic):
    assert tic.read_pressure() == pytest.approx(2.5e-6)
    assert "?V913" in tic._ser.writes
    assert tic.units == "mbar"


def test_status_string(tic):
    assert "mbar" in tic.get_status()


def test_gauge_slot_maps_to_object():
    dev = EdwardsTIC("COMX", gauge=2)
    assert dev.gauge_object == 914
    dev2 = EdwardsTIC("COMX", gauge=915)   # raw object id accepted
    assert dev2.gauge_object == 915
