#!/usr/bin/env python3
"""
ipts-predict: Kalman stylus event synthesizer for Surface Pro pen on Linux.

Pipeline (when enabled):
  raw stylus events
    -> Kalman filter per axis (smooths AND predicts in one pass)
    -> retrospective interpolation (fills gaps -> smooth curves, no polygons)
    -> uinput virtual device -> X11 -> Krita

The Kalman filter does all smoothing (via its measurement-noise term, tuned by
the Smoothing setting) and all drag reduction (via short lookahead). There is
no separate EMA stage — stacking filters caused overshoot ripple on curves.

When disabled, the daemon forwards raw events unchanged (transparent passthrough)
so the toggle can be flipped live without stopping the service.

Usage: ipts-predict.py [--factor 3] [--smoothing 5] [--sensitivity 0.5]
                       [--lookahead 11] [--disabled]
"""

import argparse
import collections
import evdev
from evdev import UInput, AbsInfo, ecodes as e
import json
import math
import os
import signal
import socket
import sys
import threading
import time

DEVICE_NAME    = 'Surface Pen Smoother'
SOCKET_PATH    = os.path.expanduser('~/.local/share/ipts-predict.sock')
PID_FILE       = os.path.expanduser('~/.local/share/ipts-predict.pid')
MAX_FACTOR     = 16
MIN_FACTOR     = 1
MAX_SMOOTHING  = 10
MIN_SMOOTHING  = 0
MAX_LOOKAHEAD  = 40.0
MAX_GAP_MS     = 80
MAX_LEAD_MM    = 5.0    # hard cap on how far the predicted lead can reach (bounds stop hooks)

SOURCE_CAPS = {
    e.EV_KEY: [320, 321, 330, 331],
    e.EV_ABS: [
        (e.ABS_X,        AbsInfo(value=0, min=0,     max=9600,  fuzz=0, flat=0, resolution=37)),
        (e.ABS_Y,        AbsInfo(value=0, min=0,     max=7200,  fuzz=0, flat=0, resolution=42)),
        (e.ABS_PRESSURE, AbsInfo(value=0, min=0,     max=4096,  fuzz=0, flat=0, resolution=0)),
        (e.ABS_TILT_X,   AbsInfo(value=0, min=-9000, max=9000,  fuzz=0, flat=0, resolution=5730)),
        (e.ABS_TILT_Y,   AbsInfo(value=0, min=-9000, max=9000,  fuzz=0, flat=0, resolution=5730)),
        (e.ABS_MISC,     AbsInfo(value=0, min=0,     max=65535, fuzz=0, flat=0, resolution=0)),
    ],
}
SOURCE_PROPS   = [e.INPUT_PROP_POINTER, e.INPUT_PROP_DIRECT]
SOURCE_VENDOR  = 0x045e
SOURCE_PRODUCT = 0x099f


# ---------------------------------------------------------------------------
# Kalman filter (one per axis)
# ---------------------------------------------------------------------------

