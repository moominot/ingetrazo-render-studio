# SPDX-License-Identifier: GPL-3.0-or-later
"""The active section plane, for the render.

IngeTrazo's section is display-only: the geometry is untouched and the viewer clips it
(core/section.py), so the model file written for Blender holds the whole model. The job
carries the plane and ``blender/studio_scene.py`` cuts the meshes with it.

The options (the Section tab) are kept in the document, ``settings["section"]``::

    {"cap": true,            # close the cut with a flat face
     "material": "Formigó",  # the document's material the cap is made of (None: plain grey)
     "light": "open"}        # "open": the removed part is gone, light enters the cut
                             # "blocked": it still blocks the light (invisible to the camera)

Pure Python: no Qt.
"""
from __future__ import annotations

import json

LIGHTS = ("open", "blocked")
DEFAULT = {"cap": True, "material": None, "light": "open"}
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
    return out


def job_block(scene, opts: dict | None = None) -> dict | None:
    """The plane cutting the model, with the options, as ``studio_scene.clip_section``
    reads it: ``point``, ``normal`` (the normal's side is the one that disappears),
    ``cap``, ``color``, ``light``. None when nothing is cut."""
    try:
        plane = scene.active_section()
    except Exception:  # noqa: BLE001 - an old IngeTrazo: no sections
        return None
    if plane is None or not getattr(scene, "show_section_cuts", True):
        return None                       # no plane, or its cut switched off (View > Section Cuts)
    o = clean(opts)
    p, n = plane.point, plane.normal
    block = {"point": [float(p.x()), float(p.y()), float(p.z())],
             "normal": [float(n.x()), float(n.y()), float(n.z())],
             "cap": o["cap"], "light": o["light"], "material": None,
             "color": list(FALLBACK_COLOR), "texture_size": None}
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
