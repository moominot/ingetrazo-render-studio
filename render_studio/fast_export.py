# SPDX-License-Identifier: GPL-3.0-or-later
"""A quicker model export for big models, and its progress.

``triangulate`` (the part of the glTF export that takes most of its time: on a 588 000-face model about
two thirds of 34 s) projects every face on its plane with Qt vectors and tests it for convexity. Nearly every
face of a building is a triangle or a convex quad: :class:`fast_triangles` does the same test with plain
floats (the plane's axes are worked out once per normal) and gives the very same fan; anything holed or
concave goes to IngeTrazo's own function, so the result is the same.

:class:`export_progress` counts the faces the writer takes and tells a callback how far it is.
"""
from __future__ import annotations

import logging
import math

_log = logging.getLogger(__name__)

_EPS = 1e-9
_AXES: dict = {}


def _axes(nx: float, ny: float, nz: float):
    """The two in-plane axes of a normal, as ``core.triangulate.plane_axes`` makes them (plain floats)."""
    key = (nx, ny, nz)
    got = _AXES.get(key)
    if got is not None:
        return got
    ln = math.sqrt(nx * nx + ny * ny + nz * nz)
    if ln < 1e-12:
        got = None
    else:
        nx, ny, nz = nx / ln, ny / ln, nz / ln
        ux, uy, uz = 1.0 - nx * nx, -nx * ny, -nx * nz
        if math.sqrt(ux * ux + uy * uy + uz * uz) < 0.1:
            ux, uy, uz = -ny * nx, 1.0 - ny * ny, -ny * nz
        ul = math.sqrt(ux * ux + uy * uy + uz * uz)
        ux, uy, uz = ux / ul, uy / ul, uz / ul
        vx, vy, vz = ny * uz - nz * uy, nz * ux - nx * uz, nx * uy - ny * ux
        vl = math.sqrt(vx * vx + vy * vy + vz * vz)
        got = (ux, uy, uz, vx / vl, vy / vl, vz / vl)
    if len(_AXES) > 4096:
        _AXES.clear()
    _AXES[key] = got
    return got


def convex_fan(outer, normal):
    """The fan of a hole-free ``outer`` loop when it is convex, else None (the caller falls back)."""
    n = len(outer)
    if n == 3:
        return [(outer[0], outer[1], outer[2])]
    ax = _axes(normal.x(), normal.y(), normal.z())
    if ax is None:
        return None
    ux, uy, uz, vx, vy, vz = ax
    p0 = outer[0]
    x0, y0, z0 = p0.x(), p0.y(), p0.z()
    pts = []
    for p in outer:
        dx, dy, dz = p.x() - x0, p.y() - y0, p.z() - z0
        pts.append((dx * ux + dy * uy + dz * uz, dx * vx + dy * vy + dz * vz))
    sign = 0
    for i in range(n):
        o, a, b = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        cr = (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
        if cr > _EPS:
            if sign < 0:
                return None
            sign = 1
        elif cr < -_EPS:
            if sign > 0:
                return None
            sign = -1
    return [(p0, outer[i], outer[i + 1]) for i in range(1, n - 1)]


class fast_triangles:
    """While the model file is written: ``core.triangulate.triangulate`` takes the quick path for a
    hole-free triangle or convex polygon."""

    def __init__(self):
        self.saved = None

    def __enter__(self):
        try:
            import core.triangulate as tri
            real = self.saved = tri.triangulate

            def triangulate(outer, holes=None, normal=None):
                if normal is not None and len(outer) >= 3 and not (holes and any(len(h) >= 3 for h in holes)):
                    try:
                        fan = convex_fan(outer, normal)
                    except Exception:  # noqa: BLE001 - IngeTrazo's own function, as before
                        fan = None
                    if fan is not None:
                        return fan
                return real(outer, holes, normal)
            tri.triangulate = triangulate
        except Exception:  # noqa: BLE001 - never stops a render
            _log.exception("quick triangulation not set")
            self.saved = None
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            import core.triangulate as tri
            tri.triangulate = self.saved
            self.saved = None
        return False


def unique_faces(scene) -> int:
    """The faces of the model counting each shared mesh once (what the shared export writes)."""
    from core.group import iter_placements
    seen = set()
    n = len(getattr(getattr(scene, "loose_mesh", None), "faces", None) or ())
    for g in getattr(scene, "groups", None) or ():
        if getattr(g, "hidden", False):
            continue
        for x, _m in iter_placements(g):
            if id(x.mesh) not in seen:
                seen.add(id(x.mesh))
                n += len(x.mesh.faces)
    return n


class export_progress:
    """While the model file is written: ``callback(fraction)`` as the writer takes the faces, at most every
    ``every`` faces. ``total`` is the faces it will take (a rough number is fine: the fraction stops at 1)."""

    def __init__(self, total: int, callback, every: int = 4000):
        self.total = max(1, int(total))
        self.callback = callback
        self.every = every
        self.saved = None
        self.count = 0

    def __enter__(self):
        if self.callback is None:
            return self
        try:
            import formats.meshexport as me
            real = self.saved = me._add_face

            def add_face(face, materials, prims, attrs=None, smoother=None):
                self.count += 1
                if self.count % self.every == 0:
                    try:
                        self.callback(min(1.0, self.count / self.total))
                    except Exception:  # noqa: BLE001 - a progress bar never stops the export
                        pass
                return real(face, materials, prims, attrs, smoother)
            me._add_face = add_face
        except Exception:  # noqa: BLE001
            _log.exception("export progress not set")
            self.saved = None
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            import formats.meshexport as me
            me._add_face = self.saved
            self.saved = None
        return False


class gc_paused:
    """The cyclic garbage collector sleeps while the model file is written. The export makes millions
    of small objects that live until the end; each full collection walks all of them (seconds, on a big
    model, with the whole drawing in memory) and finds nothing to free. Switched on again after, as it was."""

    def __init__(self):
        self.was = False

    def __enter__(self):
        import gc
        self.was = gc.isenabled()
        if self.was:
            gc.disable()
        return self

    def __exit__(self, *exc):
        if self.was:
            import gc
            gc.enable()
        return False
