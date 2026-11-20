# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Studio's lights: the four kinds Blender has, kept in the document.

No Qt widget and no Blender here: the format, its cleaning, the units, the
lights that ride on a component, and the block the render job carries.

Where they live
---------------
* **Free lights**, in world metres: ``scene.plugin_data["render_studio"]["lights"]``.
* **Lights on an object** (a floor lamp, a wall light): in that group's own
  data, ``group.ext["render_studio"]["lights"]``, in the group's own axes
  (``core.group.group_frame``). Moving, rotating or copying the object takes
  its lights along; a copy of a component carries them too.
* **The Render tab's lights** (IngeTrazo's own point lights and spots) are
  read as they are and rendered too; the editor can convert them.

One light
---------
::

    {"id": "a1b2c3d4", "name": "", "type": "point" | "spot" | "area" | "sun",
     "on": true,
     "pos": [x, y, z],              # metres (the object's axes for one on an object)
     "dir": [dx, dy, dz],           # where it shines (spot, area, sun)
     "spin": 0.0,                   # degrees about "dir" (turns an area's rectangle)
     "unit": "W" | "lm",            # Blender watts or lumens; a sun is always W/m²
     "power": 800.0,
     "kelvin": 2700,                # or null: then "color" [r, g, b] 0..1
     "color": [1.0, 0.8, 0.6],
     "radius": 0.05,                # point/spot: the bulb's size (soft shadows)
     "spot_angle": 60.0, "spot_blend": 0.25,
     "shape": "rectangle",          # area: square, rectangle, disk, ellipse
     "size": 1.2, "size_y": 0.3,    # area: metres
     "spread": 180.0,               # area: how wide it spreads (Cycles)
     "sun_angle": 0.53,             # sun: its disc, degrees
     "shadow": true,
     "ies": ""}                     # an .ies profile (point/spot/area; Cycles only)
