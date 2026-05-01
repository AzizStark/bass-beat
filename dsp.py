import numpy as np


def asen(n, lo, hi):
    """Palindrome mirror wrap: 0 1 2 3 ... 59 59 ... 3 2 1 0
    Matches Rainmeter's asen() used when InvertMirror=0 and Mirror=1."""
    d = n
    if d > hi:
        d = hi - (n - hi)
    if d < lo:
        d = lo - (n - lo)
    return int(np.clip(d, lo, hi))


def sens(n, lo, hi):
    """Circular wrap: 0 1 2 ... 59 0 1 2 ...
    Matches Rainmeter's sens()."""
    d = n
    if d > hi:
        d = n - hi
    if d < lo:
        d = hi + n + 1
    return int(np.clip(d, lo, hi))


_smoothing_cache = {}


def _get_smoothing_indices(n, smoothing, mirror, invert_mirror):
    key = (n, smoothing, mirror, invert_mirror)
    if key in _smoothing_cache:
        return _smoothing_cache[key]

    audio_measures = n - 1
    wrap_fn = asen if (not invert_mirror and mirror) else sens

    idx_table = np.empty((n, smoothing * 2 + 1), dtype=np.int32)
    for i in range(n):
        for j, s in enumerate(range(-smoothing, smoothing + 1)):
            idx_table[i, j] = wrap_fn(i + s, 0, audio_measures)

    _smoothing_cache[key] = idx_table
    return idx_table


def apply_smoothing(raw_bands, smoothing=3, mirror=True, invert_mirror=False):
    """Applies the same smoothing kernel as generateVis.lua.

    With Smoothing=3 and 60 audio measures, each smoothed value is the
    average of 7 neighbors (i-3 ... i+3), with edge wrapping via
    asen() or sens() matching the Rainmeter config.
    """
    n = len(raw_bands)
    if smoothing == 0:
        return raw_bands.copy()

    idx = _get_smoothing_indices(n, smoothing, mirror, invert_mirror)
    return raw_bands[idx].mean(axis=1)


_mirror_cache = {}


def build_mirrored_bar_values(smoothed_bands, num_bars=120, mirror=True, invert_mirror=False):
    """Maps 60 smoothed audio bands to 120 visual bars with mirroring.

    Matches generateVis.lua's bar generation loop exactly:
    - Mirror=1, InvertMirror=0:
      bar i <= audioMeasures -> band i
      bar i > audioMeasures  -> band (bands-1 - i), i.e. palindrome
    """
    num_bands = len(smoothed_bands)
    key = (num_bands, num_bars, mirror, invert_mirror)

    if key not in _mirror_cache:
        bands_total = num_bars - 1
        audio_measures = (num_bands - 1) if (num_bars % 2 == 0) else (num_bands // 2)

        idx = np.arange(num_bars, dtype=np.int32)
        if mirror:
            if invert_mirror:
                idx = np.where(idx <= audio_measures, idx, idx - audio_measures - 1)
            else:
                idx = np.where(idx <= audio_measures, idx, bands_total - idx)

        _mirror_cache[key] = np.clip(idx, 0, num_bands - 1)

    return smoothed_bands[_mirror_cache[key]]


def parse_color(colorstring):
    """Parse Rainmeter color string 'R,G,B,A:Percent' or '#RRGGBB'."""
    colorstring = colorstring.strip()
    if colorstring.startswith('#'):
        r = int(colorstring[1:3], 16)
        g = int(colorstring[3:5], 16)
        b = int(colorstring[5:7], 16)
        a = 255
        pct = float(colorstring[8:]) if len(colorstring) > 7 else 0.0
        return (r, g, b, a, pct)

    parts = colorstring.split(',')
    r = float(parts[0])
    g = float(parts[1])
    b = float(parts[2])

    gm = parts[3].split(':')
    a = float(gm[0])
    pct = float(gm[1])
    return (r, g, b, a, pct)


def gradient_of(c1, c2, percent):
    """Linearly interpolate between two RGBA colors by percent (0-100)."""
    t = percent / 100.0
    return (
        c1[0] + (c2[0] - c1[0]) * t,
        c1[1] + (c2[1] - c1[1]) * t,
        c1[2] + (c2[2] - c1[2]) * t,
        c1[3] + (c2[3] - c1[3]) * t,
    )


def compute_gradient_colors(gcolor_string, num_bars):
    """Compute per-bar RGBA colors from the gradient string.

    Matches GetGradients() from generateVis.lua exactly.
    GColor format: 'R,G,B,A:Pct|R,G,B,A:Pct|...'
    e.g. '210,228,255,255:0|239,33,177,255:50|222,231,254,255:100'
    """
    stops = []
    for part in gcolor_string.split('|'):
        stops.append(parse_color(part))

    colors = [(s[0], s[1], s[2], s[3]) for s in stops]
    percents = [s[4] for s in stops]

    bar_colors = []
    ppb = 100.0 / num_bars
    i_band = 0
    i_color = 0

    while i_band < num_bars:
        band_pct = i_band * ppb

        if i_color + 1 < len(percents) and percents[i_color + 1] == band_pct:
            bar_colors.append(colors[i_color + 1])
            i_color += 1
            i_band += 1
        else:
            if i_color + 1 < len(percents) and percents[i_color + 1] > band_pct:
                p = ((band_pct - percents[i_color]) /
                     (percents[i_color + 1] - percents[i_color])) * 100.0
                bar_colors.append(gradient_of(colors[i_color], colors[i_color + 1], p))
                i_band += 1

            if i_color + 1 < len(percents) and percents[i_color + 1] < band_pct:
                i_color += 1

    return bar_colors


# Default gradient from Variables.inc
DEFAULT_GCOLOR = "210,228,255,255:0|239,33,177,255:50|222,231,254,255:100"