class KalmanAxis:
    """
    Scalar Kalman filter for a single position axis.
    State: [position, velocity].

    Smooths the noisy IPTS position and provides a velocity estimate used to
    predict slightly ahead (drag reduction). On a direction change the incoming
    measurement disagrees strongly with the prediction, so the filter corrects
    quickly and gracefully — no large overshoot.

    `r` (measurement noise) is set live from the Smoothing setting:
    higher r -> filter trusts the model more -> smoother but less responsive.
    """
    def __init__(self, q_pos=2.0, q_vel=50.0, r=8.0):
        self.q_pos = q_pos
        self.q_vel = q_vel
        self.r     = r
        self.ready = False
        self.pos = self.vel = 0.0
        self.p00 = self.p01 = self.p10 = self.p11 = 0.0

    def reset(self, pos):
        self.pos = pos
        self.vel = 0.0
        self.p00 = 100.0; self.p01 = 0.0
        self.p10 = 0.0;   self.p11 = 100.0
        self.ready = True

    def update(self, measurement, dt):
        if not self.ready:
            self.reset(measurement)
            return
        dt = max(dt, 0.001)
        # Predict
        pos_p = self.pos + self.vel * dt
        vel_p = self.vel
        p00_p = self.p00 + dt*(self.p10 + self.p01) + dt*dt*self.p11 + self.q_pos
        p01_p = self.p01 + dt*self.p11
        p10_p = self.p10 + dt*self.p11
        p11_p = self.p11 + self.q_vel
        # Kalman gain
        s  = p00_p + self.r
        k0 = p00_p / s
        k1 = p10_p / s
        # Correct
        innov    = measurement - pos_p
        self.pos = pos_p + k0 * innov
        self.vel = vel_p + k1 * innov
        self.p00 = (1 - k0) * p00_p
        self.p01 = (1 - k0) * p01_p
        self.p10 = p10_p - k1 * p00_p
        self.p11 = p11_p - k1 * p01_p

    def predict_ahead(self, lookahead_s):
        return self.pos + self.vel * lookahead_s


class VelocityTracker:
    """
    Least-squares velocity over a short window of recent raw samples.

    A windowed linear fit gives a velocity that is both smooth (averages out
    per-sample jitter) AND responsive (no EMA lag) — better than either the raw
    Kalman velocity (noisy) or an EMA of it (laggy). Used to drive the forward
    prediction, so the lead tracks the true pen motion tightly and overshoots
    less at transitions.
    """
    def __init__(self, window=6):
        self.t  = collections.deque(maxlen=window)
        self.px = collections.deque(maxlen=window)
        self.py = collections.deque(maxlen=window)

    def reset(self):
        self.t.clear(); self.px.clear(); self.py.clear()

    def update(self, t, x, y):
        self.t.append(t); self.px.append(x); self.py.append(y)

    def velocity(self):
        """Return (vx, vy) in units/sec via least-squares slope, or (0,0)."""
        n = len(self.t)
        if n < 2:
            return 0.0, 0.0
        t0 = self.t[0]
        ts = [tt - t0 for tt in self.t]
        mean_t = sum(ts) / n
        denom = sum((tt - mean_t) ** 2 for tt in ts)
        if denom < 1e-9:
            return 0.0, 0.0
        mean_x = sum(self.px) / n
        mean_y = sum(self.py) / n
        vx = sum((ts[i]-mean_t)*(self.px[i]-mean_x) for i in range(n)) / denom
        vy = sum((ts[i]-mean_t)*(self.py[i]-mean_y) for i in range(n)) / denom
        return vx, vy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_source_device():
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            if ('IPTSD Virtual Stylus' in dev.name and
                    dev.info.vendor == SOURCE_VENDOR and
                    dev.info.product == SOURCE_PRODUCT):
                return dev
            dev.close()
        except Exception:
            pass
    return None


def terminate_other_instances():
    """
    Ensure this is the only ipts-predict.py running. Scans /proc for any other
    process whose command line contains this script's name and terminates it,
    so a stale/orphaned daemon can't keep holding the device grab. Returns the
    number of instances terminated.
    """
    me = os.getpid()
    script = os.path.basename(__file__)   # 'ipts-predict.py'
    victims = []
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == me:
            continue
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                cmdline = f.read().replace(b'\0', b' ').decode(errors='ignore')
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if script in cmdline and 'python' in cmdline:
            victims.append(pid)

    for pid in victims:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    # Wait up to 3s for graceful exit (their signal handler releases the grab)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        alive = []
        for pid in victims:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except ProcessLookupError:
                pass
        if not alive:
            break
        time.sleep(0.1)
        victims = alive

    # Force-kill anything still hanging on
    for pid in victims:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    return len(victims)


def lerp_int(a, b, t):
    return int(a + (b - a) * t)


