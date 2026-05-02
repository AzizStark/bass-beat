import math
import cairo
import numpy as np
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class CircularVisualizer:
    """Renders the BassBeat2 circular visualizer using Cairo."""

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
        self.image_scale_factor = image_scale_factor

        self.halfwidth = (radius + bar_height) * scale
        hw = self.halfwidth

        angles_rad = np.array([
            math.radians(start_angle + (end_angle / num_bars) * (i + 0.5))
            for i in range(num_bars)
        ])
        cos_a = np.cos(angles_rad)
        sin_a = np.sin(angles_rad)

        self._bar_matrices = []
        for i in range(num_bars):
            c, s = cos_a[i], sin_a[i]
            if scale != 1.0:
                c *= scale
                s *= scale
            self._bar_matrices.append(cairo.Matrix(c, s, -s, c, hw, hw))

        self._bar_colors_rgba = [
            (r / 255.0, g / 255.0, b / 255.0, a / 255.0) for r, g, b, a in bar_colors
        ]

        self._bar_x = -bar_width / 2.0
        self._r_scaled = radius * scale
        self._identity = cairo.Matrix()

        self._center_image = None
        self._img_w = 0
        self._img_h = 0
        center_path = image_path or os.path.join(SCRIPT_DIR, "assets", "default.png")
        if os.path.exists(center_path):
            self._center_image = cairo.ImageSurface.create_from_png(center_path)
            self._img_w = self._center_image.get_width()
            self._img_h = self._center_image.get_height()
            self._img_circle_r = min(self._img_w, self._img_h) / 2.0
            self._img_cx = self._img_w / 2.0
            self._img_cy = self._img_h / 2.0
        self._image_base = (radius * 2) + 2 * (0.005 * radius * image_scale_factor)

    def get_widget_size(self):
        return int(self.halfwidth * 2), int(self.halfwidth * 2)

    def render(self, ctx, bar_values, beat_value=0.0):
        ctx.set_operator(cairo.OPERATOR_CLEAR)
        ctx.paint()
        ctx.set_operator(cairo.OPERATOR_OVER)

        self._draw_bars(ctx, bar_values)
        self._draw_center_image(ctx, beat_value)

    def _draw_bars(self, ctx, bar_values):
        bh_scale = self.bar_height
        bw = self.bar_width
        bx = self._bar_x
        r_sc = self._r_scaled
        matrices = self._bar_matrices
        colors = self._bar_colors_rgba
        rectangle = ctx.rectangle
        set_source_rgba = ctx.set_source_rgba
        fill = ctx.fill
        set_matrix = ctx.set_matrix
        base_matrix = ctx.get_matrix()

        for i in range(self.num_bars):
            bar_h = bar_values[i] * bh_scale
            if bar_h < 0.5:
                continue

            set_matrix(matrices[i])
            rectangle(bx, -(r_sc + bar_h), bw, bar_h)
            set_source_rgba(*colors[i])
            fill()

        set_matrix(base_matrix)

    def _draw_center_image(self, ctx, beat_value):
        if self._center_image is None:
            return

        hw = self.halfwidth
        target_size = self._image_base + beat_value * 144.0

        sx = target_size / self._img_w
        sy = target_size / self._img_h
        offset = hw - target_size * 0.5

        ctx.save()
        ctx.translate(offset, offset)
        ctx.scale(sx, sy)

        ctx.set_source_surface(self._center_image, 0, 0)
        ctx.get_source().set_filter(cairo.FILTER_BILINEAR)

        ctx.arc(self._img_cx, self._img_cy, self._img_circle_r, 0, 6.283185307179586)
        ctx.clip()
        ctx.paint()
        ctx.restore()
