# SPDX-License-Identifier: GPL-3.0-or-later
"""The final picture: its size and its file format. No Qt, no Blender.

Kept in the document with the other settings (``settings["output"]``)::

    "output": {
      "size": "view",              # "view" (the 3D view's shape, from "width"), a preset key, or "custom"
      "height": 1080,              # pixels (with "view" the height follows the 3D view)
      "dpi": 300,                  # for the paper sizes, and to say how big a print is
      "format": "png",             # png png16 jpeg tiff16 exr
      "jpeg_quality": 92,
      "transparent": false,        # the sky left transparent (png, png16, tiff16, exr)
      "projection": "normal",      # "normal", "flat" (a cylindrical panorama: verticals stay straight) or
                                   # "360" (equirectangular, 2:1, all round); panoramas render with Cycles
      "angle": 180                 # "flat": the horizontal angle covered, degrees
    }

The width stays in ``settings["width"]``, as before.
"""
from __future__ import annotations

from .i18n import tr, translate_on_show  # noqa: F401

MIN_PX, MAX_PX = 16, 16384

#: key → (label, width, height); paper sizes are millimetres (landscape), turned into pixels at the dpi.
SIZES = (
    ("view", "Same shape as the 3D view", None, None),
    ("hd", "HD 1280 × 720", 1280, 720),
    ("fullhd", "Full HD 1920 × 1080", 1920, 1080),
    ("qhd", "QHD 2560 × 1440", 2560, 1440),
    ("uhd", "4K UHD 3840 × 2160", 3840, 2160),
    ("square", "Square 2048 × 2048", 2048, 2048),
    ("portrait45", "Portrait 4:5, 1080 × 1350", 1080, 1350),
    ("story", "Vertical 9:16, 1080 × 1920", 1080, 1920),
    ("pano", "Panorama 3:1, 4800 × 1600", 4800, 1600),
    ("a4", "A4 landscape (at the dpi)", "297mm", "210mm"),
    ("a4p", "A4 portrait (at the dpi)", "210mm", "297mm"),
    ("a3", "A3 landscape (at the dpi)", "420mm", "297mm"),
    ("a3p", "A3 portrait (at the dpi)", "297mm", "420mm"),
    ("a2", "A2 landscape (at the dpi)", "594mm", "420mm"),
    ("a1", "A1 landscape (at the dpi)", "841mm", "594mm"),
    ("custom", "Custom", None, None),
)
SIZE_BY_KEY = {s[0]: s for s in SIZES}

#: key → (label, extension, Blender image settings, keeps transparency, can be retouched)
FORMATS = {
    "png": ("PNG, 8 bits", ".png", {"file_format": "PNG", "color_depth": "8", "compression": 15}, True, True),
    "png16": ("PNG, 16 bits", ".png", {"file_format": "PNG", "color_depth": "16", "compression": 15}, True, False),
    "jpeg": ("JPEG", ".jpg", {"file_format": "JPEG"}, False, True),
    "tiff16": ("TIFF, 16 bits", ".tif", {"file_format": "TIFF", "color_depth": "16", "tiff_codec": "DEFLATE"},
               True, False),
    "exr": ("OpenEXR, 32-bit float (linear light)", ".exr",
            {"file_format": "OPEN_EXR", "color_depth": "32", "exr_codec": "ZIP"}, True, False),
}
FORMAT_ORDER = ("png", "jpeg", "png16", "tiff16", "exr")

PROJECTIONS = ("normal", "flat", "360")
DEFAULT = {"size": "view", "height": 1080, "dpi": 300, "format": "png", "jpeg_quality": 92, "transparent": False,
           "projection": "normal", "angle": 180}


def _int(v, lo, hi, default):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f:
        return default
    return int(round(max(lo, min(hi, f))))


def clean(raw) -> dict:
    """A trusted copy of the output settings (defaults for whatever is missing or wrong)."""
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT)
    if raw.get("size") in SIZE_BY_KEY:
        out["size"] = raw["size"]
    out["height"] = _int(raw.get("height"), MIN_PX, MAX_PX, DEFAULT["height"])
    out["dpi"] = _int(raw.get("dpi"), 30, 1200, DEFAULT["dpi"])
    if raw.get("format") in FORMATS:
        out["format"] = raw["format"]
    out["jpeg_quality"] = _int(raw.get("jpeg_quality"), 10, 100, DEFAULT["jpeg_quality"])
    out["transparent"] = bool(raw.get("transparent", False)) and FORMATS[out["format"]][3]
    out["projection"] = raw.get("projection") if raw.get("projection") in PROJECTIONS else "normal"
    out["angle"] = _int(raw.get("angle"), 30, 360, DEFAULT["angle"])
    return out


