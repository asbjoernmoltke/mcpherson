"""Read-only Edwards TIC discovery probe -- RUN AT THE CONTROLLER.

SAFE: only reads (``?V`` / ``?S`` queries). Never commands pumps or gauges.
Identifies the controller, dumps each gauge object's raw value/setup reply (so
we can read the wide-range gauge slot, value format, and unit), and probes the
pump objects. Also tries the older AGC-style commands as a fallback in case the
controller speaks that dialect.

Run:  python tests/discover_edwards.py [COMport]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
TERM = "\r"


def comm(ser, cmd: str) -> str:
    ser.reset_input_buffer()
    ser.write((cmd + TERM).encode("ascii"))
    raw = ser.read_until(TERM.encode("ascii"))
    if not raw:  # maybe the controller uses CRLF / LF
        raw = ser.readline()
    return raw.decode("ascii", errors="replace").strip()


def main() -> int:
    print(f"=== Edwards probe on {PORT} (9600 8N1, read-only) ===")
    try:
        ser = serial.Serial(PORT, baudrate=9600, bytesize=serial.EIGHTBITS,
                            stopbits=serial.STOPBITS_ONE, parity=serial.PARITY_NONE,
                            timeout=0.8)
    except Exception as exc:
        print("Could not open port:", exc)
        return 1

    try:
        print("\n-- TIC controller identity --")
        for obj, label in [("?V902", "controller type"),
                           ("?S902", "controller setup"),
                           ("?V904", "turbo pump (904)"),
                           ("?V910", "backing pump (910)"),
                           ("?V905", "object 905")]:
            print(f"  {obj:8s} ({label:18s}) -> {comm(ser, obj)!r}")

        print("\n-- Gauges (TIC objects 913/914/915) --")
        for obj in (913, 914, 915):
            print(f"  ?V{obj} value -> {comm(ser, f'?V{obj}')!r}")
            print(f"  ?S{obj} setup -> {comm(ser, f'?S{obj}')!r}")

        print("\n-- AGC-style fallback (older dialect) --")
        for cmd in ("?V940", "?GV 1", "?V 1", "?NU 1"):
            print(f"  {cmd:8s} -> {comm(ser, cmd)!r}")

        print("\nNOTE: identify which gauge object is the Wide Range Gauge "
              "(setup/type reply), the pressure value format, and the unit. "
              "Set EdwardsTIC(gauge=..., units=...) accordingly.")
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
