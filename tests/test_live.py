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
    from spectrometer.gui.worker import AcquisitionWorker
    return AcquisitionWorker(system)


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


def _make_strict(cam):
    """Monkeypatch the six acquisition-config setters on a DummyCamera
    instance so each asserts the camera is idle (not acquiring) when called
    -- proving _configure_camera's pause/resume actually happened, rather
    than just passing regardless (a plain DummyCamera doesn't care about
    acquisition state at all, so it wouldn't catch a missing pause/resume)."""
    names = ("set_exposure", "set_trigger_mode", "set_internal_shutter",
             "set_readout_rate", "set_preamp_gain", "set_em_gain")
    originals = {}

    def make_wrapper(name, orig):
        def wrapper(*args, **kwargs):
            assert not cam._acquiring, (
                "%s called while camera was acquiring" % name)
            return orig(*args, **kwargs)
        return wrapper

    for name in names:
        orig = getattr(cam, name)
        originals[name] = orig
        setattr(cam, name, make_wrapper(name, orig))
    return originals


# --- camera settings while live view is streaming (self-blocking fix) -----
def test_camera_settings_take_effect_while_live(qapp):
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _worker(sys)
        cam = sys.devices.camera
        _make_strict(cam)
        errors: list[str] = []
        w.error.connect(errors.append)

        t = threading.Thread(target=w.do_live)
        t.start()
        time.sleep(0.15)
        assert cam._acquiring

        w.set_exposure(0.05)
        assert cam.get_exposure() == 0.05
        assert cam._acquiring                  # resumed after the change

        w.set_trigger_mode("ext")
        assert cam.get_trigger_mode() == "ext"
        assert cam._acquiring

        # Unsupported on the conventional-CCD dummy -- _configure_camera's
        # pause/resume must still run (the strict wrapper would have raised
        # AssertionError otherwise) and the error must surface, not crash.
        w.set_em_gain(0)
        assert errors and "gain" in errors[-1].lower()
        assert cam._acquiring                  # still resumed despite the error

        assert t.is_alive()                    # live view never stopped
        w.stop_live()
        t.join(timeout=2)
        assert not t.is_alive()
    finally:
        sys.close_all()


def test_camera_fan_does_not_pause_acquisition_while_live(qapp):
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _worker(sys)
        cam = sys.devices.camera
        stops = {"n": 0}
        orig_stop = cam.stop_acquisition

        def counting_stop():
            stops["n"] += 1
            return orig_stop()
        cam.stop_acquisition = counting_stop

        t = threading.Thread(target=w.do_live)
        t.start()
        time.sleep(0.15)
        w.set_camera_fan(True)
        assert stops["n"] == 0                 # fan control never pauses acquisition

        w.stop_live()
        t.join(timeout=2)
    finally:
        sys.close_all()


def test_other_long_ops_refused_while_live(qapp):
    """do_home/do_single/do_scan/etc. must be refused (not run, not queue
    silently) while live view is active -- necessary because neither the
    grating Home/Stop buttons nor the Shutter Open/Close buttons are
    disabled by the GUI while busy."""
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _worker(sys)
        grating = sys.devices.grating
        home_calls = {"n": 0}
        orig_home = grating.home

        def counting_home():
            home_calls["n"] += 1
            return orig_home()
        grating.home = counting_home

        t = threading.Thread(target=w.do_live)
        t.start()
        time.sleep(0.15)

        errors: list[str] = []
        w.error.connect(errors.append)

        w.do_home()
        assert home_calls["n"] == 0
        w.do_single()
        w.do_scan(400.0, 410.0)
        w.set_grating("1200g/mm")
        w.do_goto_wavelength(450.0)
        w.set_shutter(False)
        w.connect_device("camera")
        w.disconnect_device("camera")
        assert sys.devices.camera.is_connected  # disconnect was refused
        assert len(errors) >= 8
        assert all("live" in e.lower() for e in errors)
        assert t.is_alive()                     # live view undisturbed

        w.stop_live()
        t.join(timeout=2)
        assert not t.is_alive()

        # Guards are transient, not latched: home works again once live stops.
        w.do_home()
        assert home_calls["n"] == 1
    finally:
        sys.close_all()