"""
from __future__ import annotations

import copy
import math
import os
import uuid

KEY = "render_studio"
TYPES = ("point", "spot", "area", "sun")
SHAPES = ("square", "rectangle", "disk", "ellipse")
UNITS = ("W", "lm")
MIN_KELVIN, MAX_KELVIN = 1000, 12000
DEFAULT_KELVIN = 2700

#: Lumens per Blender watt for a white light. Blender's watts are radiant,
#: not a bulb's electrical watts; its manual's table puts an 800 lm LED bulb
#: at 2.1 W (≈ 381 lm/W) and a 1000 lm bulb at 2.9 W (≈ 345). The first is
#: used: a conversion to start from, not a photometric truth.
LM_PER_W = 381.0

#: What a new light of each kind starts with.
DEFAULTS = {
    "point": {"unit": "lm", "power": 800.0, "kelvin": 2700, "radius": 0.05},
    "spot": {"unit": "lm", "power": 700.0, "kelvin": 3000, "radius": 0.03,
             "spot_angle": 40.0, "spot_blend": 0.25},
    "area": {"unit": "lm", "power": 3600.0, "kelvin": 4000, "shape": "square",
             "size": 0.6, "size_y": 0.6, "spread": 180.0},
    "sun": {"unit": "W", "power": 3.0, "kelvin": 5500, "sun_angle": 0.53},
}

#: Ready-made lights: (key, type, label, settings over the type's defaults).
PRESETS = (
    ("candle", "point", "Candle (12 lm)", {"power": 12.0, "kelvin": 1850, "radius": 0.01}),
    ("bulb", "point", "Bulb, 800 lm (≈ 60 W)", {"power": 800.0, "kelvin": 2700, "radius": 0.04}),
    ("bulb_big", "point", "Bulb, 1500 lm (≈ 100 W)", {"power": 1500.0, "kelvin": 2700, "radius": 0.05}),
    ("lantern", "point", "Garden lantern, 300 lm", {"power": 300.0, "kelvin": 2200, "radius": 0.08}),
    ("downlight", "spot", "Downlight, 700 lm, 40°", {"power": 700.0, "kelvin": 3000, "spot_angle": 40.0,
                                                    "spot_blend": 0.3, "radius": 0.03}),
    ("track", "spot", "Track spot, 1000 lm, 24°", {"power": 1000.0, "kelvin": 3000, "spot_angle": 24.0,
                                                  "spot_blend": 0.2, "radius": 0.02}),
    ("street", "spot", "Street lamp, 10 000 lm", {"power": 10000.0, "kelvin": 4000, "spot_angle": 130.0,
                                                 "spot_blend": 0.6, "radius": 0.15}),
    ("flood", "spot", "Floodlight, 5000 lm, 60°", {"power": 5000.0, "kelvin": 5000, "spot_angle": 60.0,
                                                  "spot_blend": 0.3, "radius": 0.1}),
    ("panel", "area", "LED panel 60×60, 3600 lm", {"power": 3600.0, "kelvin": 4000, "shape": "square",
                                                   "size": 0.6, "size_y": 0.6}),
    ("tube", "area", "Fluorescent tube 120 cm, 2500 lm", {"power": 2500.0, "kelvin": 4000,
                                                         "shape": "rectangle", "size": 1.2, "size_y": 0.04}),
    ("strip", "area", "LED strip 1 m, 1000 lm", {"power": 1000.0, "kelvin": 3000, "shape": "rectangle",
                                                "size": 1.0, "size_y": 0.01, "spread": 120.0}),
    ("window", "area", "Window fill (sky), 2×1.5 m", {"unit": "W", "power": 200.0, "kelvin": 7500,
                                                     "shape": "rectangle", "size": 2.0, "size_y": 1.5}),
    ("disk", "area", "Ceiling disc Ø 40 cm, 2000 lm", {"power": 2000.0, "kelvin": 3500, "shape": "disk",
                                                      "size": 0.4, "size_y": 0.4}),
    ("sun", "sun", "Extra sun, 3 W/m²", {"power": 3.0, "kelvin": 5500}),
    ("moon", "sun", "Moonlight, 0.05 W/m²", {"power": 0.05, "kelvin": 8000, "sun_angle": 0.52}),
)

PRESET_BY_KEY = {p[0]: p for p in PRESETS}


def new_id() -> str:
    return uuid.uuid4().hex[:8]


# ---- colour and units ---------------------------------------------------------------

def kelvin_to_rgb(kelvin: float) -> tuple:
    """The colour of a black body at ``kelvin`` (Tanner Helland's fit, the
    one IngeTrazo's Render tab uses), its brightest channel at 1."""
    t = max(1000.0, min(40000.0, float(kelvin))) / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * (t - 60) ** -0.1332047592
        g = 288.1221695283 * (t - 60) ** -0.0755148492
        b = 255.0
    rgb = [max(0.0, min(255.0, c)) / 255.0 for c in (r, g, b)]
    top = max(rgb) or 1.0
    return tuple(round(c / top, 4) for c in rgb)


def cone_solid_angle(angle_deg: float) -> float:
    """Solid angle (sr) of a cone ``angle_deg`` wide (full angle)."""
    half = math.radians(max(1.0, min(180.0, float(angle_deg)))) / 2.0
    return 2.0 * math.pi * (1.0 - math.cos(half))


def blender_watts(light: dict) -> float:
    """The light's power as Blender's ``energy``.

    Lumens become watts at :data:`LM_PER_W`. A Blender spot is a point
    light with a mask: its cone does not gather the power, so the lumens of a
    spot (what leaves through its cone) are spread back over the whole sphere
    — a narrow 700 lm downlight is as bright in its beam as the lumens say.
    A sun is W/m² already."""
    p = max(0.0, float(light.get("power", 0.0)))
    kind = light.get("type", "point")
    if kind == "sun" or light.get("unit", "W") != "lm":
        return p
    w = p / LM_PER_W
    if kind == "spot":
        w *= 4.0 * math.pi / cone_solid_angle(light.get("spot_angle", 60.0))
    return w


def lumens(light: dict) -> float | None:
    """The light's lumens (None for a sun): the inverse of :func:`blender_watts`."""
    kind = light.get("type", "point")
    if kind == "sun":
        return None
    p = max(0.0, float(light.get("power", 0.0)))
    if light.get("unit") == "lm":
        return p
    lm = p * LM_PER_W
    if kind == "spot":
        lm *= cone_solid_angle(light.get("spot_angle", 60.0)) / (4.0 * math.pi)
    return lm


def convert_unit(light: dict, unit: str) -> dict:
    """The same light, its power given in ``unit`` (it shines the same)."""
    if unit not in UNITS or light.get("type") == "sun" or light.get("unit") == unit:
        return dict(light)
    out = dict(light, unit=unit)
    if unit == "lm":
        out["power"] = round(lumens(light), 3)
    else:
        out["power"] = round(blender_watts(light), 4)
    return out


def power_label(light: dict) -> str:
    if light.get("type") == "sun":
        return f"{light.get('power', 0):g} W/m²"
    if light.get("unit") == "lm":
        return f"{light.get('power', 0):,.0f} lm".replace(",", " ")
    return f"{light.get('power', 0):g} W"


# ---- directions ---------------------------------------------------------------------

def aim_from_angles(heading_deg: float, tilt_deg: float) -> list:
    """A direction from its heading (0° = north, +Y, clockwise) and its tilt
    below the horizon (90° = straight down) — as the Render tab's spots."""
    h, t = math.radians(heading_deg), math.radians(tilt_deg)
    return [round(math.cos(t) * math.sin(h), 6), round(math.cos(t) * math.cos(h), 6),
            round(-math.sin(t), 6)]


def angles_from_aim(d) -> tuple:
    x, y, z = (float(v) for v in d)
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    tilt = math.degrees(math.asin(max(-1.0, min(1.0, -z / n))))
    heading = math.degrees(math.atan2(x, y)) % 360.0 if math.hypot(x, y) > 1e-9 else 0.0
    return round(heading, 1), round(tilt, 1)


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v] if n > 1e-12 else [0.0, 0.0, -1.0]


