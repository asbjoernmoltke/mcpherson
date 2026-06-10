"""Live Edwards TIC monitor -- READ-ONLY. Watch a pump-down.

Polls the wide-range gauge + turbo/backing objects on a fixed interval and
prints a timestamped line, so we can see the pumps spin up and the pressure
fall (and capture the pumps' running reply format for the GUI status display).
Never commands anything.

Run:  python tests/monitor_edwards.py [COM] [duration_s] [interval_s]
      defaults: COM7  300  3
"""
from __future__ import annotations

import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 300.0
INTERVAL = float(sys.argv[3]) if len(sys.argv) > 3 else 3.0
TERM = "\r"


def comm(ser, cmd: str) -> str:
    ser.reset_input_buffer()
    ser.write((cmd + TERM).encode("ascii"))
    raw = ser.read_until(TERM.encode("ascii"))
    if not raw:
        raw = ser.readline()
    return raw.decode("ascii", errors="replace").strip()


def field0(reply: str):
    """First ';'-separated data field of a `=V<obj> <data>` reply."""
    body = reply.split(" ", 1)[1] if " " in reply else reply
    return body.split(";", 1)[0].strip()


def main() -> int:
    print("=== Edwards TIC monitor on %s for %.0fs (read-only) ===" % (PORT, DURATION))
    print("Start the pumps now (backing first, then turbo) -- watch them come alive.\n")
    try:
        ser = serial.Serial(PORT, 9600, bytesize=serial.EIGHTBITS,
                            stopbits=serial.STOPBITS_ONE, parity=serial.PARITY_NONE,
                            timeout=0.8)
    except Exception as exc:
        print("Could not open %s: %s" % (PORT, exc))
        return 1
    print("%-8s | %-12s | turbo: st spd%%  pwr | backing | raw turbo ?V904/905"
          % ("t (s)", "pressure(Pa)"))
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < DURATION:
            p = field0(comm(ser, "?V913"))
            v904 = comm(ser, "?V904"); v905 = comm(ser, "?V905")
            v906 = comm(ser, "?V906"); v910 = comm(ser, "?V910")
            print("%7.0f | %-12s | %5s %5s %5s | %5s | %r %r"
                  % (time.monotonic() - t0, p, field0(v904), field0(v905),
                     field0(v906), field0(v910), v904, v905))
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("stopped.")
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