def emit_event(ui, x, y, pressure, tilt_x, tilt_y, misc):
    ui.write(e.EV_ABS, e.ABS_X,        x)
    ui.write(e.EV_ABS, e.ABS_Y,        y)
    ui.write(e.EV_ABS, e.ABS_PRESSURE, pressure)
    ui.write(e.EV_ABS, e.ABS_TILT_X,   tilt_x)
    ui.write(e.EV_ABS, e.ABS_TILT_Y,   tilt_y)
    ui.write(e.EV_ABS, e.ABS_MISC,     misc)
    ui.syn()


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------

class PenDaemon:
    def __init__(self, factor, smoothing, sensitivity, lookahead, enabled):
        self.running = True
        self.cfg = {
            'enabled':     enabled,
            'factor':      factor,
            'smoothing':   smoothing,
            'sensitivity': sensitivity,
            'lookahead_ms': lookahead,
        }
        self.real_count  = 0
        self.synth_count = 0
        self.tool_active = False
        self.rec = None   # open file handle when recording raw-vs-output trace

    def run(self):
        print("Searching for IPTSD stylus...", flush=True)
        src = find_source_device()
        if src is None:
            print("ERROR: IPTSD Virtual Stylus not found.", file=sys.stderr)
            sys.exit(1)
        print(f"Found: {src.name} ({src.path})", flush=True)

        # Single-instance: terminate any other ipts-predict.py (stale orphans
        # from manual runs or restart races) so only this process holds the
        # device grab.
        killed = terminate_other_instances()
        if killed:
            print(f"Terminated {killed} stale instance(s).", flush=True)
            time.sleep(0.3)   # let the kernel release the grab
        os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))

        print(f"Creating uinput device: '{DEVICE_NAME}'", flush=True)
        before = set(os.listdir('/dev/input'))
        ui = UInput(SOURCE_CAPS, name=DEVICE_NAME,
                    vendor=SOURCE_VENDOR, product=SOURCE_PRODUCT,
                    version=1, input_props=SOURCE_PROPS)
        time.sleep(0.5)
        after   = set(os.listdir('/dev/input'))
        new_evs = sorted(f for f in (after - before) if f.startswith('event'))
        print(f"Virtual device: /dev/input/{new_evs[0] if new_evs else '?'}", flush=True)

        def shutdown(signum=None, frame=None):
            self.running = False
            try: src.close()
            except Exception: pass

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT,  shutdown)

        time.sleep(0.8)
        src.grab()
        print(f"Grabbed {src.path}. Enabled={self.cfg['enabled']}. Running.", flush=True)
        print(f"Socket: {SOCKET_PATH}", flush=True)

        threading.Thread(target=self._socket_thread, daemon=True).start()
        self._reader_loop(src, ui)

        print("Shutting down...", flush=True)
        try: src.ungrab()
        except Exception: pass
        try: src.close()
        except Exception: pass
        ui.close()
        try: os.unlink(PID_FILE)
        except Exception: pass
        print("Done.", flush=True)

    def _reader_loop(self, src, ui):
        RES_X = 37.0
        RES_Y = 42.0

        buf    = {}
        prev   = None   # (x, y, pressure, tilt_x, tilt_y, misc)
        prev_t = None

        kx = KalmanAxis()
        ky = KalmanAxis()
        vel = VelocityTracker(window=6)   # windowed least-squares velocity
        prx = pry = None     # previous RAW position (speed/landing check)
        raw_spd = 0.0        # smoothed raw speed mm/s

        try:
            for ev in src.read_loop():
                if not self.running:
                    break

                if ev.type == e.EV_ABS:
                    buf[ev.code] = ev.value

                elif ev.type == e.EV_KEY:
                    if ev.code in (320, 321):  # BTN_TOOL_PEN / BTN_TOOL_RUBBER
                        self.tool_active = bool(ev.value)
                        if not self.tool_active:
                            prev = None
                            prev_t = None
                            kx.ready = False
                            ky.ready = False
                            vel.reset()
                            prx = pry = None
                            raw_spd = 0.0
                    ui.write(e.EV_KEY, ev.code, ev.value)
                    ui.syn()

                elif ev.type == e.EV_SYN:
                    now = time.monotonic()

                    raw_x    = buf.get(e.ABS_X,        prev[0] if prev else 0)
                    raw_y    = buf.get(e.ABS_Y,        prev[1] if prev else 0)
                    pressure = buf.get(e.ABS_PRESSURE, prev[2] if prev else 0)
                    tilt_x   = buf.get(e.ABS_TILT_X,   prev[3] if prev else 0)
                    tilt_y   = buf.get(e.ABS_TILT_Y,   prev[4] if prev else 0)
                    misc     = buf.get(e.ABS_MISC,     prev[5] if prev else 0)
                    buf = {}

                    # --- Passthrough when disabled ---
                    if not self.cfg['enabled']:
                        emit_event(ui, raw_x, raw_y, pressure, tilt_x, tilt_y, misc)
                        self.real_count += 1
                        prev   = (raw_x, raw_y, pressure, tilt_x, tilt_y, misc)
                        prev_t = now
                        continue

                    smoothing = self.cfg['smoothing']
                    dt = (now - prev_t) if prev_t else 0.021

                    # Kalman: smooth + velocity. r mapped from Smoothing slider.
                    kx.r = ky.r = 2.0 + smoothing * 4.0   # 2 (raw) .. 42 (heavy)
                    kx.update(raw_x, dt)
                    ky.update(raw_y, dt)

                    # Velocity tracker: windowed least-squares slope over recent
                    # raw samples — smooth AND responsive, the input the user asked
                    # for. Drives the forward prediction.
                    vel.update(now, raw_x, raw_y)
                    vtx, vty = vel.velocity()

                    # Raw speed (mm/s), lightly smoothed — drives the lead scaling.
                    if prx is not None and dt > 0:
                        inst = math.hypot((raw_x-prx)/RES_X, (raw_y-pry)/RES_Y) / dt
                        raw_spd = 0.5 * inst + 0.5 * raw_spd
                    prx, pry = raw_x, raw_y

                    # Speed-proportional lead: full reach when fast (drag reduction),
                    # shrinking to zero as the pen stops (so it can't overshoot the
                    # endpoint). Then a hard distance cap bounds the worst-case hook
                    # on very fast abrupt stops — the one case forward prediction
                    # cannot fully anticipate.
                    lead_scale  = min(1.0, raw_spd / 80.0)
                    lookahead_s = (self.cfg['lookahead_ms'] / 1000.0) * lead_scale
                    off_x = vtx * lookahead_s
                    off_y = vty * lookahead_s
                    off_mm = math.hypot(off_x / RES_X, off_y / RES_Y)
                    if off_mm > MAX_LEAD_MM:
                        s = MAX_LEAD_MM / off_mm
                        off_x *= s; off_y *= s
                    bx = kx.pos + off_x
                    by = ky.pos + off_y

                    # Landing: at a near-stop, settle exactly onto the raw position
                    # so the stroke ends where the tip is (no Kalman-lag undershoot).
                    land = max(0.0, 1.0 - raw_spd / 20.0) ** 2
                    bx += (raw_x - bx) * land
                    by += (raw_y - by) * land

                    if self.tool_active:
                        x = max(0, min(9600, int(bx)))
                        y = max(0, min(7200, int(by)))
                    else:
                        x = int(kx.pos)
                        y = int(ky.pos)

                    pkx, pky = kx.pos, ky.pos

                    # Optional trace recording: raw input vs emitted output,
                    # aligned per real event, for offline analysis.
                    rec = self.rec
                    if rec is not None:
                        try:
                            rec.write(f"{now:.4f},{int(self.tool_active)},"
                                      f"{raw_x},{raw_y},{x},{y},{lead_scale:.3f}\n")
                        except Exception:
                            pass

                    # Retrospective interpolation (kills polygon corners)
                    max_factor  = self.cfg['factor']
                    mm_per_step = max(0.1, self.cfg['sensitivity'])
                    if (prev is not None and self.tool_active and
                            prev_t is not None and dt * 1000 < MAX_GAP_MS):
                        px, py, pp, ptx, pty, pm = prev
                        dist_mm = math.hypot((x - px) / RES_X, (y - py) / RES_Y)
                        steps = max(1, min(max_factor, int(dist_mm / mm_per_step)))
                        for i in range(1, steps):
                            t = i / steps
                            emit_event(ui,
                                lerp_int(px, x, t), lerp_int(py, y, t),
                                lerp_int(pp, pressure, t),
                                lerp_int(ptx, tilt_x, t),
                                lerp_int(pty, tilt_y, t),
                                lerp_int(pm, misc, t))
                            self.synth_count += 1

                    # Emit the single output position
                    emit_event(ui, x, y, pressure, tilt_x, tilt_y, misc)
                    self.real_count += 1

                    prev   = (x, y, pressure, tilt_x, tilt_y, misc)
                    prev_t = now

        except Exception as ex:
            if self.running:
                print(f"[reader] error: {ex}", flush=True)
            self.running = False

    def _socket_thread(self):
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o600)
        srv.listen(1)
        srv.settimeout(1.0)

        while self.running:
            try:
                conn, _ = srv.accept()
                try:
                    cmd = json.loads(conn.recv(4096).decode().strip())
                    c = self.cfg
                    if 'enabled'      in cmd: c['enabled']      = bool(cmd['enabled'])
                    if 'factor'       in cmd: c['factor']       = max(MIN_FACTOR,    min(MAX_FACTOR,    int(cmd['factor'])))
                    if 'smoothing'    in cmd: c['smoothing']    = max(MIN_SMOOTHING, min(MAX_SMOOTHING, int(cmd['smoothing'])))
                    if 'sensitivity'  in cmd: c['sensitivity']  = max(0.1,           min(2.0,           float(cmd['sensitivity'])))
                    if 'lookahead_ms' in cmd: c['lookahead_ms'] = max(0.0,           min(MAX_LOOKAHEAD, float(cmd['lookahead_ms'])))
                    if 'record_start' in cmd:
                        try:
                            if self.rec: self.rec.close()
                            self.rec = open(cmd['record_start'], 'w')
                            self.rec.write('t,tool,raw_x,raw_y,out_x,out_y,lead\n')
                        except Exception:
                            self.rec = None
                    if cmd.get('record_stop'):
                        r = self.rec; self.rec = None
                        try:
                            if r: r.flush(); r.close()
                        except Exception: pass
                    conn.send(json.dumps({
                        'ok': True, **c,
                        'real_count':  self.real_count,
                        'synth_count': self.synth_count,
                        'tool_active': self.tool_active,
                        'recording':   self.rec is not None,
                    }).encode())
                except Exception as ex:
                    try: conn.send(json.dumps({'ok': False, 'error': str(ex)}).encode())
                    except Exception: pass
                conn.close()
            except socket.timeout:
                continue

        srv.close()
        try: os.unlink(SOCKET_PATH)
        except Exception: pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--factor',      type=int,   default=3,    help='Max synthetic events per real pair')
    p.add_argument('--smoothing',   type=int,   default=5,    help='Kalman smoothing 0-10')
    p.add_argument('--sensitivity', type=float, default=0.5,  help='mm per synthetic event')
    p.add_argument('--lookahead',   type=float, default=11.0, help='Drag-reduction lookahead ms (0=off)')
    p.add_argument('--disabled',    action='store_true',      help='Start in passthrough (off) mode')
    args = p.parse_args()
    PenDaemon(args.factor, args.smoothing, args.sensitivity,
              args.lookahead, not args.disabled).run()


if __name__ == '__main__':
    main()
