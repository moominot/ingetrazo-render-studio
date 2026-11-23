# SPDX-License-Identifier: GPL-3.0-or-later
"""The active section plane, for the render.

IngeTrazo's section is display-only: the geometry is untouched and the viewer clips it
(core/section.py), so the model file written for Blender holds the whole model. The job
carries the plane and ``blender/studio_scene.py`` cuts the meshes with it.

The options (the Section tab) are kept in the document, ``settings["section"]``::

    {"cap": true,            # close the cut with a flat face
     "style": "material",    # the cap is made of: "material" (of the drawing), "flat" (one colour),
                             # "hatch" (a pattern of lines or dots over a colour) or "drawing": as IngeTrazo fills the
                             # cut itself (each plane's or box's own fill, else the style's Section Fill)
     "material": "Formigó",  # style "material": the document's material (None: plain grey)
     "color": [r, g, b],     # styles "flat" and "hatch": the colour (the ground of a hatch)
     "pattern": "diagonal",  # style "hatch": diagonal, cross, grid, dots
     "line": [r, g, b],      # style "hatch": the colour of the lines or dots
     "spacing": 0.1,         # style "hatch": metres between lines
     "shadows": true,        # false: the cap neither casts nor receives shadows (flat, as drawn)
     "outline": true,        # the rim of the cap is drawn (a line, apart from the outlines of the model)
     "outline_color": [r, g, b],   # its colour (sRGB, as the picture shows it)
     "outline_width": 2.4,   # its thickness, in pixels of the final picture
     "light": "open"}        # "open": the removed part is gone, light enters the cut
                             # "blocked": it still blocks the light (invisible to the camera)

Pure Python: no Qt.
"""
from __future__ import annotations

import json

LIGHTS = ("open", "blocked")
STYLES = ("material", "flat", "hatch", "drawing")
PATTERNS = ("diagonal", "cross", "grid", "dots")
DEFAULT = {"cap": True, "style": "material", "material": None, "color": [0.35, 0.37, 0.41],
           "pattern": "diagonal", "line": [0.1, 0.1, 0.1], "spacing": 0.1, "shadows": True, "light": "open",
           "outline": True, "outline_color": [0.05, 0.05, 0.05], "outline_width": 2.4}
#: IngeTrazo's default colour for a cut's fill (core/section.py's style).
FALLBACK_COLOR = (0.35, 0.37, 0.41)


def clean(raw) -> dict:
    """A trusted copy of the options in ``raw`` (anything a document holds)."""
    out = dict(DEFAULT)
    if not isinstance(raw, dict):
        return out
    out["cap"] = bool(raw.get("cap", True))
    out["light"] = raw.get("light") if raw.get("light") in LIGHTS else "open"
    m = raw.get("material")
    out["material"] = m.strip() if isinstance(m, str) and m.strip() else None
    out["style"] = raw.get("style") if raw.get("style") in STYLES else "material"
    out["pattern"] = raw.get("pattern") if raw.get("pattern") in PATTERNS else "diagonal"
    out["color"] = _rgb(raw.get("color"), DEFAULT["color"])
    out["line"] = _rgb(raw.get("line"), DEFAULT["line"])
    try:
        sp = float(raw.get("spacing", 0.1))
    except (TypeError, ValueError):
        sp = 0.1
    out["spacing"] = max(0.005, min(5.0, sp)) if sp == sp else 0.1
    out["shadows"] = bool(raw.get("shadows", True))
    out["outline"] = bool(raw.get("outline", True))
    out["outline_color"] = _rgb(raw.get("outline_color"), DEFAULT["outline_color"])
    try:
        ow = float(raw.get("outline_width", DEFAULT["outline_width"]))
    except (TypeError, ValueError):
        ow = DEFAULT["outline_width"]
    out["outline_width"] = max(0.3, min(20.0, ow)) if ow == ow else DEFAULT["outline_width"]
    return out


def _rgb(v, default) -> list:
    try:
        c = [float(x) for x in v][:3]
        if len(c) == 3 and all(x == x for x in c):
            return [max(0.0, min(1.0, x)) for x in c]
    except (TypeError, ValueError):
        pass
    return list(default)


def plane_objects(scene) -> list:
    """IngeTrazo's cutting planes now, as it holds them: the active section plane and, in 0.6.3, the six faces of the active section box
    (``core.section.cut_planes``); the plane alone in an IngeTrazo without boxes. ``[]`` when nothing cuts (or Section Cuts is off)."""
    if not getattr(scene, "show_section_cuts", True):
        return []
    try:
        from core.section import cut_planes
        return list(cut_planes(scene))
    except Exception:  # noqa: BLE001 - an IngeTrazo without section boxes
        try:
            plane = scene.active_section()
        except Exception:  # noqa: BLE001 - an old IngeTrazo: no sections
            return []
        return [plane] if plane is not None else []


