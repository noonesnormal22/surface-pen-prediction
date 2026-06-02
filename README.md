# DISCLAIMER!!!
This plug-in was made in Claude Code and will likely have quirks that only something like Claude Code will produce. I'm an artist first before anything else, so I, the human typing this paragraph, just need something that works. It still needs some extra tweaking here and there, but for what it can do, I was impressed. Please fork this and make it better (and don't tell the other artist this was made with AI XD).

---NoOnesNormal

# Pen Prediction — Krita Plugin for Surface Pro Pen Lag

> *Reduces Surface Pen lag in Krita on Linux by smoothing and predicting stylus input below the app layer.*

A workaround for the Surface Pro pen lag problem in Krita on Linux. Makes drawing feel nearly identical to Windows by synthesizing additional input events between the hardware's ~46 Hz poll rate.

**Result:** Smooth curves, no (noticable) polygon artifacts, and near-zero perceptible drag — confirmed working on Surface Pro 7 with Krita 5.3.1 (Flatpak) on X11.

---

## Requirements

- Linux with the `linux-surface` kernel and `iptsd` userspace daemon running
- Python 3.10+
- `python3-evdev` installed (`pip install evdev` or system package)
- Krita installed as a Flatpak (tested on 5.3.1)
- X11 session (tested on Cinnamon). Wayland has compositor frame-sync batching that makes lag significantly worse — switch to X11 if possible.

---

## Installation

**1. Download or clone this repository.**

**2. Run the installer** (handles device access + the background daemon; it will ask for `sudo` once to install the udev rule):
```bash
cd surface-pen-prediction
./install.sh
```

**3. Install the Krita plugin** (the installer prints these steps too):
- Krita → **Tools → Scripts → Import Python Plugin from File** → select `pen_prediction-krita-docker.zip`
- **Settings → Configure Krita → Python Plugin Manager** → enable **Pen Prediction** → restart Krita
- **Settings → Dockers → Pen Prediction** to open the panel

A green dot in the docker confirms the daemon is running. That's it — start drawing.

