"""Read-only Edwards TIC pump search -- RUN AT THE CONTROLLER.

SAFE: only ?V (value) / ?S (setup) queries -- never commands a pump. Sweeps the
turbo + backing object range so we can find which objects report this rig's
pumps (backing nXDS, turbo nEXT85D) and how to read their state/speed. The
chamber may be at atmosphere with the pumps OFF, so a connected-but-stopped
pump reads 0 -- the ?S setup reply (pump type) is the reliable "is it wired?"
signal.

TIC object map (Edwards TIC200): 904-909 = turbo, 910-912 = backing, 913-915 =
gauges 1/2/3. Reply: `=V<obj> <data>` / `=S<obj> <data>`; `*` prefix = error or
state-coded reply.

Run:  python tests/discover_edwards_pumps.py [COMport]   (default COM7)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
TERM = "\r"

LABELS = {
    902: "system status",
    904: "TURBO state", 905: "turbo speed", 906: "turbo power",
    907: "turbo (907)", 908: "turbo (908)", 909: "turbo (909)",
    910: "BACKING state", 911: "backing (911)", 912: "backing (912)",
    913: "gauge 1 (ref)",
}


def comm(ser, cmd: str) -> str:
    ser.reset_input_buffer()
    ser.write((cmd + TERM).encode("ascii"))
    raw = ser.read_until(TERM.encode("ascii"))
    if not raw:
        raw = ser.readline()
    return raw.decode("ascii", errors="replace").strip()


def main() -> int:
    print("=== Edwards TIC pump search on %s (read-only) ===" % PORT)
    try:
        ser = serial.Serial(PORT, baudrate=9600, bytesize=serial.EIGHTBITS,
                            stopbits=serial.STOPBITS_ONE, parity=serial.PARITY_NONE,
                            timeout=0.8)
    except Exception as exc:
        print("Could not open %s: %s" % (PORT, exc))
        return 1

    try:
        print("\n-- Value (?V) + Setup (?S) per object --")
        for obj in (902, 904, 905, 906, 907, 908, 909, 910, 911, 912, 913):
            label = LABELS.get(obj, "")
            v = comm(ser, "?V%d" % obj)
            s = comm(ser, "?S%d" % obj)
            print("  obj %d %-16s ?V -> %-28r  ?S -> %r" % (obj, label, v, s))

        print("\nLook for: a turbo object whose ?S reports a pump type (nEXT85D)"
              " and a backing object whose ?S reports the nXDS -- those are the"
              " ones to read for status. Non-pump objects error or echo zeros.")
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