# ---- cleaning -----------------------------------------------------------------------

def _num(v, lo, hi, default):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return max(lo, min(hi, f))


def _vec(v, default):
    try:
        out = [float(c) for c in v][:3]
    except (TypeError, ValueError):
        return list(default)
    if len(out) != 3 or not all(math.isfinite(c) for c in out):
        return list(default)
    return out


def new_light(kind: str, pos=(0.0, 0.0, 0.0), **over) -> dict:
    """A fresh light of ``kind`` at ``pos`` (cleaned)."""
    kind = kind if kind in TYPES else "point"
    raw = {"type": kind, "pos": list(pos), "dir": [0.0, 0.0, -1.0]}
    raw.update(DEFAULTS[kind])
    raw.update(over)
    raw.setdefault("id", new_id())
    return clean_light(raw)


def from_preset(key: str, pos=(0.0, 0.0, 0.0), **over) -> dict:
    _k, kind, label, values = PRESET_BY_KEY[key]
    return new_light(kind, pos, **{**values, **over})


def clean_light(raw) -> dict | None:
    """One light as the format says, whatever a hand-edited or older file
    holds: unknown kinds are dropped (None), numbers clamped, ids kept."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("type", raw.get("kind", "point"))
    if kind not in TYPES:
        return None
    d = DEFAULTS[kind]
    unit = raw.get("unit", d["unit"])
    if kind == "sun" or unit not in UNITS:
        unit = "W"
    kelvin = raw.get("kelvin", d.get("kelvin", DEFAULT_KELVIN))
    color = None
    if kelvin is not None:
        kelvin = int(round(_num(kelvin, MIN_KELVIN, MAX_KELVIN, DEFAULT_KELVIN)))
        color = list(kelvin_to_rgb(kelvin))
    else:
        c = _vec(raw.get("color"), (1.0, 1.0, 1.0))
        color = [max(0.0, min(1.0, v)) for v in c]
    shape = raw.get("shape", d.get("shape", "square"))
    if shape not in SHAPES:
        shape = "square"
    ies = raw.get("ies") or ""
    out = {
        "id": str(raw.get("id") or new_id())[:32],
        "name": str(raw.get("name", ""))[:80],
        "type": kind,
        "on": bool(raw.get("on", True)),
        "pos": _vec(raw.get("pos"), (0.0, 0.0, 0.0)),
        "dir": _unit(_vec(raw.get("dir"), (0.0, 0.0, -1.0))),
        "spin": _num(raw.get("spin", 0.0), -360.0, 360.0, 0.0),
        "unit": unit,
        "power": _num(raw.get("power", d["power"]), 0.0, 1e7, d["power"]),
        "kelvin": kelvin,
        "color": color,
        "radius": _num(raw.get("radius", d.get("radius", 0.05)), 0.0, 10.0, 0.05),
        "spot_angle": _num(raw.get("spot_angle", d.get("spot_angle", 60.0)), 1.0, 180.0, 60.0),
        "spot_blend": _num(raw.get("spot_blend", d.get("spot_blend", 0.25)), 0.0, 1.0, 0.25),
        "shape": shape,
        "size": _num(raw.get("size", d.get("size", 0.6)), 0.001, 100.0, 0.6),
        "size_y": _num(raw.get("size_y", d.get("size_y", 0.6)), 0.001, 100.0, 0.6),
        "spread": _num(raw.get("spread", d.get("spread", 180.0)), 1.0, 180.0, 180.0),
        "sun_angle": _num(raw.get("sun_angle", d.get("sun_angle", 0.53)), 0.0, 90.0, 0.53),
        "shadow": bool(raw.get("shadow", True)),
        "ies": str(ies) if isinstance(ies, str) else "",
    }
    if shape == "square" or shape == "disk":
        out["size_y"] = out["size"]
    return out


def clean_lights(raw) -> list:
    """A list of lights, cleaned, with unique ids (a pasted duplicate gets a new one)."""
    out, seen = [], set()
    for lt in raw if isinstance(raw, list) else []:
        c = clean_light(lt)
        if c is None:
            continue
        if c["id"] in seen:
            c["id"] = new_id()
        seen.add(c["id"])
        out.append(c)
    return out


def from_render_tab(lt: dict, index: int) -> dict:
    """A light of IngeTrazo's Render tab (``core.render_blender.clean_lights``)
    in this format: its watts are Blender watts already."""
    kind = "spot" if lt.get("kind") == "spot" else "point"
    raw = {"id": f"rt{index}", "type": kind, "name": lt.get("name", ""), "on": lt.get("on", True),
           "pos": lt.get("pos"), "dir": lt.get("dir", (0.0, 0.0, -1.0)), "unit": "W",
           "power": lt.get("power", 400.0), "kelvin": lt.get("kelvin"), "color": lt.get("color"),
           "radius": 0.08, "spot_angle": lt.get("angle", 60.0), "spot_blend": 0.35}
    return clean_light(raw)


# ---- lights on an object ---------------------------------------------------------------

def _mat_rows(m):
    """A 4×4 matrix as rows of floats: a QMatrix4x4 (column-major ``data()``),
    nested lists, or None (identity)."""
    if m is None:
        return None
    if hasattr(m, "data") and callable(m.data):
        d = list(m.data())
        return [[d[c * 4 + r] for c in range(4)] for r in range(4)]
    return [list(map(float, row)) for row in m]


def _mul(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def map_point(m, p):
    if m is None:
        return [float(c) for c in p]
    x, y, z = p
    return [m[r][0] * x + m[r][1] * y + m[r][2] * z + m[r][3] for r in range(3)]


def map_vector(m, v):
    if m is None:
        return [float(c) for c in v]
    x, y, z = v
    return [m[r][0] * x + m[r][1] * y + m[r][2] * z for r in range(3)]


def invert(m):
    """Inverse of an affine 4×4 (rows); None stays None."""
    if m is None:
        return None
    a = [row[:3] for row in m[:3]]
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
           - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    if abs(det) < 1e-15:
        raise ValueError("a flat object has no axes to hold a light")
    inv = [[0.0] * 3 for _ in range(3)]
    for r in range(3):
        for c in range(3):
            r1, r2 = [i for i in range(3) if i != c]
            c1, c2 = [i for i in range(3) if i != r]
            minor = a[r1][c1] * a[r2][c2] - a[r1][c2] * a[r2][c1]
            inv[r][c] = ((-1) ** (r + c)) * minor / det
    t = [m[r][3] for r in range(3)]
    ti = [-sum(inv[r][k] * t[k] for k in range(3)) for r in range(3)]
    return [inv[0] + [ti[0]], inv[1] + [ti[1]], inv[2] + [ti[2]], [0.0, 0.0, 0.0, 1.0]]


def group_lights(group) -> list:
    ext = getattr(group, "ext", None) or {}
    block = ext.get(KEY) if isinstance(ext, dict) else None
    return clean_lights((block or {}).get("lights")) if isinstance(block, dict) else []


def to_world(light: dict, frame) -> dict:
    """A light in an object's axes (``frame`` rows, None = world) put in the world."""
    out = dict(light)
    out["pos"] = map_point(frame, light["pos"])
    out["dir"] = _unit(map_vector(frame, light["dir"]))
    return out


