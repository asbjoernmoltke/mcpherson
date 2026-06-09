"""Per-device connect/disconnect and offline-safe status polling."""
from __future__ import annotations

import math

import pytest

from spectrometer.core.system import build_system


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _worker(system):
    from spectrometer.gui.worker import HardwareWorker
    return HardwareWorker(system)


def test_disconnect_keeps_poll_alive_and_reconnect(qapp):
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _worker(sys)
        snaps = []
        w.status_updated.connect(snaps.append)   # same thread -> synchronous

        w._poll_status()
        assert snaps[-1]["connections"]["grating"] is True

        # Disconnect the grating: poll must still produce a snapshot, with the
        # grating section showing offline defaults rather than crashing.
        w.disconnect_device("grating")
        assert not sys.devices.grating.is_connected
        snap = snaps[-1]
        assert snap["connections"]["grating"] is False
        assert snap["grating"] == "offline"
        assert snap["position"] == 0 and snap["homed"] is False
        # other devices unaffected
        assert snap["connections"]["camera"] is True

        # Reconnect
        w.connect_device("grating")
        assert sys.devices.grating.is_connected
        assert snaps[-1]["connections"]["grating"] is True
    finally:
        sys.close_all()


def test_camera_offline_blocks_acquire_and_defaults(qapp):
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _worker(sys)
        snaps = []
        w.status_updated.connect(snaps.append)

        w.disconnect_device("camera")
        snap = snaps[-1]
        assert snap["connections"]["camera"] is False
        assert snap["camera"] == "offline"
        assert math.isnan(snap["temperature"])
        assert snap["can_acquire"] is False        # can't acquire without a camera
    finally:
        sys.close_all()


def test_laser_offline_defaults_are_safe(qapp):
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _worker(sys)
        snaps = []
        w.status_updated.connect(snaps.append)

        w.disconnect_device("laser")
        snap = snaps[-1]
        assert snap["laser"] == "offline"
        assert snap["laser_on"] is False
        assert snap["laser_supports_power"] is False
        assert snap["laser_allowed_rep_rates"] is None
    finally:
        sys.close_all()


def test_unknown_device_emits_error(qapp):
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _worker(sys)
        errors = []
        w.error.connect(errors.append)
        w.connect_device("teleporter")
        assert errors and "Unknown device" in errors[-1]
    finally:
        sys.close_all()