def describe(scene) -> str:
    """What cuts the render now, as a key the Section tab words: "plane", "box", "both", "off" (Section Cuts is switched off) or "none"."""
    plane = box = None
    try:
        plane = scene.active_section()
    except Exception:  # noqa: BLE001
        pass
    try:
        box = scene.active_section_box()
    except Exception:  # noqa: BLE001 - no section boxes in this IngeTrazo
        pass
    if not getattr(scene, "show_section_cuts", True) and (plane is not None or box is not None):
        return "off"
    if plane is not None and box is not None:
        return "both"
    return "plane" if plane is not None else ("box" if box is not None else "none")


def drawing_fill(plane, scene) -> dict | None:
    """The fill IngeTrazo gives the cut of ``plane`` (its own, else the style's Section Fill: ``core.section.effective_fill``) as the render's
    cap options: ``{"cap", "style", "color", "pattern", "line", "spacing", "texture_size"}``. «Solid» and «each layer with its own hatch» are
    a flat colour; a hatch or cross hatch is lines of the fill's colour over a pale ground of it; «none» is an open cut. None when this
    IngeTrazo does not say."""
    try:
        from core.section import effective_fill
        pattern, color, spacing = effective_fill(plane, getattr(scene, "display_style", None))
    except Exception:  # noqa: BLE001
        return None
    rgb = [max(0.0, min(1.0, float(c))) for c in list(color)[:3]]
    if pattern == "none":
        return {"cap": False}
    if pattern in ("hatch", "cross"):
        pale = [round(0.85 + 0.15 * c, 4) for c in rgb]
        return {"cap": True, "style": "hatch", "color": pale, "pattern": "diagonal" if pattern == "hatch" else "cross", "line": rgb,
                "spacing": max(0.005, float(spacing)), "texture_size": [1.0, 1.0]}
    return {"cap": True, "style": "flat", "color": rgb}


def job_block(scene, opts: dict | None = None) -> dict | None:
    """The cut, with the options, as ``studio_scene.clip_section`` reads it: ``planes`` (the active plane and the faces of the active box,
    each ``point`` and ``normal`` — the normal's side is the one that disappears — and, with the cap «like the drawing», the plane's own
    cap options), and the first plane's ``point``, ``normal`` besides, then ``cap``, ``color``, ``light``. None when nothing is cut."""
    cutting = plane_objects(scene)
    if not cutting:
        return None                       # no plane or box, or their cut switched off (View > Section Cuts)
    o = clean(opts)
    plane = cutting[0]
    p, n = plane.point, plane.normal
    block = {"point": [float(p.x()), float(p.y()), float(p.z())],
             "normal": [float(n.x()), float(n.y()), float(n.z())],
             "cap": o["cap"], "light": o["light"], "material": None, "style": o["style"],
             "shadows": o["shadows"], "color": list(FALLBACK_COLOR), "texture_size": None}
    block["planes"] = []
    for pl in cutting:
        pp, nn = pl.point, pl.normal
        entry = {"point": [float(pp.x()), float(pp.y()), float(pp.z())], "normal": [float(nn.x()), float(nn.y()), float(nn.z())]}
        if o["style"] == "drawing":
            entry.update(drawing_fill(pl, scene) or {})
        block["planes"].append(entry)
    if o["style"] == "drawing":
        block["style"] = "flat"           # (what a plane says nothing about)
        return block
    if o["style"] in ("flat", "hatch"):
        block["color"] = list(o["color"])
        if o["style"] == "hatch":
            block.update(pattern=o["pattern"], line=list(o["line"]), spacing=o["spacing"], texture_size=[1.0, 1.0])
        return block                                  # (the pattern is made in metres: uv = metres)
    name = o["material"]
    mat = (getattr(scene, "materials", None) or {}).get(name) if name else None
    if mat is not None:
        from .materials import export_name
        block["material"] = export_name(name)       # the model's own Blender material, when it wears it
        if getattr(mat, "color", None) is not None:
            block["color"] = [float(c) for c in mat.color[:3]]
        tex = getattr(mat, "texture", None) or {}
        try:
            block["texture_size"] = [float(tex.get("sw") or 1.0), float(tex.get("sh") or 1.0)] if tex else None
        except (TypeError, ValueError):
            block["texture_size"] = None
    return block


def signature(scene, opts: dict | None = None) -> str:
    """What the render depends on in the section (for the live view)."""
    return json.dumps(job_block(scene, opts), sort_keys=True)
