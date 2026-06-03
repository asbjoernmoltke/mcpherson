"""Driver composition: build the full set of devices in real or dummy mode.

This is the single place that decides between hardware and simulation, so the
rest of the system never imports a concrete driver directly. In ``dummy``
mode every device is simulated, enabling fully offline development.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..utilities import log
from .base import (CameraDriver, GratingDriver, LaserDriver, ShutterDriver,
                   VacuumDriver)


@dataclass
class DeviceBundle:
    """The five hardware drivers the spectrometer is built from."""
    camera: CameraDriver
    grating: GratingDriver
    shutter: ShutterDriver
    laser: LaserDriver
    vacuum: VacuumDriver

    def open_all(self) -> None:
        for dev in (self.vacuum, self.shutter, self.laser, self.grating,
                    self.camera):
            dev.open()

    def close_all(self) -> None:
        # Close camera first, then beam-blocking/​safety devices last.
        for dev in (self.camera, self.grating, self.laser, self.shutter,
                    self.vacuum):
            try:
                dev.close()
            except Exception as exc:  # pragma: no cover
                log.error("Error closing %s: %s" % (type(dev).__name__, exc))


def build_devices(dummy: bool = False, *, grating_port: str = "COM5") -> DeviceBundle:
    """Construct all drivers. ``dummy=True`` returns an all-simulated bundle."""
    if dummy:
        from .andor_camera import DummyCamera
        from .laser import DummyLaser
        from .mcpherson import DummyGrating
        from .shutter import DummyShutter
        from .vacuum import DummyVacuum

        log.info("Building DUMMY device bundle.")
        return DeviceBundle(
            camera=DummyCamera(),
            grating=DummyGrating(),
            shutter=DummyShutter(),
            laser=DummyLaser(),
            vacuum=DummyVacuum(),
        )

    # Real hardware. Shutter/laser/vacuum concretes are still TBD, so they
    # fall back to dummies until that hardware is chosen (see plan open items).
    from .andor_camera import AndorCamera
    from .laser import DummyLaser
    from .mcpherson import MP_789A_4
    from .shutter import DummyShutter
    from .vacuum import DummyVacuum

    log.warn("Building REAL device bundle; shutter/laser/vacuum are still "
             "simulated until that hardware is selected.")
    return DeviceBundle(
        camera=AndorCamera(),
        grating=MP_789A_4(grating_port),
        shutter=DummyShutter(),
        laser=DummyLaser(),
        vacuum=DummyVacuum(),
    )
