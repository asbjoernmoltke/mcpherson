"""McPherson 789A-4 bounded JOG test -- COMMANDS MOTION. Run at the controller.

Unlike ``discover_mcpherson.py`` (read-only), this MOVES the grating. It is
deliberately small, slow, and symmetric so the mechanism ends where it began:

    set a gentle velocity -> jog +N steps -> jog -N steps (return)

Safety:
* Refuses to start a direction whose limit switch is already engaged.
* Polls the ``]`` status every cycle (bit 2 = moving, 64 = upper limit,
  128 = lower limit); on any limit bit, timeout, error, or Ctrl-C it sends the
  soft-stop ``@`` immediately.
* Never homes and never issues an absolute move.

Run:  python tests/jog_mcpherson.py [COMport] [steps] [velocity]
      defaults: COM5  20000 steps  10000 steps/s
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
VELOCITY = int(sys.argv[3]) if len(sys.argv) > 3 else 10000
TERM = b"\r\n"

BIT_MOVING, BIT_UPPER, BIT_LOWER = 2, 64, 128


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
    for _ in range(3):                       # triple-redundant, like the driver
        comm(ser, b"@")
        time.sleep(0.05)


def jog(ser, steps: int) -> bool:
    """Command a relative move and block until it stops. Returns True on a
    clean stop, False if a limit/timeout forced an abort."""
    direction = "+" if steps > 0 else "-"
    forbidden = BIT_UPPER if steps > 0 else BIT_LOWER

    status = _first_int(comm(ser, b"]")) or 0
    if status & forbidden:
        print("  REFUSED: %s-limit already engaged (status=%d)." % (direction, status))
        return False

    cmd = ("%s%d" % (direction, abs(steps))).encode("ascii")
    print("  TX %r ..." % cmd)
    comm(ser, cmd)

    expected_s = abs(steps) / max(1, VELOCITY)
    start = time.monotonic()
    hard_deadline = start + expected_s * 3 + 5.0
    saw_motion = False
    try:
        while True:
            time.sleep(0.2)
            raw = comm(ser, b"]")
            status = _first_int(raw)
            now = time.monotonic()
            if status is None:
                print("  no status reply (%r); stopping." % raw)
                soft_stop(ser)
                return False
            if status & (BIT_UPPER | BIT_LOWER):
                print("  LIMIT hit (status=%d) -> soft stop." % status)
                soft_stop(ser)
                return False
            if status & BIT_MOVING:
                saw_motion = True
            moving = bool(status & BIT_MOVING)
            # Done once it reports stopped and we're past ~half the expected
            # travel time (avoids a false 'done' before motion ramps up).
            if not moving and (saw_motion or now - start > expected_s * 0.5):
                print("  stopped (status=%d, %.1fs)." % (status, now - start))
                return True
            if now > hard_deadline:
                print("  TIMEOUT after %.1fs -> soft stop." % (now - start))
                soft_stop(ser)
                return False
    except KeyboardInterrupt:
        print("\n  Ctrl-C -> soft stop.")
        soft_stop(ser)
        return False


def main() -> int:
    print("=== McPherson 789A-4 JOG on %s: +/-%d steps @ %d steps/s ===\n"
          "    (symmetric; returns to start. Watch the mechanism.)"
          % (PORT, STEPS, VELOCITY))
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
            print("Unexpected identity reply %r -- aborting." % rx)
            return 1
        print("Identified 789A-4 (%r)." % rx)

        print("Setting velocity V%d ..." % VELOCITY)
        comm(ser, ("V%d" % VELOCITY).encode("ascii"))

        print("\n[1/2] Jog UP (+%d):" % STEPS)
        if not jog(ser, +STEPS):
            print("Up-jog aborted; not returning automatically. Inspect state.")
            return 1

        print("\n[2/2] Jog DOWN (-%d) to return:" % STEPS)
        if not jog(ser, -STEPS):
            print("Down-jog aborted. Mechanism may be offset from start.")
            return 1

        final = _first_int(comm(ser, b"]"))
        print("\nDone. Final status ] = %s (0 = idle off home/limits)." % final)
        print("If both jogs moved the grating and it returned, motion + the "
              "blocking/stop path work. Next: home to set the reference.")
    finally:
        soft_stop(ser)                       # belt-and-braces: leave it stopped
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
