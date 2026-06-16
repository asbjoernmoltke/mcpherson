"""Set the TIC turbo auto-vent option to 'On stop' (object 922 setup = 0).

The vent valve is on the turbo vent port, so it can only auto-vent. 'On 50%'
(=1) vents while the turbo decelerates through 50% speed; 'On stop' (=0) vents
only at a full stop, so a standby/spin-down no longer vents. Reversible: re-run
with arg '1' to restore 'On 50%'.

Reads the option back to confirm.

Run:  python tests/set_vent_on_stop.py [0|1] [COMport]   (default 0 COM7)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # noqa: E402

VALUE = sys.argv[1] if len(sys.argv) > 1 else "0"
PORT = sys.argv[2] if len(sys.argv) > 2 else "COM7"
TERM = "\r"
NAMES = {"0": "On stop", "1": "On 50%"}


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
        before = comm(ser, "?S922")
        print("before: ?S922 -> %r  (%s)"
              % (before, NAMES.get(before.split()[-1] if before else "", "?")))
        resp = comm(ser, "!S922 %s" % VALUE)
        print("set:    !S922 %s -> %r" % (VALUE, resp))
        after = comm(ser, "?S922")
        opt = after.split()[-1] if after else ""
        print("after:  ?S922 -> %r  (%s)" % (after, NAMES.get(opt, "?")))
        if opt == VALUE:
            print("OK: auto-vent option is now '%s'." % NAMES.get(VALUE, VALUE))
            return 0
        print("!! option did NOT change to %s -- check the reply above." % VALUE)
        return 2
    finally:
        ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
