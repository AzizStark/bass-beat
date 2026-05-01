#!/usr/bin/env python3
"""BassBeat2 Linux -- Circular Audio Visualizer

A precise port of the BassBeat2 Rainmeter skin.
All FFT parameters, band mapping, smoothing, mirroring,
gradient colors, and geometry are matched exactly.

Usage:
    python main.py [--no-transparent] [--size SIZE] [--fps FPS]

Requires: numpy, sounddevice, PyGObject (gi), cairo
On Ubuntu/Debian: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0
"""

import sys
import argparse
import numpy as np

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

from audio_capture import AudioCapture
from dsp import (
    apply_smoothing, build_mirrored_bar_values,
    compute_gradient_colors, DEFAULT_GCOLOR,
)
from renderer import CircularVisualizer

# --- Configuration matching Variables.inc exactly ---
NUM_AUDIO_BANDS = 60
NUM_BARS = 120
BAR_WIDTH = 4.5
BAR_HEIGHT = 306
RADIUS = 144
START_ANGLE = 0
END_ANGLE = 360
SCALE = 1.0
SMOOTHING = 3
MIRROR = True
INVERT_MIRROR = False
GCOLOR = DEFAULT_GCOLOR


class VisualizerWindow(Gtk.Window):
    def __init__(self, transparent=True, size=None, fps=60):
        super().__init__(title="BassBeat2")

        self.bar_colors = compute_gradient_colors(GCOLOR, NUM_BARS)

        self.visualizer = CircularVisualizer(
            bar_colors=self.bar_colors,
            num_bars=NUM_BARS,
            bar_width=BAR_WIDTH,
            bar_height=BAR_HEIGHT,
            radius=RADIUS,
            start_angle=START_ANGLE,
            end_angle=END_ANGLE,
            scale=SCALE,
        )

        w, h = self.visualizer.get_widget_size()
        if size is not None:
            scale_factor = size / max(w, h)
            w = int(w * scale_factor)
            h = int(h * scale_factor)
        self._render_w = w
        self._render_h = h

        self.set_default_size(w, h)
        self.set_resizable(False)

        if transparent:
            self.set_app_paintable(True)
            self.set_decorated(False)
            screen = self.get_screen()
            visual = screen.get_rgba_visual()
            if visual is not None:
                self.set_visual(visual)
            self.set_keep_below(True)
            self.stick()

        self._drawing_area = Gtk.DrawingArea()
        self._drawing_area.set_size_request(w, h)
        self._drawing_area.connect('draw', self._on_draw)
        self.add(self._drawing_area)

        self.connect('destroy', self._on_destroy)
        self.connect('key-press-event', self._on_key_press)

        self._enable_drag()

        self._audio = AudioCapture(num_bands=NUM_AUDIO_BANDS, fps=fps)
        self._bar_values = np.zeros(NUM_BARS, dtype=np.float64)
        self._beat_value = 0.0

        self._fps = fps
        self._timer_id = None

    def start(self):
        self._audio.start()
        interval_ms = max(1, int(1000 / self._fps))
        self._timer_id = GLib.timeout_add(interval_ms, self._tick)
        self.show_all()

    def _tick(self):
        raw_bands = self._audio.get_bands()

        smoothed = apply_smoothing(
            raw_bands, smoothing=SMOOTHING,
            mirror=MIRROR, invert_mirror=INVERT_MIRROR
        )

        bar_values = build_mirrored_bar_values(
            smoothed, num_bars=NUM_BARS,
            mirror=MIRROR, invert_mirror=INVERT_MIRROR
        )

        self._bar_values = bar_values

        beat_band_idx = 26
        self._beat_value = raw_bands[beat_band_idx] if beat_band_idx < len(raw_bands) else 0.0

        self._drawing_area.queue_draw()
        return True

    def _on_draw(self, widget, ctx):
        ctx.set_operator(0)  # CLEAR
        ctx.paint()
        ctx.set_operator(2)  # OVER

        alloc = widget.get_allocation()
        vis_w, vis_h = self.visualizer.get_widget_size()

        sx = alloc.width / vis_w
        sy = alloc.height / vis_h
        s = min(sx, sy)

        if s != 1.0:
            ctx.scale(s, s)

        self.visualizer.render(ctx, self._bar_values, self._beat_value)

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
        if event.button == 1:
            self.begin_move_drag(
                event.button, int(event.x_root), int(event.y_root),
                event.time
            )


def main():
    parser = argparse.ArgumentParser(description='BassBeat2 Linux Visualizer')
    parser.add_argument('--no-transparent', action='store_true',
                        help='Disable transparent background')
    parser.add_argument('--size', type=int, default=None,
                        help='Override widget size (max dimension in px)')
    parser.add_argument('--fps', type=int, default=60,
                        help='Target frames per second (default: 60)')
    args = parser.parse_args()

    win = VisualizerWindow(
        transparent=not args.no_transparent,
        size=args.size,
        fps=args.fps,
    )
    win.start()
    Gtk.main()


if __name__ == '__main__':
    main()
