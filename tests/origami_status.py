"""Read-only status dump for the NKT Origami XPS (module type 0x95).

SAFE: reads registers only -- never writes, never changes emission/shutter/
state. Used to learn the live configuration (FSM state, emission bit, the
rep-rate index <-> Hz mapping, pulse-picker value, power scaling) so the
driver's control registers can be mapped without guessing.

Run:  python tests/origami_status.py [COMport]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectrometer.drivers.laser_nkt import NKTLaser  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
ADDR = 15

_STATUS_BITS = {
    0: "Emission On", 1: "Main interlock open", 2: "Switching PRR",
    3: "Aux interlock open", 5: "Supply voltage low", 6: "Temp out of range",
    14: "Module error", 15: "Error present",
}
_FSM_TARGET_VALID = "[1,3,5,6]"


def main() -> int:
    laser = NKTLaser(port=PORT)
    nkt = laser._api()
    nkt.openPorts(PORT, 1, 0)

    def u8(reg):
        r, v = nkt.registerReadU8(PORT, ADDR, reg, -1)
        return v if r == 0 else f"<err {nkt.RegisterResultTypes(r)}>"

    def u16(reg):
        r, v = nkt.registerReadU16(PORT, ADDR, reg, -1)
        return v if r == 0 else f"<err {nkt.RegisterResultTypes(r)}>"

    def u32(reg):
        r, v = nkt.registerReadU32(PORT, ADDR, reg, -1)
        return v if r == 0 else f"<err {nkt.RegisterResultTypes(r)}>"

    print(f"=== Origami XPS @ {PORT} addr {ADDR} ===")
    print("Main FSM state (0x01):        ", u8(0x01), f"(target valid {_FSM_TARGET_VALID})")
    print("Main FSM target (0x30):       ", u8(0x30))

    status = u32(0x66)
    print("Status bits (0x66):           ", status,
          "->", [name for bit, name in _STATUS_BITS.items()
                 if isinstance(status, int) and status & (1 << bit)])
    print("Error code (0x67):            ", u8(0x67))

    print("Shutter control (0x34):       ", u8(0x34), "(0=closed,1=open)")
    print("Pulse rep-rate index (0x35):  ", u8(0x35), "(range 0-12)")
    print("Freq division factor (0x36):  ", u32(0x36), "(pulse picker, 1-1e6)")

    regen = u32(0x02)
    out = u32(0x03)
    print("Regen PRR (0x02):             ", regen, "Hz")
    print("Output PRR (0x03):            ", out, "Hz",
          f"= {out/1e3:.1f} kHz" if isinstance(out, int) else "")

    print("Relative output power (0x05): ", u16(0x05), "(range 0-4000)")
    print("Output power meas (0x10):     ", u16(0x10), "* 0.001 W")
    print("Output power setpt (0x20):    ", u16(0x20), "* 0.001 W")

    nkt.closePorts("")
    print("\nNOTE: read-only. Re-run while changing rep-rate index in NKT "
          "CONTROL to map index -> kHz; note which FSM state = emission off.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
