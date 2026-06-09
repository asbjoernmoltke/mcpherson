"""McPherson 789A-4 FINE-HOME experiment -- COMMANDS MOTION. Read-then-decide.

Question under test: is the controller's high-accuracy Find-Home (F1000,0)
actually broken, or did the earlier run just time out? At 1000 steps/s, scanning
back across the ~72000-step settle takes ~72 s, but the driver only waited 60 s.

This runs the fine-find with a GENEROUS timeout and logs every ] transition with
timestamps so we can see exactly what F does: enable home circuit, make sure
we're on the flag, settle in, A24 (high-accuracy), F1000,0, then watch until it
stops (moving bit clears) or the timeout. Bounded by the limit switches.

Raw serial (no SafeSerial), so it can't hit the close()/__del__ path.

Run:  python tests/fine_home_mcpherson.py [COM] [settle] [F_speed] [timeout_s]
      defaults: COM5  72000  1000  180
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
SETTLE = int(sys.argv[2]) if len(sys.argv) > 2 else 72000
F_SPEED = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
TIMEOUT_S = float(sys.argv[4]) if len(sys.argv) > 4 else 180.0
TERM = b"\r\n"

BIT_MOVING, BIT_HOME, BIT_UPPER, BIT_LOWER = 2, 32, 64, 128


def comm(ser, cmd: bytes, delay: float = 0.15) -> bytes:
    ser.reset_input_buffer()
    ser.write(cmd + TERM)
    time.sleep(delay)
    return ser.read(128)


def status(ser) -> int:
    raw = comm(ser, b"]")
    digits = ""
    for ch in raw.decode("utf-8", "replace"):
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else 0


def soft_stop(ser) -> None:
    for _ in range(3):
        comm(ser, b"@")
        time.sleep(0.05)


def sweep_to_flag(ser) -> bool:
    """Coarse M-23000 onto the flag if we're not already on it."""
    if status(ser) & BIT_HOME:
        return True
    comm(ser, b"M-23000")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        s = status(ser)
        if s & BIT_HOME:
            soft_stop(ser); return True
        if s & (BIT_UPPER | BIT_LOWER):
            soft_stop(ser); print("  limit before flag (%d)." % s); return False
        time.sleep(0.1)
    soft_stop(ser); return False


def main() -> int:
    print("=== 789A-4 fine-home experiment on %s: settle %d, F%d, timeout %.0fs ==="
          % (PORT, SETTLE, F_SPEED, TIMEOUT_S))
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

        comm(ser, b"A8")
        if not sweep_to_flag(ser):
            print("Could not get on the flag; aborting."); return 1
        print("On the home flag (] = %d)." % status(ser))

        if SETTLE:
            comm(ser, ("V60000").encode()); comm(ser, ("-%d" % SETTLE).encode())
            t = time.monotonic()
            while status(ser) & BIT_MOVING and time.monotonic() - t < 10:
                time.sleep(0.1)
            print("Settled -%d (] = %d)." % (SETTLE, status(ser)))

        comm(ser, b"A24")
        print("A24 high-accuracy; ] = %d. Sending F%d,0 ..." % (status(ser), F_SPEED))
        comm(ser, ("F%d,0" % F_SPEED).encode())

        start = time.monotonic(); last = None; result = "timeout"
        while True:
            s = status(ser); el = time.monotonic() - start
            if s != last:
                print("  t=%5.1fs  ] = %d  (moving=%s home=%s)"
                      % (el, s, bool(s & BIT_MOVING), bool(s & BIT_HOME)))
                last = s
            if s & (BIT_UPPER | BIT_LOWER):
                soft_stop(ser); result = "limit (%d)" % s; break
            if not (s & BIT_MOVING) and el > 1.0:
                result = "STOPPED on ]=%d (home=%s)" % (s, bool(s & BIT_HOME)); break
            if el > TIMEOUT_S:
                soft_stop(ser); result = "timeout after %.0fs" % el; break
            time.sleep(0.2)

        comm(ser, b"A0")
        print("\nResult: %s." % result)
        print("Read the mechanical counter -- did it settle on a stable value? "
              "If F stopped cleanly on the flag, F1000,0 works; the earlier run "
              "just timed out (60s < ~72s scan).")
        return 0
    except KeyboardInterrupt:
        print("\nCtrl-C -> soft stop."); soft_stop(ser); return 1
    finally:
        soft_stop(ser); ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
