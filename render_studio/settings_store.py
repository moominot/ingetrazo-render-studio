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
        "ground_shadow": true,           # with no ground: an invisible floor that only shows the model's shadow
        "ground_look": {"type": "", "color": null, "roughness": 0.9, "haze": 1.0, "offset": 0.0, "grass_radius": 0.0, "ground_radius": 0.0},
                                         # the ground's type (see presets.GROUND_TYPES), its colour (null: the look's),
                                         # roughness 0..1, horizon haze (multiple of the usual distance, 0 = none)
                                         # and height offset in metres; ground_radius: metres of generated ground (0 = a very large
                                         # one), which also sets how far the haze melts it into the horizon;
                                         # grass_radius: metres of grass round the model when the ground's material is
                                         # grass (0 = the model's farthest point plus 10 m)
        "style": {"mode": "none", "width": 0, "color": [r, g, b], "material": "", "model_color": [r, g, b], "lux_max": 0,
                  "noise": 0.5, "extend": 0.4, "wetness": 0.5, "paper": 0.5, "edges": 0.4},
                                         # none | white | model | light | sketch | watercolour, see style()
        "skyline": {"type": "", "height": 4.0, "distance": 0.0, "seed": 1, "color": null},
                                         # distant mountains, hills, forest or city that hide the line between ground and sky
        "ground_material": null,         # or {"name": "<model material>", "tile": metres (0 = the picture's own size)}
        "sliders": {                     # the panel's sliders
          "exposure_bias": 0.0,          # stops (EV)
          "clouds": 0.25,                # 0..1
          "sun_scale": 1.0,              # multiple of the look's sun
          "warmth": 0.0,                 # -1..1
          "saturation": 1.06,            # multiple
          "vignette": 0.16 },
        "hdri": null,                    # or {"path": "...", "rotation": 0..360 degrees,
                                         #     "brightness": stops, "height": metres (0.5..30, default 2.5),
                                         #     "light": true|false}
        "backdrop": null,                # or {"path": "...", "fit": "fill"|"fit"|"stretch", "brightness": stops};
                                         #     one flat picture behind the model (not with a 360° one)
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


def _colour(v, default):
    try:
        c = [max(0.0, min(1.0, float(x))) for x in v][:3]
        return c if len(c) == 3 else list(default)
    except (TypeError, ValueError):
        return list(default)


def flat(raw) -> dict | None:
    """The plain-colour background, cleaned: ``color`` (sRGB 0..1); None: none."""
    if not isinstance(raw, dict):
        return None
    return {"color": _colour(raw.get("color"), [1.0, 1.0, 1.0])}


def shadows(raw, old_style=None) -> dict:
    """How the shadows are drawn, cleaned (see presets.SHADOW_DEFAULT). A document that kept a sketch's hatching in its style
    (``old_style``) and says nothing of shadows brings it here; its colour was the outlines', in linear light."""
    d = dict(presets.SHADOW_DEFAULT)
    if not isinstance(raw, dict):
        if not (isinstance(old_style, dict) and old_style.get("mode") == "sketch" and old_style.get("hatch") in presets.SHADOW_DRAWS):
            return d
        linear = _colour(old_style.get("color"), presets.STYLE_DEFAULT["color"])
        raw = {"draw": old_style["hatch"], "opacity": old_style.get("hatch_opacity", 0.7),
               "spacing": old_style.get("hatch_spacing"), "angle": old_style.get("hatch_angle"),
               "color": [12.92 * c if c <= 0.0031308 else 1.055 * c ** (1.0 / 2.4) - 0.055 for c in linear]}
    d["draw"] = raw.get("draw") if raw.get("draw") in presets.SHADOW_DRAWS else "render"
    d["color"] = _colour(raw.get("color"), presets.SHADOW_DEFAULT["color"])
    for key, lo, hi in (("opacity", 0.05, 1.0), ("spacing", 3.0, 60.0), ("angle", 0.0, 180.0)):
        d[key] = _num(raw.get(key), lo, hi, presets.SHADOW_DEFAULT[key])
    return d


