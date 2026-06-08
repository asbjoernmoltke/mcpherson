"""McPherson 789A-4 COARSE HOME -- COMMANDS MOTION. Run at the controller.

First-contact homing: enable the home circuit (A8), then sweep toward the home
flag at a moderate constant velocity and soft-stop the instant the flag bit
appears in the ``]`` status. This lands the mechanism ON the home flag (a
repeatable reference) without the driver's fragile fine-edge routine -- enough
to verify that homing works and which direction home is.

Robustness / safety:
* Direction-adaptive: tries DOWN first; if it reaches a limit switch before the
  flag, it reverses and sweeps UP (home must lie between the two limits).
* Bounded three ways -- limit switches (64/128), a per-sweep timeout, and
  Ctrl-C -- each of which issues the triple-redundant soft-stop ``@``.
* Uses the constant-velocity ``M`` move (the controller does not auto-stop; we
  stop it), never an absolute move, never the fine-find.

Run:  python tests/home_mcpherson.py [COMport] [velocity] [timeout_s]
      defaults: COM5  20000 steps/s  300 s/sweep
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
VELOCITY = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
TIMEOUT_S = float(sys.argv[3]) if len(sys.argv) > 3 else 300.0
TERM = b"\r\n"

BIT_MOVING, BIT_HOME, BIT_UPPER, BIT_LOWER = 2, 32, 64, 128


def comm(ser, cmd: bytes, delay: float = 0.15) -> bytes:
    ser.reset_input_buffer()
    ser.write(cmd + TERM)
    time.sleep(delay)
    return ser.read(128)


def _first_int(reply: bytes):
    digits = b""
    for ch in reply:
        if chr(ch).isdigit():
            digits += bytes([ch])
        elif digits:
            break
    return int(digits) if digits else None


def soft_stop(ser) -> None:
    for _ in range(3):
        comm(ser, b"@")
        time.sleep(0.05)


def sweep(ser, direction: str) -> str:
    """Constant-velocity move until the home flag, a limit, or timeout.
    Returns 'home' | 'limit' | 'timeout'."""
    limit_bit = BIT_LOWER if direction == "-" else BIT_UPPER
    cmd = ("M%s%d" % (direction, VELOCITY)).encode("ascii")
    print("  sweep %s: TX %r (timeout %.0fs)" % (direction, cmd, TIMEOUT_S))
    comm(ser, cmd)
    start = time.monotonic()
    last_print = 0.0
    while True:
        time.sleep(0.15)
        status = _first_int(comm(ser, b"]"))
        elapsed = time.monotonic() - start
        if status is None:
            print("    no status reply -> stop."); soft_stop(ser); return "timeout"
        if status & BIT_HOME:
            soft_stop(ser)
            print("    HOME flag found (status=%d, %.1fs)." % (status, elapsed))
            return "home"
        if status & (BIT_UPPER | BIT_LOWER):
            soft_stop(ser)
            which = "UPPER" if status & BIT_UPPER else "LOWER"
            print("    %s limit (status=%d, %.1fs) before flag." % (which, status, elapsed))
            return "limit"
        if elapsed - last_print >= 2.0:
            last_print = elapsed
            print("    ... moving (status=%d, %.0fs)" % (status, elapsed))
        if elapsed > TIMEOUT_S:
            soft_stop(ser)
            print("    TIMEOUT (%.0fs) -> stop." % elapsed)
            return "timeout"


def main() -> int:
    print("=== McPherson 789A-4 COARSE HOME on %s @ %d steps/s ===\n"
          "    Watch the mechanism. Ctrl-C soft-stops at any time.\n"
          % (PORT, VELOCITY))
    try:
        ser = serial.Serial(PORT, baudrate=9600, bytesize=serial.EIGHTBITS,
                            stopbits=serial.STOPBITS_ONE, parity=serial.PARITY_NONE,
                            timeout=0.3)
    except Exception as exc:
        print("Could not open %s: %s" % (PORT, exc))
        return 1

    try:
        time.sleep(0.2)
        rx = comm(ser, b" ")
        if b"v2.55" not in rx and b"#" not in rx:
            print("Unexpected identity %r -- aborting." % rx)
            return 1
        print("Identified 789A-4 (%r)." % rx)

        print("Enabling home circuit (A8)...")
        comm(ser, b"A8")

        status = _first_int(comm(ser, b"]")) or 0
        print("Initial status ] = %d" % status)
        if status & BIT_HOME:
            print("Already on the home flag -- nothing to sweep.")
            result = "home"
        else:
            result = "timeout"
            for direction in ("-", "+"):          # try DOWN, then UP
                result = sweep(ser, direction)
                if result == "home":
                    break
                if result == "timeout":
                    break
                print("  reversing after %s limit..." % direction)

        comm(ser, b"A0")                          # disable home circuit (clean)
        final = _first_int(comm(ser, b"]"))

        if result == "home":
            print("\nHOMED (coarse): on the home flag, final ] = %s." % final)
            print("Reference established. Follow-up: fine edge-find + set the "
                  "driver's position 0, then verify a known relative move.")
            return 0
        print("\nHOME NOT established (%s). Mechanism stopped safely; inspect "
              "before retrying (direction / flag / wiring)." % result)
        return 1
    except KeyboardInterrupt:
        print("\nCtrl-C -> soft stop.")
        soft_stop(ser)
        return 1
    finally:
        soft_stop(ser)
        ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
