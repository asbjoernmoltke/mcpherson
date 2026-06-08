"""McPherson 789A-4 homing-SWEEP verification -- COMMANDS MOTION.

Companion to ``home_mcpherson.py``. The grating was found already sitting on the
home flag, so coarse-home returned trivially. This proves the *approach*:

  A8 (enable home circuit) -> confirm ON flag (]=32)
  -> jog +OFFSET to clear the flag (confirm ]=0, off flag, no limit)
  -> sweep DOWN at constant velocity, re-detect the flag (]=32)

This also confirms the home direction (home is the '-' side here) and gives a
rough flag distance (elapsed x velocity). Bounded by the limit switches, a
timeout, and Ctrl-C (all soft-stop with @).

Run:  python tests/verify_home_mcpherson.py [COM] [offset] [velocity] [timeout_s]
      defaults: COM5  150000 steps  12000 steps/s  120 s
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
OFFSET = int(sys.argv[2]) if len(sys.argv) > 2 else 150000
VELOCITY = int(sys.argv[3]) if len(sys.argv) > 3 else 12000
TIMEOUT_S = float(sys.argv[4]) if len(sys.argv) > 4 else 120.0
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


def jog_blocking(ser, steps: int) -> bool:
    """Relative move, block until stopped. Returns True on clean stop."""
    forbidden = BIT_UPPER if steps > 0 else BIT_LOWER
    if (_first_int(comm(ser, b"]")) or 0) & forbidden:
        print("  REFUSED: limit already engaged."); return False
    comm(ser, ("%s%d" % ("+" if steps > 0 else "-", abs(steps))).encode("ascii"))
    expected = abs(steps) / max(1, VELOCITY)
    start = time.monotonic(); saw = False
    while True:
        time.sleep(0.15)
        s = _first_int(comm(ser, b"]"))
        now = time.monotonic()
        if s is None or s & (BIT_UPPER | BIT_LOWER):
            soft_stop(ser); print("  limit/no-reply during jog (s=%s)." % s); return False
        if s & BIT_MOVING:
            saw = True
        elif saw or now - start > expected * 0.5:
            return True
        if now - start > expected * 3 + 5:
            soft_stop(ser); print("  jog timeout."); return False


def main() -> int:
    print("=== 789A-4 homing-sweep verification on %s ===\n"
          "    +%d steps off flag, then sweep -%d/s back. Watch it.\n"
          % (PORT, OFFSET, VELOCITY))
    try:
        ser = serial.Serial(PORT, baudrate=9600, bytesize=serial.EIGHTBITS,
                            stopbits=serial.STOPBITS_ONE, parity=serial.PARITY_NONE,
                            timeout=0.3)
    except Exception as exc:
        print("Could not open %s: %s" % (PORT, exc)); return 1

    try:
        time.sleep(0.2)
        rx = comm(ser, b" ")
        if b"v2.55" not in rx and b"#" not in rx:
            print("Unexpected identity %r." % rx); return 1
        print("Identified 789A-4.")

        comm(ser, b"A8")                              # enable home circuit
        comm(ser, ("V%d" % VELOCITY).encode("ascii"))
        on_flag = (_first_int(comm(ser, b"]")) or 0) & BIT_HOME
        print("Start: ] home bit = %s (expect ON flag)." % bool(on_flag))

        print("\n[1/2] Jog +%d to clear the flag..." % OFFSET)
        if not jog_blocking(ser, +OFFSET):
            print("Jog failed; aborting."); return 1
        off = _first_int(comm(ser, b"]")) or 0
        print("  ] = %d -> %s flag." % (off, "OFF" if not off & BIT_HOME else "STILL ON"))
        if off & BIT_HOME:
            print("  Flag wider than offset; re-run with a larger offset.")
            return 1

        print("\n[2/2] Sweep DOWN (M-%d) to re-acquire the flag..." % VELOCITY)
        comm(ser, ("M-%d" % VELOCITY).encode("ascii"))
        start = time.monotonic(); result = "timeout"
        while True:
            time.sleep(0.15)
            s = _first_int(comm(ser, b"]")); el = time.monotonic() - start
            if s is None:
                soft_stop(ser); break
            if s & BIT_HOME:
                soft_stop(ser); result = "home"
                print("  HOME re-acquired: ]=%d after %.1fs (~%d steps)."
                      % (s, el, int(el * VELOCITY))); break
            if s & (BIT_UPPER | BIT_LOWER):
                soft_stop(ser); result = "limit"
                print("  LIMIT (%d) before flag at %.1fs -- wrong direction?" % (s, el)); break
            if el > TIMEOUT_S:
                soft_stop(ser); print("  timeout %.0fs." % el); break

        comm(ser, b"A0")
        if result == "home":
            print("\nHOMING SWEEP VERIFIED: off-flag -> swept down -> re-detected "
                  "the flag. Home is the '-' direction; driver's M- assumption holds.")
            return 0
        print("\nSweep did not re-acquire the flag (%s). Inspect before retry." % result)
        return 1
    except KeyboardInterrupt:
        print("\nCtrl-C -> soft stop."); soft_stop(ser); return 1
    finally:
        soft_stop(ser); ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
