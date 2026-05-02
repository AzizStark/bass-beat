#!/usr/bin/env python3
"""BassBeat -- Circular Audio Visualizer

Usage:
    python main.py [--config PATH]

Requires: numpy, sounddevice, PyGObject (gi), cairo
Optional: PyOpenGL (for hardware-accelerated rendering)
"""

import sys
import os
import argparse
import numpy as np

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

from config import load_config
from audio_capture import AudioCapture
from dsp import (
    apply_smoothing, build_mirrored_bar_values,
    compute_gradient_colors,
)
from renderer import CircularVisualizer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class VisualizerWindow(Gtk.Window):
    def __init__(self, cfg):
        super().__init__(title="BassBeat2")
        self.set_wmclass("bassbeat", "BassBeat")

        disp = cfg["display"]
        vis = cfg["visualizer"]
        aud = cfg["audio"]
        col = cfg["colors"]
        img = cfg["image"]
        rend = cfg["renderer"]

        self._fps = disp["fps"]
        self._smoothing = vis["smoothing"]
        self._mirror = vis["mirror"]
        self._invert_mirror = vis["invert_mirror"]
        self._num_bars = vis["bars"]
        self._backend = rend["backend"]

        self.bar_colors = compute_gradient_colors(col["gradient"], self._num_bars)

        image_path = img["path"]
        if not os.path.isabs(image_path):
            image_path = os.path.join(SCRIPT_DIR, image_path)

        if self._backend == "opengl":
            from renderer_gl import GLVisualizer, HAS_GL
            if not HAS_GL:
                print("OpenGL not available, falling back to cairo")
                self._backend = "cairo"

        if self._backend == "opengl":
            from renderer_gl import GLVisualizer
            self._gl_vis = GLVisualizer(
                bar_colors=self.bar_colors,
                num_bars=self._num_bars,
                bar_width=vis["bar_width"],
                bar_height=vis["bar_height"],
                radius=vis["radius"],
                start_angle=vis["start_angle"],
                end_angle=vis["end_angle"],
                scale=vis["scale"],
                min_bar_height=vis["min_bar_height"],
                image_path=image_path,
                image_scale_factor=img["scale_factor"],
            )
            hw = self._gl_vis.halfwidth
            w, h = self._gl_vis.get_widget_size()
        else:
            self._gl_vis = None
            self._cairo_vis = CircularVisualizer(
                bar_colors=self.bar_colors,
                num_bars=self._num_bars,
                bar_width=vis["bar_width"],
                bar_height=vis["bar_height"],
                radius=vis["radius"],
                start_angle=vis["start_angle"],
                end_angle=vis["end_angle"],
                scale=vis["scale"],
                min_bar_height=vis["min_bar_height"],
                image_path=image_path,
                image_scale_factor=img["scale_factor"],
            )
            w, h = self._cairo_vis.get_widget_size()

        size = disp["size"]
        if size and size > 0:
            scale_factor = size / max(w, h)
            w = int(w * scale_factor)
            h = int(h * scale_factor)

        self.set_default_size(w, h)
        self.set_resizable(False)
        self._win_w = w
        self._win_h = h
        self._position = disp.get("position", "center")
        self._draggable = disp.get("draggable", True)

        if disp["transparent"]:
            self.set_app_paintable(True)
            self.set_decorated(False)
            screen = self.get_screen()
            visual = screen.get_rgba_visual()
            if visual is not None:
                self.set_visual(visual)
            if disp["keep_below"]:
                self.set_keep_below(True)
            self.stick()
            if self._draggable:
                self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
            else:
                self.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
            self.set_skip_taskbar_hint(True)
            self.set_skip_pager_hint(True)

        if self._backend == "opengl":
            self._gl_area = Gtk.GLArea()
            self._gl_area.set_required_version(3, 3)
            self._gl_area.set_has_alpha(True)
            self._gl_area.set_size_request(w, h)
            self._gl_area.connect('render', self._on_gl_render)
            self.add(self._gl_area)
        else:
            self._drawing_area = Gtk.DrawingArea()
            self._drawing_area.set_size_request(w, h)
            self._drawing_area.connect('draw', self._on_draw)
            self.add(self._drawing_area)

        self.connect('destroy', self._on_destroy)
        self.connect('key-press-event', self._on_key_press)
        self._enable_drag()

        self._audio = AudioCapture(
            num_bands=aud["bands"],
            fft_size=aud["fft_size"],
            fft_buffer_size=aud["fft_buffer_size"],
            freq_min=aud["freq_min"],
            freq_max=aud["freq_max"],
            sensitivity=aud["sensitivity"],
            fft_attack=aud["fft_attack"],
            fft_decay=aud["fft_decay"],
            fps=self._fps,
            fps_sync_decay=disp.get("fps_sync_decay", True),
        )
        self._bar_values = np.zeros(self._num_bars, dtype=np.float64)
        self._beat_value = 0.0
        self._timer_id = None

    def start(self):
        self._audio.start()
        interval_ms = max(1, int(1000 / self._fps))
        self._timer_id = GLib.timeout_add(interval_ms, self._tick)
        self.show_all()
        self._apply_position()
        self._disable_compositor_effects()

    def _apply_position(self):
        pos = self._position.strip().lower()
        if pos == "center":
            screen = self.get_screen()
            monitor = screen.get_monitor_at_window(self.get_window())
            geo = screen.get_monitor_geometry(monitor)
            x = geo.x + (geo.width - self._win_w) // 2
            y = geo.y + (geo.height - self._win_h) // 2
            self.move(x, y)
        elif "," in pos:
            try:
                x, y = pos.split(",", 1)
                self.move(int(x.strip()), int(y.strip()))
            except ValueError:
                pass

    def _disable_compositor_effects(self):
        try:
            from ctypes import cdll, c_ulong, c_long, c_char_p, c_int, c_void_p, byref
            xlib = cdll.LoadLibrary("libX11.so.6")
            xlib.XOpenDisplay.restype = c_void_p
            xlib.XOpenDisplay.argtypes = [c_char_p]
            xlib.XInternAtom.restype = c_ulong
            xlib.XInternAtom.argtypes = [c_void_p, c_char_p, c_int]
            xlib.XChangeProperty.argtypes = [c_void_p, c_ulong, c_ulong, c_ulong,
                                              c_int, c_int, c_void_p, c_int]
            xlib.XFlush.argtypes = [c_void_p]
            xlib.XCloseDisplay.argtypes = [c_void_p]

            xid = self.get_window().get_xid()
            dpy = xlib.XOpenDisplay(None)
            if not dpy:
                return

            cardinal = xlib.XInternAtom(dpy, b"CARDINAL", 0)
            for name in [b"_PICOM_SHADOW", b"_COMPTON_SHADOW", b"_KDE_NET_WM_SHADOW"]:
                atom = xlib.XInternAtom(dpy, name, 0)
                val = (c_ulong * 1)(0)
                xlib.XChangeProperty(dpy, xid, atom, cardinal, 32, 0, byref(val), 1)

            motif_atom = xlib.XInternAtom(dpy, b"_MOTIF_WM_HINTS", 0)
            hints = (c_long * 5)(2, 0, 0, 0, 0)
            xlib.XChangeProperty(dpy, xid, motif_atom, motif_atom, 32, 0, byref(hints), 5)

            xlib.XFlush(dpy)
            xlib.XCloseDisplay(dpy)
        except Exception:
            pass

        self._print_compositor_hint()

    @staticmethod
    def _print_compositor_hint():
        import shutil
        if shutil.which("picom"):
            print(
                "NOTE: If you see a shadow/blur box, add this to your picom config's\n"
                '      shadow=false rule:  "window_type = \'desktop\' || "',
                flush=True,
            )

    def _tick(self):
        raw_bands = self._audio.get_bands()

        smoothed = apply_smoothing(
            raw_bands, smoothing=self._smoothing,
            mirror=self._mirror, invert_mirror=self._invert_mirror,
        )
        self._bar_values = build_mirrored_bar_values(
            smoothed, num_bars=self._num_bars,
            mirror=self._mirror, invert_mirror=self._invert_mirror,
        )

        beat_band_idx = 26
        self._beat_value = raw_bands[beat_band_idx] if beat_band_idx < len(raw_bands) else 0.0

        if self._backend == "opengl":
            self._gl_area.queue_draw()
        else:
            self._drawing_area.queue_draw()
        return True

    def _on_draw(self, widget, ctx):
        ctx.set_operator(0)  # CLEAR
        ctx.paint()
        ctx.set_operator(2)  # OVER

        alloc = widget.get_allocation()
        vis_w, vis_h = self._cairo_vis.get_widget_size()
        s = min(alloc.width / vis_w, alloc.height / vis_h)
        if s != 1.0:
            ctx.scale(s, s)

        self._cairo_vis.render(ctx, self._bar_values, self._beat_value)

    def _on_gl_render(self, area, ctx):
        alloc = area.get_allocation()
        self._gl_vis.render(alloc.width, alloc.height,
                            self._bar_values, self._beat_value)
        return True

    def _on_destroy(self, *args):
        self._audio.stop()
        if self._timer_id:
            GLib.source_remove(self._timer_id)
        Gtk.main_quit()

    def _on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape or event.keyval == Gdk.KEY_q:
            self.destroy()

    def _enable_drag(self):
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect('button-press-event', self._on_button_press)

    def _on_button_press(self, widget, event):
        if event.button == 1 and self._draggable:
            self.begin_move_drag(
                event.button, int(event.x_root), int(event.y_root),
                event.time,
            )


def main():
    parser = argparse.ArgumentParser(description='BassBeat2 Linux Visualizer')
    parser.add_argument('--config', type=str, default=None,
                        help='Path to config.toml')
    args = parser.parse_args()

    cfg = load_config(args.config)

    print(f"BassBeat2: backend={cfg['renderer']['backend']}, "
          f"fps={cfg['display']['fps']}, "
          f"bars={cfg['visualizer']['bars']}, "
          f"transparent={cfg['display']['transparent']}",
          flush=True)

    win = VisualizerWindow(cfg)
    win.start()
    Gtk.main()


if __name__ == '__main__':
    main()
