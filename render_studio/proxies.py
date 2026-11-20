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


def cache_dir() -> Path:
    from core import render_blender as rb
    return rb.work_base().parent / "render-studio" / "proxies"


def _rows(m) -> list:
    """A QMatrix4x4 as four rows (Z up, metres: IngeTrazo's and Blender's frame)."""
    return [[float(v) for v in m.row(r).toTuple()] for r in range(4)]


def _paint_key(paint) -> str:
    return json.dumps(paint, sort_keys=True, default=str) if paint else ""


def _export(src: Path, pid: str, paint, out: Path) -> bool:
    """Write the original ``pid`` of ``src`` to ``out`` (.glb, at identity,
    wearing ``paint`` where its faces have none). False when the file does
    not hold it."""
    from PySide6.QtGui import QMatrix4x4

    from core.scene import Scene
    from formats import igz
    from formats.gltf import save_glb
    sc = Scene()
    igz.load_into(sc, src)
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
    save_glb(sc, tmp)                   # no camera: the structure kept, copies sharing one mesh
    os.replace(tmp, out)
    return True


def job_block(scene, doc_path=None, cache: Path | None = None):
    """``(block, missing)``: the job's ``"proxies"`` list —
    ``[{"name", "glb", "matrices": [4×4 rows…]}]``, one entry per original
    and paint — and the proxies whose original was not found (they render
    as their stand-in). Writes the .glb files the cache lacks."""
    cache = cache or cache_dir()
    entries: dict = {}
    missing = []
    for g in shown_proxies(scene):
        info = info_of(g)
        src = original_file(info, doc_path)
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
                    if not _export(src, info["id"], paint, glb):
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
