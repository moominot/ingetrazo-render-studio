# SPDX-License-Identifier: GPL-3.0-or-later
"""The drawing's own fog (IngeTrazo 0.6.3: Styles › Fog), so that the render has the fog the 3D view shows.

IngeTrazo's fog is a depth fade measured along the camera's view axis: nothing before ``distance`` metres, the fog's colour from
``distance + thickness`` on, a smoothstep between them (its shader's ``smoothstep(start, end, depth)``). Blender's mist pass is the same
axial depth, so the render's fog is the same fade (see ``studio_scene.build_compositor``). When the drawing has fog on it is THE fog of
the render and of the preview; when it has none, the Fog group's own sliders (fog thickness, where it starts) are the render's.
"""
from __future__ import annotations

import math


def _linear(c: float) -> float:
    c = max(0.0, min(1.0, float(c)))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def of(scene) -> dict | None:
    """``{"start", "thickness", "color"}`` of the drawing's fog (metres; ``color`` linear RGB, or None for «use the background»: the
    render's own horizon light), or None when the drawing has none (or an IngeTrazo that has no fog yet)."""
    style = getattr(scene, "display_style", None)
    if style is None or not bool(getattr(style, "fog_enabled", False)):
        return None

    def num(name, default, lo, hi):
        try:
            v = float(getattr(style, name, default))
        except (TypeError, ValueError):
            return default
        return min(hi, max(lo, v)) if math.isfinite(v) else default

    color = None
    if not bool(getattr(style, "fog_use_background", False)):
        raw = getattr(style, "fog_color", None)
        try:
            color = [round(_linear(c), 5) for c in list(raw)[:3]]
        except (TypeError, ValueError):
            color = None
        if color is not None and len(color) < 3:
            color = None
    return {"start": round(num("fog_distance", 10.0, 0.0, 40000.0), 3),
            "thickness": round(num("fog_thickness", 10.0, 0.01, 40000.0), 3), "color": color}


def apply(block: dict, scene) -> dict:
    """The look's block with the drawing's fog: it replaces the render's own (``fog`` 0) when the drawing has fog on."""
    fog = of(scene)
    if fog is None:
        return block
    block["fog"] = 0.0
    block["fog_drawing"] = fog
    return block
