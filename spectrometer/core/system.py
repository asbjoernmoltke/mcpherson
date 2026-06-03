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

    def open_all(self) -> None:
        self.devices.open_all()

    def close_all(self) -> None:
        self.devices.close_all()


def build_system(dummy: bool = False, *, grating_port: str = "COM5",
                 cooling_threshold: float | None = None,
                 grating_name: str = "1200g/mm") -> System:
    devices = build_devices(dummy=dummy, grating_port=grating_port)
    abort = threading.Event()

    vacuum = VacuumController(
        devices.vacuum,
        **({"cooling_threshold": cooling_threshold}
           if cooling_threshold is not None else {}))
    # Placeholder calibration (real ones load from file). Use the standard
    # detector width rather than querying the camera, which is not yet open.
    calibration = default_calibration(grating_name, n_pixels=2048)

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
                  sync=sync, calibration=calibration, engine=engine)
