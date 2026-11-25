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


def ink_colour(style: dict, srgb: bool = False) -> tuple:
    """The outline colour of the style (linear RGB, as the panel keeps it) as 0..255 sRGB; ``srgb``: it is already as the screen shows it
    (the Section tab's colour buttons keep what the eye sees)."""
    rgb = (style.get("color") or (0.05, 0.05, 0.05))[:3]
    if srgb:
        return tuple(int(round(255 * max(0.0, min(1.0, float(c))))) for c in rgb)
    return tuple(int(round(255 * _srgb(c))) for c in rgb)


#: «Line extension» at 100 % (the panel's slider keeps a fraction): this many centimetres of the model.
EXTEND_MAX_CM = 50.0


#: The thickness of an outline left «automatic» (as the old sketch's was).
AUTO_WIDTH = 1.5


def plain(style: dict) -> dict:
    """A style with ``parts`` as one that says its outline itself: its thickness (automatic worked out), its hand and its
    extension, whatever its mode. Any other style as it is."""
    parts = (style or {}).get("parts")
    if not parts:
        return style
    out = {k: v for k, v in style.items() if k != "parts"}
    on = bool(parts.get("outline"))
    out.update(mode="none", model_on=on, width=(float(style.get("width") or 0.0) or AUTO_WIDTH) if on else 0.0,
               hand=float(style.get("noise", 0.0) or 0.0), extend=float(style.get("extend", 0.0) or 0.0))
    return out


def line_style(style: dict, height: int, px_per_m: float | None = None) -> st.LineStyle:
    """The hand of the style: ``width`` is in pixels of the picture (as Freestyle's was), ``noise`` 0..1 how loose the stroke is (0 a
    ruler), ``extend`` 0..1 how far lines run past their corners, both only in a sketch. A style that carries ``hand`` (the render
    window's controls) takes ``hand``, ``extend`` and ``opacity`` whatever its mode."""
    style = plain(style)
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
    # The extension is a length of the model, in centimetres, turned into pixels at the model's own distance (``px_per_m`` of the view).
    cm = style.get("extend_cm")
    if cm is None:
        cm = extend * EXTEND_MAX_CM
    extend_px = max(0.0, float(cm)) / 100.0 * (px_per_m if px_per_m and px_per_m > 0 else height / 6.0)
    return st.LineStyle(
        hand=noise,
        width=width * st.REFERENCE_HEIGHT / max(1, height),        # Croquis' widths scale with the picture: keep the pixels
        profile_scale=1.0 + 0.6 * noise,                           # a ruled line is even; a hand leans on the shapes' edges
        overshoot=2.0 * extend,
        double_stroke=noise > 0.05, breaks=noise > 0.2,
        opacity=max(0.05, min(1.0, float(style.get("opacity", 1.0) or 1.0))), extend_px=extend_px)


def window_style(style: dict) -> dict:
    """The panel's style as the render window's outline controls start: ``width``, ``color``, ``hand``, ``extend`` and ``opacity``
    (a sketch keeps its irregular stroke; any other style starts as a ruler)."""
    if (style or {}).get("parts"):
        own = plain(style)
        out = {"mode": style.get("mode", "none"), "width": own["width"], "model_on": own["model_on"],
               "extend_cm": own["extend"] * EXTEND_MAX_CM, "color": list(style.get("color") or (0.05, 0.05, 0.05))[:3],
               "hand": own["hand"], "extend": own["extend"], "opacity": 1.0}
        cut = cut_of(style)
        if cut is not None:
            out["cut"] = dict(cut)
        return out
    sketch = style.get("mode") == "sketch"
    width = float(style.get("width", 0.0) or 0.0)
    out = {"mode": style.get("mode", "none"), "width": width if width > 0.0 else (1.5 if sketch else 0.0),
           "model_on": bool(width > 0.0 or sketch),
           "extend_cm": (float(style.get("extend", 0.0)) * EXTEND_MAX_CM) if sketch else 0.0,
           "color": list(style.get("color") or (0.05, 0.05, 0.05))[:3],
           "hand": float(style.get("noise", 0.0)) if sketch else 0.0,
           "extend": float(style.get("extend", 0.0)) if sketch else 0.0, "opacity": 1.0}
    cut = cut_of(style)
    if cut is not None:
        out["cut"] = dict(cut)
    return out


def cut_of(style: dict | None) -> dict | None:
    """The style's ``cut`` (a section is active): ``{"on", "color", "width", "opacity", "cap"}``: the rim of the cap, apart from the model's
    own outlines, and whether the cap is there to hide what lies behind it. None when no section cuts."""
    cut = (style or {}).get("cut")
    return cut if isinstance(cut, dict) else None


