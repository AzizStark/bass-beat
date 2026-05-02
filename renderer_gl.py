import math
import os
import cairo
import ctypes
import numpy as np

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk

try:
    from OpenGL.GL import *
    from OpenGL.GL import shaders
    HAS_GL = True
except ImportError:
    HAS_GL = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 aPos;
layout(location = 1) in vec4 aColor;
layout(location = 2) in vec2 aLocalPos;
layout(location = 3) in vec2 aBarSize;
out vec4 vColor;
out vec2 vLocalPos;
out vec2 vBarSize;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
    vColor = aColor;
    vLocalPos = aLocalPos;
    vBarSize = aBarSize;
}
"""

_FRAGMENT_SHADER = """
#version 330 core
in vec4 vColor;
in vec2 vLocalPos;
in vec2 vBarSize;
out vec4 FragColor;
void main() {
    float hw = vBarSize.x * 0.5;
    float hh = vBarSize.y * 0.5;
    float dx = abs(vLocalPos.x) - hw;
    float dy = abs(vLocalPos.y) - hh;
    float ax = 1.0 - smoothstep(-1.0, 0.5, dx);
    float ay = 1.0 - smoothstep(-1.0, 0.5, dy);
    float aa = ax * ay;
    FragColor = vec4(vColor.rgb, vColor.a * aa);
}
"""

_TEX_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 aPos;
layout(location = 1) in vec2 aTexCoord;
out vec2 vTexCoord;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
    vTexCoord = aTexCoord;
}
"""

_TEX_FRAGMENT_SHADER = """
#version 330 core
in vec2 vTexCoord;
out vec4 FragColor;
uniform sampler2D uTexture;
uniform float uRadius;
uniform vec2 uCenter;
void main() {
    vec2 diff = gl_FragCoord.xy - uCenter;
    if (dot(diff, diff) > uRadius * uRadius)
        discard;
    FragColor = texture(uTexture, vTexCoord);
}
"""