> The installer is safe to re-run, detects whether you have systemd, and warns if `python3-evdev` or `iptsd` is missing. Prefer to do it by hand? See [Manual setup](#manual-setup) below.

### Per-distro setup

Each block has three steps: (1) the linux-surface kernel + `iptsd` — **skip if your pen already works**, it's not part of this project; (2) this project's one dependency, `python-evdev`; (3) the installer. The Step 1 repo key/URL can change over time — if a line fails, check the [linux-surface wiki](https://github.com/linux-surface/linux-surface/wiki/Installation-and-Setup).

**Debian / Ubuntu / Mint**
```bash
# 1. kernel + iptsd (skip if pen already works)
wget -qO - https://raw.githubusercontent.com/linux-surface/linux-surface/master/pkg/keys/surface.asc \
  | gpg --dearmor | sudo dd of=/etc/apt/keyrings/linux-surface.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/linux-surface.gpg] https://pkg.surfacelinux.com/debian release main" \
  | sudo tee /etc/apt/sources.list.d/linux-surface.list
sudo apt update
sudo apt install linux-image-surface linux-headers-surface iptsd libwacom-surface
sudo update-grub && sudo reboot
# 2. dependency
sudo apt install python3-evdev
# 3. install
cd ~/surface-pen-prediction && ./install.sh
```

**Arch / Manjaro / EndeavourOS**
```bash
# 1. kernel + iptsd (skip if pen already works)
curl -s https://raw.githubusercontent.com/linux-surface/linux-surface/master/pkg/keys/surface.asc \
  | sudo pacman-key --add -
sudo pacman-key --lsign-key 56C464BAAC421453
echo -e "[linux-surface]\nServer = https://pkg.surfacelinux.com/arch/" | sudo tee -a /etc/pacman.conf
sudo pacman -Syu
sudo pacman -S linux-surface linux-surface-headers iptsd
sudo reboot
# 2. dependency
sudo pacman -S python-evdev
# 3. install
cd ~/surface-pen-prediction && ./install.sh
```

**Fedora**
```bash
# 1. kernel + iptsd (skip if pen already works)
sudo dnf config-manager --add-repo https://pkg.surfacelinux.com/fedora/linux-surface.repo
sudo dnf install kernel-surface iptsd libwacom-surface
sudo reboot
# 2. dependency
sudo dnf install python3-evdev
# 3. install
cd ~/surface-pen-prediction && ./install.sh
```

**openSUSE**
```bash
# 1. kernel + iptsd — follow the linux-surface wiki (no first-party zypper repo)
# 2. dependency
sudo zypper install python3-evdev
# 3. install
cd ~/surface-pen-prediction && ./install.sh
```

**No systemd (Artix / Void / Alpine)**
```bash
# 1. kernel + iptsd per your distro;  python-evdev via pkg manager (or pip install --user evdev)
# 2. udev rule + run the daemon manually (add the last line to session autostart)
cd ~/surface-pen-prediction
sudo cp 99-surface-pen-krita.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
python3 daemon/ipts-predict.py &
```

Then import the Krita plugin (Step 3 above) on every distro.

### Manual setup

If you'd rather not run the script:

```bash
# 1. Device access (lets the daemon read the pen and write a virtual device)
sudo cp 99-surface-pen-krita.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=input
sudo udevadm trigger --name-match=uinput

# 2a. Daemon via systemd (auto-starts on login).
#     The unit has a __DAEMON_DIR__ placeholder — substitute the repo path:
sed "s|__DAEMON_DIR__|$PWD|g" daemon/ipts-predict.service \
    > ~/.config/systemd/user/ipts-predict.service
systemctl --user daemon-reload
systemctl --user enable --now ipts-predict

# 2b. ...or without systemd, run it directly (add to your session autostart)
python3 daemon/ipts-predict.py &
```

Then import `pen_prediction-krita-docker.zip` in Krita as described above. To rebuild the
zip after editing the plugin source: `./build-plugin.sh`.

---

## Configuration

The docker has an on/off checkbox and four sliders. All update the daemon live — no restart needed.

| Setting | What it does | Default |
|---|---|---|
| **Smoothing on** (checkbox) | Master toggle. Off = transparent passthrough (raw pen). | on |
| **Smoothing** | Kalman smoothing strength. 0 = track raw tightly, 10 = heavy. | 2 |
| **Lookahead** | Drag reduction: constant forward lead in ms. `<10` feels draggy, `15` is the sweet spot, `40` is too floaty. | 15 |
| **Factor** | Max interpolation points inserted per real sample (kills polygon corners). | 3 |
| **Speed sensitivity** | How readily interpolation kicks in at slow speeds. Low = more fill-in when drawing slowly. | 5 |

**Recommended starting point:** the defaults (Smoothing 2, Lookahead 15, Factor 3, Sensitivity 5) are tuned for the Surface Pro 7 and were validated on real artwork. From there:

- **Still feels draggy?** Raise Lookahead toward 20–25.
- **Tip floats / overshoots corners?** Lower Lookahead toward 8–10.
- **Lines look rough at slow speed?** Raise Smoothing a notch or two — but note the value is in the pipeline, not heavy smoothing, so small changes go a long way.

The lead is constant (speed-scaled), so raising Lookahead moves the whole line uniformly closer to your pen rather than changing the feel speed-by-speed. Hooks at stroke ends are bounded by the 5 mm lead cap regardless of setting.

---

## The Problem

On Linux, the Surface Pro pen communicates through Intel's IPTS (Precise Touch & Stylus) system. The kernel driver polls the firmware for new pen data approximately **46 times per second** (~21ms between samples). Windows achieves 120–240 Hz using proprietary firmware paths that Linux doesn't have access to.

At 46 Hz, fast strokes look like polygons instead of curves — Krita draws a straight line between each sample, and at fast drawing speeds those straight segments are visible. There's also a perceptible "drag" where the stroke lags behind the pen tip.

This plugin fixes both problems without touching any kernel drivers.

---

## How It Works

Two components work together.

### 1. The Daemon (`daemon/ipts-predict.py`)

A Python process that runs in the background as a systemd user service. It:

1. **Grabs** the real stylus device (`/dev/input/event261`) exclusively — the kernel stops delivering its events to X11/Krita, so only the daemon sees them.
2. **Creates** a new virtual input device (`Surface Pen Smoother`) via uinput — Krita draws from this instead.
3. **Processes** each real pen event before forwarding it. The pipeline, in order:

**Kalman filter (per axis).** The raw IPTS position is noisy. A small Kalman filter smooths it and, as a by-product, maintains a position+velocity estimate. The amount of smoothing is the **Smoothing** slider (it sets the filter's measurement-noise term: low = tracks raw tightly, high = heavily smoothed).

**Velocity tracker.** A windowed least-squares fit over the last several raw samples produces a velocity estimate that is both *smooth* (averages out per-sample jitter) and *responsive* (no lag). This is what drives the forward prediction — a clean velocity is the key to prediction that reduces drag without feeling rubbery.

**Forward prediction (drag reduction).** The output position is the Kalman position plus `velocity × lookahead`. This pushes the inked point ahead toward where the pen actually is, cancelling the hardware's ~15–21 ms latency. Three safeguards keep it honest:

- **Speed-proportional lead** — the forward reach scales with how fast you're actually moving. Full lead when fast (where you feel drag), shrinking to zero as you stop (so it physically cannot overshoot the endpoint).
- **Landing** — at a near-stop the output settles exactly onto the raw position, so strokes end where the tip is (no lag-induced undershoot).
- **Lead cap** — a hard 5 mm limit bounds the worst-case overshoot on very fast abrupt stops, the one case forward prediction genuinely cannot anticipate (the system only learns the pen stopped *one frame after* it did).

**Retrospective interpolation.** Finally, between the previous output point and the new one, the daemon inserts several intermediate points so Krita receives a dense stream (~150–200 Hz effective) instead of ~46 Hz. This eliminates the polygon-corner artifact on fast curves. It uses only known positions, so it never overshoots. Fill density scales with stroke speed and the **Factor** / **Speed sensitivity** controls.

When the daemon is toggled **off**, it forwards raw events untouched (transparent passthrough), so smoothing can be flipped live without stopping the service.

### 2. The Krita Plugin (`plugin/pen_prediction/`)

A standard Krita Python docker panel that:

- Connects to the daemon via a Unix socket at `~/.local/share/ipts-predict.sock`
- Shows live status (running/not running, event counts)
- Exposes all parameters as sliders/toggles that update the daemon in real time without restarting
- Sends SIGTERM to the daemon when Krita closes (this works across the Flatpak sandbox because Flatpak shares the host PID namespace by default)

The plugin does **not** start the daemon — the daemon is managed by systemd. If the daemon is not running, the plugin shows the command to start it. On systems **without systemd**, the plugin detects this automatically and shows the manual start command instead:

```bash
python3 daemon/ipts-predict.py &
```

---

## How the Daemon and Plugin Communicate

The daemon listens on a Unix socket at `~/.local/share/ipts-predict.sock`. The plugin connects and sends JSON commands:

```json
{"enabled": true}
{"smoothing": 2}
{"lookahead_ms": 15.0}
{"factor": 3}
{"sensitivity": 0.5}
{"status": true}
{"record_start": "/tmp/trace.csv"}
{"record_stop": true}
```

Any command also returns the current full state (plus `real_count`, `synth_count`, `tool_active`, `recording`), which the plugin uses to update the status display. `record_start`/`record_stop` write a per-event trace of raw input vs. emitted output — feed it to `tools/analyze-strokes.py` to measure hooks, endpoint accuracy, and ellipse roundness.

---

## Daemon Control

```bash
systemctl --user start ipts-predict    # start
systemctl --user stop ipts-predict     # stop (restores original pen device)
systemctl --user status ipts-predict   # check
systemctl --user enable ipts-predict   # auto-start on login
systemctl --user disable ipts-predict  # remove auto-start
cat /tmp/ipts-predict.log             # view logs
```

---

## Compatibility Notes

**Display server:** X11 strongly recommended. Wayland adds compositor frame-sync batching that groups pen events into bursts, making the effective rate much lower and less consistent than the IPTS hardware ceiling.

**Cinnamon session:** Make sure you're in the regular **Cinnamon** session, not **Cinnamon (Software Rendering)**. The software rendering session sets `LIBGL_ALWAYS_SOFTWARE=1` which forces Krita to use CPU rasterization (llvmpipe) — this makes canvas updates slow and compounds the lag problem. You can verify with `glxinfo | grep renderer`: it should say `Intel` or your GPU, not `llvmpipe`.

**Other Surface models:** Tested on Surface Pro 7. Other models using IPTS (Pro 4, 5, 6) should work but the ABS axis ranges and resolutions in `daemon/ipts-predict.py` (`SOURCE_CAPS`) may need adjusting to match your device. Run `python3 -c "import evdev; d = evdev.InputDevice('/dev/input/eventXXX'); print(d.capabilities())"` on your IPTSD Virtual Stylus device to get the correct values.

**Krita version:** Tested on 5.3.1 Flatpak. Should work on any Krita version with Python plugin support.

---

## Tuning Internals

Most tuning is done from the docker. For deeper changes, the daemon has a few constants and classes worth knowing:

**`KalmanAxis`** (`q_pos`, `q_vel`, `r`): the per-axis filter. `r` (measurement noise) is normally driven by the **Smoothing** slider, so you rarely touch it. `q_vel` controls how fast the filter's velocity can change — raise for snappier direction response, lower for steadier velocity. `q_pos` is position process noise. Device units: ABS_X is 0–9600 across ~260 mm, so 1 unit ≈ 0.027 mm.

**`VelocityTracker(window=6)`**: windowed least-squares velocity used for prediction. A larger window = smoother but slightly laggier velocity; smaller = snappier but noisier.

**Module constants:**
- `MAX_LEAD_MM = 5.0` — hard cap on the predicted lead distance; bounds the worst-case stop hook.
- The speed-proportional lead reaches full strength at `80 mm/s` (in the reader loop) — lower it to get full drag reduction at slower drawing speeds.

**`tools/analyze-strokes.py`** quantifies the effect of any change: record a trace via the docker's hidden socket commands (or `record_start`/`record_stop`) and run the analyzer to see end-hook, endpoint accuracy, and ellipse roundness by stroke-length bucket.

---

## Forking / Adapting

**Other Surface models (Pro 4, 5, 6, Book):**
The `SOURCE_CAPS` dict in `ipts-predict.py` is hardcoded for the SP7. Get your device's values with:
```bash
python3 -c "import evdev; d = evdev.InputDevice('/dev/input/eventXXX'); print(d.capabilities())"
```
Point it at your IPTSD Virtual Stylus device and paste the output into `SOURCE_CAPS`.

**Other tablets (Wacom, Huion, XP-Pen):**
These run at higher native rates so the polygon problem is less severe, but the Kalman smoothing and retrospective interpolation still help with jitter. Replace `SOURCE_CAPS` and update `find_source_device()` to match your device name/vendor/product ID.

**Wayland users:**
The daemon works at the evdev level but synthetic events pass through the Wayland compositor which may re-batch them. Try running Krita with `QT_QPA_PLATFORM=xcb` to force X11 via Xwayland, which bypasses compositor batching.

**Non-Flatpak Krita:**
Change `CONFIG_FILE` in `pen_prediction.py` from `~/.var/app/org.kde.krita/data/krita/` to `~/.local/share/krita/`. Plugin directory is `~/.local/share/krita/pykrita/`.

**Other drawing apps (Xournal++, Inkscape, etc.):**
The daemon works below the application layer. Any app reading X11 tablet input gets the smoothed events automatically — no plugin needed.

**Systems without systemd (Void, Alpine, Artix, etc.):**
The `ipts-predict.service` file won't apply, but the daemon itself works anywhere. Run it manually:
```bash
python3 daemon/ipts-predict.py &
```
The Krita plugin detects whether systemd is present and shows the appropriate start command in the docker when the daemon isn't running. For auto-start without systemd, add the manual command to your session startup script (e.g. `~/.xinitrc` or your display manager's autostart).

---

## Files

```
surface-pen-prediction/
├── README.md                        ← this file
├── LICENSE                          ← public domain (Unlicense)
├── install.sh                       ← daemon setup script
├── build-plugin.sh                  ← rebuilds pen_prediction-krita-docker.zip from source
├── pen_prediction-krita-docker.zip               ← Krita plugin (import via Tools → Scripts)
├── 99-surface-pen-krita.rules       ← udev rule for device access
├── daemon/
│   ├── ipts-predict.py              ← main daemon
│   └── ipts-predict.service         ← systemd user service unit
├── plugin/
│   ├── pen_prediction.desktop       ← Krita plugin metadata
│   └── pen_prediction/
│       ├── __init__.py
│       └── pen_prediction.py        ← Krita docker UI
└── tools/
    ├── stylus-rate-test.py          ← measures real stylus event rate via X11
    ├── record.py                    ← record a raw-vs-output trace (start/stop/status)
    └── analyze-strokes.py           ← measures hooks / endpoint accuracy / roundness from a trace
```

### tools/stylus-rate-test.py

Standalone diagnostic. Run it while drawing to measure your actual hardware event rate — useful for before/after comparisons or characterising a different device. Needs only python3 + python-xlib. Output: Hz, gap distribution, and how many gaps would produce visible polygon corners.

### tools/record.py + tools/analyze-strokes.py

The measurement workflow used to tune (and validate) the drag reduction.

**Easiest — the docker button.** The Pen Prediction docker has a **Record trace** button under *Diagnostics*. Click it, draw, click **Stop**, and it saves a timestamped `~/pen-trace-*.csv` (the docker shows the exact path and the analyze command). Then:

```bash
tools/analyze-strokes.py ~/pen-trace-20260602-021500.csv
```

**Or from the command line** (handy for scripting, or on a fork without the docker):

```bash
tools/record.py start /tmp/test.csv    # begin capturing raw-vs-output trace
#  ... draw in Krita for a bit ...
tools/record.py stop                   # stop
tools/analyze-strokes.py /tmp/test.csv # report the numbers
```

Both wrap the daemon's `record_start`/`record_stop` socket commands. `analyze-strokes.py` reads the CSV and reports, bucketed by stroke length: **end hook** (forward overshoot past a stop), **final endpoint** error (under/overshoot), and **ellipse roundness** (raw vs. output). This is how we proved the fast-stroke hooks dropped from 15 mm to ~0 — if you fork and change the prediction math, this is how you check whether you made it better or worse.

---

## Origin

This project was built entirely through a single session with **[Claude Code](https://claude.ai/code)** (Anthropic's AI coding tool), including the research, system diagnostics, algorithm design, daemon implementation, Krita plugin, and all documentation. The human contributor (bruh) directed the work, tested each iteration, and made the design decisions — Claude Code wrote and debugged the code.

If you're curious what AI-assisted systems programming looks like end-to-end, this repo is a decent example.

---# DISCLAIMER!!!
This plug-in was made in Claude Code and will likely have quirks that only something like Claude Code will produce. I'm an artist first before anything else, so I, the human typing this paragraph, just need something that works. It still needs some extra tweaking here and there, but for what it can do, I was impressed. Please fork this and make it better (and don't tell the other artist this was made with AI XD).

---NoOnesNormal

# Pen Prediction — Krita Plugin for Surface Pro Pen Lag

> *Reduces Surface Pen lag in Krita on Linux by smoothing and predicting stylus input below the app layer.*

A workaround for the Surface Pro pen lag problem in Krita on Linux. Makes drawing feel nearly identical to Windows by synthesizing additional input events between the hardware's ~46 Hz poll rate.

**Result:** Smooth curves, no polygon artifacts, and near-zero perceptible drag — confirmed working on Surface Pro 7 with Krita 5.3.1 (Flatpak) on X11.

---

## The Problem

On Linux, the Surface Pro pen communicates through Intel's IPTS (Precise Touch & Stylus) system. The kernel driver polls the firmware for new pen data approximately **46 times per second** (~21ms between samples). Windows achieves 120–240 Hz using proprietary firmware paths that Linux doesn't have access to.

At 46 Hz, fast strokes look like polygons instead of curves — Krita draws a straight line between each sample, and at fast drawing speeds those straight segments are visible. There's also a perceptible "drag" where the stroke lags behind the pen tip.

This plugin fixes both problems without touching any kernel drivers.

---

## How It Works

Two components work together.

### 1. The Daemon (`daemon/ipts-predict.py`)

A Python process that runs in the background as a systemd user service. It:

1. **Grabs** the real stylus device (`/dev/input/event261`) exclusively — the kernel stops delivering its events to X11/Krita, so only the daemon sees them.
2. **Creates** a new virtual input device (`Surface Pen Smoother`) via uinput — Krita draws from this instead.
3. **Processes** each real pen event before forwarding it. The pipeline, in order:

**Kalman filter (per axis).** The raw IPTS position is noisy. A small Kalman filter smooths it and, as a by-product, maintains a position+velocity estimate. The amount of smoothing is the **Smoothing** slider (it sets the filter's measurement-noise term: low = tracks raw tightly, high = heavily smoothed).

**Velocity tracker.** A windowed least-squares fit over the last several raw samples produces a velocity estimate that is both *smooth* (averages out per-sample jitter) and *responsive* (no lag). This is what drives the forward prediction — a clean velocity is the key to prediction that reduces drag without feeling rubbery.

**Forward prediction (drag reduction).** The output position is the Kalman position plus `velocity × lookahead`. This pushes the inked point ahead toward where the pen actually is, cancelling the hardware's ~15–21 ms latency. Three safeguards keep it honest:

- **Speed-proportional lead** — the forward reach scales with how fast you're actually moving. Full lead when fast (where you feel drag), shrinking to zero as you stop (so it physically cannot overshoot the endpoint).
- **Landing** — at a near-stop the output settles exactly onto the raw position, so strokes end where the tip is (no lag-induced undershoot).
- **Lead cap** — a hard 5 mm limit bounds the worst-case overshoot on very fast abrupt stops, the one case forward prediction genuinely cannot anticipate (the system only learns the pen stopped *one frame after* it did).

**Retrospective interpolation.** Finally, between the previous output point and the new one, the daemon inserts several intermediate points so Krita receives a dense stream (~150–200 Hz effective) instead of ~46 Hz. This eliminates the polygon-corner artifact on fast curves. It uses only known positions, so it never overshoots. Fill density scales with stroke speed and the **Factor** / **Speed sensitivity** controls.

When the daemon is toggled **off**, it forwards raw events untouched (transparent passthrough), so smoothing can be flipped live without stopping the service.

> **Design note:** earlier versions stacked an EMA position smoother, a cornering guard, and a stroke-age ramp on top of this. Each fixed a specific measured artifact but made the *feel* rubbery, because a constantly-varying lead reads worse than a small constant one. The shipping design deliberately keeps the lead steady (speed-proportional only) and accepts a tiny corner overshoot in exchange for a consistent, predictable feel. See the project journal for the full evolution.

### 2. The Krita Plugin (`plugin/pen_prediction/`)

A standard Krita Python docker panel that:

- Connects to the daemon via a Unix socket at `~/.local/share/ipts-predict.sock`
- Shows live status (running/not running, event counts)
- Exposes all parameters as sliders/toggles that update the daemon in real time without restarting
- Sends SIGTERM to the daemon when Krita closes (this works across the Flatpak sandbox because Flatpak shares the host PID namespace by default)

The plugin does **not** start the daemon — the daemon is managed by systemd. If the daemon is not running, the plugin shows the command to start it. On systems **without systemd**, the plugin detects this automatically and shows the manual start command instead:

```bash
python3 daemon/ipts-predict.py &
```

---

## Requirements

- Linux with the `linux-surface` kernel and `iptsd` userspace daemon running
- Python 3.10+
- `python3-evdev` installed (`pip install evdev` or system package)
- Krita installed as a Flatpak (tested on 5.3.1)
- X11 session (tested on Cinnamon). Wayland has compositor frame-sync batching that makes lag significantly worse — switch to X11 if possible.

---

## Installation

**1. Download or clone this repository.**

**2. Run the installer** (handles device access + the background daemon; it will ask for `sudo` once to install the udev rule):
```bash
cd surface-pen-prediction
./install.sh
```

**3. Install the Krita plugin** (the installer prints these steps too):
- Krita → **Tools → Scripts → Import Python Plugin from File** → select `pen_prediction-krita-docker.zip`
- **Settings → Configure Krita → Python Plugin Manager** → enable **Pen Prediction** → restart Krita
- **Settings → Dockers → Pen Prediction** to open the panel

A green dot in the docker confirms the daemon is running. That's it — start drawing.

> The installer is safe to re-run, detects whether you have systemd, and warns if `python3-evdev` or `iptsd` is missing. Prefer to do it by hand? See [Manual setup](#manual-setup) below.

### Per-distro setup

Each block has three steps: (1) the linux-surface kernel + `iptsd` — **skip if your pen already works**, it's not part of this project; (2) this project's one dependency, `python-evdev`; (3) the installer. The Step 1 repo key/URL can change over time — if a line fails, check the [linux-surface wiki](https://github.com/linux-surface/linux-surface/wiki/Installation-and-Setup).

**Debian / Ubuntu / Mint**
```bash
# 1. kernel + iptsd (skip if pen already works)
wget -qO - https://raw.githubusercontent.com/linux-surface/linux-surface/master/pkg/keys/surface.asc \
  | gpg --dearmor | sudo dd of=/etc/apt/keyrings/linux-surface.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/linux-surface.gpg] https://pkg.surfacelinux.com/debian release main" \
  | sudo tee /etc/apt/sources.list.d/linux-surface.list
sudo apt update
sudo apt install linux-image-surface linux-headers-surface iptsd libwacom-surface
sudo update-grub && sudo reboot
# 2. dependency
sudo apt install python3-evdev
# 3. install
cd ~/surface-pen-prediction && ./install.sh
```

**Arch / Manjaro / EndeavourOS**
```bash
# 1. kernel + iptsd (skip if pen already works)
curl -s https://raw.githubusercontent.com/linux-surface/linux-surface/master/pkg/keys/surface.asc \
  | sudo pacman-key --add -
sudo pacman-key --lsign-key 56C464BAAC421453
echo -e "[linux-surface]\nServer = https://pkg.surfacelinux.com/arch/" | sudo tee -a /etc/pacman.conf
sudo pacman -Syu
sudo pacman -S linux-surface linux-surface-headers iptsd
sudo reboot
# 2. dependency
sudo pacman -S python-evdev
# 3. install
cd ~/surface-pen-prediction && ./install.sh
```

**Fedora**
```bash
# 1. kernel + iptsd (skip if pen already works)
sudo dnf config-manager --add-repo https://pkg.surfacelinux.com/fedora/linux-surface.repo
sudo dnf install kernel-surface iptsd libwacom-surface
sudo reboot
# 2. dependency
sudo dnf install python3-evdev
# 3. install
cd ~/surface-pen-prediction && ./install.sh
```

**openSUSE**
```bash
# 1. kernel + iptsd — follow the linux-surface wiki (no first-party zypper repo)
# 2. dependency
sudo zypper install python3-evdev
# 3. install
cd ~/surface-pen-prediction && ./install.sh
```

**No systemd (Artix / Void / Alpine)**
```bash
# 1. kernel + iptsd per your distro;  python-evdev via pkg manager (or pip install --user evdev)
# 2. udev rule + run the daemon manually (add the last line to session autostart)
cd ~/surface-pen-prediction
sudo cp 99-surface-pen-krita.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
python3 daemon/ipts-predict.py &
```

Then import the Krita plugin (Step 3 above) on every distro.

### Manual setup

If you'd rather not run the script:

```bash
# 1. Device access (lets the daemon read the pen and write a virtual device)
sudo cp 99-surface-pen-krita.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=input
sudo udevadm trigger --name-match=uinput

# 2a. Daemon via systemd (auto-starts on login).
#     The unit has a __DAEMON_DIR__ placeholder — substitute the repo path:
sed "s|__DAEMON_DIR__|$PWD|g" daemon/ipts-predict.service \
    > ~/.config/systemd/user/ipts-predict.service
systemctl --user daemon-reload
systemctl --user enable --now ipts-predict

# 2b. ...or without systemd, run it directly (add to your session autostart)
python3 daemon/ipts-predict.py &
```

Then import `pen_prediction-krita-docker.zip` in Krita as described above. To rebuild the
zip after editing the plugin source: `./build-plugin.sh`.

---

## Configuration

The docker has an on/off checkbox and four sliders. All update the daemon live — no restart needed.

| Setting | What it does | Default |
|---|---|---|
| **Smoothing on** (checkbox) | Master toggle. Off = transparent passthrough (raw pen). | on |
| **Smoothing** | Kalman smoothing strength. 0 = track raw tightly, 10 = heavy. | 2 |
| **Lookahead** | Drag reduction: constant forward lead in ms. `<10` feels draggy, `15` is the sweet spot, `40` is too floaty. | 15 |
| **Factor** | Max interpolation points inserted per real sample (kills polygon corners). | 3 |
| **Speed sensitivity** | How readily interpolation kicks in at slow speeds. Low = more fill-in when drawing slowly. | 5 |

**Recommended starting point:** the defaults (Smoothing 2, Lookahead 15, Factor 3, Sensitivity 5) are tuned for the Surface Pro 7 and were validated on real artwork. From there:

- **Still feels draggy?** Raise Lookahead toward 20–25.
- **Tip floats / overshoots corners?** Lower Lookahead toward 8–10.
- **Lines look rough at slow speed?** Raise Smoothing a notch or two — but note the value is in the pipeline, not heavy smoothing, so small changes go a long way.

The lead is constant (speed-scaled), so raising Lookahead moves the whole line uniformly closer to your pen rather than changing the feel speed-by-speed. Hooks at stroke ends are bounded by the 5 mm lead cap regardless of setting.

---

## How the Daemon and Plugin Communicate

The daemon listens on a Unix socket at `~/.local/share/ipts-predict.sock`. The plugin connects and sends JSON commands:

```json
{"enabled": true}
{"smoothing": 2}
{"lookahead_ms": 15.0}
{"factor": 3}
{"sensitivity": 0.5}
{"status": true}
{"record_start": "/tmp/trace.csv"}
{"record_stop": true}
```

Any command also returns the current full state (plus `real_count`, `synth_count`, `tool_active`, `recording`), which the plugin uses to update the status display. `record_start`/`record_stop` write a per-event trace of raw input vs. emitted output — feed it to `tools/analyze-strokes.py` to measure hooks, endpoint accuracy, and ellipse roundness.

---

## Daemon Control

```bash
systemctl --user start ipts-predict    # start
systemctl --user stop ipts-predict     # stop (restores original pen device)
systemctl --user status ipts-predict   # check
systemctl --user enable ipts-predict   # auto-start on login
systemctl --user disable ipts-predict  # remove auto-start
cat /tmp/ipts-predict.log             # view logs
```

---

## Compatibility Notes

**Display server:** X11 strongly recommended. Wayland adds compositor frame-sync batching that groups pen events into bursts, making the effective rate much lower and less consistent than the IPTS hardware ceiling.

**Cinnamon session:** Make sure you're in the regular **Cinnamon** session, not **Cinnamon (Software Rendering)**. The software rendering session sets `LIBGL_ALWAYS_SOFTWARE=1` which forces Krita to use CPU rasterization (llvmpipe) — this makes canvas updates slow and compounds the lag problem. You can verify with `glxinfo | grep renderer`: it should say `Intel` or your GPU, not `llvmpipe`.

**Other Surface models:** Tested on Surface Pro 7. Other models using IPTS (Pro 4, 5, 6) should work but the ABS axis ranges and resolutions in `daemon/ipts-predict.py` (`SOURCE_CAPS`) may need adjusting to match your device. Run `python3 -c "import evdev; d = evdev.InputDevice('/dev/input/eventXXX'); print(d.capabilities())"` on your IPTSD Virtual Stylus device to get the correct values.

**Krita version:** Tested on 5.3.1 Flatpak. Should work on any Krita version with Python plugin support.

---

## Tuning Internals

Most tuning is done from the docker. For deeper changes, the daemon has a few constants and classes worth knowing:

**`KalmanAxis`** (`q_pos`, `q_vel`, `r`): the per-axis filter. `r` (measurement noise) is normally driven by the **Smoothing** slider, so you rarely touch it. `q_vel` controls how fast the filter's velocity can change — raise for snappier direction response, lower for steadier velocity. `q_pos` is position process noise. Device units: ABS_X is 0–9600 across ~260 mm, so 1 unit ≈ 0.027 mm.

**`VelocityTracker(window=6)`**: windowed least-squares velocity used for prediction. A larger window = smoother but slightly laggier velocity; smaller = snappier but noisier.

**Module constants:**
- `MAX_LEAD_MM = 5.0` — hard cap on the predicted lead distance; bounds the worst-case stop hook.
- The speed-proportional lead reaches full strength at `80 mm/s` (in the reader loop) — lower it to get full drag reduction at slower drawing speeds.

**`tools/analyze-strokes.py`** quantifies the effect of any change: record a trace via the docker's hidden socket commands (or `record_start`/`record_stop`) and run the analyzer to see end-hook, endpoint accuracy, and ellipse roundness by stroke-length bucket.

---

## Forking / Adapting

**Other Surface models (Pro 4, 5, 6, Book):**
The `SOURCE_CAPS` dict in `ipts-predict.py` is hardcoded for the SP7. Get your device's values with:
```bash
python3 -c "import evdev; d = evdev.InputDevice('/dev/input/eventXXX'); print(d.capabilities())"
```
Point it at your IPTSD Virtual Stylus device and paste the output into `SOURCE_CAPS`.

**Other tablets (Wacom, Huion, XP-Pen):**
These run at higher native rates so the polygon problem is less severe, but the Kalman smoothing and retrospective interpolation still help with jitter. Replace `SOURCE_CAPS` and update `find_source_device()` to match your device name/vendor/product ID.

**Wayland users:**
The daemon works at the evdev level but synthetic events pass through the Wayland compositor which may re-batch them. Try running Krita with `QT_QPA_PLATFORM=xcb` to force X11 via Xwayland, which bypasses compositor batching. (This is to say, good luck.)

**Non-Flatpak Krita:**
Change `CONFIG_FILE` in `pen_prediction.py` from `~/.var/app/org.kde.krita/data/krita/` to `~/.local/share/krita/`. Plugin directory is `~/.local/share/krita/pykrita/`.

**Other drawing apps (Xournal++, Inkscape, etc.):**
The daemon works below the application layer. Any app reading X11 tablet input gets the smoothed events automatically — no plugin needed. (Not actually tested yet)

**Systems without systemd (Void, Alpine, Artix, etc.):**
The `ipts-predict.service` file won't apply, but the daemon itself works anywhere. Run it manually:
```bash
python3 daemon/ipts-predict.py &
```
The Krita plugin detects whether systemd is present and shows the appropriate start command in the docker when the daemon isn't running. For auto-start without systemd, add the manual command to your session startup script (e.g. `~/.xinitrc` or your display manager's autostart).

---

## Files

```
surface-pen-prediction/
├── README.md                        ← this file
├── LICENSE                          ← public domain (Unlicense)
├── install.sh                       ← daemon setup script
├── build-plugin.sh                  ← rebuilds pen_prediction-krita-docker.zip from source
├── pen_prediction-krita-docker.zip               ← Krita plugin (import via Tools → Scripts)
├── 99-surface-pen-krita.rules       ← udev rule for device access
├── daemon/
│   ├── ipts-predict.py              ← main daemon
│   └── ipts-predict.service         ← systemd user service unit
├── plugin/
│   ├── pen_prediction.desktop       ← Krita plugin metadata
│   └── pen_prediction/
│       ├── __init__.py
│       └── pen_prediction.py        ← Krita docker UI
└── tools/
    ├── stylus-rate-test.py          ← measures real stylus event rate via X11
    ├── record.py                    ← record a raw-vs-output trace (start/stop/status)
    └── analyze-strokes.py           ← measures hooks / endpoint accuracy / roundness from a trace
```

### tools/stylus-rate-test.py (doesn't actually work - no write mechanism)

Standalone diagnostic. Run it while drawing to measure your actual hardware event rate — useful for before/after comparisons or characterising a different device. Needs only python3 + python-xlib. Output: Hz, gap distribution, and how many gaps would produce visible polygon corners.

### tools/record.py + tools/analyze-strokes.py

The measurement workflow used to tune (and validate) the drag reduction.

**Easiest — the docker button.** The Pen Prediction docker has a **Record trace** button under *Diagnostics*. Click it, draw, click **Stop**, and it saves a timestamped `~/pen-trace-*.csv` (the docker shows the exact path and the analyze command). Then:

```bash
tools/analyze-strokes.py ~/pen-trace-20260602-021500.csv
```

**Or from the command line** (handy for scripting, or on a fork without the docker):

```bash
tools/record.py start /tmp/test.csv    # begin capturing raw-vs-output trace
#  ... draw in Krita for a bit ...
tools/record.py stop                   # stop
tools/analyze-strokes.py /tmp/test.csv # report the numbers
```

Both wrap the daemon's `record_start`/`record_stop` socket commands. `analyze-strokes.py` reads the CSV and reports, bucketed by stroke length: **end hook** (forward overshoot past a stop), **final endpoint** error (under/overshoot), and **ellipse roundness** (raw vs. output). This is how we proved the fast-stroke hooks dropped from 15 mm to ~0 — if you fork and change the prediction math, this is how you check whether you made it better or worse.

---

## Origin

This project was built entirely through a single session with **[Claude Code](https://claude.ai/code)** (Anthropic's AI coding tool), including the research, system diagnostics, algorithm design, daemon implementation, Krita plugin, and all documentation. The human contributor directed the work, tested each iteration, and made the design decisions — Claude Code wrote and debugged the code.

The session log is preserved in full in the `Obsidian/` project notes if you want to see how the design evolved (spoiler: the first approach crashed the compositor).

---

## License

Do whatever you want with it. If it helps you draw, that's enough.

## License

MIT (aka fork it so "reel tru arTEESTS" won't get butthurt over it being made by AI). 