def cut_line_style(style: dict, height: int) -> st.LineStyle:
    """The hand of the cap's rim: the model's hand (only for the pen's pressure, since the rim is always straight), its own width and ink."""
    cut = cut_of(style) or {}
    base = line_style(style, height)
    width = max(0.3, float(cut.get("width", 2.4) or 2.4))
    hand = max(base.hand, max(0.0, min(1.0, float(cut.get("hand", 0.0) or 0.0))))
    return st.LineStyle(hand=hand, width=width * st.REFERENCE_HEIGHT / max(1, height), profile_scale=1.0, overshoot=0.0, extend_px=0.0,
                        double_stroke=False, breaks=False,
                        opacity=max(0.05, min(1.0, float(cut.get("opacity", 1.0) or 1.0))))


def _wants_model(style: dict) -> bool:
    style = plain(style)
    if not style.get("model_on", True):
        return False
    return float(style.get("width", 0.0) or 0.0) > 0.0 or style.get("mode") == "sketch"


def wanted(style: dict | None) -> bool:
    style = style or {}
    cut = cut_of(style)
    return _wants_model(style) or bool(cut and cut.get("on") and float(cut.get("width", 0.0) or 0.0) > 0.0)


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


def segments(geom, camera, width: int, height: int, cut=None):
    """``(segs, outline, weight, cut_segs)`` in pixels of a ``width``×``height`` picture: the visible parts of the edges of ``geom``
    (IngeTrazo's ``hlr_geometry()``: triangles, hard edges, soft edges, their normals) seen from ``camera``, straight runs joined, fine
    detail thinned as a hand does, each with its weight. ``cut``: ``{"planes", "lines", "chords", "cap"}`` (see :func:`cut_lines`): the cap
    (when ``cap``) is put in the depth buffer and the cut's own lines come back apart, as ``cut_segs``."""
    cam = copy.copy(camera)
    cam.aspect = width / max(1.0, float(height))
    scale = min(1.0, MAX_BUFFER / max(1, width))
    bw, bh = max(1, int(round(width * scale))), max(1, int(round(height * scale)))
    tris = np.asarray(geom[0], dtype=np.float64).reshape(-1, 3, 3)
    M, persp = vis.clip_matrix(cam), bool(cam.perspective)
    zbuf, _index = vis.depth_buffer(tris, M, bw, bh, persp)
    if cut is not None and cut.get("cap", True):
        planes = _plane_arrays(cut["planes"])
        for a, plane in enumerate(planes):
            fill_cap(zbuf, cap_mask(cut["chords"][a], M, bw, bh, persp), plane, planes[:a] + planes[a + 1:], M, persp)
    segs, outline = vis.visible_lines(geom, cam, bw, bh, zbuf=zbuf)
    segs, outline = vis.merge_collinear(segs, outline, tol=1.5)
    segs = segs / scale
    cut_segs = np.empty((0, 4))
    if cut is not None and len(cut.get("lines", ())):
        empty = np.empty((0, 2, 3))
        cs, co = vis.visible_lines((tris, np.asarray(cut["lines"], dtype=np.float64).reshape(-1, 2, 3), empty, empty), cam, bw, bh, zbuf=zbuf)
        cut_segs, _o = vis.merge_collinear(cs, co, tol=1.5)
        cut_segs = cut_segs / scale
    return st.simplify(segs, outline, height) + (cut_segs,)


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
    t = np.where(cross_a | cross_b, (eps - da) / np.where(da != db, db - da, 1.0), 0.0)
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
        pa = A + (((eps - dA) / (dO - dA))[:, None]) * (O - A)          # on A → O
        pb = B + (((eps - dB) / (dO - dB))[:, None]) * (O - B)          # on B → O
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
        parts.append(np.stack([P, P + (((eps - dP) / (dQ - dP))[:, None]) * (Q - P), P + (((eps - dP) / (dR - dP))[:, None]) * (R - P)], axis=1))
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


