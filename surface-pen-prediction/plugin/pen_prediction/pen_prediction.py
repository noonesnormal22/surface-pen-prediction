"""
Pen Prediction — Krita Python plugin.

Controls the ipts-predict daemon (Kalman stylus smoother) via a Unix socket.
The daemon does all the work; this docker is the control panel.
"""

import json
import os
import signal
import socket
import time

from krita import Krita, Extension, DockWidget, DockWidgetFactory, DockWidgetFactoryBase
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLabel, QSlider, QGroupBox, QCheckBox, QPushButton,
)

SOCKET_PATH = os.path.expanduser('~/.local/share/ipts-predict.sock')
PID_FILE    = os.path.expanduser('~/.local/share/ipts-predict.pid')
DAEMON_LOG  = '/tmp/ipts-predict.log'


def _config_file():
    """Store the docker's settings in Krita's own data dir, adapting to
    whichever install this is (Flatpak vs native package vs other)."""
    candidates = [
        os.path.expanduser('~/.var/app/org.kde.krita/data/krita'),  # Flatpak
        os.path.expanduser('~/.local/share/krita'),                 # native
    ]
    for d in candidates:
        if os.path.isdir(d):
            return os.path.join(d, 'pen_prediction.json')
    # Nothing found — fall back to a per-user config dir that always exists.
    base = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'pen_prediction.json')


CONFIG_FILE = _config_file()
DOCKER_ID = 'pen_prediction_docker'


def send_command(cmd: dict):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(SOCKET_PATH)
        s.send(json.dumps(cmd).encode())
        raw = s.recv(4096).decode()
        s.close()
        return json.loads(raw)
    except Exception:
        return None


def stop_daemon():
    try:
        pid = int(open(PID_FILE).read().strip())
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def _has_systemd():
    try:
        return os.path.isdir('/run/systemd/system')
    except Exception:
        return False


def _start_hint():
    if _has_systemd():
        return ('<small>Start: <tt>systemctl --user start ipts-predict</tt><br>'
                'Auto-start: <tt>systemctl --user enable ipts-predict</tt></small>')
    # No systemd: the daemon lives next to wherever the repo was cloned, which
    # we can't know from inside Krita — point at the script generically.
    return ('<small>systemd not found. Start the daemon manually from the<br>'
            'repo: <tt>python3 daemon/ipts-predict.py &amp;</tt></small>')


def make_slider(lo, hi, default, tick=1):
    sl = QSlider(Qt.Horizontal)
    sl.setRange(lo, hi)
    sl.setValue(default)
    sl.setTickInterval(tick)
    sl.setTickPosition(QSlider.TicksBelow)
    return sl


class PenPredictionDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Pen Prediction')
        self._cfg = self._load_config()
        self._build_ui()
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_daemon)
        self._poll_timer.start(3000)
        self._poll_daemon()
        Krita.instance().notifier().applicationClosing.connect(self._on_krita_closing)

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setSpacing(6)

        # Status
        status_box = QGroupBox('Daemon')
        sb = QVBoxLayout(status_box)
        self._status_label = QLabel('Checking...')
        sb.addWidget(self._status_label)
        self._enable_check = QCheckBox('Smoothing on')
        self._enable_check.setChecked(self._cfg.get('enabled', True))
        self._enable_check.stateChanged.connect(self._on_enable)
        sb.addWidget(self._enable_check)
        layout.addWidget(status_box)

        self._hint_label = QLabel(_start_hint())
        self._hint_label.setWordWrap(True)
        self._hint_label.hide()
        layout.addWidget(self._hint_label)

        # Smoothing
        sm_box = QGroupBox('Smoothing')
        sml = QVBoxLayout(sm_box)
        self._smooth_label  = QLabel(f"Smoothing: {self._cfg.get('smoothing', 5)}/10")
        self._smooth_slider = make_slider(0, 10, self._cfg.get('smoothing', 5))
        self._smooth_slider.valueChanged.connect(self._on_smooth)
        sml.addWidget(self._smooth_label)
        sml.addWidget(self._smooth_slider)
        sml.addWidget(QLabel('<small>Kalman smoothing. 0=raw · 5=default · 10=heavy</small>'))
        layout.addWidget(sm_box)

        # Drag reduction
        drag_box = QGroupBox('Drag reduction')
        dl = QVBoxLayout(drag_box)
        dv = int(self._cfg.get('lookahead_ms', 15))
        self._drag_label  = QLabel(f'Lookahead: {dv} ms')
        self._drag_slider = make_slider(0, 40, dv, tick=5)
        self._drag_slider.valueChanged.connect(self._on_drag)
        dl.addWidget(self._drag_label)
        dl.addWidget(self._drag_slider)
        dl.addWidget(QLabel('<small>Constant forward lead. &lt;10=draggy · 15=default · '
                            '40=too floaty. Stop guard prevents end overshoot.</small>'))
        layout.addWidget(drag_box)

        # Interpolation
        f_box = QGroupBox('Interpolation')
        fl = QVBoxLayout(f_box)
        self._factor_label  = QLabel(f"Factor: {self._cfg.get('factor', 3)}×")
        self._factor_slider = make_slider(1, 8, self._cfg.get('factor', 3))
        self._factor_slider.valueChanged.connect(self._on_factor)
        fl.addWidget(self._factor_label)
        fl.addWidget(self._factor_slider)
        fl.addWidget(QLabel('<small>Fill events per real sample. 1=off · 3=default · 8=max</small>'))
        layout.addWidget(f_box)

        # Speed sensitivity
        sen_box = QGroupBox('Speed sensitivity')
        senl = QVBoxLayout(sen_box)
        sv = self._cfg.get('sensitivity_raw', 5)
        self._sen_label  = QLabel(self._sen_text(sv))
        self._sen_slider = make_slider(1, 10, sv)
        self._sen_slider.valueChanged.connect(self._on_sensitivity)
        senl.addWidget(self._sen_label)
        senl.addWidget(self._sen_slider)
        senl.addWidget(QLabel('<small>Low=more interpolation at slow speeds</small>'))
        layout.addWidget(sen_box)

        # Diagnostics — record a raw-vs-output trace for analyze-strokes.py
        rec_box = QGroupBox('Diagnostics')
        rl = QVBoxLayout(rec_box)
        self._record_btn = QPushButton('● Record trace')
        self._record_btn.setCheckable(True)
        self._record_btn.clicked.connect(self._on_record)
        self._record_label = QLabel('<small>Saves a trace you can analyze.</small>')
        self._record_label.setWordWrap(True)
        rl.addWidget(self._record_btn)
        rl.addWidget(self._record_label)
        layout.addWidget(rec_box)

        # Stats
        self._stats_label = QLabel('—')
        self._stats_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._stats_label)

        log_label = QLabel(f'<small>Log: {DAEMON_LOG}</small>')
        log_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(log_label)

        layout.addStretch()

        # Wrap in a scroll area so the docker can be resized freely and never
        # crowds the canvas — content scrolls instead of forcing a tall minimum.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(root)
        self.setWidget(scroll)

    # --- Slider text helpers ---
    def _sen_text(self, raw):
        return f'Sensitivity: {raw}/10  ({0.1 + (raw-1)*(1.9/9):.1f} mm/step)'

    def _raw_to_mm(self, raw):
        return 0.1 + (raw - 1) * (1.9 / 9.0)

    # --- Callbacks ---
    def _on_enable(self, _state):
        on = self._enable_check.isChecked()
        self._cfg['enabled'] = on
        self._save_config()
        send_command({'enabled': on})

    def _on_smooth(self, v):
        self._smooth_label.setText(f'Smoothing: {v}/10')
        self._cfg['smoothing'] = v
        self._save_config()
        send_command({'smoothing': v})

    def _on_drag(self, v):
        self._drag_label.setText(f'Lookahead: {v} ms')
        self._cfg['lookahead_ms'] = v
        self._save_config()
        send_command({'lookahead_ms': float(v)})

    def _on_factor(self, v):
        self._factor_label.setText(f'Factor: {v}×')
        self._cfg['factor'] = v
        self._save_config()
        send_command({'factor': v})

    def _on_sensitivity(self, v):
        self._sen_label.setText(self._sen_text(v))
        self._cfg['sensitivity_raw'] = v
        self._save_config()
        send_command({'sensitivity': self._raw_to_mm(v)})

    def _on_record(self, checked):
        if checked:
            # Save to the home dir (visible to both the Flatpak plugin and the
            # host-side daemon) with a timestamp so traces don't overwrite.
            path = os.path.expanduser(
                time.strftime('~/pen-trace-%Y%m%d-%H%M%S.csv'))
            resp = send_command({'record_start': path})
            if resp and resp.get('recording'):
                self._record_path = path
                self._record_btn.setText('■ Stop recording')
                self._record_label.setText(
                    f'<small>Recording… draw, then click stop.<br>'
                    f'→ {path}</small>')
            else:
                self._record_btn.setChecked(False)
                self._record_label.setText(
                    '<small style="color:#f44336">Could not start — is the daemon running?</small>')
        else:
            send_command({'record_stop': True})
            self._record_btn.setText('● Record trace')
            saved = getattr(self, '_record_path', None)
            if saved:
                self._record_label.setText(
                    f'<small>Saved: {saved}<br>'
                    f'Analyze: <tt>tools/analyze-strokes.py {os.path.basename(saved)}</tt></small>')
            else:
                self._record_label.setText('<small>Stopped.</small>')

    def _on_krita_closing(self):
        self._poll_timer.stop()
        # stop any in-progress recording so the file is flushed
        send_command({'record_stop': True})
        stop_daemon()

    # --- Polling ---
    def _poll_daemon(self):
        resp = send_command({'status': True})
        if resp and resp.get('ok'):
            on   = resp.get('enabled', True)
            sm   = resp.get('smoothing', '?')
            la   = resp.get('lookahead_ms', 0)
            r    = resp.get('real_count', 0)
            s    = resp.get('synth_count', 0)
            tool = 'active' if resp.get('tool_active') else 'away'
            state = f'smooth {sm} · {la}ms tip' if on else 'passthrough (off)'
            self._set_status(f'Running · {state}', ok=True)
            self._stats_label.setText(f'Real: {r} · Synth: {s} · Tool: {tool}')
            self._hint_label.hide()
            # keep checkbox in sync without re-triggering signal
            if self._enable_check.isChecked() != on:
                self._enable_check.blockSignals(True)
                self._enable_check.setChecked(on)
                self._enable_check.blockSignals(False)
            # keep record button in sync with the daemon's actual state
            rec = resp.get('recording', False)
            if self._record_btn.isChecked() != rec:
                self._record_btn.blockSignals(True)
                self._record_btn.setChecked(rec)
                self._record_btn.setText('■ Stop recording' if rec else '● Record trace')
                self._record_btn.blockSignals(False)
        else:
            self._set_status('Not running', ok=False)
            self._stats_label.setText('—')
            self._hint_label.show()

    def _set_status(self, text, ok=True):
        dot = '<span style="color:#4caf50">●</span>' if ok else '<span style="color:#f44336">●</span>'
        self._status_label.setText(f'{dot} {text}')

    # --- Config ---
    def _load_config(self):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            return {'enabled': True, 'smoothing': 2, 'lookahead_ms': 15,
                    'factor': 3, 'sensitivity_raw': 5}

    def _save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self._cfg, f)
        except Exception:
            pass

    def canvasChanged(self, canvas):
        pass


class PenPrediction(Extension):
    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        pass

    def createActions(self, window):
        pass


def registerDocker():
    Krita.instance().addDockWidgetFactory(
        DockWidgetFactory(DOCKER_ID, DockWidgetFactoryBase.DockRight, PenPredictionDocker)
    )
