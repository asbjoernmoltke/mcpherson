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


def build_devices(dummy: bool = False, *, grating_port: str = "COM5",
                  laser_port: str | None = None,
                  laser_interface: str = "cli",
                  vacuum_port: str = "COM7", vacuum_gauge: int = 1,
                  vacuum_units: str = "mbar") -> DeviceBundle:
    """Construct all drivers. ``dummy=True`` returns an all-simulated bundle.

    ``laser_port`` is the Origami's COM port. ``laser_interface`` selects how
    we talk to it: ``"cli"`` (38400 ASCII, default, unambiguous) or
    ``"interbus"`` (NKTPDLL register protocol). The laser is switched into the
    matching mode at startup if needed.
    """
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

    # Real hardware. The NKT laser is now real; shutter/vacuum concretes are
    # still TBD, so they fall back to dummies (see plan open items).
    from .andor_camera import AndorCamera
    from .mcpherson import MP_789A_4
    from .shutter import DummyShutter
    from .vacuum_edwards import EdwardsTIC

    log.warn("Building REAL device bundle; the shutter is still simulated "
             "until that hardware is selected.")
    laser = _build_origami(laser_interface, laser_port)
    return DeviceBundle(
        camera=AndorCamera(),
        grating=MP_789A_4(grating_port),
        shutter=DummyShutter(),
        laser=laser,
        vacuum=EdwardsTIC(vacuum_port, gauge=vacuum_gauge, units=vacuum_units),
    )


def _build_origami(interface: str, port: str | None):
    """Pick the Origami driver and ensure the laser is in the matching mode."""
    from . import origami_mode

    interface = interface.lower()
    if interface == "cli":
        port = port or "COM6"  # confirmed FTDI port; override via laser_port
        try:
            origami_mode.ensure_mode(port, "cli")
        except Exception as exc:
            log.error("Origami CLI mode-ensure failed (%s); will still try to "
                      "open the CLI port." % exc)
        from .laser_origami_cli import OrigamiCLI
        return OrigamiCLI(port)
    elif interface == "interbus":
        if port:
            try:
                origami_mode.ensure_mode(port, "nktpbus")
            except Exception as exc:
                log.error("Origami NKTPBus mode-ensure failed: %s" % exc)
        from .laser_nkt import OrigamiXPS
        return OrigamiXPS(port)
    raise ValueError("laser_interface must be 'cli' or 'interbus'.")
