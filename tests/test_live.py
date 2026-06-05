"""Live-view lifecycle tests (worker loop, dummy devices)."""
from __future__ import annotations

import threading
import time

import pytest

from spectrometer.core.system import build_system


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _worker(system):
    from spectrometer.gui.worker import HardwareWorker
    return HardwareWorker(system)


def test_live_opens_streams_and_stops(qapp):
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _worker(sys)
        # Count streamed frames directly (Qt signals can't deliver to the
        # test thread without a running event loop).
        cam = sys.devices.camera
        orig = cam.read_newest_image
        calls = {"n": 0}

        def counting():
            calls["n"] += 1
            return orig()
        cam.read_newest_image = counting

        t = threading.Thread(target=w.do_live)
        t.start()
        time.sleep(0.2)
        assert sys.shutter.is_open               # shutter opened for live
        assert cam._acquiring                     # camera streaming
        w.stop_live()
        t.join(timeout=2)
        assert not t.is_alive()
        assert not sys.shutter.is_open            # closed after stop
        assert not cam._acquiring
        assert not w._busy
        assert calls["n"] > 0                     # frames were read/streamed
    finally:
        sys.close_all()


def test_estop_stops_live(qapp):
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _worker(sys)
        t = threading.Thread(target=w.do_live)
        t.start()
        time.sleep(0.15)
        sys.safety.estop()                        # latches abort -> loop exits
        t.join(timeout=2)
        assert not t.is_alive()
        assert not sys.shutter.is_open
        assert not w._busy
    finally:
        sys.close_all()
