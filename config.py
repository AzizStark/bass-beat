import os
import tomllib

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.toml")

DEFAULTS = {
    "display": {
        "fps": 60,
        "size": 0,
        "transparent": True,
        "keep_below": True,
    },
    "renderer": {
        "backend": "cairo",
    },
    "visualizer": {
        "bars": 120,
        "bar_width": 4.5,
        "bar_height": 306,
        "radius": 144,
        "start_angle": 0,
        "end_angle": 360,
        "scale": 1.0,
        "smoothing": 3,
        "mirror": True,
        "invert_mirror": False,
        "min_bar_height": 0,
    },
    "colors": {
        "gradient": "210,228,255,255:0|239,33,177,255:50|222,231,254,255:100",
    },
    "audio": {
        "fft_size": 8192,
        "fft_buffer_size": 16384,
        "fft_attack": 0,
        "fft_decay": 65,
        "freq_min": 22,
        "freq_max": 200,
        "sensitivity": 33,
        "bands": 60,
    },
    "image": {
        "path": "assets/default.png",
        "scale_factor": 80,
    },
}


def _deep_merge(base, override):
    merged = dict(base)
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def load_config(path=None):
    if path is None:
        path = CONFIG_PATH

    cfg = dict(DEFAULTS)

    if os.path.exists(path):
        with open(path, "rb") as f:
            user = tomllib.load(f)
        cfg = _deep_merge(cfg, user)

    return cfg
