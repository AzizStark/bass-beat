#!/bin/bash
set -e

INSTALL_DIR="$HOME/.local/share/bassbeat"
BIN_LINK="$HOME/.local/bin/bassbeat"
CONFIG_DIR="$HOME/.config/bassbeat"

echo "BassBeat — Installer"
echo ""

# ── Preflight ──
FAIL=""
python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk" 2>/dev/null || FAIL="yes"
python3 -c "import cairo" 2>/dev/null || FAIL="${FAIL}yes"
python3 -c "import ctypes; ctypes.cdll.LoadLibrary('libportaudio.so.2')" 2>/dev/null || FAIL="${FAIL}yes"

if [ -n "$FAIL" ]; then
    echo "Missing system dependencies. Install them first:"
    echo ""
    if command -v pacman &>/dev/null; then
        echo "  sudo pacman -S python-gobject gtk3 portaudio"
    elif command -v apt &>/dev/null; then
        echo "  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 libportaudio2 python3-venv"
    elif command -v dnf &>/dev/null; then
        echo "  sudo dnf install python3-gobject gtk3 portaudio"
    elif command -v zypper &>/dev/null; then
        echo "  sudo zypper install python3-gobject gtk3 portaudio"
    elif command -v xbps-install &>/dev/null; then
        echo "  sudo xbps-install -S python3-gobject gtk+3 portaudio"
    elif command -v nix-env &>/dev/null; then
        echo "  nix-shell -p python3 gobject-introspection gtk3 portaudio"
    else
        echo "  Install PyGObject, GTK3, and PortAudio with your package manager"
    fi
    echo ""
    echo "Then re-run ./setup.sh"
    exit 1
fi

echo "  Dependencies: OK"

# ── Install files ──
echo "  Installing to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR/assets"
mkdir -p "$CONFIG_DIR"
mkdir -p "$(dirname "$BIN_LINK")"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "$SCRIPT_DIR"/main.py "$INSTALL_DIR/"
cp "$SCRIPT_DIR"/audio_capture.py "$INSTALL_DIR/"
cp "$SCRIPT_DIR"/dsp.py "$INSTALL_DIR/"
cp "$SCRIPT_DIR"/renderer.py "$INSTALL_DIR/"
cp "$SCRIPT_DIR"/renderer_gl.py "$INSTALL_DIR/"
cp "$SCRIPT_DIR"/config.py "$INSTALL_DIR/"
cp "$SCRIPT_DIR"/requirements.txt "$INSTALL_DIR/"
cp "$SCRIPT_DIR"/assets/* "$INSTALL_DIR/assets/"

if [ ! -f "$CONFIG_DIR/config.toml" ]; then
    cp "$SCRIPT_DIR"/config.toml "$CONFIG_DIR/config.toml"
    echo "  Config: created $CONFIG_DIR/config.toml"
else
    echo "  Config: keeping existing $CONFIG_DIR/config.toml"
fi

# ── Virtual environment ──
if [ ! -d "$INSTALL_DIR/.venv" ]; then
    echo "  Creating virtual environment..."
    python3 -m venv --system-site-packages "$INSTALL_DIR/.venv"
fi

echo "  Installing Python packages..."
"$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip 2>/dev/null
"$INSTALL_DIR/.venv/bin/pip" install -q numpy pulsectl sounddevice PyOpenGL 2>/dev/null

# ── Launcher ──
cat > "$BIN_LINK" << 'LAUNCHER'
#!/bin/bash
INSTALL_DIR="$HOME/.local/share/bassbeat"
CONFIG="$HOME/.config/bassbeat/config.toml"

case "$1" in
    --config)
        cat "$CONFIG"
        exit 0
        ;;
    --edit)
        ${EDITOR:-${VISUAL:-xdg-open}} "$CONFIG"
        exit 0
        ;;
    --config-path)
        echo "$CONFIG"
        exit 0
        ;;
    --help|-h)
        echo "Usage: bassbeat [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  --config       Print current config"
        echo "  --edit         Open config in editor"
        echo "  --config-path  Print config file path"
        echo "  --help         Show this help"
        echo ""
        echo "Config: $CONFIG"
        exit 0
        ;;
esac

if command -v pw-metadata &>/dev/null; then
    pw-metadata -n settings 0 clock.force-quantum 128 &>/dev/null
fi

exec "$INSTALL_DIR/.venv/bin/python3" "$INSTALL_DIR/main.py" --config "$CONFIG" "$@" 2>/dev/null
LAUNCHER
chmod +x "$BIN_LINK"
echo "  Launcher: $BIN_LINK"

# ── Preflight verify ──
"$INSTALL_DIR/.venv/bin/python3" -c "
import numpy, sounddevice, cairo
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
" 2>/dev/null

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Preflight check failed. Try:"
    echo "  rm -rf $INSTALL_DIR/.venv && ./setup.sh"
    exit 1
fi

echo "  Preflight: OK"

# ── Autostart ──
echo ""
read -p "  Launch on startup? [y/N] " AUTOSTART

if [[ "$AUTOSTART" =~ ^[Yy]$ ]]; then
    DESKTOP_DIR="$HOME/.config/autostart"
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_DIR/bassbeat.desktop" << EOF
[Desktop Entry]
Type=Application
Name=BassBeat
Exec=$BIN_LINK
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
Comment=Circular audio visualizer
EOF
    echo "  Autostart: $DESKTOP_DIR/bassbeat.desktop"

    # Also handle WM-based autostart for tiling WMs
    for rc in "$HOME/.config/bspwm/bspwmrc" \
              "$HOME/.config/i3/config" \
              "$HOME/.config/hypr/hyprland.conf" \
              "$HOME/.config/sway/config"; do
        if [ -f "$rc" ] && ! grep -q "bassbeat" "$rc" 2>/dev/null; then
            echo ""
            echo "  Detected $(basename "$(dirname "$rc")") config at $rc"
            read -p "  Add bassbeat to it? [y/N] " ADD_WM
            if [[ "$ADD_WM" =~ ^[Yy]$ ]]; then
                case "$rc" in
                    *bspwm*)    echo "$BIN_LINK &" >> "$rc" ;;
                    *i3/*)      echo "exec --no-startup-id $BIN_LINK" >> "$rc" ;;
                    *hypr*)     echo "exec-once = $BIN_LINK" >> "$rc" ;;
                    *sway*)     echo "exec $BIN_LINK" >> "$rc" ;;
                esac
                echo "  Added to $rc"
            fi
        fi
    done
fi

echo ""
echo "Done! Run with:"
echo ""
echo "  bassbeat"
echo ""
echo "Edit config at: $CONFIG_DIR/config.toml"
echo "Uninstall: rm -rf $INSTALL_DIR $CONFIG_DIR $BIN_LINK"
echo ""
