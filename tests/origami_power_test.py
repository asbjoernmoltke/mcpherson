"""Interactive Origami XPS power/energy bench tool -- RUN AT THE LASER.

Purpose: determine empirically which control register drives the output and
its scaling, by setting candidate registers and reading the laser's measured
power/energy (correlate with your external power meter).

  *** THIS COMMANDS LASER EMISSION. Run only with the beam safely dumped and
      appropriate eye protection. Emission is always disabled on exit. ***

Candidate control registers (Origami XPS, type 0x95, from Register Files/95.txt):
  0x05  Relative output power   [0-4000]   (U16)
  0x20  Output power setpoint   W          (U16, x0.001)
  0x21  Output energy setpoint  nJ         (U16, x10)
Read-back:
  0x10  Output power (measured) W          (U16, x0.001)
  0x11  Output energy (measured) nJ        (U16, x10)
  0x02/0x03 Regen/Output PRR    Hz         (U32)

Notes from the hardware owner: older firmware expresses the setting in nJ
(max ~40000 nJ = 40 uJ at <=100 kHz); newer firmware may use mW. Max pulse
energy is rep-rate dependent (energy-limited <=100 kHz at 40 uJ, then
average-power-limited: 200 kHz->20 uJ, 300 kHz->40/3 uJ, ...). Use this tool
to find the truth for THIS unit.

Run:  python tests/origami_power_test.py [COMport]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectrometer.drivers.laser_nkt import OrigamiXPS  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
ADDR = 15

# register : (name, kind, read_scale)  kind in {u8,u16,u32}
REG_REL_POWER = 0x05      # [0-4000]
REG_FSM_TARGET = 0x30
REG_SHUTTER = 0x34
REG_PRR_INDEX = 0x35
REG_FREQ_DIV = 0x36
REG_POWER_W_SETPT = 0x20  # x0.001 W
REG_ENERGY_NJ_SETPT = 0x21  # x10 nJ
REG_MEAS_POWER_W = 0x10   # x0.001 W
REG_MEAS_ENERGY_NJ = 0x11  # x10 nJ
REG_OUT_PRR = 0x03        # Hz, U32
REG_FSM_STATE = 0x01
REG_STATUS = 0x66
FSM_OFF, FSM_RUN = 1, 6   # FSM_RUN to confirm (valid [1,3,5,6])


class Bench:
    def __init__(self, port):
        self.port = port
        self.laser = OrigamiXPS(port=port)
        self.nkt = self.laser._api()

    def _ck(self, result, what):
        ok = result == 0
        print(("  ok  " if ok else "  ERR ") + what
              + ("" if ok else " -> " + self.nkt.RegisterResultTypes(result)))
        return ok

    def ru8(self, reg):
        r, v = self.nkt.registerReadU8(self.port, ADDR, reg, -1)
        return v if r == 0 else None

    def ru16(self, reg):
        r, v = self.nkt.registerReadU16(self.port, ADDR, reg, -1)
        return v if r == 0 else None

    def ru32(self, reg):
        r, v = self.nkt.registerReadU32(self.port, ADDR, reg, -1)
        return v if r == 0 else None

    def wu8(self, reg, val, what):
        return self._ck(self.nkt.registerWriteU8(self.port, ADDR, reg, val, -1), what)

    def wu16(self, reg, val, what):
        return self._ck(self.nkt.registerWriteU16(self.port, ADDR, reg, val, -1), what)

    def wu32(self, reg, val, what):
        return self._ck(self.nkt.registerWriteU32(self.port, ADDR, reg, val, -1), what)

    # --- lifecycle ----------------------------------------------------
    def open(self):
        self.nkt.openPorts(self.port, 1, 0)
        print(f"Opened {self.port}. Forcing standby (shutter closed, FSM OFF).")
        self.disable()

    def disable(self):
        self.wu8(REG_SHUTTER, 0, "shutter -> closed")
        self.wu8(REG_FSM_TARGET, FSM_OFF, "FSM -> OFF")

    def enable(self):
        ans = input("  Type 'YES' to ENABLE EMISSION (beam dumped?): ").strip()
        if ans != "YES":
            print("  aborted.")
            return
        self.wu8(REG_FSM_TARGET, FSM_RUN, f"FSM -> RUN({FSM_RUN})")
        self.wu8(REG_SHUTTER, 1, "shutter -> open")

    def close(self):
        self.disable()
        self.nkt.closePorts(self.port)
        print("Disabled and closed port.")

    # --- readouts -----------------------------------------------------
    def status(self):
        status = self.ru32(REG_STATUS)
        emitting = bool(status) and bool(status & 1)
        mp, me = self.ru16(REG_MEAS_POWER_W), self.ru16(REG_MEAS_ENERGY_NJ)
        prr = self.ru32(REG_OUT_PRR)
        print(f"  FSM state={self.ru8(REG_FSM_STATE)}  emission={'ON' if emitting else 'off'}"
              f"  status=0x{(status or 0):X}")
        print(f"  rep index={self.ru8(REG_PRR_INDEX)}  out PRR={prr} Hz"
              f"  freq-div(PP)={self.ru32(REG_FREQ_DIV)}")
        print(f"  setpoints: rel-power(0x05)={self.ru16(REG_REL_POWER)}"
              f"  power(0x20)={_scaled(self.ru16(REG_POWER_W_SETPT), 0.001)} W"
              f"  energy(0x21)={_scaled(self.ru16(REG_ENERGY_NJ_SETPT), 10)} nJ")
        print(f"  MEASURED: power(0x10)={_scaled(mp, 0.001)} W"
              f"  energy(0x11)={_scaled(me, 10)} nJ")

    def sweep(self, reg, start, stop, step, dwell):
        import time
        reg = int(reg, 0)
        print(f"Sweeping reg 0x{reg:02X} from {start} to {stop} step {step}, "
              f"dwell {dwell}s. Reading measured power/energy.")
        v = start
        while (step > 0 and v <= stop) or (step < 0 and v >= stop):
            self.wu16(reg, int(v), f"0x{reg:02X} <- {int(v)}")
            time.sleep(dwell)
            mp = _scaled(self.ru16(REG_MEAS_POWER_W), 0.001)
            me = _scaled(self.ru16(REG_MEAS_ENERGY_NJ), 10)
            print(f"    set={int(v):6d}  meas power={mp} W  energy={me} nJ")
            v += step


def _scaled(raw, scale):
    return None if raw is None else round(raw * scale, 4)


HELP = """
commands:
  s                         show status / readouts
  rate <index>              set rep-rate index (0-12)
  pp <n>                    set pulse-picker (freq-division) 1..1000000
  rel <0-4000>              set relative output power (0x05)
  powerW <watts>            set output power setpoint (0x20)
  energy <nJ>               set output energy setpoint (0x21)
  on / off                  enable (with confirm) / disable emission
  sweep <reg> <a> <b> <st> <dwell>   e.g. sweep 0x05 0 4000 200 1.0
  h                         help
  q                         disable emission and quit
