"""Per-device connect/disconnect and offline-safe status polling."""
from __future__ import annotations

import math

import pytest

from spectrometer.core.system import build_system


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _acq_worker(system):
    from spectrometer.gui.worker import AcquisitionWorker
    return AcquisitionWorker(system)


def _aux_worker(system):
    from spectrometer.gui.aux_worker import AuxWorker
    return AuxWorker(system)


def test_disconnect_keeps_poll_alive_and_reconnect(qapp):
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _acq_worker(sys)
        snaps = []
        w.status_updated.connect(snaps.append)   # same thread -> synchronous

        w._poll_status()
        assert snaps[-1]["connections"]["grating"] is True
        # In dummy mode every device is a simulated stand-in.
        assert snaps[-1]["simulated"]["shutter"] is True
        assert snaps[-1]["simulated"]["camera"] is True

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
        w = _acq_worker(sys)
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
        w = _aux_worker(sys)
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


def test_mp789_defers_connection_to_open():
    # Constructing the real grating driver must NOT touch the port (so the GUI
    # can build with the grating offline); open() reports a missing port.
    from spectrometer.drivers.mcpherson import MP_789A_4
    drv = MP_789A_4("COM_NOPE")
    assert not drv.is_connected
    with pytest.raises(RuntimeError):
        drv.open()
    assert not drv.is_connected


def test_real_bundle_constructs_without_connecting():
    # build_devices(dummy=False) builds the real drivers but connects nothing,
    # so a missing/offline rig never blocks construction of the system.
    from spectrometer.drivers.factory import build_devices
    b = build_devices(dummy=False, grating_port="COM_NOPE",
                      laser_interface="cli", laser_port="COM_NOPE",
                      vacuum_port="COM_NOPE")
    assert not b.camera.is_connected
    assert not b.grating.is_connected
    assert not b.laser.is_connected
    assert not b.vacuum.is_connected


def test_vacuum_pump_status_in_snapshot(qapp):
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _aux_worker(sys)
        snaps = []
        w.status_updated.connect(snaps.append)
        w._poll_status()
        # Dummy pumps default to stopped; running them shows "Running".
        assert snaps[-1]["vacuum_turbo"] == "Stopped"
        sys.vacuum.backing_on()
        w._poll_status()
        assert snaps[-1]["vacuum_backing"] == "Running"
        # offline -> no pump status (None, shown as '--')
        w.disconnect_device("vacuum")
        assert snaps[-1]["vacuum_turbo"] is None
    finally:
        sys.close_all()


def test_unknown_device_emits_error(qapp):
    sys = build_system(dummy=True)
    sys.open_all()
    try:
        w = _acq_worker(sys)
        errors = []
        w.error.connect(errors.append)
        w.connect_device("teleporter")
        assert errors and "Unknown device" in errors[-1]
    finally:
        sys.close_all()
