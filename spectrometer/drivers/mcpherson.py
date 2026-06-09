# https://github.com/mitbailey/MMC/tree/master
# @file mp_789a_4.py
# @author Mit Bailey (mitbailey@outlook.com)
# @brief Driver for the McPherson Model 789A-4 Scan Controller.
# @version See Git tags for version information.
# @date 2022.11.04
# 
# @copyright Copyright (c) 2022
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
#

# import serial
from __future__ import annotations
import threading
import time
from ..utilities import ports_finder
from ..utilities import safe_serial
from threading import Lock
from ..utilities import log

from .base import GratingDriver

class MP_789A_4(GratingDriver):
    WR_DLY = 0.05
    HSM = 4
    MAX_VEL = 60000
    DEF_VEL = 60000
    MIN_VEL = 0

    # ] limit-status reply is a decimal BIT-SUM. Parse it as an int and test
    # bits -- substring checks ('2' in '32') misfire. Confirmed on hw 2026-06-08:
    # the home bit only appears after `A8`; home is the '-' direction.
    ST_MOVING = 2
    ST_HOME = 32
    ST_UPPER = 64
    ST_LOWER = 128
    HOME_SWEEP_TIMEOUT = 300.0   # s; bounded by the limit switches in any case
    HOME_SETTLE_STEPS = 10000    # settle into the flag before the fine edge-find
    FINE_HOME_TIMEOUT = 90.0     # F1000,0 scans ~1 s per 1000 settle steps; margin

    @staticmethod
    def _parse_status(reply) -> int:
        """First integer token in a controller reply (e.g. ``]   32 `` -> 32).
        Robust to the ``]``/``^`` echo and trailing spaces/CRLF."""
        if isinstance(reply, (bytes, bytearray)):
            reply = reply.decode('utf-8', errors='replace')
        digits = ''
        for ch in reply:
            if ch.isdigit():
                digits += ch
            elif digits:
                break
        return int(digits) if digits else 0

    def _limit_status(self) -> int:
        """Parsed ``]`` status (bit-sum: 2 moving, 32 home, 64/128 limits)."""
        return self._parse_status(self.s.xfer([b']']))

    def backend(self)->str:
        return 'MP_789A_4'

    def __init__(self, port):
        """ MP_789A_4 constructor.

        Args:
            port (_type_): The port on which to attempt a connection.

        Raises:
            RuntimeError: Raised if `port` is NoneType.
            RuntimeError: Raised if `port` is not found in the list of available ports; may already be in use.
            RuntimeError: Raised if the serial ID request response times out.
            RuntimeError: Raised if the serial ID request response is invalid. 
            RuntimeError: Raised is the SafeSerial object is NoneType.
        """

        # Default values for the class.
        self.s_name = 'MP789'
        self.l_name = 'McPherson 789A-4'
        self._homing = False
        self._moving = False
        self.moving_poll_mutex = Lock()
        self._backlash_lock = False
        self.stop_queued = 0
        self._position = 0

        self._home_speed_mult = 1
        self._move_speed_mult = 1

        log.info('Attempting to connect to McPherson Model 789A-4 Scan Controller on port %s.'%(port))

        # Check if we were given a port.
        if port is None:
            log.error('Port is none type.')
            raise RuntimeError('Port is none type.')
        
        # Check if the port is available.
        ser_ports = ports_finder.find_serial_ports()
        if port not in ser_ports:
            log.error('Port not valid. Is another program using the port?')
            raise RuntimeError('Port not valid. Is another program using the port?')

        # Get a SafeSerial connection on the port and begin communication.
        self.s = safe_serial.SafeSerial(port, 9600, timeout=0.3)

        # self.s.write(b' ')
        # time.sleep(MP_789A_4.WR_DLY)
        # rx = self.s.read(128)#.decode('utf-8').rstrip()

        rx = self.s.xfer([b' '])

        log.debug(rx)

        # Check the response to ensure connection to a 789A-4.
        if rx is None or rx == b'':
            raise RuntimeError('Response timed out.')
        elif rx == b' v2.55\r\n#\r\n':
            log.info('McPherson model 789A-4 Scan Controller found.')
        elif rx == b' #\r\n':
            log.info('McPherson model 789A-4 Scan Controller already initialized.')
        else:
            raise RuntimeError('Invalid response.')

        if self.s is None:
            raise RuntimeError('self.s is None')

        # Starting movement watchdog. Daemon + a stop event so the process can
        # exit cleanly and close() can join it (the original looped forever).
        self._watchdog_stop = threading.Event()
        self.movement_status_tid = threading.Thread(
            target=self.movement_status_thread, daemon=True)
        self.movement_status_tid.start()

        # Home the 789A-4.
        # self.home()

    def movement_status_thread(self):
        # This thread runs in the background.
        # It will be the only thing which calls the internal _is_moving() function.
        # The middleware calls the external is_moving() function.
        # This way we can ensure that the device is only queried for movement status when it is safe to do so.

        while not self._watchdog_stop.is_set():
            time.sleep(0.25)

            axis_moving = self._moving

            if axis_moving:
                # Check if the backlash lock is active. If so, we should check again later.
                if self._backlash_lock:
                    # log.info('Backlash lock is active. Skipping movement inquiry.')
                    log.info('Backlash lock is active, but not skipping movement inquiry.')

                    # continue

                # Update the movement status of the axis which is moving.
                log.info('Checking movement status of axis.')
                self._moving = self._is_moving()
                log.info(f'Axis is moving? {self._moving}.')

            # Checking for movement in this last case isn't necessary because we know when we initiate an axis move - it should be set to True (moving) when its told to move. The assumption should be that it does begin to move. Then, we use the previous case to prove it isn't moving once its stopped (or failed to start moving).
            elif not axis_moving:
                # Update the movement status of all alive axes, since none are reported as moving.
                log.info('Axis has not been marked or reported as moving. Skipping movement inquiry.')

    def set_stage(self, stage):
        pass

    def get_stage(self):
        return None

    def home(self) -> bool:
        """Home the 789A-4 (integer ``]`` bit-parsing; validated on hw 2026-06-08).

        Enables the home circuit (``A8`` -- REQUIRED before the home bit 32
        appears in ``]``), brings the mechanism onto the home flag (home is the
        ``-`` direction), runs the controller's high-accuracy Find-Home to pin
        the edge, then resets the software position to 0.

        Motion during homing is driven by direct ``]`` polling (not the
        watchdog), so ``_moving`` is kept False and ``_homing`` True throughout.

        Raises:
            RuntimeError: on a limit switch (cannot find the flag) or timeout.
        Returns:
            bool: True on success.
        """
        self.stop()                          # halt + clear flags before homing
        self._enact_speed_factor(self._home_speed_mult)
        self._homing = True
        self._moving = False
        log.info('Beginning home.')
        try:
            self.s.xfer([b'A8'])             # enable home circuit (REQUIRED)
            status = self._limit_status()
            log.info('Home: initial ] status = %d.' % status)
            if status & (self.ST_UPPER | self.ST_LOWER):
                raise RuntimeError(
                    'On a limit switch (status=%d); move off it before homing.'
                    % status)

            if status & self.ST_HOME:
                # Already on the flag: back off (+) until clear, so the approach
                # below always lands on the flag from the same (upper) side.
                log.info('On the home flag; backing off (+) until clear.')
                self._sweep_to_home_state(b'M+23000', want_on_flag=False)

            # Approach the flag from above (home is the '-' direction); the
            # coarse sweep stops on the flag's leading edge.
            log.info('Sweeping - to the home flag.')
            self._sweep_to_home_state(b'M-23000', want_on_flag=True)

            # Fine-edge homing. Settle a SHORT way into the flag, then the
            # controller's high-accuracy Find-Home (F1000,0) creeps to the
            # precise edge. Verified on hw 2026-06-08: F1000,0 works but scans
            # at 1000 steps/s (~1 s per 1000 settle steps), so the settle is
            # kept small (the original -72000 took ~94 s). A24 switches the home
            # bit to the narrow high-accuracy zone (reads 0 just off it), so we
            # wait on the moving bit, not the home bit. NOTE: this fine path is
            # not yet re-verified on hardware after trimming the settle.
            log.info('Fine edge-find: settle -%d then F1000,0.'
                     % self.HOME_SETTLE_STEPS)
            self.s.xfer([b'-%d' % self.HOME_SETTLE_STEPS])
            self._wait_stopped(timeout=30.0)
            self.s.xfer([b'A24'])            # high-accuracy circuit
            self.s.xfer([b'F1000,0'])        # find home edge @ 1000 steps/s
            time.sleep(1.0)                  # let F start before we poll (it
            #                                  ramps within ~0.5 s) so we don't
            #                                  read a premature 'stopped'.
            self._wait_stopped(timeout=self.FINE_HOME_TIMEOUT)
            self.s.xfer([b'A0'])             # disable home circuit
            self._position = 0
            log.info('Home complete (fine edge); software position 0.')
            return True
        finally:
            self._moving = False
            self._homing = False
            self._enact_speed_factor(self._move_speed_mult)

    # --- homing helpers (integer-status, limit-safe) -------------------
    def _sweep_to_home_state(self, move_cmd: bytes, want_on_flag: bool) -> None:
        """Constant-velocity sweep until the home bit matches ``want_on_flag``,
        then soft-stop. Bounded by the limit switches and a timeout."""
        self.s.xfer([move_cmd])
        deadline = time.monotonic() + self.HOME_SWEEP_TIMEOUT
        while True:
            status = self._limit_status()
            if status & (self.ST_UPPER | self.ST_LOWER):
                self._soft_stop()
                raise RuntimeError(
                    'Hit a limit switch while homing (status=%d). Home flag '
                    'not found in this direction.' % status)
            if bool(status & self.ST_HOME) == want_on_flag:
                self._soft_stop()
                return
            if time.monotonic() > deadline:
                self._soft_stop()
                raise RuntimeError('Home sweep timed out (status=%d).' % status)
            time.sleep(MP_789A_4.WR_DLY * 3)

    def _wait_stopped(self, timeout: float = 30.0) -> None:
        """Block until the controller reports stopped (``]`` moving bit clear),
        raising on a limit switch. For finite moves / Find-Home."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self._limit_status()
            if status & (self.ST_UPPER | self.ST_LOWER):
                self._soft_stop()
                raise RuntimeError('Hit a limit switch (status=%d).' % status)
            if not (status & self.ST_MOVING):
                return
            time.sleep(MP_789A_4.WR_DLY * 3)
        # A timeout means motion did not complete as expected -- treat it as a
        # failure, never a silent success.
        self._soft_stop()
        raise RuntimeError('Move did not stop within %.0fs (status=%d).'
                           % (timeout, self._limit_status()))

    def get_position(self):
        """ Returns the current position of the 789A-4.

        Returns:
            _type_: The position.
        """

        log.debug('func: get_position')
        return self._position
    
    def _soft_stop(self):
        """Triple-redundant ``@`` soft-stop WITHOUT touching the _moving /
        _homing flags (used inside the homing sequence)."""
        for _ in range(3):
            self.s.xfer([b'@'])
            log.info('Stopping.')
            time.sleep(MP_789A_4.WR_DLY)

    def stop(self):
        """ Triple-redundant serial stop command (E-stop path). """
        self.stop_queued = 1
        self._soft_stop()
        self._moving = False
        self._homing = False

    def is_moving(self):
        """_summary_

        Returns:
            _type_: Is moving (True) or is not moving (False).
        """

        log.debug('func: is_moving')

        if self._backlash_lock:
            log.info('is_moving is returning true because the Backlash lock is active.')
            return True
        elif self._homing:
            return True
        else:
            return self._moving

        # # If the `_backlash_lock` flag is set then the 789A-4 is already performing a move command.
        # # If the `_backlash_lock` flag is set then the 789A-4 is already performing a move command.
        # # if self._backlash_lock:
        # #     log.warn('BACKLASH LOCK is set. Device is moving.')
        # #     return True

        # # Acquire the mutex and begin inquiring as to the moving status (double-redundant).
        # self.moving_poll_mutex.acquire()
        # log.debug('ACQUIRED MOVING POLL MUTEX')
        # status = self.s.xfer([b'^']).decode('utf-8').rstrip()
        # # self.s.write(b'^')
        # # time.sleep(MP_789A_4.WR_DLY)
        # # status = self.s.read(128).decode('utf-8').rstrip()
        # time.sleep(MP_789A_4.WR_DLY)
        # status2 = self.s.xfer([b'^']).decode('utf-8').rstrip()
        # # self.s.write(b'^')
        # # time.sleep(MP_789A_4.WR_DLY)
        # # status2 = self.s.read(128).decode('utf-8').rstrip()
        # time.sleep(MP_789A_4.WR_DLY)
        # self.moving_poll_mutex.release()

        # # Check the returned status to determine movement status.
        # if ('0' in status and '0' in status2) and ('+' not in status and '+' not in status2 and '-' not in status and '-' not in status2):
        #     log.info('MOVING STATUS >>>%s<<< >>>%s<<<; INDICATES STOPPED.'%(status, status2))
        #     self._moving = False
        #     return False
        # else:
        #     log.info('MOVING STATUS: >>>%s<<<; INDICATES MOVING.'%(status))
        #     self._moving = True
        #     return True

    # Internal-calling only.
    def _is_moving(self):
        self.moving_poll_mutex.acquire()

        log.debug('ACQUIRED MOVING POLL MUTEX')
        raw = self.s.xfer([b'^'])
        log.debug('789 _status:', raw)
        time.sleep(MP_789A_4.WR_DLY)

        # `^` reads moving status (0 = stopped, non-zero = in motion). Parse the
        # integer rather than substring-matching '0' (which a value like 10/20
        # would also contain).
        moving = self._parse_status(raw) != 0

        self.moving_poll_mutex.release()

        self._moving = moving
        return moving

    def is_homing(self):
        """ Return homing status.

        Returns:
            _type_: Homing (True) or not homing (False).
        """

        log.debug('func: is_homing')
        return self._homing

    # Moves to a position, in steps, based on the software's understanding of where it last was.
    def move_to(self, position: int, backlash: int = 0):
        """ Moves to a position based on the software's understanding of where the 789A-4 last was.
            Position information is not tracked by the 789A-4.

        Args:
            position (int): The position in steps.
            backlash (int): The amount of backlash correction to perform in steps.
        """

        if self._homing or self._moving or self._backlash_lock:
            log.warn(f'Device is homing ({self._homing}), moving ({self._moving}), or performing backlash correction ({self._backlash_lock}). Cannot move.')
            return
        
        # self.moving_poll_mutex.acquire()
        self._moving = True

        try:

            self.stop_queued = 0

            log.debug('func: move_to')
            
            steps = position - self._position

            if (steps < 0) and (backlash > 0):
                self._backlash_lock = True

                try:
                    if self.stop_queued == 0:
                        log.debug('MOVE-DEBUG: Performing overshot manuever.')
                        self.move_relative(steps - backlash, backlash_bypass=True)

                    if self.stop_queued == 0:
                        log.debug('MOVE-DEBUG: Performing backlash correction.')
                        self.move_relative(backlash, backlash_bypass=True)

                except Exception as e:
                    log.error('Error during backlash correction:', e)
                    self._backlash_lock = False
                    raise e
                
                self._backlash_lock = False
            else:
                log.debug('MOVE-DEBUG: Performing simple no-backlash move.')
                self.move_relative(steps)

            self.stop_queued = 0
            self._backlash_lock = False

        except Exception as e:
            # self.moving_poll_mutex.release()
            raise e

        # # Backlash correction only necessary if (1) requested and (2) moving in the negative direction.
        # log.warn('BACKLASH: %d'%(backlash))
        # log.warn('BACKLASH: %d'%(backlash))
        # log.warn('BACKLASH: %d'%(backlash))
        # if (steps < 0) and (backlash > 0):
        #     # Acquire `_backlash_lock` (should probably be a mutex lock, not a flag). Prevents movement before backlash.
        #     self._backlash_lock = True
            
        #     # Check if we have a queued stop command prior to moving.
        #     if self.stop_queued == 0:
        #         self.move_relative(steps - backlash)
            
        #     # Check if we have a queued stop command prior to performing backlash correction.
        #     if self.stop_queued == 0:
        #         self.move_relative(backlash)
            
        #     # Release lock.
        #     self._backlash_lock = False
        # else:
        #     # Simple move.
        #     self.move_relative(steps)

        # # Clear all queued stops since move/stop has been processed.
        # self.stop_queued = 0

    def move_relative(self, steps: int, backlash_bypass=False):
        """ Private function for use by `move_to()`. Moves a relative number of steps.

        Args:
            steps (int): Number of steps to move.
        """

        log.debug('func: move_relative')
        log.info('Being told to move %d steps.'%(steps))

        # Query limit switch status.
        # self.s.write(b']')
        # time.sleep(MP_789A_4.WR_DLY)     
        # rx = self.s.read(128).decode('utf-8')
        # Parse the limit status as an int + test bits (substring checks like
        # '64' in rx miss combined states e.g. 66 = upper-limit + moving).
        status = self._parse_status(self.s.xfer([b']']))

        if steps > 0:
            # Verify we are not at the upper limit.
            if status & self.ST_UPPER:
                log.warn('Upper limit switch hit. Cannot move further in this direction.')
                raise RuntimeError('Upper limit switch hit. Cannot move further in this direction.')

            log.info('Moving...')
            self._moving = True
            log.debug([b'+%d'%(steps)])
            # self.s.write(b'+%d'%(steps))

            self.s.xfer([b'+%d'%(steps)])
            time.sleep(MP_789A_4.WR_DLY)
        elif steps < 0:
            # Verify we are not at the lower limit.
            if status & self.ST_LOWER:
                log.warn('Lower limit switch hit. Cannot move further in this direction.')
                raise RuntimeError('Lower limit switch hit. Cannot move further in this direction.')

            log.info('Moving...')
            self._moving = True
            log.debug(b'-%d'%(steps))
            # self.s.write(b'-%d'%(steps * -1))

            self.s.xfer([b'-%d'%(steps)])
            time.sleep(MP_789A_4.WR_DLY)
        else:
            log.info('Not moving (0 steps).')
            return
        self._position += steps

        self._moving = True
        if not backlash_bypass:
            while self.is_moving():
                log.debug('(not bypass) BLOCKING until movement is completed.')
                time.sleep(0.05)
        elif backlash_bypass:
            while self._moving:
                log.debug('(bypass) BLOCKING until movement is completed.')
                time.sleep(0.05)

        log.debug('FINISHED BLOCKING because moving is', self._moving)
        time.sleep(MP_789A_4.WR_DLY)
        
    def set_home_speed_mult(self, speed):
        log.info(f'Setting home speed multiplier to {speed}.')
        self._home_speed_mult = speed

    def set_move_speed_mult(self, speed):
        log.info(f'Setting move speed multiplier to {speed}.')
        self._move_speed_mult = speed

        self._enact_speed_factor(self._move_speed_mult)

    def _enact_speed_factor(self, speed_factor):
        vel_int = int(speed_factor * MP_789A_4.MAX_VEL)

        log.debug('_enact_speed_factor: (pre)', vel_int)

        if vel_int > MP_789A_4.MAX_VEL:
            vel_int = MP_789A_4.MAX_VEL
        elif vel_int < MP_789A_4.MIN_VEL:
            vel_int = MP_789A_4.MIN_VEL

        msg = f'V{str(vel_int)}'
        rx = self.s.xfer([msg.encode('utf-8')]).decode('utf-8')

        log.debug('_enact_speed_factor: (post)', vel_int)

    def _reset_speed_factor(self):
        msg = f'V{str(MP_789A_4.DEF_VEL)}'
        rx = self.s.xfer([msg.encode('utf-8')]).decode('utf-8')

    def short_name(self):
        """ Returns the short name of the device.

        Returns:
            str: The short name.
        """

        log.debug('func: short_name')
        return self.s_name

    def long_name(self):
        """ Returns the full name of the device.

        Returns:
            str: The full name.
        """

        log.debug('func: long_name')
        return self.l_name
    
    def open(self):
        pass

    def close(self):
        # Stop the watchdog before closing the port so it doesn't poll a
        # closed handle.
        stop = getattr(self, "_watchdog_stop", None)
        if stop is not None:
            stop.set()
        tid = getattr(self, "movement_status_tid", None)
        if tid is not None and tid.is_alive():
            tid.join(timeout=1.0)
        self.s.close()

    @property
    def is_connected(self) -> bool:
        return getattr(self, 's', None) is not None

    def get_status(self) -> str:
        if not self.is_connected:
            return "Disconnected"
        if self._homing:
            return "Homing"
        if self._moving:
            return "Moving"
        return "Idle"


class DummyGrating(GratingDriver):
    """Software simulation of the McPherson 789A-4 for offline development.

    Simulates timed, blocking moves (like the real driver, which blocks until
    motion completes), tracks position with soft limits, and supports a fast
    ``stop()`` so the E-stop path can be exercised without hardware. Motion
    duration is deliberately short and capped so offline scans run quickly.
    """

    # Position is tracked relative to the home flag (0). The 234/302 spans
    # millions of controller-steps and goes negative below the home wavelength,
    # so the soft limits are wide and symmetric.
    MIN_POSITION = -9_000_000
    MAX_POSITION = 9_000_000
    SIM_STEP_RATE = 200_000   # simulated steps/second
    SIM_MAX_MOVE_TIME = 0.5   # cap on simulated move duration (s)

    def __init__(self, port: str | None = "DUMMY"):
        self.s_name = "MP789_DUMMY"
        self.l_name = "McPherson 789A-4 (DUMMY)"
        self._position = 0
        self._moving = False
        self._homing = False
        self._stop_requested = False
        self._home_speed_mult = 1
        self._move_speed_mult = 1
        log.info("DummyGrating created on port %s." % port)

    # --- Driver lifecycle ---------------------------------------------
    def open(self) -> None:
        log.info("DummyGrating open.")

    def close(self) -> None:
        log.info("DummyGrating close.")

    @property
    def is_connected(self) -> bool:
        return True

    def get_status(self) -> str:
        if self._homing:
            return "Homing"
        if self._moving:
            return "Moving"
        return "Idle"

    # --- GratingDriver ------------------------------------------------
    def home(self) -> bool:
        log.info("DummyGrating: homing.")
        self._homing = True
        self._stop_requested = False
        time.sleep(0.2)
        self._position = 0
        self._homing = False
        log.info("DummyGrating: homed.")
        return True

    def get_position(self) -> int:
        return self._position

    def stop(self) -> None:
        log.info("DummyGrating: STOP.")
        self._stop_requested = True
        self._moving = False
        self._homing = False

    def is_moving(self) -> bool:
        return self._moving

    def is_homing(self) -> bool:
        return self._homing

    def move_to(self, position: int, backlash: int = 0) -> None:
        steps = position - self._position
        if steps < 0 and backlash > 0:
            self.move_relative(steps - backlash)
            self.move_relative(backlash)
        else:
            self.move_relative(steps)

    def move_relative(self, steps: int) -> None:
        if steps == 0:
            return
        target = self._position + steps
        if target < self.MIN_POSITION or target > self.MAX_POSITION:
            log.warn("DummyGrating: move to %d clamped to limits." % target)
            target = max(self.MIN_POSITION, min(self.MAX_POSITION, target))

        duration = min(abs(steps) / self.SIM_STEP_RATE, self.SIM_MAX_MOVE_TIME)
        self._stop_requested = False
        self._moving = True
        # Simulate motion in small slices so a concurrent stop() is honoured.
        slices = max(1, int(duration / 0.02))
        for _ in range(slices):
            if self._stop_requested:
                log.warn("DummyGrating: move interrupted by stop().")
                self._moving = False
                return
            time.sleep(duration / slices)
        self._position = target
        self._moving = False

    def set_home_speed_mult(self, speed):
        self._home_speed_mult = speed

    def set_move_speed_mult(self, speed):
        self._move_speed_mult = speed

    def short_name(self):
        return self.s_name

    def long_name(self):
        return self.l_name


# Backwards-compatible alias for the original class name.
MP_789A_4_DUMMY = DummyGrating

""" 
McPherson Model 789A-4 Scan Controller Command Set

ASCII       Value   Desc.
-----------------------------------------------
[SPACE]     0x20    Init   
[CR]        0x0D    Carriage Return
@                   Soft Stop
A0                  Set Home Switch OFF
A8                  Set Home Switch ON
A24                 Enable Homing Circuit
^C          0x03    Reset
C1                  Clear
F1000,0             Find Home
G                   Run Internal Program
I                   Starting Velocity
K                   Ramp Slope
P                   Enter & Exit Program Mode
S                   Save
V                   Scanning Velocity
X                   Examine Parameters
]                   Read Limit Switch Status
+                   Index Scan In Up Direction
-                   Index Scan In Down Direction
^                   Read Moving Status
"""