"""


def main() -> int:
    print(__doc__)
    bench = Bench(PORT)
    bench.open()
    bench.status()
    print(HELP)
    try:
        while True:
            try:
                parts = input("origami> ").strip().split()
            except EOFError:
                break
            if not parts:
                continue
            cmd, args = parts[0], parts[1:]
            try:
                if cmd == "q":
                    break
                elif cmd in ("h", "help"):
                    print(HELP)
                elif cmd == "s":
                    bench.status()
                elif cmd == "rate":
                    bench.wu8(REG_PRR_INDEX, int(args[0]), f"rep index <- {args[0]}")
                elif cmd == "pp":
                    bench.wu32(REG_FREQ_DIV, int(args[0]), f"freq-div <- {args[0]}")
                elif cmd == "rel":
                    bench.wu16(REG_REL_POWER, int(args[0]), f"0x05 <- {args[0]}")
                elif cmd == "powerW":
                    bench.wu16(REG_POWER_W_SETPT, int(round(float(args[0]) / 0.001)),
                               f"0x20 <- {args[0]} W")
                elif cmd == "energy":
                    bench.wu16(REG_ENERGY_NJ_SETPT, int(round(float(args[0]) / 10)),
                               f"0x21 <- {args[0]} nJ")
                elif cmd == "on":
                    bench.enable()
                elif cmd == "off":
                    bench.disable()
                elif cmd == "sweep":
                    bench.sweep(args[0], float(args[1]), float(args[2]),
                                float(args[3]), float(args[4]))
                else:
                    print("  unknown command; 'h' for help.")
            except (IndexError, ValueError) as exc:
                print(f"  bad args: {exc}")
    finally:
        bench.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
