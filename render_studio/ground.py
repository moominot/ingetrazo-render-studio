# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the generated ground's grass is centred: the centroid of the drawing's objects.

Plain Python on IngeTrazo's scene (numpy for the meshes). The centroid is the mean of the centres of every
visible object's box (each placement of a component counts once), in the world, on the ground plane.
"""
from __future__ import annotations

#: Past this many distinct meshes the walk would cost seconds: the model's own box centre is used instead.
MAX_MESHES = 6000


def centroid(scene) -> list:
    """``[x, y]`` in metres: the mean of the centres of the boxes of the scene's visible objects."""
    import numpy as np
    from PySide6.QtGui import QVector3D
    try:
        from core.lazy_mesh import plan_of
    except Exception:  # noqa: BLE001 - an IngeTrazo without lazy meshes
        plan_of = lambda mesh: None  # noqa: E731
    pts = []
    centres = {}
    try:
        placements = list(scene.placements())
    except Exception:  # noqa: BLE001 - an older scene: its box below
        placements = []
    if len({id(g.mesh) for g, _m in placements}) <= MAX_MESHES:
        for g, m in placements:
            key = id(g.mesh)
            if key not in centres:
                plan = plan_of(g.mesh)
                arr = plan.pos if plan is not None else np.array(
                    [[v.position.x(), v.position.y(), v.position.z()] for v in g.mesh.vertices])
                centres[key] = ((arr.min(axis=0) + arr.max(axis=0)) / 2.0).tolist() if len(arr) else None
            c = centres[key]
            if c is None:
                continue
            p = m.map(QVector3D(*c)) if m is not None else QVector3D(*c)
            pts.append((p.x(), p.y()))
    loose = []
    try:
        for face in scene.loose_mesh.faces:
            if scene.entity_visible(face):
                loose.extend((v.x(), v.y()) for v in face.vertices)
    except Exception:  # noqa: BLE001
        loose = []
    if loose:
        xs, ys = [p[0] for p in loose], [p[1] for p in loose]
        pts.append(((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0))
    if not pts:
        lo, hi = scene.bounds()
        if lo is None:
            return [0.0, 0.0]
        return [(lo.x() + hi.x()) / 2.0, (lo.y() + hi.y()) / 2.0]
    return [round(sum(p[0] for p in pts) / len(pts), 4), round(sum(p[1] for p in pts) / len(pts), 4)]
