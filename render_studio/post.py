# SPDX-License-Identifier: GPL-3.0-or-later
"""Live adjustments of a finished render, without rendering again.

Pure NumPy on 8-bit RGB: exposure in stops (in linear light), contrast
around mid-grey, saturation, warmth (a white-balance tilt) and vignette.
The defaults leave the image exactly as rendered.
"""
from __future__ import annotations

import numpy as np

NEUTRAL = {"exposure": 0.0, "contrast": 1.0, "saturation": 1.0, "warmth": 0.0, "vignette": 0.0}


def _to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def is_neutral(adj: dict) -> bool:
    return all(abs(float(adj.get(k, v)) - v) < 1e-6 for k, v in NEUTRAL.items())


def adjust(rgb: np.ndarray, adj: dict) -> np.ndarray:
    """``rgb``: H×W×3 uint8 → adjusted H×W×3 uint8."""
    if is_neutral(adj):
        return rgb
    x = rgb.astype(np.float32) / 255.0
    ev = float(adj.get("exposure", 0.0))
    warmth = float(adj.get("warmth", 0.0))
    if ev or warmth:
        lin = _to_linear(x) * (2.0 ** ev)
        if warmth:
            lin = lin * np.array([1.0 + 0.12 * warmth, 1.0, 1.0 - 0.12 * warmth], dtype=np.float32)
        # A soft shoulder instead of a hard clip when the exposure goes up.
        lin = np.where(lin > 0.8, 0.8 + (1 - np.exp(-(lin - 0.8) * 5)) * 0.2, lin)
        x = _to_srgb(lin)
    c = float(adj.get("contrast", 1.0))
    if c != 1.0:
        x = np.clip((x - 0.5) * c + 0.5, 0.0, 1.0)
    s = float(adj.get("saturation", 1.0))
    if s != 1.0:
        luma = (x @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))[..., None]
        x = np.clip(luma + (x - luma) * s, 0.0, 1.0)
    v = float(adj.get("vignette", 0.0))
    if v:
        h, w = x.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        r = np.sqrt(((xx - (w - 1) / 2) / (w / 2)) ** 2 + ((yy - (h - 1) / 2) / (h / 2)) ** 2) / np.sqrt(2)
        x = x * (1.0 - v * np.clip(r, 0, 1) ** 2.2)[..., None]
    return (np.clip(x, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
