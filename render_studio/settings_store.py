# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Studio's settings, as they are kept in the IngeTrazo document.

They live in the document's own data (``scene.plugin_data["render_studio"]``,
saved in the .igz) so the look travels with the drawing and anything else that
reads the document, such as IngeTrazo's own Blender render, can read it. The
format is a public contract; ``version`` goes up if it ever changes::

    plugin_data["render_studio"] = {
      "materials": { "<IngeTrazo material name>": {render settings of that material} },
      "settings": {
        "version": 1,
        "look": "clear",                 # clear partly_cloudy golden_hour overcast
                                         # white_model interior night
        "engine": "eevee",               # or "cycles"
        "quality": 1,                    # 0 draft, 1 medium, 2 high
        "width": 1920,                   # pixels; the height follows the 3D view
        "ground": true,                  # the generated ground under the model
        "sliders": {                     # the panel's sliders
          "exposure_bias": 0.0,          # stops (EV)
          "clouds": 0.25,                # 0..1
          "sun_scale": 1.0,              # multiple of the look's sun
          "warmth": 0.0,                 # -1..1
          "saturation": 1.06,            # multiple
          "vignette": 0.16 },
        "hdri": null,                    # or {"path": "...", "rotation": 0..360 degrees,
                                         #     "brightness": stops, "light": true|false}
        "output": {"size": "view", "height": 1080, "dpi": 300, "format": "png",
                   "jpeg_quality": 92, "transparent": false},      # see output.py
        "section": {"cap": true, "material": null, "light": "open"}   # see section.py
      } }

Pure Python: no Qt, so it can be tested and read by anything.
"""
from __future__ import annotations

from . import output, presets, section

VERSION = 1
ENGINES = ("eevee", "cycles")


def _num(value, lo, hi, default):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:                                        # NaN
        return default
    return max(lo, min(hi, v))


def clean(raw) -> dict | None:
    """A trusted copy of ``raw`` (whatever a document holds), or None when
    it holds nothing usable. Unknown looks and engines fall back; numbers are
    clamped to the ranges the panel offers."""
    if not isinstance(raw, dict) or not raw:
        return None
    look = raw.get("look")
    sliders_in = raw.get("sliders") if isinstance(raw.get("sliders"), dict) else {}
    sliders = {}
    for key, (_label, lo, hi, _default, _unit) in presets.SLIDERS.items():
        if key in sliders_in and sliders_in[key] is not None:
            sliders[key] = _num(sliders_in[key], lo, hi, None)
            if sliders[key] is None:
                del sliders[key]
    out = {
        "version": VERSION,
        "look": look if look in presets.PRESETS else "clear",
        "engine": raw.get("engine") if raw.get("engine") in ENGINES else "eevee",
        "quality": int(_num(raw.get("quality"), 0, 2, 1)),
        "width": int(_num(raw.get("width"), 320, 16384, 1920)),
        "ground": bool(raw.get("ground", True)),
        "sliders": sliders,
        "hdri": None,
        "output": output.clean(raw.get("output")),
        "section": section.clean(raw.get("section")),
    }
    h = raw.get("hdri")
    if isinstance(h, dict) and isinstance(h.get("path"), str) and h["path"]:
        out["hdri"] = {"path": h["path"],
                       "rotation": _num(h.get("rotation"), 0.0, 360.0, 0.0),
                       "brightness": _num(h.get("brightness"), -3.0, 3.0, 0.0),
                       "light": bool(h.get("light", True))}
    return out


def read(plugin_data) -> dict | None:
    """The cleaned settings in a document's plugin data, or None."""
    block = (plugin_data or {}).get("render_studio") if isinstance(plugin_data, dict) else None
    return clean((block or {}).get("settings")) if isinstance(block, dict) else None
