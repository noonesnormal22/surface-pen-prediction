#!/bin/bash
# Pen Prediction — full installer.
# Sets up device access (udev), the background daemon (systemd user service),
# and points you at the Krita plugin zip. Safe to re-run.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SYSTEMD_USER="$HOME/.config/systemd/user"
UDEV_RULE="/etc/udev/rules.d/99-surface-pen-krita.rules"

echo "=== Pen Prediction — Installer ==="
echo ""

# --- 1. Prerequisites ---
echo "[1/4] Checking prerequisites..."
if ! python3 -c "import evdev" 2>/dev/null; then
    echo "  ERROR: python3-evdev not found. Install it first:"
    echo "    Debian/Ubuntu/Mint:  sudo apt install python3-evdev"
    echo "    Arch:                sudo pacman -S python-evdev"
    echo "    pip:                 pip install --user evdev"
    exit 1
fi
if ! python3 -c "import evdev; exit(0 if any('IPTSD Virtual Stylus' in evdev.InputDevice(p).name for p in evdev.list_devices()) else 1)" 2>/dev/null; then
    echo "  WARNING: IPTSD Virtual Stylus not found. Is iptsd running?"
    echo "  (Continuing — the daemon will report this if the device is missing.)"
fi
echo "      OK."

# --- 2. udev rule (needs sudo) ---
echo "[2/4] Installing udev rule (grants pen + uinput access)..."
if [ -f "$UDEV_RULE" ] && cmp -s "$SCRIPT_DIR/99-surface-pen-krita.rules" "$UDEV_RULE"; then
    echo "      Already installed."
else
    sudo cp "$SCRIPT_DIR/99-surface-pen-krita.rules" "$UDEV_RULE"
    sudo udevadm control --reload-rules
    sudo udevadm trigger --subsystem-match=input
    sudo udevadm trigger --name-match=uinput
    echo "      Installed."
fi

# --- 3. systemd user service ---
echo "[3/4] Installing background daemon (systemd user service)..."
if [ -d /run/systemd/system ]; then
    mkdir -p "$SYSTEMD_USER"
    # Bake the real install path into the unit so it works wherever the repo
    # was cloned (the committed unit uses a __DAEMON_DIR__ placeholder).
    sed "s|__DAEMON_DIR__|$SCRIPT_DIR|g" \
        "$SCRIPT_DIR/daemon/ipts-predict.service" > "$SYSTEMD_USER/ipts-predict.service"
    systemctl --user daemon-reload
    systemctl --user enable ipts-predict
    systemctl --user restart ipts-predict
    sleep 2
    if systemctl --user is-active --quiet ipts-predict; then
        echo "      Daemon running (auto-starts on login)."
    else
        echo "      Failed to start. Check: journalctl --user -u ipts-predict"
        exit 1
    fi
else
    echo "      No systemd detected. Start the daemon manually instead:"
    echo "        python3 $SCRIPT_DIR/daemon/ipts-predict.py &"
    echo "      (add that to your session autostart, e.g. ~/.xinitrc)"
fi

# --- 4. Krita plugin ---
echo "[4/4] Krita plugin..."
echo "      In Krita:  Tools -> Scripts -> Import Python Plugin from File"
echo "      Select:    $SCRIPT_DIR/pen_prediction-krita-docker.zip"
echo "      Then:      Settings -> Configure Krita -> Python Plugin Manager"
echo "                 enable 'Pen Prediction', restart Krita."
echo "      Open it:   Settings -> Dockers -> Pen Prediction"

echo ""
echo "=== Done ==="
echo "Daemon control:  systemctl --user start|stop|status ipts-predict"
echo "Log:             cat /tmp/ipts-predict.log"
