import math
import os
import cairo
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
out vec4 vColor;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
    vColor = aColor;
}
"""

_FRAGMENT_SHADER = """
#version 330 core
in vec4 vColor;
out vec4 FragColor;
void main() {
    FragColor = vColor;
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

        self._bar_angles_rad = []
        for i in range(num_bars):
            angle = start_angle + (end_angle / num_bars) * (i + 0.5)
            self._bar_angles_rad.append(math.radians(angle))

        self._bar_colors_norm = np.array(
            [(r / 255.0, g / 255.0, b / 255.0, a / 255.0) for r, g, b, a in bar_colors],
            dtype=np.float32,
        )

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

        self._msaa_fbo = 0
        self._msaa_rbo_color = 0
        self._msaa_rbo_depth = 0
        self._resolve_fbo = 0
        self._resolve_tex = 0
        self._msaa_w = 0
        self._msaa_h = 0
        self._msaa_samples = 4

    def _ensure_msaa_fbo(self, width, height):
        if self._msaa_w == width and self._msaa_h == height and self._msaa_fbo:
            return

        if self._msaa_fbo:
            glDeleteFramebuffers(1, [self._msaa_fbo])
            glDeleteRenderbuffers(1, [self._msaa_rbo_color])
            glDeleteFramebuffers(1, [self._resolve_fbo])
            glDeleteTextures([self._resolve_tex])

        samples = self._msaa_samples

        self._msaa_fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self._msaa_fbo)

        self._msaa_rbo_color = glGenRenderbuffers(1)
        glBindRenderbuffer(GL_RENDERBUFFER, self._msaa_rbo_color)
        glRenderbufferStorageMultisample(GL_RENDERBUFFER, samples, GL_RGBA8, width, height)
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                  GL_RENDERBUFFER, self._msaa_rbo_color)

        self._resolve_fbo = glGenFramebuffers(1)
        self._resolve_tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self._resolve_tex)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height,
                     0, GL_RGBA, GL_UNSIGNED_BYTE, None)
        glBindFramebuffer(GL_FRAMEBUFFER, self._resolve_fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, self._resolve_tex, 0)

        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        self._msaa_w = width
        self._msaa_h = height

    def render(self, width, height, bar_values, beat_value=0.0):
        self.init_gl()

        default_fbo = glGetIntegerv(GL_FRAMEBUFFER_BINDING)

        self._ensure_msaa_fbo(width, height)

        glBindFramebuffer(GL_FRAMEBUFFER, self._msaa_fbo)
        glViewport(0, 0, width, height)
        glClearColor(0.0, 0.0, 0.0, 0.0)
        glClear(GL_COLOR_BUFFER_BIT)

        self._draw_bars_gl(width, height, bar_values)
        self._draw_center_image_gl(width, height, beat_value)

        glBindFramebuffer(GL_READ_FRAMEBUFFER, self._msaa_fbo)
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, default_fbo)
        glBlitFramebuffer(0, 0, width, height,
                          0, 0, width, height,
                          GL_COLOR_BUFFER_BIT, GL_LINEAR)
        glBindFramebuffer(GL_FRAMEBUFFER, default_fbo)

    def _draw_bars_gl(self, vp_w, vp_h, bar_values):
        hw = self.halfwidth
        sx = 1.0 / hw
        sy = -1.0 / hw

        verts = []
        for i in range(self.num_bars):
            value = bar_values[i] if i < len(bar_values) else 0.0
            bar_h = max(self.min_bar_height, value * self.bar_height)
            if bar_h < 0.5:
                continue

            angle = self._bar_angles_rad[i]
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)

            bw2 = self.bar_width / 2
            r_inner = self.radius * self.scale
            r_outer = r_inner + bar_h

            corners = [
                (-bw2, -r_outer),
                (bw2, -r_outer),
                (bw2, -r_inner),
                (-bw2, -r_inner),
            ]

            r, g, b, a = self._bar_colors_norm[i]
            for lx, ly in [corners[0], corners[1], corners[2],
                           corners[0], corners[2], corners[3]]:
                rx = lx * cos_a - ly * sin_a
                ry = lx * sin_a + ly * cos_a
                verts.extend([rx * sx, ry * sy, r, g, b, a])

        if not verts:
            return

        data = np.array(verts, dtype=np.float32)

        glUseProgram(self._bar_shader)
        glBindVertexArray(self._bar_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._bar_vbo)
        glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_DYNAMIC_DRAW)

        stride = 6 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(8))

        glDrawArrays(GL_TRIANGLES, 0, len(verts) // 6)
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
