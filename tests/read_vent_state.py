"""Read-only: dump the TIC vent / standby / pump state. Commands nothing.

Run:  python tests/read_vent_state.py [COMport]   (default COM7)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
TERM = "\r"

QUERIES = [
    ("?V913", "gauge pressure (Pa;unit;state)"),
    ("?V904", "turbo state"),
    ("?V905", "turbo speed %"),
    ("?V910", "backing state"),
    ("?V908", "turbo STANDBY  (?V: 4=in standby, 0=not)"),
    ("?V922", "VENT VALVE state (0-4; on/off)"),
    ("?S922", "vent OPTION  (?S: 0=on stop, 1=on 50%)"),
    ("?S904", "turbo setup"),
]


def comm(ser, cmd: str) -> str:
    ser.reset_input_buffer()
    ser.write((cmd + TERM).encode("ascii"))
    raw = ser.read_until(TERM.encode("ascii"))
    if not raw:
        raw = ser.readline()
    return raw.decode("ascii", errors="replace").strip()


def main() -> int:
    try:
        ser = serial.Serial(PORT, baudrate=9600, bytesize=serial.EIGHTBITS,
                            stopbits=serial.STOPBITS_ONE,
                            parity=serial.PARITY_NONE, timeout=0.8)
    except Exception as exc:
        print("Could not open %s: %s" % (PORT, exc))
        return 1
    try:
        print("=== TIC vent/standby/pump state on %s (read-only) ===" % PORT)
        for cmd, label in QUERIES:
            print("  %-6s %-42s -> %r" % (cmd, label, comm(ser, cmd)))
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