def plane_chords(tris, point, normal, eps: float = 1e-6):
    """The chords a plane cuts out of triangles (T, 3, 3): (K, 2, 3), the segment inside each triangle that the plane crosses. A vertex ON
    the plane counts as on the kept side, for every triangle alike, so the rings stay closed."""
    tris = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
    if not len(tris):
        return np.empty((0, 2, 3))
    n = np.asarray(normal, dtype=np.float64)
    n = n / max(float(np.linalg.norm(n)), 1e-12)
    d = (tris - np.asarray(point, dtype=np.float64)) @ n
    gone = d > eps
    mixed = gone.any(axis=1) & ~gone.all(axis=1)
    T, D, G = tris[mixed], d[mixed], gone[mixed]
    if not len(T):
        return np.empty((0, 2, 3))
    lone = np.where(G.sum(axis=1) == 1, np.argmax(G, axis=1), np.argmin(G, axis=1))      # the vertex alone on its side
    rows = np.arange(len(T))
    i, j, k = lone, (lone + 1) % 3, (lone + 2) % 3

    def where_crossed(a, b):
        da, db = D[rows, a], D[rows, b]
        t = (eps - da) / np.where(db != da, db - da, 1.0)
        return T[rows, a] + t[:, None] * (T[rows, b] - T[rows, a])
    return np.stack([where_crossed(i, j), where_crossed(i, k)], axis=1)


def _plane_arrays(planes):
    return [(np.asarray(p, dtype=np.float64), np.asarray(n, dtype=np.float64) / max(float(np.linalg.norm(n)), 1e-12)) for p, n in planes]


def cut_lines(tris, planes, eps: float = 1e-6):
    """The cut's own lines, from the model's triangles (before they are cut): ``(lines, chords)``. ``lines`` (K, 2, 3): the rim of every cap,
    each plane's chords kept only where the other planes leave the material, and the lines where two cuts meet inside it (a section box's
    inner corners). ``chords``: each plane's whole chords (the cap's rings, for filling it)."""
    planes = _plane_arrays(planes)
    all_chords = [plane_chords(tris, p, n, eps) for p, n in planes]
    lines = []
    for a, (pa, na) in enumerate(planes):
        c = all_chords[a]
        for b, (pb, nb) in enumerate(planes):
            if b != a and len(c):
                c, _x = _clip_segments(c, None, (c - pb) @ nb, eps)
        if len(c):
            lines.append(c)
    for a in range(len(planes)):
        for b in range(a + 1, len(planes)):
            seg = _pair_line(planes[a], planes[b], all_chords[a])
            if seg is None:
                continue
            for c_, (pc, nc) in enumerate(planes):               # …and only where the others leave the material
                if c_ not in (a, b) and len(seg):
                    seg, _x = _clip_segments(seg, None, (seg - pc) @ nc, eps)
            if len(seg):
                lines.append(seg)
    return (np.concatenate(lines) if lines else np.empty((0, 2, 3))), all_chords


