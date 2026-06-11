"""Vacuum pump control + start/stop interlocks (dummy)."""
from __future__ import annotations

import pytest

from spectrometer.core.exceptions import InterlockError
from spectrometer.core.system import build_system


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _sys():
    s = build_system(dummy=True)
    s.open_all()
    return s


def test_turbo_refused_until_backing_runs():
    s = _sys()
    try:
        assert not s.vacuum.backing_running and not s.vacuum.turbo_running
        with pytest.raises(InterlockError):
            s.vacuum.turbo_on()                 # backing not running yet
        s.vacuum.backing_on()
        assert s.vacuum.backing_running
        s.vacuum.turbo_on()                     # now allowed
        assert s.vacuum.turbo_running
    finally:
        s.close_all()


def test_backing_off_refused_while_turbo_running():
    s = _sys()
    try:
        s.vacuum.backing_on()
        s.vacuum.turbo_on()
        with pytest.raises(InterlockError):
            s.vacuum.backing_off()              # turbo still running
        s.vacuum.turbo_off()
        s.vacuum.backing_off()                  # ok once turbo stopped
        assert not s.vacuum.backing_running
    finally:
        s.close_all()


def test_worker_pump_slots_and_snapshot(qapp):
    s = _sys()
    try:
        from spectrometer.gui.worker import HardwareWorker
        w = HardwareWorker(s)
        errors: list[str] = []
        w.error.connect(errors.append)

        w.set_turbo(True)                       # refused: no backing
        assert errors and "backing" in errors[-1].lower()
        assert not s.vacuum.turbo_running

        w.set_backing(True)
        w.set_turbo(True)                       # now ok
        snaps: list[dict] = []
        w.status_updated.connect(snaps.append)
        w._poll_status()
        assert snaps[-1]["turbo_running"] is True
        assert snaps[-1]["backing_running"] is True
        assert snaps[-1]["vacuum_can_control"] is True
    finally:
        s.close_all()