def to_local(light: dict, frame) -> dict:
    """The inverse of :func:`to_world`."""
    inv = invert(frame)
    out = dict(light)
    out["pos"] = [round(c, 6) for c in map_point(inv, light["pos"])]
    out["dir"] = [round(c, 6) for c in _unit(map_vector(inv, light["dir"]))]
    return out


def _frame_of(group, base):
    """The world matrix of a placement's own axes: its composed placement × its axes."""
    m = _mat_rows(getattr(group, "xform", None))
    world = _mul(base, m) if m is not None else base
    return world, _mul(world, _mat_rows(getattr(group, "axes", None)))


def _layer_shown(scene, layer):
    if not layer or not hasattr(scene, "layer"):
        return True
    try:
        ly = scene.layer(layer)
    except Exception:  # noqa: BLE001
        return True
    return ly is None or getattr(ly, "visible", True)


def iter_object_lights(scene):
    """``(group, path, frame, light)`` for every light on an object, its frame
    the world matrix of the object's axes. ``path`` is the uids from the
    top-level object down. Hidden objects and hidden tags give none."""
    def walk(group, base, path, inherited):
        if getattr(group, "hidden", False):
            return
        layer = getattr(group, "layer", None) or inherited
        if not _layer_shown(scene, layer):
            return
        world, frame = _frame_of(group, base)
        here = path + (getattr(group, "uid", str(id(group))),)
        for lt in group_lights(group):
            yield group, here, frame, lt
        for child in getattr(group, "children", None) or ():
            yield from walk(child, world, here, layer)

    for g in list(getattr(scene, "groups", None) or ()):
        yield from walk(g, None, (), None)


