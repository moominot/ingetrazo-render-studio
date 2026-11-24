# SPDX-License-Identifier: GPL-3.0-or-later
"""Proxies: light stand-ins in the drawing, the full models in the render.

A proxy is a top-level component whose mesh is a light stand-in (a box…)
while its full model waits in an .igz file of its own. The data follows the
Proxies extension (PESI3D/ingetrazo-proxies, GPL-3.0-or-later), which the
Components manager (asset_manager) writes too::

    group.ext["proxy_tool"] = {"id", "file", "rel", "state": "proxy" | "original", …}

and the original file holds a component at identity tagged
``ext["proxy_tool"] = {"id"}``. Only the data format is shared; no code is
taken from that extension, which need not be installed.

For the render, every proxy showing its stand-in is left out of the model
file, and its original is written once to a .glb of its own (kept in a
cache, keyed by the original file's date and size and the paint the proxy
wears). The job lists each original with the matrices of its placements;
Blender imports it once and places it with collection instances, so a
hundred trees cost one tree in memory and nothing in the export.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

_log = logging.getLogger(__name__)

KEY = "proxy_tool"


def info_of(group) -> dict | None:
    info = (getattr(group, "ext", None) or {}).get(KEY)
    return info if isinstance(info, dict) and info.get("id") else None


def shown_proxies(scene) -> list:
    """The top-level placements showing their stand-in that the render would
    draw (hidden ones and ones on a hidden layer stay out, as any object)."""
    out = []
    for g in getattr(scene, "groups", ()) or ():
        info = info_of(g)
        if info and info.get("state") == "proxy" and scene.entity_visible(g):
            out.append(g)
    return out


def original_file(info: dict, doc_path=None) -> Path | None:
    """The original's file: relative to the drawing first (a project folder
    moved as a whole), then the path it was written to."""
    rel = info.get("rel")
    if rel and doc_path:
        p = Path(os.path.normpath(Path(doc_path).parent / rel))
        if p.is_file():
            return p
    p = Path(info.get("file") or "")
    return p if info.get("file") and p.is_file() else None


def ensure_original(info: dict, doc_path=None) -> Path | None:
    """``original_file``, writing it first for a proxy that went in without
    one (a heavy model, ``info["lazy"]``: the Components manager reads its
    source file again, once). None when it cannot be had."""
    src = original_file(info, doc_path)
    if src is not None or not info.get("lazy"):
        return src
    import sys
    mod = next((m for k, m in list(sys.modules.items())
                if k.endswith("asset_manager.place") and hasattr(m, "materialize")), None)
    if mod is None:
        return None
    try:
        mod.materialize(info)
    except Exception:  # noqa: BLE001 - that proxy renders as its stand-in
        _log.exception("original of %s not written", info.get("name"))
        return None
    return original_file(info, doc_path)


def cache_dir() -> Path:
    from core import render_blender as rb
    return rb.work_base().parent / "render-studio" / "proxies"


def _rows(m) -> list:
    """A QMatrix4x4 as four rows (Z up, metres: IngeTrazo's and Blender's frame)."""
    return [[float(v) for v in m.row(r).toTuple()] for r in range(4)]


def _paint_key(paint) -> str:
    return json.dumps(paint, sort_keys=True, default=str) if paint else ""


def _export(src: Path, pid: str, paint, out: Path, progress=None) -> bool:
    """Write the original ``pid`` of ``src`` to ``out`` (.glb, at identity,
    wearing ``paint`` where its faces have none). False when the file does
    not hold it. ``progress(fraction)``, when given, says how far it is (the
    modal's bar: a heavy original takes minutes)."""
    from PySide6.QtGui import QMatrix4x4

    from core.scene import Scene
    from formats import igz
    from formats.gltf import save_glb
    def tell(f):
        if progress is not None:
            try:
                progress(max(0.0, min(1.0, f)))
            except Exception:  # noqa: BLE001 - a progress bar never stops the export
                pass
    sc = Scene()
    igz.load_into(sc, src, progress=(lambda f, _t="": tell(0.4 * f)) if progress else None)
    found = next((g for g in sc.groups if (info_of(g) or {}).get("id") == pid), None)
    if found is None:
        return False
    found.xform = QMatrix4x4()
    found.hidden = False
    if paint:
        found.material = paint
    sc.groups[:] = [found]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.glb")
    if progress is None:
        save_glb(sc, tmp)               # no camera: the structure kept, copies sharing one mesh
    else:
        from . import fast_export
        from core.group import iter_placements
        total = sum(len(pg.mesh.faces) for pg, _m in iter_placements(found))
        with fast_export.fast_triangles(), fast_export.gc_paused(),                 fast_export.export_progress(total, lambda f: tell(0.4 + 0.6 * f)):
            save_glb(sc, tmp)
    os.replace(tmp, out)
    return True


def job_block(scene, doc_path=None, cache: Path | None = None, progress=None):
    """``(block, missing)``: the job's ``"proxies"`` list —
    ``[{"name", "glb", "matrices": [4×4 rows…]}]``, one entry per original
    and paint — and the proxies whose original was not found (they render
    as their stand-in). Writes the .glb files the cache lacks."""
    cache = cache or cache_dir()
    entries: dict = {}
    missing = []
    for g in shown_proxies(scene):
        info = info_of(g)
        src = ensure_original(info, doc_path)
        if src is None:
            missing.append(g)
            continue
        paint = getattr(g, "material", None)
        st = src.stat()
        sig = f"{src.resolve()}|{st.st_size}|{int(st.st_mtime)}|{info['id']}|{_paint_key(paint)}"
        key = hashlib.sha1(sig.encode("utf-8", "replace")).hexdigest()[:16]
        e = entries.get(key)
        if e is None:
            glb = cache / f"{info['id'][:12]}-{key}.glb"
            if not glb.is_file():
                try:
                    if not _export(src, info["id"], paint, glb, progress):
                        missing.append(g)
                        continue
                except Exception:  # noqa: BLE001 - that proxy renders as its stand-in
                    _log.exception("original of %s not exported", info.get("name") or g.name)
                    missing.append(g)
                    continue
            e = entries[key] = {"name": info.get("name") or g.name, "glb": str(glb), "matrices": []}
        from PySide6.QtGui import QMatrix4x4
        e["matrices"].append(_rows(g.xform if g.xform is not None else QMatrix4x4()))
    return list(entries.values()), missing


class left_out:
    """While the model file is written: the proxies in ``groups`` are hidden
    (the export leaves hidden objects out), then shown again as they were.
    Nothing reaches the undo history or the drawing's version."""

    def __init__(self, groups):
        self.groups = list(groups)
        self.was = []

    def __enter__(self):
        self.was = [g.hidden for g in self.groups]
        for g in self.groups:
            g.hidden = True
        return self

    def __exit__(self, *exc):
        for g, h in zip(self.groups, self.was):
            g.hidden = h
        return False


#: Lines are drawn of the originals up to this many triangles in all (a hundred trees of 50 000 faces are 5 million): past it a
#: proxy is only an occluder (its triangles hide what is behind it, and it has no lines of its own).
LINES_BUDGET = 4_000_000
_geom_cache: dict = {}


def _original_geometry(src: Path, pid: str):
    """The original's lines and faces at identity (hlr geometry arrays), kept while the file does not change; None when it has none."""
    from core.scene import Scene
    from formats import igz
    from . import outlines
    st = src.stat()
    key = (str(src.resolve()), st.st_size, int(st.st_mtime), pid)
    if key not in _geom_cache:
        if len(_geom_cache) > 16:
            _geom_cache.clear()
        sc = Scene()
        igz.load_into(sc, src)
        found = next((g for g in sc.groups if (info_of(g) or {}).get("id") == pid), None)
        geom = None
        if found is not None:
            from PySide6.QtGui import QMatrix4x4
            found.xform = QMatrix4x4()
            found.hidden = False
            sc.groups[:] = [found]
            geom = outlines.scene_geometry(sc)
            if len(geom[0]) and not (len(geom[1]) or len(geom[2])):
                # The original came without an edge list (a lazy mesh of the engine): its lines are read from its triangles.
                geom = (geom[0],) + outlines.edges_from_triangles(geom[0])
        _geom_cache[key] = geom
    return _geom_cache[key]


def line_geometry(scene, doc_path=None, budget: int = LINES_BUDGET):
    """``(placed, extra)`` for the outlines: ``placed`` the proxies whose original is found (what the render leaves out of the model
    file, as ``job_block`` does) and ``extra`` the geometry of their originals, each at its placements (one without the room
    in ``budget`` is only an occluder). ``extra`` is None when nothing is placed."""
    from . import outlines
    parts, placed, used = [], [], 0
    for g in shown_proxies(scene):
        info = info_of(g)
        src = ensure_original(info, doc_path)
        if src is None:
            continue                                   # rendered as its stand-in: the scene's own lines
        try:
            geom = _original_geometry(src, info["id"])
        except Exception:  # noqa: BLE001 - that proxy has no lines of its own
            _log.exception("lines of %s not read", info.get("name") or g.name)
            geom = None
        if geom is None:
            continue
        placed.append(g)
        from PySide6.QtGui import QMatrix4x4
        m = _rows(g.xform if g.xform is not None else QMatrix4x4())
        if used + len(geom[0]) <= budget:
            parts.append(outlines.transformed(geom, m))
            used += len(geom[0])
        else:
            parts.append(outlines.occluder(outlines.transformed(geom, m)[0]))
    return placed, (outlines.merged(parts) if parts else None)
