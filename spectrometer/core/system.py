"""System composition: drivers -> controllers -> safety -> sync.

A single place that assembles the control stack on top of a
:class:`DeviceBundle`, sharing one ``abort`` event across the camera
controller, SafetyManager, and SyncController so the E-stop/abort signal
reaches every blocking wait.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from ..controllers.camera import CameraController
from ..controllers.grating import GratingController
from ..controllers.laser import LaserController
from ..controllers.shutter import ShutterController
from ..controllers.vacuum import VacuumController
from ..drivers.factory import DeviceBundle, build_devices
from .acquisition import AcquisitionEngine
from .calibration import LinearCalibration, default_calibration
from .safety import SafetyManager
from .sync import SoftwareSync


@dataclass
class System:
    devices: DeviceBundle
    abort: threading.Event
    camera: CameraController
    grating: GratingController
    shutter: ShutterController
    laser: LaserController
    vacuum: VacuumController
    safety: SafetyManager
    sync: SoftwareSync
    calibration: LinearCalibration
    engine: AcquisitionEngine
    grating_name: str = "1200g/mm"

    def open_all(self) -> None:
        self.devices.open_all()

    def close_all(self) -> None:
        self.devices.close_all()

    def set_grating(self, grating_name: str) -> None:
        """Swap the active grating's calibration (declares which grating is
        physically installed). The mechanical home is unchanged -- only the
        position<->wavelength mapping -- so the homed state is preserved.
        Updates every holder of the calibration in one place."""
        cal = default_calibration(grating_name, n_pixels=self.calibration.n_pixels)
        self.calibration = cal
        self.grating.calibration = cal
        self.engine.calibration = cal
        self.grating_name = grating_name


def build_system(dummy: bool = False, *, grating_port: str = "COM5",
                 cooling_threshold: float | None = None,
                 grating_name: str = "1200g/mm",
                 laser_port: str | None = None, laser_interface: str = "cli",
                 vacuum_port: str = "COM7", vacuum_gauge: int = 1,
                 vacuum_units: str = "Pa") -> System:
    devices = build_devices(dummy=dummy, grating_port=grating_port,
                            laser_port=laser_port, laser_interface=laser_interface,
                            vacuum_port=vacuum_port, vacuum_gauge=vacuum_gauge,
                            vacuum_units=vacuum_units)
    abort = threading.Event()

    vacuum = VacuumController(
        devices.vacuum,
        **({"cooling_threshold": cooling_threshold}
           if cooling_threshold is not None else {}))
    # Placeholder calibration (real ones load from file). Newton DO920P is
    # 1024 px wide; query the live camera once open for the authoritative size.
    calibration = default_calibration(grating_name, n_pixels=1024)

    camera = CameraController(devices.camera,
                              vacuum_ok=lambda: vacuum.vacuum_ok,
                              abort=abort)
    grating = GratingController(devices.grating, calibration=calibration)
    shutter = ShutterController(devices.shutter)
    laser = LaserController(devices.laser)

    safety = SafetyManager(camera=camera, grating=grating, shutter=shutter,
                           laser=laser, vacuum=vacuum, abort=abort)
    sync = SoftwareSync(shutter, camera, abort=abort)
    engine = AcquisitionEngine(camera=camera, grating=grating, sync=sync,
                               safety=safety, calibration=calibration,
                               abort=abort)

    return System(devices=devices, abort=abort, camera=camera, grating=grating,
                  shutter=shutter, laser=laser, vacuum=vacuum, safety=safety,
                  sync=sync, calibration=calibration, engine=engine,
                  grating_name=grating_name)


def build_system_from_settings(settings, dummy: bool = False) -> System:
    """Build the system using a :class:`~spectrometer.core.settings.Settings`."""
    return build_system(
        dummy=dummy, grating_port=settings.grating_port,
        cooling_threshold=settings.cooling_threshold,
        grating_name=settings.grating_name, laser_port=settings.laser_port,
        laser_interface=settings.laser_interface, vacuum_port=settings.vacuum_port,
        vacuum_gauge=settings.vacuum_gauge, vacuum_units=settings.vacuum_units)
