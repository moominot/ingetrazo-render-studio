# SPDX-License-Identifier: GPL-3.0-or-later
"""The active section plane, for the render.

IngeTrazo's section is display-only: the geometry is untouched and the viewer clips it
(core/section.py), so the model file written for Blender holds the whole model. The job
carries the plane and ``blender/studio_scene.py`` cuts the meshes with it.
"""
from __future__ import annotations

import json


def job_block(scene) -> dict | None:
    """``{"point": [x, y, z], "normal": [x, y, z]}`` of the plane cutting the model (the
    normal's side is the one that disappears), or None when nothing is cut."""
    try:
        plane = scene.active_section()
    except Exception:  # noqa: BLE001 - an old IngeTrazo: no sections
        return None
    if plane is None:
        return None
    p, n = plane.point, plane.normal
    return {"point": [float(p.x()), float(p.y()), float(p.z())],
            "normal": [float(n.x()), float(n.y()), float(n.z())]}


def signature(scene) -> str:
    """What the render depends on in the section (for the live view)."""
    return json.dumps(job_block(scene), sort_keys=True)
