"""Probe whether the TIC accepts SERIAL pump commands -- NON-DESTRUCTIVE.

The only way to know if the TIC is in serial (vs parallel) control mode is to
send a `!C` command and read the error code (0 = accepted, 5 = parallel mode
rejects serial start/stop). To learn this WITHOUT changing anything, we read
each pump's current state and then command it to the state it is ALREADY in
(tell a stopped pump to stop, a running pump to run). That is a no-op on the
hardware but still exercises the control path and returns the real error code.

After the probe it prints what a real start/stop WOULD do, but does not do it.

Run:  python tests/probe_pump_control.py [COMport]   (default COM7)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
TERM = "\r"

TURBO_OBJ, BACKING_OBJ = 904, 910
STATE = {0: "Stopped", 1: "Starting", 2: "Stopping", 3: "Stopping",
         4: "Running", 5: "Accelerating", 6: "Braking", 7: "Braking"}
RUNNING_STATES = {1, 4, 5}  # treat anything spinning/heading-up as "on"


def comm(ser, cmd: str) -> str:
    ser.reset_input_buffer()
    ser.write((cmd + TERM).encode("ascii"))
    raw = ser.read_until(TERM.encode("ascii"))
    if not raw:
        raw = ser.readline()
    return raw.decode("ascii", errors="replace").strip()


def field0(reply: str):
    """First ';'-separated data field of a =V reply, as int, or None."""
    if not reply or reply[0] in "*?":
        return None
    body = reply.split(" ", 1)[1] if " " in reply else reply
    try:
        return int(float(body.split(";")[0].strip()))
    except ValueError:
        return None


def err_code(reply: str):
    """Error int from a `*C<obj> <err>` reply, or None if unparseable."""
    parts = reply.replace(";", " ").split()
    try:
        return int(parts[-1]) if parts else None
    except ValueError:
        return None


def probe(ser, obj: int, label: str) -> None:
    st = field0(comm(ser, "?V%d" % obj))
    if st is None:
        print("  %-8s obj %d: could not read state (not wired here?) -- SKIP"
              % (label, obj))
        return
    name = STATE.get(st, "state %d" % st)
    is_on = st in RUNNING_STATES
    noop_val = 1 if is_on else 0          # command it to where it already is
    print("  %-8s obj %d: currently %s (state %d)" % (label, obj, name, st))
    reply = comm(ser, "!C%d %d" % (obj, noop_val))
    err = err_code(reply)
    verdict = {0: "ACCEPTED -- serial control works",
               5: "REJECTED err 5 -- TIC is in PARALLEL mode (serial start/stop "
                  "disabled; change the TIC to serial control)"}.get(
                      err, "error %s -- see manual Table 3" % err)
    print("    no-op !C%d %d -> %r  => %s" % (obj, noop_val, reply, verdict))


def main() -> int:
    print("=== TIC pump-control probe on %s (non-destructive no-op) ===" % PORT)
    try:
        ser = serial.Serial(PORT, baudrate=9600, bytesize=serial.EIGHTBITS,
                            stopbits=serial.STOPBITS_ONE,
                            parity=serial.PARITY_NONE, timeout=0.8)
    except Exception as exc:
        print("Could not open %s: %s" % (PORT, exc))
        return 1
    try:
        gauge = comm(ser, "?V913")
        print("gauge obj 913 -> %r\n" % gauge)
        probe(ser, BACKING_OBJ, "BACKING")
        probe(ser, TURBO_OBJ, "TURBO")
        print("\nNo pump state was changed. If both say ACCEPTED, the GUI"
              "\nStart/Stop buttons will work. If err 5, the TIC must be put"
              "\ninto serial control mode first.")
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
