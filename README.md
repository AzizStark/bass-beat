# BassBeat

> **⚠️ Beta** — This project is experimental. Expect rough edges, especially with compositor integration and audio device detection across different distros.

A circular audio visualizer that reacts to your music in real-time. Runs natively on Linux as a desktop widget.

![BassBeat](test_render.png)

## Install

Install system dependencies first, then run setup:

**Arch / Manjaro:**
```bash
sudo pacman -S python-gobject gtk3 portaudio
```

**Ubuntu / Debian:**
```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 libportaudio2 python3-venv
```

**Fedora:**
```bash
sudo dnf install python3-gobject gtk3 portaudio
```

**Void Linux:**
```bash
sudo xbps-install -S python3-gobject gtk+3 portaudio
```

Then:

```bash
git clone https://github.com/AzizStark/bassbeat.git
cd bassbeat
./setup.sh
```

The setup script installs to `~/.local/share/bassbeat`, creates the config at `~/.config/bassbeat/config.toml`, and adds a `bassbeat` launcher to `~/.local/bin/`.

## Usage

```
bassbeat                 Run the visualizer
bassbeat --config        Print current config
bassbeat --edit          Open config in your editor
bassbeat --config-path   Print config file path
bassbeat --help          Show help
```

## Configure

Edit with `bassbeat --edit`. Changes take effect on restart.

```toml
[display]
fps = 60                           # frames per second
position = "center"                # "center" or "x,y" coordinates (e.g. "100,200")
draggable = true                   # left-click drag to reposition
transparent = true
keep_below = true                  # desktop widget mode
fps_sync_decay = true              # consistent decay speed across fps values

[renderer]
backend = "cairo"                  # "cairo" (CPU) or "opengl" (GPU, requires PyOpenGL)

[visualizer]
bars = 120
bar_width = 4.5
bar_height = 306
radius = 144
start_angle = 0
end_angle = 360
scale = 1.0
smoothing = 3
mirror = true
invert_mirror = false

[colors]
gradient = "210,228,255,255:0|239,33,177,255:50|222,231,254,255:100"
# Rainbow:
# gradient = "255,0,0,255:0|255,255,0,255:16|0,255,0,255:33|0,255,255,255:50|0,0,255,255:67|255,0,255,255:84|255,0,0,255:100"

[audio]
fft_size = 8192
fft_buffer_size = 16384
fft_attack = 0
fft_decay = 65
freq_min = 22
freq_max = 200
sensitivity = 33
bands = 60

[image]
path = "assets/default.png"        # center image
scale_factor = 80                  # 0-100, image overlap with bars
```

## Compositor notes

BassBeat sets `_NET_WM_WINDOW_TYPE_DESKTOP` and compositor hint properties automatically. Works out of the box on most compositors.

| Compositor | Status |
|------------|--------|
| picom (legacy) | Works automatically |
| picom v13+ | Add `"window_type = 'desktop' \|\| "` to your `shadow = false` rule |
| mutter (GNOME) | Works automatically |
| kwin (KDE) | Works automatically |
| xfwm4 (Xfce) | Works automatically |

> **Note:** When `draggable = true`, the window uses `UTILITY` type to receive mouse input, which may show blur/shadow on some compositors. Set `draggable = false` once positioned for clean desktop mode.

## Autostart

The setup script can configure autostart for you. To add it manually:

**bspwm** (`~/.config/bspwm/bspwmrc`):
```bash
bassbeat &
```

**i3** (`~/.config/i3/config`):
```
exec --no-startup-id bassbeat
```

**Hyprland** (`~/.config/hypr/hyprland.conf`):
```
exec-once = bassbeat
```

**sway** (`~/.config/sway/config`):
```
exec bassbeat
```

**XDG autostart** (GNOME, KDE, Xfce):
```bash
cp ~/.config/autostart/bassbeat.desktop  # created by setup.sh
```

## Performance tips

| Tip | Effect |
|-----|--------|
| Lower `fps` | Biggest impact — halving fps halves CPU usage. Match your monitor refresh rate for best results. Going below 60 will be visually noticeable |
| Use `backend = "opengl"` | Faster rendering, lower CPU per frame |
| Use `backend = "cairo"` | More compatible, no OpenGL dependency needed |
| Reduce `bars` (e.g. 60) | Fewer bars = fewer draw calls per frame |
| Set `draggable = false` | Uses DESKTOP window type which some compositors render more efficiently |
| Lower PipeWire quantum | `pw-metadata -n settings 0 clock.force-quantum 128` for lower audio latency (reset with value `0`) |

Typical resource usage at 60fps with cairo backend: **~1-3% CPU**, **~45MB RAM**.

## Uninstall

```bash
rm -rf ~/.local/share/bassbeat ~/.config/bassbeat ~/.local/bin/bassbeat
```

Remove any autostart entries you added.

## Credits

Based on [Bass-Beat-2](https://github.com/AzizStark/Bass-Beat-2) Rainmeter skin by SnGmng & AzizStark.

## License

CC BY-SA 4.0