class GLVisualizer:
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

        angles = np.array([
            math.radians(start_angle + (end_angle / num_bars) * (i + 0.5))
            for i in range(num_bars)
        ], dtype=np.float64)
        self._cos_a = np.cos(angles).astype(np.float32)
        self._sin_a = np.sin(angles).astype(np.float32)

        self._bar_colors_norm = np.array(
            [(r / 255.0, g / 255.0, b / 255.0, a / 255.0) for r, g, b, a in bar_colors],
            dtype=np.float32,
        )

        self._r_inner = np.float32(radius * scale)
        self._bw2 = np.float32(bar_width / 2)
        self._pad = np.float32(1.0)
        self._sx = np.float32(1.0 / self.halfwidth)
        self._sy = np.float32(-1.0 / self.halfwidth)

        self._verts_buf = np.zeros((num_bars, 6, 10), dtype=np.float32)

        self._gl_initialized = False
        self._image_path = image_path or os.path.join(SCRIPT_DIR, "assets", "default.png")
        self._tex_id = 0
        self._img_w = 0
        self._img_h = 0

    def get_widget_size(self):
        return int(self.halfwidth * 2), int(self.halfwidth * 2)

    def init_gl(self):
        if self._gl_initialized:
            return
        self._gl_initialized = True

        self._bar_shader = shaders.compileProgram(
            shaders.compileShader(_VERTEX_SHADER, GL_VERTEX_SHADER),
            shaders.compileShader(_FRAGMENT_SHADER, GL_FRAGMENT_SHADER),
        )
        self._tex_shader = shaders.compileProgram(
            shaders.compileShader(_TEX_VERTEX_SHADER, GL_VERTEX_SHADER),
            shaders.compileShader(_TEX_FRAGMENT_SHADER, GL_FRAGMENT_SHADER),
        )

        self._bar_vao = glGenVertexArrays(1)
        self._bar_vbo = glGenBuffers(1)

        self._tex_vao = glGenVertexArrays(1)
        self._tex_vbo = glGenBuffers(1)

        if os.path.exists(self._image_path):
            img_surface = cairo.ImageSurface.create_from_png(self._image_path)
            self._img_w = img_surface.get_width()
            self._img_h = img_surface.get_height()
            data = np.frombuffer(img_surface.get_data(), dtype=np.uint8).reshape(
                (self._img_h, self._img_w, 4)
            ).copy()
            data[:, :, [0, 2]] = data[:, :, [2, 0]]

            self._tex_id = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, self._tex_id)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, self._img_w, self._img_h,
                         0, GL_RGBA, GL_UNSIGNED_BYTE, data)

        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def render(self, width, height, bar_values, beat_value=0.0):
        self.init_gl()

        glViewport(0, 0, width, height)
        glClearColor(0.0, 0.0, 0.0, 0.0)
        glClear(GL_COLOR_BUFFER_BIT)

        self._draw_bars_gl(width, height, bar_values)
        self._draw_center_image_gl(width, height, beat_value)

    def _draw_bars_gl(self, vp_w, vp_h, bar_values):
        n = self.num_bars
        vals = np.asarray(bar_values[:n], dtype=np.float32)
        bar_h = np.maximum(self.min_bar_height, vals * self.bar_height)
        mask = bar_h >= 0.5
        active = np.where(mask)[0]

        if len(active) == 0:
            return

        bh = bar_h[active]
        cos_a = self._cos_a[active]
        sin_a = self._sin_a[active]
        colors = self._bar_colors_norm[active]

        ri = self._r_inner
        bw2 = self._bw2
        pad = self._pad
        sx = self._sx
        sy = self._sy
        bw = self.bar_width

        bw2p = bw2 + pad
        r_outer = ri + bh
        bar_hp = bh + pad * 2
        half_bhp = bar_hp * 0.5

        lx = np.array([-bw2p, bw2p, bw2p, -bw2p, bw2p, -bw2p], dtype=np.float32)
        ly_base_inner = np.float32(-ri + pad)
        ly_outer = -(r_outer + pad)

        na = len(active)
        out = self._verts_buf[:na]

        ly0 = ly_outer
        ly2 = np.full(na, ly_base_inner, dtype=np.float32)

        for v_idx, (local_x, is_outer) in enumerate([
            (-bw2p, True), (bw2p, True), (bw2p, False),
            (-bw2p, True), (bw2p, False), (-bw2p, False),
        ]):
            local_y = ly0 if is_outer else ly2
            rx = (local_x * cos_a - local_y * sin_a) * sx
            ry = (local_x * sin_a + local_y * cos_a) * sy
            loc_y = -half_bhp if is_outer else half_bhp
            out[:, v_idx, 0] = rx
            out[:, v_idx, 1] = ry
            out[:, v_idx, 2:6] = colors
            out[:, v_idx, 6] = local_x
            out[:, v_idx, 7] = loc_y
            out[:, v_idx, 8] = bw
            out[:, v_idx, 9] = bh

        data = out[:na].reshape(-1)

        glUseProgram(self._bar_shader)
        glBindVertexArray(self._bar_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._bar_vbo)
        glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_DYNAMIC_DRAW)

        stride = 10 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(8))
        glEnableVertexAttribArray(2)
        glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
        glEnableVertexAttribArray(3)
        glVertexAttribPointer(3, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(32))

        glDrawArrays(GL_TRIANGLES, 0, na * 6)
        glBindVertexArray(0)

    def _draw_center_image_gl(self, vp_w, vp_h, beat_value):
        if self._tex_id == 0:
            return

        hw = self.halfwidth
        image_scale_offset = 2 * (0.005 * self.radius * self.image_scale_factor)
        pulse_extra = beat_value * 3.6 * 40.0
        target_size = (self.radius * 2) + image_scale_offset + pulse_extra

        half = target_size / 2.0
        sx = 1.0 / hw
        sy = -1.0 / hw

        x0 = -half * sx
        y0 = -half * sy
        x1 = half * sx
        y1 = half * sy

        verts = np.array([
            x0, y0, 0.0, 0.0,
            x1, y0, 1.0, 0.0,
            x1, y1, 1.0, 1.0,
            x0, y0, 0.0, 0.0,
            x1, y1, 1.0, 1.0,
            x0, y1, 0.0, 1.0,
        ], dtype=np.float32)

        glUseProgram(self._tex_shader)

        center_x = vp_w / 2.0
        center_y = vp_h / 2.0
        pixel_radius = (target_size / 2.0) * (min(vp_w, vp_h) / (hw * 2))

        loc_r = glGetUniformLocation(self._tex_shader, "uRadius")
        loc_c = glGetUniformLocation(self._tex_shader, "uCenter")
        glUniform1f(loc_r, pixel_radius)
        glUniform2f(loc_c, center_x, center_y)

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._tex_id)
        glUniform1i(glGetUniformLocation(self._tex_shader, "uTexture"), 0)

        glBindVertexArray(self._tex_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._tex_vbo)
        glBufferData(GL_ARRAY_BUFFER, verts.nbytes, verts, GL_DYNAMIC_DRAW)

        stride = 4 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(8))

        glDrawArrays(GL_TRIANGLES, 0, 6)
        glBindVertexArray(0)
