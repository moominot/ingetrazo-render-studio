# SPDX-License-Identifier: GPL-3.0-or-later
"""Full texture sets: a material's colour picture with its companion maps.

An IngeTrazo face carries only its colour picture (``attrs["texture"] =
{"path", "sw", "sh", "rot"}``). Material libraries ship more with it: a
normal map, roughness, ambient occlusion, displacement, metalness, opacity.
This module finds them, from the colour picture's path alone:

1. A manifest beside the picture, ``<picture stem>.pbr.json``::

       {"version": 1, "color": "<file>", "normal_gl": "<file>", "normal_dx": "<file>",
        "roughness": "<file>", "ao": "<file>", "displacement": "<file>",
        "metalness": "<file>", "opacity": "<file>", "arm": "<file>",
        "size_m": [w, h], "source": "polyhaven|ambientcg", "id": "<asset id>"}

   Every key but ``version`` and ``color`` is optional; files are relative
   to the manifest's folder and must stay inside it (an absolute path or a
   ``..`` is refused). ``arm`` is ambient occlusion, roughness and
   metalness packed in the red, green and blue channels.
2. No manifest: the sibling files the two libraries' own names give —
   Poly Haven ``<id>_diff_<res>.jpg`` → ``<id>_nor_gl_<res>``, ``_rough_``,
   ``_ao_``, ``_disp_``, ``_metal_``, ``_arm_``…; ambientCG
   ``<id>_<res>-JPG_Color.jpg`` → ``…_NormalGL``, ``_Roughness``,
   ``_AmbientOcclusion``, ``_Displacement``, ``_Metalness``, ``_Opacity``.
3. Nothing found: None (the render uses the picture alone, as before).

The result (:func:`find_maps`) is what the render job carries for the
picture, every path absolute::

    {"normal": path, "normal_flip_green": bool, "roughness": path, "ao": path,
     "displacement": path, "metalness": path, "opacity": path, "arm": path,
     "found": "manifest" | "names"}

with only the maps that exist. A DirectX normal map (``normal_dx``) is used
when there is no OpenGL one, its green channel flipped
(``normal_flip_green``).

Pure Python: no Qt, no Blender, so it is tested on its own.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

_log = logging.getLogger(__name__)

MANIFEST_SUFFIX = ".pbr.json"
MANIFEST_VERSION = 1
#: The manifest's map keys, in the order they are read.
MANIFEST_MAPS = ("normal_gl", "normal_dx", "roughness", "ao", "displacement",
                 "metalness", "opacity", "arm")
#: The maps the render job carries (besides ``normal_flip_green`` and ``found``).
JOB_MAPS = ("normal", "roughness", "ao", "displacement", "metalness", "opacity", "arm")
#: A manifest bigger than this is not a manifest.
MANIFEST_MAX_BYTES = 64 * 1024
#: Image files a companion map may be, best first after the picture's own.
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff")

#: Poly Haven: ``<id>_diff_<res>`` and each map's word in the same place.
_POLYHAVEN = re.compile(r"^(?P<id>.+)_diff_(?P<res>\d+k)$", re.IGNORECASE)
_POLYHAVEN_MAPS = (("normal_gl", "nor_gl"), ("normal_dx", "nor_dx"), ("roughness", "rough"),
                   ("ao", "ao"), ("displacement", "disp"), ("metalness", "metal"), ("arm", "arm"))
#: ambientCG: ``<id>_<res>-<FORMAT>_Color`` and each map's word at the end.
_AMBIENTCG = re.compile(r"^(?P<base>.+_\d+K-(?:JPG|PNG|EXR))_Color$", re.IGNORECASE)
_AMBIENTCG_MAPS = (("normal_gl", "NormalGL"), ("normal_dx", "NormalDX"), ("roughness", "Roughness"),
                   ("ao", "AmbientOcclusion"), ("displacement", "Displacement"),
                   ("metalness", "Metalness"), ("opacity", "Opacity"))


def manifest_path(colour) -> Path:
    """Where the manifest of a colour picture is: ``<stem>.pbr.json`` beside it."""
    colour = Path(colour)
    return colour.with_name(colour.stem + MANIFEST_SUFFIX)


def _inside(folder: Path, rel: str):
    """``rel`` (a manifest entry) as an absolute path inside ``folder``, or None
    when it is not a plain relative path to an existing file in there."""
    if not isinstance(rel, str) or not rel.strip() or "\0" in rel:
        return None
    rel = rel.strip()
    for flavour in (PurePosixPath, PureWindowsPath):      # refuse either kind, on any system
        p = flavour(rel)
        if p.is_absolute() or p.anchor or ".." in p.parts:
            return None
    try:
        base = folder.resolve()
        full = (base / rel).resolve()
        full.relative_to(base)                             # a link that leads out is refused too
    except (OSError, ValueError, RuntimeError):
        return None
    return full if full.is_file() else None


def read_manifest(path) -> dict | None:
    """A manifest checked: ``{key: absolute path}`` for each map it names that
    is a file inside its folder, plus ``size_m``/``source``/``id`` when they
    are sound. None when the file is missing, unreadable, not version 1 or
    has no ``color``. A bad entry is dropped, not the whole manifest."""
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size > MANIFEST_MAX_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        _log.info("texture set manifest unreadable: %s (%s)", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    if isinstance(version, bool) or version != MANIFEST_VERSION:
        _log.info("texture set manifest of another version ignored: %s", path)
        return None
    if not isinstance(data.get("color"), str) or not data["color"].strip():
        return None
    folder = path.parent
    out: dict = {}
    for key in MANIFEST_MAPS:
        if key not in data:
            continue
        full = _inside(folder, data[key])
        if full is None:
            _log.info("texture set manifest %s: %s refused (%r)", path, key, data[key])
            continue
        out[key] = str(full)
    size = data.get("size_m")
    if (isinstance(size, (list, tuple)) and len(size) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v < 1e4 for v in size)):
        out["size_m"] = [float(size[0]), float(size[1])]
    for key in ("source", "id"):
        if isinstance(data.get(key), str) and len(data[key]) <= 200:
            out[key] = data[key]
    return out


def _listing(folder: Path) -> dict:
    """The folder's files by lower-case name (a library's names are matched
    whatever their case, also where the file system minds it)."""
    try:
        return {p.name.lower(): p for p in folder.iterdir() if p.is_file()}
    except OSError:
        return {}


def _sibling(files: dict, stem: str, ext: str):
    for e in (ext.lower(),) + tuple(x for x in IMAGE_EXTS if x != ext.lower()):
        p = files.get((stem + e).lower())
        if p is not None:
            return p
    return None


def guess_maps(colour) -> dict:
    """The companion maps a library's own file names give for ``colour``:
    ``{manifest key: absolute path}``; empty when the name follows neither
    library or no sibling exists."""
    colour = Path(colour)
    stem, ext = colour.stem, colour.suffix
    m = _POLYHAVEN.match(stem)
    if m:
        names = [(key, f"{m['id']}_{word}_{m['res']}") for key, word in _POLYHAVEN_MAPS]
    else:
        m = _AMBIENTCG.match(stem)
        if not m:
            return {}
        names = [(key, f"{m['base']}_{word}") for key, word in _AMBIENTCG_MAPS]
    files = _listing(colour.parent)
    out = {}
    for key, name in names:
        p = _sibling(files, name, ext)
        if p is not None and p.name.lower() != colour.name.lower():
            out[key] = str(p.resolve())
    return out


def find_maps(colour) -> dict | None:
    """The companion maps of a colour picture, ready for the render job (see
    the module's docstring), or None when it has none."""
    if not colour:
        return None
    colour = Path(colour)
    raw = read_manifest(manifest_path(colour))
    found = "manifest"
    if raw is None:
        raw, found = guess_maps(colour), "names"
    out: dict = {}
    if raw.get("normal_gl"):
        out["normal"] = raw["normal_gl"]
    elif raw.get("normal_dx"):
        out["normal"], out["normal_flip_green"] = raw["normal_dx"], True
    for key in ("roughness", "ao", "displacement", "metalness", "opacity", "arm"):
        if raw.get(key):
            out[key] = raw[key]
    if not out:
        return None
    if out.get("normal"):
        out.setdefault("normal_flip_green", False)
    out["found"] = found
    return out


# ---- the model's pictures ---------------------------------------------------------

def _texture_of(attrs):
    tex = (attrs or {}).get("texture") if isinstance(attrs, dict) else None
    return tex if isinstance(tex, dict) and tex.get("path") else None


_PICS_CACHE = {"ref": None, "version": None, "out": None}


def model_pictures(scene) -> dict:
    """:func:`_model_pictures`, remembered for the model's version (it reads every face's paint: 0.8 s on
    a model of 588 000 faces, on every job the live view writes). Render Studio's own writes (a material's
    settings) do not change it: see ``materials.model_version``."""
    import weakref
    from .materials import model_version
    version = model_version(scene)
    cache = _PICS_CACHE
    if (version is not None and cache["out"] is not None and cache["version"] == version
            and cache["ref"] is not None and cache["ref"]() is scene):
        return dict(cache["out"])
    out = _model_pictures(scene)
    if version is not None:
        try:
            cache.update(ref=weakref.ref(scene), version=version, out=out)
        except TypeError:
            cache.update(ref=None, version=None, out=None)
    return dict(out)


def _model_pictures(scene) -> dict:
    """The colour pictures the model wears, keyed as the render's model file
    names them (the picture file's NAME: IngeTrazo's export groups a textured
    material under it) → the picture whose companions to look for: the
    original one under a colour tint (``texture["base"]``), else the file
    itself. Faces (loose, in groups and components, nested), objects painted
    whole and the document's named materials; the first one seen wins, as in
    the export."""
    out: dict = {}
    seen: set = set()

    def add(tex):
        if not tex:
            return
        name = Path(str(tex["path"])).name
        if name and name not in out:
            out[name] = str(tex.get("base") or tex["path"])

    def faces(mesh):
        if mesh is None or id(mesh) in seen:
            return
        seen.add(id(mesh))
        for f in getattr(mesh, "faces", ()) or ():
            add(_texture_of(getattr(f, "attrs", None)))

    def walk(groups):
        for g in groups or ():
            if id(g) in seen:
                continue
            seen.add(id(g))
            add(_texture_of(getattr(g, "material", None)))
            faces(getattr(g, "mesh", None))
            walk(getattr(g, "children", None))

    faces(getattr(scene, "mesh", None))
    faces(getattr(scene, "loose_mesh", None))
    walk(getattr(scene, "groups", None))
    for mat in (getattr(scene, "materials", None) or {}).values():
        tex = getattr(mat, "texture", None)
        add(tex if isinstance(tex, dict) and tex.get("path") else None)
    return out


def job_block(scene) -> dict:
    """``{picture file name: maps}`` for every picture of the model that has
    companion maps: the render job's ``"pbr"`` block."""
    out = {}
    for name, colour in model_pictures(scene).items():
        try:
            maps = find_maps(colour)
        except Exception as exc:  # noqa: BLE001 - one odd picture never stops a render
            _log.warning("texture set of %s not read: %s", colour, exc)
            continue
        if maps:
            out[name] = maps
    return out
