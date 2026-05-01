import math
import cairo
import numpy as np
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class CircularVisualizer:
    """Renders the BassBeat2 circular visualizer using Cairo.

    All parameters are matched to Variables.inc:
      Bands=120, BarWidth=4.5, BarHeight=306, Radius=144
      StartAngle=0, EndAngle=360, Scale=1
      Mirror=1, InvertMirror=0
      GColor=210,228,255,255:0|239,33,177,255:50|222,231,254,255:100
    """

    def __init__(self, bar_colors, num_bars=120, bar_width=4.5, bar_height=306,
                 radius=144, start_angle=0, end_angle=360, scale=1.0,
                 min_bar_height=0, image_path=None, image_scale_factor=80):
        self.num_bars = num_bars
        self.bar_width = bar_width
        self.bar_height = bar_height
        self.radius = radius
        self.start_angle = start_angle
        self.end_angle = end_angle
        self.scale = scale
        self.min_bar_height = min_bar_height
        self.bar_colors = bar_colors
        self.image_scale_factor = image_scale_factor

        self.halfwidth = (radius + bar_height) * scale

        self._precompute_bar_geometry()

        self._center_image = None
        center_path = image_path or os.path.join(SCRIPT_DIR, "assets", "default.png")
        if os.path.exists(center_path):
            self._center_image = cairo.ImageSurface.create_from_png(center_path)

    def _precompute_bar_geometry(self):
        """Precompute rotation angles for each bar -- matches generateVis.lua."""
        self._bar_angles = []
        for i in range(self.num_bars):
            angle = self.start_angle + (
                (self.end_angle / self.num_bars) * (i + 0.5)
            )
            self._bar_angles.append(angle)

    def get_widget_size(self):
        return int(self.halfwidth * 2), int(self.halfwidth * 2)

    def render(self, ctx, bar_values, beat_value=0.0):
        """Draw the full visualizer onto a Cairo context.

        bar_values: array of 120 floats [0..1]
        beat_value: raw band 26 value [0..1], used for center image pulse
        """
        w = self.halfwidth * 2
        h = self.halfwidth * 2

        ctx.set_operator(cairo.OPERATOR_CLEAR)
        ctx.paint()
        ctx.set_operator(cairo.OPERATOR_OVER)

        self._draw_bars(ctx, bar_values)
        self._draw_center_image(ctx, beat_value)

    def _draw_bars(self, ctx, bar_values):
        hw = self.halfwidth

        for i in range(self.num_bars):
            value = bar_values[i] if i < len(bar_values) else 0.0
            bar_h = max(self.min_bar_height, value * self.bar_height)

            if bar_h < 0.5:
                continue

            angle_deg = self._bar_angles[i]
            angle_rad = math.radians(angle_deg)

            r, g, b, a = self.bar_colors[i]

            ctx.save()

            ctx.translate(hw, hw)
            ctx.rotate(angle_rad)
            if self.scale != 1.0:
                ctx.scale(self.scale, self.scale)

            x = -self.bar_width / 2
            y = -(self.radius * self.scale + bar_h)

            ctx.rectangle(x, y, self.bar_width, bar_h)
            ctx.set_source_rgba(r / 255.0, g / 255.0, b / 255.0, a / 255.0)
            ctx.fill()

            ctx.restore()

    def _draw_center_image(self, ctx, beat_value):
        if self._center_image is None:
            return

        hw = self.halfwidth
        img_w = self._center_image.get_width()
        img_h = self._center_image.get_height()

        image_scale_offset = 2 * (0.005 * self.radius * self.image_scale_factor)
        pulse_extra = beat_value * 3.6 * 40.0
        target_size = (self.radius * 2) + image_scale_offset + pulse_extra

        scale_x = target_size / img_w
        scale_y = target_size / img_h

        ctx.save()
        ctx.translate(hw - target_size / 2, hw - target_size / 2)
        ctx.scale(scale_x, scale_y)

        ctx.set_source_surface(self._center_image, 0, 0)
        ctx.get_source().set_filter(cairo.FILTER_BILINEAR)

        ctx.arc(img_w / 2, img_h / 2, min(img_w, img_h) / 2, 0, 2 * math.pi)
        ctx.clip()

        ctx.paint()
        ctx.restore()
