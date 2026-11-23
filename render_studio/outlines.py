# SPDX-License-Identifier: GPL-3.0-or-later
"""The outlines of a render: ink lines drawn over the picture Blender makes.

Blender's Freestyle takes tens of seconds on a model of hundreds of thousands of faces (33 s on 670 000 triangles, against 4 s
here). So Blender renders without lines, and the lines come from IngeTrazo's own geometry through Croquis' engine
(``croquis_engine``: a depth buffer, every edge walked pixel by pixel, outlines where the model ends), from the SAME camera and
the same size. They are written as a transparent PNG (the *line layer*) that the render's script puts over the picture
(``studio_scene.overlay_lines``) before the paper or the file is written.

Everything here runs in IngeTrazo's process: NumPy and Qt, no Blender.
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path

import numpy as np

from .croquis_engine import strokes as st
from .croquis_engine import visibility as vis

_log = logging.getLogger(__name__)

#: The depth buffer is never wider than this: the lines are found there and scaled up (a hair's error at 4K, a lot less work).
MAX_BUFFER = 3000
#: Below this many pixels of height there is nothing worth drawing.
MIN_HEIGHT = 16


def _srgb(c: float) -> float:
    c = max(0.0, min(1.0, float(c)))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1.0 / 2.4) - 0.055


def ink_colour(style: dict) -> tuple:
    """The outline colour of the style (linear RGB, as the panel keeps it) as 0..255 sRGB."""
    rgb = (style.get("color") or (0.05, 0.05, 0.05))[:3]
    return tuple(int(round(255 * _srgb(c))) for c in rgb)


def line_style(style: dict, height: int) -> st.LineStyle:
    """The hand of the style: ``width`` is in pixels of the picture (as Freestyle's was), ``noise`` 0..1 how loose the stroke is (0 a
    ruler), ``extend`` 0..1 how far lines run past their corners, both only in a sketch. A style that carries ``hand`` (the render
    window's controls) takes ``hand``, ``extend`` and ``opacity`` whatever its mode."""
    if "hand" in style:
        noise = max(0.0, min(1.0, float(style.get("hand") or 0.0)))
        extend = max(0.0, min(1.0, float(style.get("extend") or 0.0)))
    else:
        sketch = style.get("mode") == "sketch"
        noise = max(0.0, min(1.0, float(style.get("noise", 0.0) or 0.0))) if sketch else 0.0
        extend = max(0.0, min(1.0, float(style.get("extend", 0.0) or 0.0))) if sketch else 0.0
    width = float(style.get("width", 0.0) or 0.0)
    if style.get("mode") == "sketch" and width <= 0.0:
        width = 1.5                                      # a sketch is lines
    width = max(width, 0.0) if width <= 0.0 else max(width, 0.6)      # a thin frame keeps a line you can see
    return st.LineStyle(
        hand=noise,
        width=width * st.REFERENCE_HEIGHT / max(1, height),        # Croquis' widths scale with the picture: keep the pixels
        profile_scale=1.0 + 0.6 * noise,                           # a ruled line is even; a hand leans on the shapes' edges
        overshoot=2.0 * extend,
        double_stroke=noise > 0.05, breaks=noise > 0.2,
        opacity=max(0.05, min(1.0, float(style.get("opacity", 1.0) or 1.0))))


def window_style(style: dict) -> dict:
    """The panel's style as the render window's outline controls start: ``width``, ``color``, ``hand``, ``extend`` and ``opacity``
    (a sketch keeps its irregular stroke; any other style starts as a ruler)."""
    sketch = style.get("mode") == "sketch"
    width = float(style.get("width", 0.0) or 0.0)
    return {"mode": style.get("mode", "none"), "width": width if width > 0.0 else (1.5 if sketch else 0.0),
            "color": list(style.get("color") or (0.05, 0.05, 0.05))[:3],
            "hand": float(style.get("noise", 0.0)) if sketch else 0.0,
            "extend": float(style.get("extend", 0.0)) if sketch else 0.0, "opacity": 1.0}


def wanted(style: dict | None) -> bool:
    style = style or {}
    return float(style.get("width", 0.0) or 0.0) > 0.0 or style.get("mode") == "sketch"


def _from_scene(scene):
    """``hlr_geometry()``'s arrays from the scene itself (IngeTrazo's per-face walk: slow on a big model, but it needs no 3D view)."""
    from core import hlr
    tris, hard, soft = hlr.collect_geometry(scene)
    t = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
    h = np.asarray([(a, b) for a, b in hard], dtype=np.float64).reshape(-1, 2, 3)
    sp = np.asarray([(a, b) for a, b, *_ in soft], dtype=np.float64).reshape(-1, 2, 3)
    sn = np.full((len(soft), 2, 3), np.nan)
    for i, (_a, _b, na, nb) in enumerate(soft):
        sn[i, 0] = na
        if nb is not None:
            sn[i, 1] = nb
    return t, h, sp, sn


def _geometry(viewport):
    """The view's lines and faces: the viewport's own ``hlr_geometry()`` (tens of milliseconds, from the caches it keeps), else the
    scene's."""
    fn = getattr(viewport, "hlr_geometry", None)
    if not callable(fn):
        fn = getattr(type(viewport), "hlr_geometry", None)
        if callable(fn):
            return fn(viewport)
        return _from_scene(viewport.scene)
    return fn()


def segments(geom, camera, width: int, height: int):
    """``(segs, outline)`` in pixels of a ``width``×``height`` picture: the visible parts of the edges of ``geom`` (IngeTrazo's
    ``hlr_geometry()``: triangles, hard edges, soft edges, their normals) seen from ``camera``, straight runs joined, fine detail
    thinned as a hand does. Also returns each line's weight."""
    cam = copy.copy(camera)
    cam.aspect = width / max(1.0, float(height))
    scale = min(1.0, MAX_BUFFER / max(1, width))
    bw, bh = max(1, int(round(width * scale))), max(1, int(round(height * scale)))
    tris = np.asarray(geom[0], dtype=np.float64).reshape(-1, 3, 3)
    zbuf, _index = vis.depth_buffer(tris, vis.clip_matrix(cam), bw, bh, bool(cam.perspective))
    segs, outline = vis.visible_lines(geom, cam, bw, bh, zbuf=zbuf)
    segs, outline = vis.merge_collinear(segs, outline, tol=1.5)
    segs = segs / scale
    return st.simplify(segs, outline, height)


def edges_from_triangles(tris, crease_deg: float = 30.0, flat_deg: float = 1.0):
    """The lines of a triangle soup, for a model that comes without its edge list: ``(hard, soft, soft normals)`` as ``hlr_geometry``
    gives them. An edge of one triangle (an open border) or of more than two is hard; between two, hard where the surfaces turn by
    more than ``crease_deg``, left out where they lie in one plane (``flat_deg``: the diagonal of a quad), else soft (a smooth surface:
    drawn only where it turns away from the eye, with both normals)."""
    T = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
    n = len(T)
    empty = (np.empty((0, 2, 3)), np.empty((0, 2, 3)), np.empty((0, 2, 3)))
    if not n:
        return empty
    pts = T.reshape(-1, 3)
    scale = max(float(np.ptp(pts, axis=0).max()), 1e-9)
    _u, vid = np.unique(np.round(pts / (scale * 1e-6)).astype(np.int64), axis=0, return_inverse=True)
    vid = vid.reshape(-1, 3)
    nrm = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    ln = np.linalg.norm(nrm, axis=1)
    ok = ln > 1e-12 * scale * scale
    nrm = nrm / np.where(ok, ln, 1.0)[:, None]
    a = np.concatenate([vid[:, 0], vid[:, 1], vid[:, 2]])
    b = np.concatenate([vid[:, 1], vid[:, 2], vid[:, 0]])
    tri = np.tile(np.arange(n), 3)
    corner = np.repeat(np.arange(3), n)                     # which side of the triangle: the edge's ends are corner and corner+1
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    keep = (lo != hi) & ok[tri]
    lo, hi, tri, corner = lo[keep], hi[keep], tri[keep], corner[keep]
    key = lo.astype(np.int64) * (int(vid.max()) + 1) + hi
    order = np.argsort(key, kind="stable")
    key, tri, corner = key[order], tri[order], corner[order]
    first = np.r_[True, key[1:] != key[:-1]]
    start = np.nonzero(first)[0]
    count = np.diff(np.r_[start, len(key)])
    t0, c0 = tri[start], corner[start]
    seg = np.stack([T[t0, c0], T[t0, (c0 + 1) % 3]], axis=1)
    hard_mask = count != 2
    two = np.nonzero(count == 2)[0]
    n0, n1 = nrm[t0[two]], nrm[tri[start[two] + 1]]
    dot = np.clip(np.einsum("ij,ij->i", n0, n1), -1.0, 1.0)
    crease = dot < np.cos(np.radians(crease_deg))
    flat = dot > np.cos(np.radians(flat_deg))
    hard_mask[two[crease]] = True
    smooth = two[~crease & ~flat]
    sn = np.stack([nrm[t0[smooth]], nrm[tri[start[smooth] + 1]]], axis=1)
    return seg[hard_mask], seg[smooth], sn


def scene_geometry(scene):
    """The scene's own lines and faces (public name of :func:`_from_scene`): what the render sees once the proxies' stand-ins, the light
    symbols and the hidden objects are left out (the caller holds those contexts while this walks the scene)."""
    return _from_scene(scene)


def transformed(geom, matrix_rows):
    """``geom`` (triangles, hard, soft, soft normals) of an original placed by a 4×4 matrix (four rows, as proxies.py keeps them)."""
    tris, hard, soft, soft_n = geom
    M = np.asarray(matrix_rows, dtype=np.float64).reshape(4, 4)
    R, t = M[:3, :3], M[:3, 3]
    nm = np.linalg.inv(R).T if abs(np.linalg.det(R)) > 1e-12 else R

    def pts(a):
        return a @ R.T + t

    def nrm(n):
        out = n @ nm.T                                 # NaN rows (an open surface's missing second face) stay NaN
        ln = np.linalg.norm(out, axis=-1, keepdims=True)
        return out / np.where(ln > 1e-12, ln, 1.0)
    return pts(tris), pts(hard), pts(soft), nrm(soft_n)


def merged(parts):
    """One geometry from several (triangles, hard, soft, soft normals) ones."""
    parts = [p for p in parts if p is not None]
    return tuple(np.concatenate([p[k] for p in parts]) if parts else np.empty((0,) + shape)
                 for k, shape in enumerate(((3, 3), (2, 3), (2, 3), (2, 3))))


def occluder(stand_in_tris):
    """A geometry that only hides: triangles with no edge (a stand-in whose original is too heavy to draw lines of)."""
    return (np.asarray(stand_in_tris, dtype=np.float64).reshape(-1, 3, 3), np.empty((0, 2, 3)), np.empty((0, 2, 3)), np.empty((0, 2, 3)))


# ---- the section: what its planes cut away is no part of the lines -----------------------------------------------------------

def cut_planes(scene) -> list:
    """The planes cutting the model now, as ``(point, normal)`` arrays: the active section plane and, in an IngeTrazo that has them (0.6.3),
    the six faces of the active section box. ``normal`` points to the side that goes. ``[]`` when nothing cuts (or Section Cuts is off)."""
    if scene is None or not getattr(scene, "show_section_cuts", True):
        return []
    try:
        from core.section import cut_planes as ingetrazo_cut_planes
        planes = list(ingetrazo_cut_planes(scene))
    except Exception:  # noqa: BLE001 - an IngeTrazo without section boxes: the active plane alone
        active = getattr(scene, "active_section", None)
        try:
            sp = active() if callable(active) else None
        except Exception:  # noqa: BLE001
            sp = None
        planes = [sp] if sp is not None else []
    out = []
    for pl in planes:
        try:
            pt, nm = pl.point, pl.normal
            out.append((np.array([pt.x(), pt.y(), pt.z()], dtype=np.float64), np.array([nm.x(), nm.y(), nm.z()], dtype=np.float64)))
        except Exception:  # noqa: BLE001 - not a plane
            continue
    return out


def _clip_segments(seg, extra, d, eps):
    """Segments ``seg`` (N, 2, 3) with per-end distances ``d`` (N, 2) beyond a plane (> 0 goes): the parts that stay, and the rows of
    ``extra`` (another array of the same N) that go with them."""
    da, db = d[:, 0], d[:, 1]
    keep = (da <= eps) | (db <= eps)
    seg, da, db = seg[keep], da[keep], db[keep]
    extra = extra[keep] if extra is not None else None
    a, b = seg[:, 0].copy(), seg[:, 1].copy()
    cross_a = da > eps                                 # the first end is on the removed side: move it to the plane
    cross_b = db > eps
    t = np.where(cross_a | cross_b, da / np.where(da != db, da - db, 1.0), 0.0)
    cut = seg[:, 0] + t[:, None] * (seg[:, 1] - seg[:, 0])
    a[cross_a] = cut[cross_a]
    b[cross_b] = cut[cross_b]
    return np.stack([a, b], axis=1), extra


def _clip_triangles(tris, d, eps):
    """Triangles (T, 3, 3) with per-corner distances ``d`` (T, 3) beyond a plane (> 0 goes): those that stay, whole or cut at the plane (a
    triangle with one corner gone becomes two, with two corners gone one), with the winding they had."""
    out = d > eps
    n_out = out.sum(axis=1)
    keep_whole = tris[n_out == 0]
    parts = [keep_whole]
    one = np.nonzero(n_out == 1)[0]                    # one corner gone: a quad, two triangles
    if len(one):
        r = np.argmax(out[one], axis=1)                # rotate so the corner gone is first: (O, A, B) in cyclic order
        T = tris[one]; D = d[one]
        idx = (r[:, None] + np.arange(3)[None, :]) % 3
        rows = np.arange(len(one))[:, None]
        O, A, B = (T[rows[:, 0], idx[:, k]] for k in range(3))
        dO, dA, dB = (D[rows[:, 0], idx[:, k]] for k in range(3))
        pa = A + ((dA / (dA - dO))[:, None]) * (O - A)          # on A → O
        pb = B + ((dB / (dB - dO))[:, None]) * (O - B)          # on B → O
        parts.append(np.stack([A, B, pb], axis=1))
        parts.append(np.stack([A, pb, pa], axis=1))
    two = np.nonzero(n_out == 2)[0]                    # two corners gone: one triangle
    if len(two):
        r = np.argmin(out[two], axis=1)                # the corner that stays first: (P, Q, R)
        T = tris[two]; D = d[two]
        idx = (r[:, None] + np.arange(3)[None, :]) % 3
        rows = np.arange(len(two))
        P, Q, R = (T[rows, idx[:, k]] for k in range(3))
        dP, dQ, dR = (D[rows, idx[:, k]] for k in range(3))
        parts.append(np.stack([P, P + ((dP / (dP - dQ))[:, None]) * (Q - P), P + ((dP / (dP - dR))[:, None]) * (R - P)], axis=1))
    return np.concatenate(parts) if len(parts) > 1 else keep_whole


def clip_geometry(geom, planes, eps: float = 1e-6):
    """``geom`` (triangles, hard edges, soft edges, soft normals) cut by ``planes`` (:func:`cut_planes`): what lies on the normal's side
    goes, as in IngeTrazo's view and in the render, so no line is drawn of the cut-away part and it hides nothing."""
    if not planes:
        return geom
    tris, hard, soft, soft_n = (np.asarray(g, dtype=np.float64) for g in geom)
    for point, normal in planes:
        n = np.asarray(normal, dtype=np.float64)
        ln = float(np.linalg.norm(n))
        if ln < 1e-12:
            continue
        n = n / ln
        p0 = np.asarray(point, dtype=np.float64)
        if len(tris):
            tris = _clip_triangles(tris, (tris - p0) @ n, eps)
        if len(hard):
            hard, _x = _clip_segments(hard, None, (hard - p0) @ n, eps)
        if len(soft):
            soft, soft_n = _clip_segments(soft, soft_n, (soft - p0) @ n, eps)
    return tris.reshape(-1, 3, 3), hard.reshape(-1, 2, 3), soft.reshape(-1, 2, 3), soft_n.reshape(-1, 2, 3)


class LineSet:
    """The visible lines of a view, found once (the costly part): ``segs`` (N, 4) pixels of a ``width``×``height`` picture, which are
    outlines, and how thin to draw each. Any style can be drawn from it without looking at the model again (:func:`strokes_image`)."""

    def __init__(self, segs, outline, weight, width: int, height: int) -> None:
        self.segs, self.outline, self.weight = segs, outline, weight
        self.width, self.height = int(width), int(height)

    def __len__(self) -> int:
        return len(self.segs)


def lineset(viewport, camera, width: int, height: int, geom=None, notes: list | None = None, planes=None):
    """The :class:`LineSet` of the view seen from ``camera`` at ``width``×``height`` (None when it shows no line). ``geom``: the geometry
    to draw (see ``panel.line_geometry``), else the viewport's own. ``planes``: what is cut away (:func:`cut_planes`; by default the
    active section plane and box of the viewport's scene)."""
    if height < MIN_HEIGHT or width < MIN_HEIGHT:
        return None
    g = geom if geom is not None else _geometry(viewport)
    if planes is None:
        planes = cut_planes(getattr(viewport, "scene", None))
    if planes:
        before = len(g[0])
        g = clip_geometry(g, planes)
        if notes is not None:
            notes.append(f"section: {len(planes)} cutting plane(s); triangles {before} -> {len(g[0])}")
    segs, outline, weight = segments(g, camera, width, height)
    if notes is not None:
        notes.append(f"geometry: triangles {len(g[0])}, hard {len(g[1])}, soft {len(g[2])}; {len(segs)} lines in {width}x{height}")
    return LineSet(segs, outline, weight, width, height) if len(segs) else None


def strokes_image(lines: LineSet, style: dict):
    """The ink of ``lines`` in ``style`` as a ``QImage`` (ARGB, transparent where there is none): the hand's strokes, one polygon each,
    laid over a picture (:func:`composite`) or saved as a layer."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF
    ls = line_style(style, lines.height)
    kinds = lines.outline if ls.profile_scale != 1.0 else None
    strokes = st.strokes_for(lines.segs, kinds, ls, lines.height, lines.weight)
    img = QImage(lines.width, lines.height, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    r, g, b = ink_colour(style)
    for s in strokes:
        p.setBrush(QColor(r, g, b, int(255 * max(0.0, min(1.0, s.opacity)))))
        p.drawPolygon(QPolygonF([QPointF(float(x), float(y)) for x, y in s.outline]))
    p.end()
    return img


def composite(base, lines: LineSet, style: dict):
    """A copy of ``base`` (a ``QImage``) with the ink of ``lines`` in ``style`` over it (the transparency of a clear sky is kept)."""
    from PySide6.QtGui import QImage, QPainter
    out = base.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    if lines is not None and len(lines):
        ink = strokes_image(lines, style)
        if ink.size() != out.size():
            ink = ink.scaled(out.size())
        p = QPainter(out)
        p.drawImage(0, 0, ink)
        p.end()
    return out


def linear_from_qcolor(c):
    """A ``QColor`` (sRGB) as the linear RGB the style keeps."""
    def lin(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return [lin(c.red()), lin(c.green()), lin(c.blue())]


def layer_image(viewport, camera, width: int, height: int, style: dict, geom=None, notes: list | None = None):
    """The line layer as a ``QImage`` (ARGB, transparent where there is no ink), or None when the view shows no line."""
    lines = lineset(viewport, camera, width, height, geom, notes)
    return strokes_image(lines, style) if lines is not None else None


def write_layer(viewport, camera, width: int, height: int, style: dict, path, geom=None, notes: list | None = None) -> str | None:
    """Make the line layer and save it as a PNG at ``path``. Returns the path, or None when there is nothing to draw (or it failed:
    a render is never lost over its lines)."""
    if not wanted(style):
        return None
    try:
        img = layer_image(viewport, camera, int(width), int(height), style, geom, notes)
        if img is None:
            return None
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if notes:
            Path(path).with_suffix(".txt").write_text(chr(10).join(notes) + chr(10), encoding="utf-8")
        return str(path) if img.save(str(path), "PNG") else None
    except Exception:  # noqa: BLE001 - the picture without its outlines is better than none
        _log.exception("outlines not drawn")
        return None
