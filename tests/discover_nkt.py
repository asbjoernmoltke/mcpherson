"""Read-only NKT discovery: load the SDK, identify ports, scan the bus.

SAFE: only scans/reads. Never enables emission, never forces standby (does
not call NKTLaser.open()). Tries both normal and legacy bus scanning, since
some pulse lasers (Origami/aeroPulse) may require legacy masterId.
Run:  python tests/discover_nkt.py
"""
from __future__ import annotations

import serial.tools.list_ports

from spectrometer.drivers.laser_nkt import NKTLaser


def list_ports() -> None:
    print("=== Serial ports (pyserial) ===")
    for p in serial.tools.list_ports.comports():
        print(f"  {p.device}: {p.description} [{p.hwid}]")


def scan(nkt, legacy: bool) -> None:
    nkt.setLegacyBusScanning(1 if legacy else 0)
    mode = "LEGACY" if legacy else "normal"
    nkt.openPorts(nkt.getAllPorts(), 1, 0)
    open_ports = nkt.getOpenPorts()
    print(f"=== {mode} scan: open ports with modules = '{open_ports}' ===")
    for portname in [p for p in open_ports.split(",") if p]:
        result, dev_list = nkt.deviceGetAllTypesV2(portname)
        for addr, dtype in enumerate(dev_list):
            if dtype != 0:
                print(f"  {portname}: type 0x{dtype:04X} at address {addr}")
    nkt.closePorts("")


def main() -> int:
    list_ports()
    nkt = NKTLaser(port=None)._api()
    print("All NKT ports:", nkt.getAllPorts())
    scan(nkt, legacy=False)
    scan(nkt, legacy=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
