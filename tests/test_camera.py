"""Camera lifecycle + config-exposure tests (#6).

Covers the cooldown-progress estimate, the non-blocking warm-up state machine
driven by the worker's status poll, and the new config pass-throughs /
capability discovery (trigger, internal shutter, A-D rate, pre-amp, EM gain).
"""
from __future__ import annotations

import pytest

from spectrometer.controllers.camera import CameraController
from spectrometer.core.system import build_system
from spectrometer.drivers.andor_camera import DummyCamera


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _worker(system):
    from spectrometer.gui.worker import HardwareWorker
    return HardwareWorker(system)


def _cooled_system():
    sys = build_system(dummy=True, cooling_threshold=1.0e-4)
    sys.open_all()
    sys.devices.vacuum.set_pressure(1.0e-6)   # good vacuum -> cooling allowed
    sys.vacuum.poll()
    return sys


# --- cooldown progress ------------------------------------------------
def test_cooldown_progress_rises_to_stable():
    sys = _cooled_system()
    try:
        cam = sys.camera
        drv = sys.devices.camera
        assert cam.cooldown_progress() == 0.0        # cooler off

        cam.cooldown(-80.0)
        p_warm = cam.cooldown_progress()             # just started, near 0
        drv._temp = -40.0
        p_mid = cam.cooldown_progress()
        assert 0.0 <= p_warm < p_mid < 1.0

        drv._temp = -80.0                            # at setpoint -> stable
        assert cam.cooldown_progress() == 1.0
    finally:
        sys.close_all()


# --- non-blocking warm-up via the worker poll -------------------------
def test_worker_warmup_is_nonblocking_and_completes(qapp):
    sys = _cooled_system()
    try:
        w = _worker(sys)
        drv = sys.devices.camera
        sys.camera.cooldown(-80.0)
        drv._temp = -80.0

        w.do_warmup()                                # returns immediately
        assert w._warming                            # warm-up pending
        assert drv.is_cooler_on()                    # cooler still on (warming)
        assert drv.get_temperature_setpoint() == sys.camera.warm_target_c

        drv._temp = sys.camera.warm_target_c         # simulate warmed up
        w._poll_status()                             # poll drives completion
        assert not w._warming
        assert not drv.is_cooler_on()                # cooler off once warm
    finally:
        sys.close_all()


def test_cooldown_cancels_pending_warmup(qapp):
    sys = _cooled_system()
    try:
        w = _worker(sys)
        w.do_warmup()
        assert w._warming
        w.do_cooldown(-70.0)
        assert not w._warming                        # new cooldown cancels warm-up
        assert sys.devices.camera.is_cooler_on()
    finally:
        sys.close_all()


# --- manual cooling fan -----------------------------------------------
def test_fan_can_be_run_at_room_temperature():
    drv = DummyCamera()
    cam = CameraController(drv, frost_point=lambda: -100.0)
    drv.set_fan_mode("off")
    assert not cam.fan_on
    cam.set_fan(True)                                # turn the fan on, no cooler
    assert cam.fan_on and drv.get_fan_mode() == "full"
    cam.set_fan(False)                               # allowed while cooler off
    assert not cam.fan_on


def test_fan_off_refused_while_cooler_on(qapp):
    from spectrometer.core.exceptions import InterlockError
    sys = _cooled_system()
    try:
        sys.camera.cooldown(-80.0)                   # cooler on
        assert sys.devices.camera.is_cooler_on()
        with pytest.raises(InterlockError):
            sys.camera.set_fan(False)                # must keep dumping heat
        assert sys.camera.fan_on                     # still on
    finally:
        sys.close_all()


def test_worker_fan_slot_and_snapshot(qapp):
    sys = _cooled_system()
    try:
        w = _worker(sys)
        snaps: list[dict] = []
        w.status_updated.connect(snaps.append)
        sys.devices.camera.set_fan_mode("off")
        w.set_camera_fan(True)
        assert snaps[-1]["camera_fan_on"] is True
        assert sys.devices.camera.get_fan_mode() == "full"
    finally:
        sys.close_all()


# --- config pass-through + capability discovery -----------------------
def test_capabilities_lists_options_for_dummy():
    cam = CameraController(DummyCamera(), frost_point=lambda: -100.0)
    caps = cam.capabilities()
    assert caps["trigger_modes"][0] == "int"
    assert "auto" in caps["internal_shutter_modes"]
    assert len(caps["readout_rates"]) == 3
    assert len(caps["preamp_gains"]) == 3
    assert caps["em_gain_range"] is None             # conventional CCD


def test_configure_passes_through_to_driver():
    drv = DummyCamera()
    cam = CameraController(drv, frost_point=lambda: -100.0)
    cam.configure(exposure_s=0.25, trigger_mode="ext",
                  internal_shutter="open", readout_index=2, preamp_index=1)
    assert drv.get_exposure() == 0.25
    assert drv.get_trigger_mode() == "ext"
    assert drv.get_internal_shutter() == "open"
    assert drv.get_readout_rate() == 2
    assert drv.get_preamp_gain() == 1


def test_em_gain_unsupported_raises_on_conventional_ccd():
    cam = CameraController(DummyCamera(), frost_point=lambda: -100.0)
    with pytest.raises(NotImplementedError):
        cam.configure(em_gain=100)


def test_em_gain_supported_on_emccd_stub():
    class EmccdDummy(DummyCamera):
        def __init__(self):
            super().__init__()
            self._em = 1
        def get_em_gain_range(self):
            return (1, 300)
        def set_em_gain(self, value):
            self._em = int(value)
        def get_em_gain(self):
            return self._em

    drv = EmccdDummy()
    cam = CameraController(drv, frost_point=lambda: -100.0)
    assert cam.capabilities()["em_gain_range"] == (1, 300)
    cam.configure(em_gain=150)
    assert drv.get_em_gain() == 150
