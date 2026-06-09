"""McPherson 789A-4 calibration move -- COMMANDS MOTION. Read the counter.

Commands a single known relative move and holds, so you can read the
monochromator's mechanical wavelength counter before and after. From the
counter delta we get nm/step directly (counter = nm x 10), which resolves
36000 vs 18000 steps/rev and the scan-direction sign.

Bounded by the limit switches; a small move (~90k steps ~ 2% of travel) stays
far from them. Raw serial (clean exit).

Run:  python tests/cal_move_mcpherson.py [COM] [signed_steps] [velocity]
      defaults: COM5  +90000  12000
"""
from __future__ import annotations

import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 90000
VELOCITY = int(sys.argv[3]) if len(sys.argv) > 3 else 12000
TERM = b"\r\n"
BIT_MOVING, BIT_UPPER, BIT_LOWER = 2, 64, 128


def comm(ser, cmd, delay=0.15):
    ser.reset_input_buffer()
    ser.write(cmd + TERM)
    time.sleep(delay)
    return ser.read(128)


def status(ser) -> int:
    digits = ""
    for ch in comm(ser, b"]").decode("utf-8", "replace"):
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else 0


def soft_stop(ser):
    for _ in range(3):
        comm(ser, b"@"); time.sleep(0.05)


def main() -> int:
    try:
        ser = serial.Serial(PORT, 9600, timeout=0.3)
    except Exception as exc:
        print("Could not open %s: %s" % (PORT, exc)); return 1
    try:
        time.sleep(0.2)
        if b"v2.55" not in comm(ser, b" ") and b"#" not in comm(ser, b" "):
            print("Not the 789A-4?"); return 1

        s0 = status(ser)
        if s0 & (BIT_UPPER | BIT_LOWER):
            print("At a limit (%d); aborting." % s0); return 1
        comm(ser, ("V%d" % VELOCITY).encode())

        sign = "+" if STEPS > 0 else "-"
        print(">>> READ THE COUNTER NOW (before), then I move %s%d steps."
              % (sign, abs(STEPS)))
        comm(ser, ("%s%d" % (sign, abs(STEPS))).encode())

        t = time.monotonic()
        expected = abs(STEPS) / max(1, VELOCITY)
        saw = False
        while True:
            s = status(ser); el = time.monotonic() - t
            if s & (BIT_UPPER | BIT_LOWER):
                soft_stop(ser); print("LIMIT hit (%d) -- stopped." % s); return 1
            if s & BIT_MOVING:
                saw = True
            elif saw or el > expected * 0.5:
                break
            if el > expected * 3 + 5:
                soft_stop(ser); print("timeout."); return 1
            time.sleep(0.1)

        print("Move done (%.1fs). >>> READ THE COUNTER NOW (after)." % (time.monotonic() - t))
        print("nm/step = (after - before)/10 / %d. Compare: 5.56e-5 => 36000/rev, "
              "1.11e-4 => 18000/rev (for 1200 g/mm)." % STEPS)
        print("To move back: python tests/cal_move_mcpherson.py %s %d %d"
              % (PORT, -STEPS, VELOCITY))
        return 0
    finally:
        ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
