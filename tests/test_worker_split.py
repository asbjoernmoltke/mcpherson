"""Regression test for the AcquisitionWorker/AuxWorker thread split.

Before the split, a single ``HardwareWorker`` handled camera+grating+shutter
*and* laser+vacuum commands on one QThread's event loop. A blocking
``do_home``/``do_single``/``do_scan`` therefore starved everything else
queued behind it on that same thread -- including unrelated laser commands
and the live status poll. This test proves a laser command completes (and
takes effect) while a grating ``home()`` is still in progress on a separate
thread, without any Qt event loop involved (mirrors ``tests/test_live.py``'s
style: run the blocking call on a background ``threading.Thread`` and poll
its ``is_alive()`` state).
"""
from __future__ import annotations

import threading
import time

import pytest

from spectrometer.core.system import build_system


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_laser_command_completes_while_grating_home_in_progress(qapp):
    from spectrometer.gui.worker import AcquisitionWorker
    from spectrometer.gui.aux_worker import AuxWorker

    sys = build_system(dummy=True)
    sys.open_all()
    try:
        acq = AcquisitionWorker(sys)
        aux = AuxWorker(sys)

        # Slow the dummy grating's home() way down so there's a comfortable
        # window to fire an overlapping laser command.
        orig_home = sys.devices.grating.home

        def slow_home():
            time.sleep(1.0)
            return orig_home()
        sys.devices.grating.home = slow_home

        t = threading.Thread(target=acq.do_home)
        t.start()
        try:
            time.sleep(0.2)   # let do_home enter the (patched) blocking call
            assert t.is_alive(), "home() should still be running"

            aux.set_laser_energy(12.0)   # must not block behind do_home

            assert sys.laser.read_pulse_energy_uj() == pytest.approx(12.0)
            assert t.is_alive(), "home() should still be in progress"
        finally:
            t.join(timeout=3)
        assert not t.is_alive()
    finally:
        sys.close_all()


def test_aux_status_poll_ticks_while_grating_home_in_progress(qapp):
    from spectrometer.gui.worker import AcquisitionWorker
    from spectrometer.gui.aux_worker import AuxWorker

    sys = build_system(dummy=True)
    sys.open_all()
    try:
        acq = AcquisitionWorker(sys)
        aux = AuxWorker(sys)

        orig_home = sys.devices.grating.home

        def slow_home():
            time.sleep(0.6)
            return orig_home()
        sys.devices.grating.home = slow_home

        snaps: list[dict] = []
        aux.status_updated.connect(snaps.append)

        t = threading.Thread(target=acq.do_home)
        t.start()
        try:
            # Poll Aux directly a few times (no Qt timer needed here) while
            # the Acquisition thread is still blocked in home() -- each call
            # must return promptly since Aux never touches the grating.
            for _ in range(3):
                assert t.is_alive()
                aux._poll_status()
                time.sleep(0.1)
            assert len(snaps) == 3
        finally:
            t.join(timeout=3)
        assert not t.is_alive()
    finally:
        sys.close_all()