def find_group(scene, path):
    """The placement at ``path`` (uids from the top-level object down), or None."""
    level = list(getattr(scene, "groups", None) or ())
    found = None
    for uid in path:
        found = next((g for g in level if getattr(g, "uid", None) == uid), None)
        if found is None:
            return None
        level = list(getattr(found, "children", None) or ())
    return found


def frame_at(scene, path):
    """The world frame of the placement at ``path`` (the composed matrices)."""
    level = list(getattr(scene, "groups", None) or ())
    base, frame = None, None
    for uid in path:
        g = next((x for x in level if getattr(x, "uid", None) == uid), None)
        if g is None:
            return None
        base, frame = _frame_of(g, base)
        level = list(getattr(g, "children", None) or ())
    return frame


def siblings(scene, group):
    """The top-level copies of ``group``'s component (they share its mesh)."""
    if getattr(group, "xform", None) is None or not getattr(group, "component", True):
        return [group]
    mesh = group.mesh
    return [g for g in getattr(scene, "groups", None) or () if getattr(g, "mesh", None) is mesh]


# ---- every light of the document ---------------------------------------------------------

def free_lights(plugin_data) -> list:
    block = (plugin_data or {}).get(KEY) if isinstance(plugin_data, dict) else None
    return clean_lights((block or {}).get("lights")) if isinstance(block, dict) else []


def render_tab_lights(scene) -> list:
    """The Render tab's lights in this format (ids ``rt0``, ``rt1``…)."""
    raw = (getattr(scene, "plugin_data", {}) or {}).get("render_blender") or {}
    try:
        from core import render_blender as rb
        lts = rb.clean_lights(list(raw.get("lights") or []))
    except Exception:  # noqa: BLE001 - an old or odd document, or no IngeTrazo: none
        return []
    return [c for c in (from_render_tab(lt, i) for i, lt in enumerate(lts)) if c is not None]


def all_lights(scene) -> list:
    """Every light, in the world: ``[{"key", "source", "light", "world", "group"}]``.

    ``key``: ``("free", id)``, ``("object", path, id)`` or ``("tab", index)`` —
    what the editor and the viewport name a light by."""
    out = []
    for lt in free_lights(getattr(scene, "plugin_data", None)):
        out.append({"key": ("free", lt["id"]), "source": "free", "light": lt, "world": lt, "group": None})
    for group, path, frame, lt in iter_object_lights(scene):
        out.append({"key": ("object", path, lt["id"]), "source": "object", "light": lt,
                    "world": to_world(lt, frame), "group": group})
    for i, lt in enumerate(render_tab_lights(scene)):
        out.append({"key": ("tab", i), "source": "tab", "light": lt, "world": lt, "group": None})
    return out


def job_block(scene) -> list:
    """The lights switched on, in the world, as ``studio_scene.add_studio_lights``
    reads them: the format above plus ``"energy"`` (Blender's) and ``"ies"``
    only when the file exists."""
    out = []
    for entry in all_lights(scene):
        lt = dict(entry["world"])
        if not lt["on"] or lt["power"] <= 0.0:
            continue
        lt["energy"] = blender_watts(lt)
        if lt["ies"] and (lt["type"] == "sun" or not os.path.isfile(lt["ies"])):
            lt["ies"] = ""
        lt["source"] = entry["source"]
        out.append(lt)
    return out


def signature(scene) -> str:
    """What the render's lights depend on (for the live view)."""
    import json
    try:
        return json.dumps(job_block(scene), sort_keys=True)
    except Exception:  # noqa: BLE001
        return ""


# ---- edits --------------------------------------------------------------------------------

def with_lights(ext, lights) -> dict | None:
    """``group.ext`` with these lights (None when nothing is left in it)."""
    ext = copy.deepcopy(ext) if isinstance(ext, dict) else {}
    block = dict(ext.get(KEY) or {}) if isinstance(ext.get(KEY), dict) else {}
    if lights:
        block["lights"] = copy.deepcopy(lights)
    else:
        block.pop("lights", None)
    if block:
        ext[KEY] = block
    else:
        ext.pop(KEY, None)
    return ext or None