def style(raw) -> dict:
    """The render's style, cleaned: ``mode`` (none, white, model, light, sketch, watercolour), the outlines every style can have
    (``width`` in pixels, 0 = none, and ``color``) and what each adds: the model's ``material`` (a name; "" = ``model_color``), the
    lux scale's top (``lux_max``, 0 = from the picture), the sketch's ``noise`` (irregular stroke) and ``extend`` (lines run past their
    corners), the watercolour's ``wetness``, ``paper`` and ``edges``."""
    d = dict(presets.STYLE_DEFAULT)
    if not isinstance(raw, dict):
        return d
    d["mode"] = raw.get("mode") if raw.get("mode") in presets.STYLES else "none"
    d["width"] = _num(raw.get("width"), 0.0, 4.0, 0.0)
    d["color"] = _colour(raw.get("color"), presets.STYLE_DEFAULT["color"])
    m = raw.get("material")
    d["material"] = m.strip()[:120] if isinstance(m, str) else ""
    d["model_color"] = _colour(raw.get("model_color"), presets.STYLE_DEFAULT["model_color"])
    d["lux_max"] = _num(raw.get("lux_max"), 0.0, 1e6, 0.0)
    for key in ("noise", "extend", "wetness", "paper", "edges"):
        d[key] = _num(raw.get(key), 0.0, 1.0, presets.STYLE_DEFAULT[key])
    d["base"] = bool(raw.get("base", True))
    return d


def skyline(raw) -> dict:
    """The distant skyline (mountains, hills, forest, city), cleaned: ``type`` ("" = none), the angle the tallest peaks
    reach above the horizon (°), the distance of its farthest layer (m, 0 = from the ground), a seed for its shape and a
    colour of its own (None: the type's)."""
    d = dict(presets.SKYLINE_DEFAULT)
    if not isinstance(raw, dict):
        return d
    d["type"] = raw.get("type") if raw.get("type") in presets.SKYLINE_TYPES else ""
    d["height"] = _num(raw.get("height"), 0.5, 20.0, 4.0)
    d["distance"] = _num(raw.get("distance"), 0.0, 20000.0, 0.0)
    d["seed"] = int(_num(raw.get("seed"), 0, 9999, 1))
    c = raw.get("color")
    try:
        c = [max(0.0, min(1.0, float(x))) for x in c][:3]
        d["color"] = c if len(c) == 3 else None
    except (TypeError, ValueError):
        d["color"] = None
    return d


def ground_look(raw) -> dict:
    """The ground's own look (type, colour, roughness, haze, offset), cleaned."""
    d = dict(presets.GROUND_DEFAULT)
    if not isinstance(raw, dict):
        return d
    d["type"] = raw.get("type") if raw.get("type") in presets.GROUND_TYPES or raw.get("type") == "custom" else ""
    c = raw.get("color")
    try:
        c = [max(0.0, min(1.0, float(x))) for x in c][:3]
        d["color"] = c if len(c) == 3 else None
    except (TypeError, ValueError):
        d["color"] = None
    d["roughness"] = _num(raw.get("roughness"), 0.0, 1.0, 0.9)
    d["haze"] = _num(raw.get("haze"), 0.0, 4.0, 1.0)
    d["offset"] = _num(raw.get("offset"), -10.0, 10.0, 0.0)
    d["grass_radius"] = _num(raw.get("grass_radius"), 0.0, 500.0, 0.0)
    d["ground_radius"] = _num(raw.get("ground_radius"), 0.0, 5000.0, 0.0)
    return d


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
        "ground_shadow": bool(raw.get("ground_shadow", True)),
        "sliders": sliders,
        "ground_look": ground_look(raw.get("ground_look")),
        "skyline": skyline(raw.get("skyline")),
        "style": style(raw.get("style")),
        "shadows": shadows(raw.get("shadows"), raw.get("style")),
        "ground_material": None,
        "hdri": None,
        "backdrop": None,
        "flat": flat(raw.get("flat")),
        "output": output.clean(raw.get("output")),
        "section": section.clean(raw.get("section")),
    }
    g = raw.get("ground_material")
    if isinstance(g, dict) and isinstance(g.get("name"), str) and g["name"]:
        out["ground_material"] = {"name": g["name"][:120], "tile": _num(g.get("tile"), 0.0, 100.0, 0.0)}
    h = raw.get("hdri")
    if isinstance(h, dict) and isinstance(h.get("path"), str) and h["path"]:
        out["hdri"] = {"path": h["path"],
                       "rotation": _num(h.get("rotation"), 0.0, 360.0, 0.0),
                       "brightness": _num(h.get("brightness"), -3.0, 3.0, 0.0),
                       "height": _num(h.get("height"), 0.5, 30.0, 2.5),
                       "light": bool(h.get("light", True))}
    b = raw.get("backdrop")
    if isinstance(b, dict) and isinstance(b.get("path"), str) and b["path"] and not out["hdri"]:
        out["backdrop"] = {"path": b["path"],
                           "fit": b.get("fit") if b.get("fit") in ("fill", "fit", "stretch") else "fill",
                           "brightness": _num(b.get("brightness"), -3.0, 3.0, 0.0)}
    return out


def read(plugin_data) -> dict | None:
    """The cleaned settings in a document's plugin data, or None."""
    block = (plugin_data or {}).get("render_studio") if isinstance(plugin_data, dict) else None
    return clean((block or {}).get("settings")) if isinstance(block, dict) else None