def mm_to_px(mm: float, dpi: int) -> int:
    return max(MIN_PX, int(round(mm / 25.4 * dpi)))


def preset_size(key: str, dpi: int = 300):
    """(width, height) in pixels of a preset, or None for «view» and «custom»."""
    _k, _label, w, h = SIZE_BY_KEY.get(key, SIZE_BY_KEY["custom"])
    if w is None:
        return None
    if isinstance(w, str):
        return mm_to_px(float(w[:-2]), dpi), mm_to_px(float(h[:-2]), dpi)
    return w, h


def is_paper(key: str) -> bool:
    return isinstance(SIZE_BY_KEY.get(key, (None, None, None))[2], str)


def frame(width: int, out: dict, view_aspect: float) -> tuple:
    """(width, height) of the final picture: the 3D view's shape from ``width``, or the
    output's own size."""
    out = clean(out)
    if out["size"] == "view":
        w = max(MIN_PX, min(MAX_PX, int(width)))
        w, h = w, max(2, round(w / max(0.05, view_aspect)))
    elif out["size"] == "custom":
        w, h = max(MIN_PX, min(MAX_PX, int(width))), out["height"]
    else:
        w, h = preset_size(out["size"], out["dpi"])
        w, h = min(MAX_PX, w), min(MAX_PX, h)
    if out["projection"] == "360":                     # all round: twice as wide as high
        h = max(2, w // 2)
    return w, h


def aspect(width: int, out: dict, view_aspect: float) -> float:
    w, h = frame(width, out, view_aspect)
    return w / max(1, h)


def describe(w: int, h: int, dpi: int) -> str:
    """«1920 × 1080 px · 2.1 MP · 16:9 · 16.3 × 9.1 cm at 300 dpi»."""
    from math import gcd
    g = gcd(w, h) or 1
    ratio = f"{w // g}:{h // g}" if max(w // g, h // g) <= 32 else f"{w / h:.2f}:1"
    cm = (w / dpi * 2.54, h / dpi * 2.54)
    return tr("{w} × {h} px · {mp:.1f} MP · {ratio} · {cw:.1f} × {ch:.1f} cm at {dpi} dpi",
              w=w, h=h, mp=w * h / 1e6, ratio=ratio, cw=cm[0], ch=cm[1], dpi=dpi)


def blender_settings(out: dict) -> dict:
    """What the job's ``studio["output"]`` carries for Blender."""
    out = clean(out)
    _label, ext, settings, alpha, _retouch = FORMATS[out["format"]]
    s = dict(settings)
    if out["format"] == "jpeg":
        s["quality"] = out["jpeg_quality"]
    s["color_mode"] = "RGBA" if out["transparent"] and alpha else "RGB"
    return {"format": out["format"], "extension": ext, "image_settings": s,
            "transparent": out["transparent"] and alpha, "projection": out["projection"], "angle": out["angle"]}


def extension(fmt: str) -> str:
    return FORMATS.get(fmt, FORMATS["png"])[1]


def retouchable(fmt: str) -> bool:
    """Whether the preview window's retouching can be saved in that format (8 bits)."""
    return FORMATS.get(fmt, FORMATS["png"])[4]


DEFAULT_PATTERN = "renderStudio-{date}"
#: …and for several scenes at once, which need telling apart.
DEFAULT_SCENES_PATTERN = "renderStudio-{date}-{scene}"
#: The names that were the default before: kept as they were stored, they give way to the new one.
OLD_DEFAULTS = ("{document}-{look}-{date}", "{document}-{scene}-{date}")


def save_name(stamp: str = "") -> str:
    """The name a render is saved under (without its extension): renderStudio-date-time."""
    import time
    return DEFAULT_PATTERN.replace("{date}", stamp or time.strftime("%Y%m%d-%H%M%S"))


def file_name(pattern: str, document: str, look: str, stamp: str, ext: str, scene: str = "view") -> str:
    """A file name from ``pattern`` ({document} {scene} {look} {date}), safe for any system. ``scene``: the name of
    the scene being rendered («view» for the current view)."""
    import re
    name = (pattern or DEFAULT_PATTERN).replace("{document}", document or "render").replace("{scene}", scene or "view") \
        .replace("{look}", look or "").replace("{date}", stamp)
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" .-_") or "render"
    return name + ext