def _pair_line(pa, pb, chords):
    """Where two cuts meet inside the material: the stretches of the line ``a`` ∩ ``b`` that lie inside the closed rings ``chords`` of ``a``
    (even-odd along the line), (M, 2, 3), or None (parallel planes, no material there)."""
    (p0, na), (p1, nb) = pa, pb
    if chords is None or not len(chords):
        return None
    d = np.cross(na, nb)
    dd = float(d @ d)
    if dd < 1e-12:
        return None
    ca, cb = float(na @ p0), float(nb @ p1)
    origin = (ca * np.cross(nb, d) + cb * np.cross(d, na)) / dd
    across = np.cross(d, na)                              # in plane a, square to the line
    s0, s1 = (chords[:, 0] - origin) @ across, (chords[:, 1] - origin) @ across
    hit = (s0 > 0.0) != (s1 > 0.0)
    if not hit.any():
        return None
    q0, q1 = chords[hit, 0], chords[hit, 1]
    f = (s0[hit] / (s0[hit] - s1[hit]))[:, None]
    ts = np.sort(((q0 + (q1 - q0) * f) - origin) @ d)
    pairs = ts[:len(ts) // 2 * 2].reshape(-1, 2)         # an open ring: left out
    pairs = pairs[pairs[:, 1] - pairs[:, 0] > 1e-9]
    if not len(pairs):
        return None
    out = np.empty((len(pairs), 2, 3))
    out[:, 0] = origin + pairs[:, 0, None] * d
    out[:, 1] = origin + pairs[:, 1, None] * d
    return out


def cap_mask(chords, M, width: int, height: int, persp: bool):
    """A (height, width) bool picture of what the rings ``chords`` (K, 2, 3, one plane's cut) cover seen through ``M``: an even-odd scanline
    fill of the projected chords (a plane projects to the screen in straight lines, so the screen is where to fill)."""
    mask = np.zeros((height, width), dtype=bool)
    if chords is None or not len(chords):
        return mask
    A, B = vis._clip_segments(vis.to_clip(chords[:, 0], M), vis.to_clip(chords[:, 1], M))
    if not len(A):
        return mask
    ax, ay, _aq = vis._screen(A, width, height, persp)
    bx, by, _bq = vis._screen(B, width, height, persp)
    ok = np.isfinite(ax) & np.isfinite(ay) & np.isfinite(bx) & np.isfinite(by)
    ax, ay, bx, by = ax[ok], ay[ok], bx[ok], by[ok]
    flip = ay > by
    ax, bx = np.where(flip, bx, ax), np.where(flip, ax, bx)
    ay, by = np.where(flip, by, ay), np.where(flip, ay, by)
    r0 = np.maximum(np.ceil(ay - 0.5), 0).astype(np.int64)
    r1 = np.minimum(np.ceil(by - 0.5) - 1, height - 1).astype(np.int64)
    n = np.maximum(r1 - r0 + 1, 0)
    if not n.sum():
        return mask
    seg = np.repeat(np.arange(len(n)), n)
    rows = r0[seg] + (np.arange(len(seg)) - np.repeat(np.cumsum(n) - n, n))
    x = ax[seg] + (rows + 0.5 - ay[seg]) * (bx - ax)[seg] / (by - ay)[seg]
    order = np.lexsort((x, rows))
    rows, x = rows[order], x[order]
    same_next = np.r_[rows[1:] == rows[:-1], False]
    first = np.r_[True, rows[1:] != rows[:-1]]
    rank = np.arange(len(rows)) - np.maximum.accumulate(np.where(first, np.arange(len(rows)), 0))
    left = np.nonzero((rank % 2 == 0) & same_next)[0]
    c0 = np.clip(np.ceil(x[left] - 0.5), 0, width).astype(np.int64)
    c1 = np.clip(np.ceil(x[left + 1] - 0.5), 0, width).astype(np.int64)
    diff = np.zeros((height, width + 1), dtype=np.int32)
    np.add.at(diff, (rows[left], c0), 1)
    np.add.at(diff, (rows[left], c1), -1)
    return np.cumsum(diff, axis=1)[:, :width] > 0


def fill_cap(zbuf, mask, plane, others, M, persp: bool, eps: float = 1e-6) -> None:
    """The cap of ``plane`` in the depth buffer: where ``mask`` is, the plane's own depth, if it is nearer than what is there (so the lines of
    what lies behind the cap are hidden by it). Only where the other cuts (``others``) leave the material."""
    rows, cols = np.nonzero(mask)
    if not len(rows):
        return
    h, w = mask.shape
    Minv = np.linalg.inv(M)
    nx = (cols + 0.5) / w * 2.0 - 1.0
    ny = 1.0 - (rows + 0.5) / h * 2.0

    def unproject(z):
        c = np.stack([nx, ny, np.full_like(nx, z), np.ones_like(nx)], axis=1)
        p = c @ Minv.T
        return p[:, :3] / p[:, 3:4]
    near, far = unproject(-1.0), unproject(1.0)
    point, normal = plane
    D = far - near
    den = D @ normal
    ok = np.abs(den) > 1e-12
    t = np.where(ok, ((point - near) @ normal) / np.where(ok, den, 1.0), 0.0)
    P = near + t[:, None] * D
    keep = ok.copy()
    for pc, nc in others:
        keep &= (P - pc) @ nc <= eps
    if not keep.any():
        return
    P, rows, cols = P[keep], rows[keep], cols[keep]
    c = P @ M[:, :3].T + M[:, 3]
    q = 1.0 / c[:, 3] if persp else -c[:, 2] / c[:, 3]
    if persp:
        good = c[:, 3] > 0
        q, rows, cols = q[good], rows[good], cols[good]
    zbuf[rows, cols] = np.maximum(zbuf[rows, cols], q)


def _px_per_m(tris, camera, width: int, height: int):
    """How many pixels one metre of the model takes in the picture, at the model's own distance (the middle of its box): a point and a
    point a metre to its side, through the view. None when it cannot be told."""
    try:
        pts = np.asarray(tris, dtype=np.float64).reshape(-1, 3)
        if not len(pts):
            return None
        cam = copy.copy(camera)
        cam.aspect = width / max(1.0, float(height))
        M = vis.clip_matrix(cam)
        centre = (pts.min(axis=0) + pts.max(axis=0)) / 2.0
        f = cam.forward()
        fwd = np.array([f.x(), f.y(), f.z()], dtype=np.float64)
        right = np.cross(fwd, np.array([0.0, 0.0, 1.0]))
        if np.linalg.norm(right) < 1e-6:
            right = np.array([1.0, 0.0, 0.0])
        right /= np.linalg.norm(right)
        c = vis.to_clip(np.stack([centre, centre + right]), M)
        x = (c[:, 0] / c[:, 3] * 0.5 + 0.5) * width
        y = (0.5 - c[:, 1] / c[:, 3] * 0.5) * height
        px = float(np.hypot(x[1] - x[0], y[1] - y[0]))
        return px if np.isfinite(px) and px > 1e-6 else None
    except Exception:  # noqa: BLE001 - a guess is used instead
        return None


class LineSet:
    """The visible lines of a view, found once (the costly part): ``segs`` (N, 4) pixels of a ``width``×``height`` picture, which are
    outlines, and how thin to draw each. Any style can be drawn from it without looking at the model again (:func:`strokes_image`)."""

    def __init__(self, segs, outline, weight, width: int, height: int, cut=None, px_per_m=None) -> None:
        self.segs, self.outline, self.weight = segs, outline, weight
        self.width, self.height = int(width), int(height)
        self.px_per_m = px_per_m                       # pixels of one metre of the model, at the model's own distance (for lengths in cm)
        self.cut = np.empty((0, 4)) if cut is None else cut          # the rim of the caps (and where two cuts meet), apart

    def __len__(self) -> int:
        return len(self.segs) + len(self.cut)


def lineset(viewport, camera, width: int, height: int, geom=None, notes: list | None = None, planes=None, cut_outline: bool = False,
            cap: bool = True):
    """The :class:`LineSet` of the view seen from ``camera`` at ``width``×``height`` (None when it shows no line). ``geom``: the geometry
    to draw (see ``panel.line_geometry``), else the viewport's own. ``planes``: what is cut away (:func:`cut_planes`; by default the
    active section plane and box of the viewport's scene)."""
    if height < MIN_HEIGHT or width < MIN_HEIGHT:
        return None
    g = geom if geom is not None else _geometry(viewport)
    if planes is None:
        planes = cut_planes(getattr(viewport, "scene", None))
    cut = None
    if planes:
        before = len(g[0])
        if cut_outline or cap:
            lines, chords = cut_lines(g[0], planes)                 # from the triangles as they are, before they are cut
            cut = {"planes": planes, "lines": lines if cut_outline else np.empty((0, 2, 3)), "chords": chords, "cap": cap}
        g = clip_geometry(g, planes)
        if notes is not None:
            notes.append(f"section: {len(planes)} cutting plane(s); triangles {before} -> {len(g[0])}"
                         + (f"; {len(cut['lines'])} cut lines" if cut is not None else ""))
    segs, outline, weight, cut_segs = segments(g, camera, width, height, cut)
    if notes is not None:
        notes.append(f"geometry: triangles {len(g[0])}, hard {len(g[1])}, soft {len(g[2])}; {len(segs)} lines, {len(cut_segs)} of the cut, "
                     f"in {width}x{height}")
    return LineSet(segs, outline, weight, width, height, cut_segs, _px_per_m(g[0], camera, width, height)) if (len(segs) or len(cut_segs)) else None


def strokes_image(lines: LineSet, style: dict):
    """The ink of ``lines`` in ``style`` as a ``QImage`` (ARGB, transparent where there is none): the hand's strokes, one polygon each,
    laid over a picture (:func:`composite`) or saved as a layer."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF
    img = QImage(lines.width, lines.height, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)

    def paint(strokes, rgb):
        for s in strokes:
            p.setBrush(QColor(rgb[0], rgb[1], rgb[2], int(255 * max(0.0, min(1.0, s.opacity)))))
            p.drawPolygon(QPolygonF([QPointF(float(x), float(y)) for x, y in s.outline]))
    if _wants_model(style) and len(lines.segs):
        ls = line_style(style, lines.height, lines.px_per_m)
        kinds = lines.outline if ls.profile_scale != 1.0 else None
        paint(st.strokes_for(lines.segs, kinds, ls, lines.height, lines.weight), ink_colour(style))
    cut = cut_of(style)
    if cut and cut.get("on") and len(lines.cut):
        rim = ink_colour({"color": cut.get("color") or style.get("color")}, srgb=bool(cut.get("srgb", True)))
        # The rim of a cut is drawn with a ruler: straight lines, and with no hand (0) the same width all along.
        paint(st.strokes_for(lines.cut, None, cut_line_style(style, lines.height), lines.height, None, straight=True), rim)
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
    cut = cut_of(style)
    lines = lineset(viewport, camera, width, height, geom, notes, cut_outline=bool(cut and cut.get("on")),
                    cap=bool(cut.get("cap", True)) if cut else True)
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
