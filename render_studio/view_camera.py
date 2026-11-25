# SPDX-License-Identifier: GPL-3.0-or-later
"""The 3D view's camera as Blender needs it.

IngeTrazo's own ``camera_dict`` says where the eye is, what it looks at and which
way is up. A two-point perspective is more than that: the picture plane stands
upright (so the verticals stay vertical) and the frame slides up or down to keep
the subject in it. So does a frame shifted by a matched photo. Both are said here:
the level sight line as the target, and ``frame_shift``, which Blender takes as
its camera's shift. Pure Python (no Qt of its own).
"""
from __future__ import annotations


def frame_shift(camera) -> tuple[float, float]:
    """How far the frame of a perspective view is slid from the sight line, right and up, both in view HEIGHTS (the unit of a
    Blender camera fitted to its height). Read from the view's own projection, so it is what the 3D view shows."""
    if not getattr(camera, "perspective", True):
        return 0.0, 0.0
    try:
        m = camera.projection_matrix()
        # a frustum's third column: (right + left) / (right - left) and (top + bottom) / (top - bottom)
        return float(m.column(2).x()) / 2.0 * float(camera.aspect), float(m.column(2).y()) / 2.0
    except Exception:  # noqa: BLE001 - a camera without a projection: no shift
        return 0.0, 0.0


def camera_dict(camera) -> dict:
    """IngeTrazo's ``camera_dict`` with the two-point view's level sight line and the frame's shift."""
    from core import render_blender as rb
    out = rb.camera_dict(camera)
    level_of = getattr(camera, "_level_forward", None)
    level = level_of() if callable(level_of) else None
    if level is not None:
        eye = camera.eye()
        aim = eye + level * float(camera.target_depth())
        out["target"] = [aim.x(), aim.y(), aim.z()]
        out["up"] = [0.0, 0.0, 1.0]
    sx, sy = frame_shift(camera)
    if abs(sx) > 1e-6 or abs(sy) > 1e-6:
        out["frame_shift"] = [round(sx, 6), round(sy, 6)]
    return out


def camera_key(camera) -> tuple:
    """What a live picture depends on in the camera (IngeTrazo's key, and what this module adds)."""
    from core import render_blender as rb
    d = camera_dict(camera)
    return (rb.camera_key(camera), tuple(round(v, 3) for v in d["target"] + d["up"]),
            tuple(round(v, 4) for v in d.get("frame_shift", (0.0, 0.0))))
