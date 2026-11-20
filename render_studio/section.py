# SPDX-License-Identifier: GPL-3.0-or-later
"""The active section plane, for the render.

IngeTrazo's section is display-only: the geometry is untouched and the viewer clips it
(core/section.py), so the model file written for Blender holds the whole model. The job
carries the plane and ``blender/studio_scene.py`` cuts the meshes with it.

The options (the Section tab) are kept in the document, ``settings["section"]``::

    {"cap": true,            # close the cut with a flat face
     "color": [r, g, b],     # of the cap; null: the cut's own fill colour in IngeTrazo
     "light": "open"}        # "open": the removed part is gone, light enters the cut
                             # "blocked": it still blocks the light (invisible to the camera)

Pure Python: no Qt.
"""
from __future__ import annotations

import json

LIGHTS = ("open", "blocked")
DEFAULT = {"cap": True, "color": None, "light": "open"}
#: IngeTrazo's default colour for a cut's fill (core/section.py's style).
FALLBACK_COLOR = (0.35, 0.37, 0.41)


def clean(raw) -> dict:
    """A trusted copy of the options in ``raw`` (anything a document holds)."""
    out = dict(DEFAULT)
    if not isinstance(raw, dict):
        return out
    out["cap"] = bool(raw.get("cap", True))
    out["light"] = raw.get("light") if raw.get("light") in LIGHTS else "open"
    c = raw.get("color")
    if isinstance(c, (list, tuple)) and len(c) == 3:
        try:
            out["color"] = [max(0.0, min(1.0, float(v))) for v in c]
        except (TypeError, ValueError):
            out["color"] = None
    return out


def job_block(scene, opts: dict | None = None) -> dict | None:
    """The plane cutting the model, with the options, as ``studio_scene.clip_section``
    reads it: ``point``, ``normal`` (the normal's side is the one that disappears),
    ``cap``, ``color``, ``light``. None when nothing is cut."""
    try:
        plane = scene.active_section()
    except Exception:  # noqa: BLE001 - an old IngeTrazo: no sections
        return None
    if plane is None:
        return None
    o = clean(opts)
    color = o["color"]
    if color is None:
        own = (getattr(plane, "fill", None) or {}).get("color")
        color = list(own) if own else list(FALLBACK_COLOR)
    p, n = plane.point, plane.normal
    return {"point": [float(p.x()), float(p.y()), float(p.z())],
            "normal": [float(n.x()), float(n.y()), float(n.z())],
            "cap": o["cap"], "color": [float(c) for c in color[:3]], "light": o["light"]}


def signature(scene, opts: dict | None = None) -> str:
    """What the render depends on in the section (for the live view)."""
    return json.dumps(job_block(scene, opts), sort_keys=True)
