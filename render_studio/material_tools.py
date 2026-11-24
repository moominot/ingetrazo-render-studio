# SPDX-License-Identifier: GPL-3.0-or-later
"""Make, copy and apply materials from the material editor, with IngeTrazo's own commands.

A material is an entry of the document's registry (``scene.materials``: a colour or a picture, a
translucency, a finish) that faces and objects wear by name; Render Studio keeps its render settings for
it (the editor's ``materials`` data). Each function here is ONE undo step: the registry entry, the paint on
the selection and the settings travel in one compound command, as the Paint tool does for one click.
"""
from __future__ import annotations

import copy
import json

from core.group import Group
from core.history import (Command, CompoundCommand, SetFaceColorCommand, SetFaceMaterialTagCommand,
                          SetFaceOpacityCommand, SetFaceTextureCommand, SetGroupMaterialCommand)
from core.materials import Material
from core.mesh import Face

from . import studio_data


def unique_name(scene, base, specs=None) -> str:
    """``base``, or ``base (2)``, ``base (3)``… the first that no material of the document or of the
    editor's settings has."""
    base = (base or "").strip() or "Material"
    taken = set(getattr(scene, "materials", None) or {}) | set(specs or {})
    if base not in taken:
        return base
    n = 2
    while f"{base} ({n})" in taken:
        n += 1
    return f"{base} ({n})"


def _specs(app) -> dict:
    return dict((app.document_data({}) or {}).get("materials") or {})


def _spec_command(app, name, spec):
    """The command that stores ``spec`` as the settings of ``name`` (None where IngeTrazo has no such
    command: the caller writes it after)."""
    data = dict(app.document_data({}) or {})
    mats = dict(data.get("materials") or {})
    mats[name] = copy.deepcopy(spec)
    data["materials"] = mats
    cls = getattr(studio_data, "StudioDataCommand", None)
    return cls(app.key, data) if cls is not None and hasattr(app, "key") else None


def selection_count(scene) -> int:
    """How many faces and objects are selected (what applying would paint)."""
    return sum(1 for e in scene.selection if isinstance(e, (Face, Group)))


def paint_commands(scene, mat) -> tuple:
    """``(commands, count)`` that paint what is selected (faces, objects as a whole) with ``mat``, the
    way the Paint tool does."""
    faces = [e for e in scene.selection if isinstance(e, Face)]
    groups = [e for e in scene.selection if isinstance(e, Group)]
    cmds = []
    if faces:
        if mat.texture:
            cmds.append(SetFaceTextureCommand(faces, dict(mat.texture)))
        else:
            cmds += [SetFaceColorCommand(faces, tuple(mat.color or (0.8, 0.8, 0.8))),
                     SetFaceTextureCommand(faces, None)]
        cmds += [SetFaceOpacityCommand(faces, mat.opacity), SetFaceMaterialTagCommand(faces, mat.name, mat)]
    for g in groups:
        cmds.append(SetGroupMaterialCommand(g, mat.face_attrs()))
    return cmds, len(faces) + len(groups)


class DeleteMaterialCommand(Command):
    """Take an unused material out of the document's registry (undo puts it back as it was)."""

    def __init__(self, name) -> None:
        self.name = name
        self._old = None

    def do(self, scene) -> None:
        self._old = scene.materials.pop(self.name, None)
        scene.version += 1

    def undo(self, scene) -> None:
        if self._old is not None:
            scene.materials[self.name] = self._old
        scene.version += 1


def delete_material(app, name) -> bool:
    """Remove the material ``name`` from the document, one undo step. Only one that no face or object wears
    (it would leave them with a name that has no material); returns False when it is used or not there."""
    from . import materials as M
    scene = app.scene
    if name not in (getattr(scene, "materials", None) or {}):
        return False
    if M.used_materials(scene).get(name, 0):
        return False
    _run(app, [DeleteMaterialCommand(name)], name, None)
    return True


def _run(app, cmds, name, spec):
    vp = app.viewport
    spec_cmd = _spec_command(app, name, spec) if spec else None
    if spec_cmd is not None:
        cmds = cmds + [spec_cmd]
    vp.history.execute(cmds[0] if len(cmds) == 1 else CompoundCommand(cmds))
    if spec and spec_cmd is None:                    # an IngeTrazo without the command: its own step
        data = dict(app.document_data({}) or {})
        mats = dict(data.get("materials") or {})
        mats[name] = copy.deepcopy(spec)
        data["materials"] = mats
        app.set_document_data(data)
    notify = getattr(vp, "notify_scene_changed", None)
    if callable(notify):
        notify()
    vp.update()


def create_material(app, name, *, color=None, texture=None, opacity=None, apply=True, spec=None, finish=None):
    """A new material in the document, one undo step; painted on the selection when ``apply``.
    ``texture``: ``{"path", "sw", "sh"}`` (a picture), else ``color`` (RGB floats). Returns
    ``(final name, how many faces and objects it was painted on)``."""
    scene = app.scene
    name = unique_name(scene, name, _specs(app))
    mat = Material(name, color=None if texture else tuple(color or (0.8, 0.8, 0.8)),
                   texture=dict(texture) if texture else None, opacity=opacity, finish=finish)
    cmds = [SetFaceMaterialTagCommand([], name, mat)]        # an empty stamp only registers it
    painted = 0
    if apply:
        more, painted = paint_commands(scene, mat)
        cmds += more
    _run(app, cmds, name, spec)
    return name, painted


def duplicate_material(app, name, *, apply=False):
    """A copy of the material ``name`` (its colour or picture, translucency, finish and Render Studio
    settings) under a name of its own: ``name (2)``. One undo step; painted on the selection when
    ``apply``. Returns ``(new name, painted)`` or ``(None, 0)`` when the document has no such material."""
    scene = app.scene
    src = (getattr(scene, "materials", None) or {}).get(name)
    if src is None:
        return None, 0
    specs = _specs(app)
    new = unique_name(scene, name, specs)
    mat = Material(new, color=src.color, texture=copy.deepcopy(src.texture), opacity=src.opacity,
                   finish=getattr(src, "finish", None))
    cmds = [SetFaceMaterialTagCommand([], new, mat)]
    painted = 0
    if apply:
        more, painted = paint_commands(scene, mat)
        cmds += more
    spec = json.loads(json.dumps(specs[name])) if specs.get(name) else None
    _run(app, cmds, new, spec)
    return new, painted


def apply_to_selection(app, name):
    """Paint what is selected with the material ``name``, one undo step. Returns the count, or None
    when the document has no such material."""
    mat = (getattr(app.scene, "materials", None) or {}).get(name)
    if mat is None:
        return None
    cmds, painted = paint_commands(app.scene, mat)
    if cmds:
        _run(app, cmds, name, None)
    return painted


def arm_paint_bucket(app, name):
    """Make ``name`` the Paint tool's material and pick the tool: the next click on a face or an
    object paints it. Returns True, or False when there is no such material or no Paint tool."""
    mat = (getattr(app.scene, "materials", None) or {}).get(name)
    win = getattr(app, "window", None)
    if mat is None or win is None or not hasattr(win, "_activate_tool"):
        return False
    from tools.paint import PaintTool
    PaintTool.current_is_default = False
    PaintTool.current_texture_plane = None
    if mat.texture:
        PaintTool.current_texture = dict(mat.texture)
    else:
        PaintTool.current_texture = None
        PaintTool.current_color = tuple(mat.color or (1.0, 1.0, 1.0))
    PaintTool.current_opacity = mat.opacity
    PaintTool.current_material = mat
    win._activate_tool("paint")
    sync = getattr(getattr(getattr(win, "tray", None), "materials", None), "sync_from_paint", None)
    if callable(sync):
        sync()
    return True


# ---- a material in a file of its own -------------------------------------------------------------------
#
# IngeTrazo's own material file is the ``.igmat`` (a ZIP: ``material.json`` and ``textures/``). Render Studio's
# settings for the material travel in that same file, under the material's ``"render_studio"`` key, with the
# pictures of its maps in ``rs-maps/``. IngeTrazo reads past them (it takes only the keys it knows), so the file
# is also an ordinary material file for the palette's Import… and *My materials*. An IngeTrazo without
# ``formats.igmat`` writes the older ``.rsmat`` (JSON and a folder of pictures); every build still reads it, and
# the ``.skm`` material files IngeTrazo can import are read too (their colour or picture, no settings).

FILE_FORMAT = "render-studio-material"          # the older .rsmat
LEGACY_EXTENSION = ".rsmat"
IGMAT = ".igmat"
SKM = ".skm"
SETTINGS_KEY = "render_studio"
MAPS_DIR = "rs-maps/"
_EPOCH = (1980, 1, 1, 0, 0, 0)                  # fixed ZIP times: the same material gives the same bytes
_MAX_DOC = 8 << 20
_MAX_MAP = 256 << 20


def _igmat():
    """IngeTrazo's ``formats.igmat``, or None in a build that does not have it yet."""
    try:
        from formats import igmat
        return igmat
    except ImportError:
        return None


def extension() -> str:
    """The extension a saved material gets: ``.igmat``, or ``.rsmat`` in a build without material files."""
    return IGMAT if _igmat() is not None else LEGACY_EXTENSION


def save_filter() -> str:
    return ("IngeTrazo material (*.igmat)" if _igmat() is not None
            else f"Render Studio material (*{LEGACY_EXTENSION})")


def open_filter() -> str:
    if _igmat() is None:
        return f"Render Studio material (*{LEGACY_EXTENSION})"
    return ";;".join(("Material files (*.igmat *.skm *.rsmat)", "IngeTrazo material (*.igmat)",
                      "SKM material (*.skm)", f"Render Studio material (*{LEGACY_EXTENSION})"))


def _file_refs(spec) -> list:
    """The image files a material's Render Studio settings point to: ``[(holder dict, key)]``."""
    refs = []
    for m in ((spec or {}).get("maps") or {}).values():
        if isinstance(m, dict) and m.get("path"):
            refs.append((m, "path"))
    return refs


def _write_zip(path, entries) -> None:
    """``entries`` (``[(member, bytes, compress_type)]``) as the ZIP ``path``, atomically."""
    import os
    import zipfile
    from pathlib import Path
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w") as zf:
        for member, data, ctype in entries:
            info = zipfile.ZipInfo(member, date_time=_EPOCH)
            info.compress_type = ctype
            zf.writestr(info, data)
    os.replace(tmp, path)


def _add_settings(path, spec) -> None:
    """Put the Render Studio settings ``spec`` (its map pictures copied in) into the ``.igmat`` ``path``, as
    those of the one material it holds."""
    import zipfile
    from pathlib import Path
    maps = {}
    for i, (holder, key) in enumerate(_file_refs(spec)):
        src = Path(str(holder[key]))
        if src.is_file():
            member = f"{MAPS_DIR}map-{i + 1}{src.suffix.lower()}"
            maps[member] = src.read_bytes()
            holder[key] = member
    entries = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            data = zf.read(info)
            if info.filename == "material.json":
                payload = json.loads(data.decode("utf-8"))
                payload["materials"][0][SETTINGS_KEY] = spec
                data = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
            entries.append((info.filename, data, info.compress_type))
    entries += [(member, maps[member], zipfile.ZIP_STORED) for member in sorted(maps)]
    _write_zip(path, entries)


def _copy_beside(src, folder, stem, used):
    """Copy the image ``src`` into ``folder`` and return the file name it has there ('' when it cannot be)."""
    from pathlib import Path
    import shutil
    src = Path(str(src))
    if not src.is_file():
        return ""
    name = f"{stem}{src.suffix.lower()}"
    n = 2
    while name in used:
        name = f"{stem}-{n}{src.suffix.lower()}"
        n += 1
    used.add(name)
    shutil.copyfile(src, Path(folder) / name)
    return name


def _save_rsmat(app, name, path) -> str:
    """The older file, for an IngeTrazo without ``.igmat``: JSON, its pictures copied beside it in a folder of
    the same name so the file can be moved, shared and loaded in another drawing."""
    from pathlib import Path
    mat = app.scene.materials[name]
    path = Path(path)
    if path.suffix.lower() != LEGACY_EXTENSION:
        path = path.with_suffix(LEGACY_EXTENSION)
    path.parent.mkdir(parents=True, exist_ok=True)
    pics = path.with_suffix("")                      # <file>/ : the pictures
    used: set = set()
    spec = json.loads(json.dumps(_specs(app).get(name) or {}))
    data = {"format": FILE_FORMAT, "version": 1, "name": name, "opacity": mat.opacity,
            "finish": getattr(mat, "finish", None)}
    if mat.color is not None:
        data["color"] = [float(c) for c in mat.color[:3]]
    texture = copy.deepcopy(mat.texture) if mat.texture else None

    def keep(src, stem):
        if not Path(str(src)).is_file():
            return ""
        pics.mkdir(exist_ok=True)
        got = _copy_beside(src, pics, stem, used)
        return f"{pics.name}/{got}" if got else ""
    if texture and texture.get("path"):
        rel = keep(texture["path"], "picture")
        if rel:
            texture["path"] = rel
        data["texture"] = texture
    for i, (holder, key) in enumerate(_file_refs(spec)):
        rel = keep(holder[key], f"map-{i + 1}")
        if rel:
            holder[key] = rel
    if spec:
        data["settings"] = spec
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def save_material(app, name, path) -> str:
    """Write the material ``name`` (its colour or picture, translucency, finish and Render Studio settings) to
    ``path`` as an ``.igmat``, a single file with its pictures inside so it can be moved, shared and loaded in
    another drawing or opened by IngeTrazo itself. Returns the file written, or '' when the document has no
    such material."""
    from pathlib import Path
    mat = (getattr(app.scene, "materials", None) or {}).get(name)
    if mat is None:
        return ""
    igmat = _igmat()
    if igmat is None:
        return _save_rsmat(app, name, path)
    path = Path(path)
    if path.suffix.lower() != IGMAT:
        path = path.with_suffix(IGMAT)
    path.parent.mkdir(parents=True, exist_ok=True)
    igmat.save_materials(path, [mat])
    spec = json.loads(json.dumps(_specs(app).get(name) or {}))
    if spec:
        _add_settings(path, spec)
    return str(path)


def read_material(path) -> dict | None:
    """The older ``.rsmat`` file ``path`` as a dict with its pictures' paths made absolute; None when it is not
    one."""
    from pathlib import Path
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != FILE_FORMAT:
        return None

    def absolute(p):
        p = Path(str(p))
        return str(p if p.is_absolute() else (path.parent / p))
    if isinstance(data.get("texture"), dict) and data["texture"].get("path"):
        data["texture"]["path"] = absolute(data["texture"]["path"])
    for holder, key in _file_refs(data.get("settings")):
        holder[key] = absolute(holder[key])
    return data


def _read_settings(path) -> dict:
    """The Render Studio settings kept in the ``.igmat`` ``path``, ``{material name: settings}``, their map
    pictures taken out into IngeTrazo's texture cache (a picture the file lost keeps its path, which finds
    nothing)."""
    import zipfile
    from core.texture import cache_image
    out: dict = {}
    with zipfile.ZipFile(path) as zf:
        try:
            info = zf.getinfo("material.json")
            if info.file_size > _MAX_DOC:
                return out
            payload = json.loads(zf.read(info).decode("utf-8"))
        except (KeyError, ValueError):
            return out
        raws = payload.get("materials") if isinstance(payload, dict) else None
        for raw in raws if isinstance(raws, list) else []:
            if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                continue
            spec = raw.get(SETTINGS_KEY)
            if not isinstance(spec, dict) or not spec:
                continue
            for holder, key in _file_refs(spec):
                member = str(holder[key])
                if not member.startswith(MAPS_DIR):
                    continue
                try:
                    if zf.getinfo(member).file_size > _MAX_MAP:
                        continue
                    holder[key] = str(cache_image(zf.read(member), member.rsplit("/", 1)[-1], "embedded"))
                except (KeyError, OSError):
                    pass
            out.setdefault(raw["name"].strip(), spec)
    return out


def read_materials(path) -> list | None:
    """The materials in the file ``path`` (``.igmat``, ``.skm`` or the older ``.rsmat``) as
    ``[(Material, Render Studio settings or None)]``; None when it is not a material file this build reads."""
    import zipfile
    from pathlib import Path
    path = Path(path)
    ext = path.suffix.lower()
    try:
        if ext == LEGACY_EXTENSION:
            data = read_material(path)
            if data is None:
                return None
            color = data.get("color")
            mat = Material((data.get("name") or "Material"), color=tuple(color) if color else None,
                           texture=data.get("texture") or None, opacity=data.get("opacity"),
                           finish=data.get("finish") or None)
            return [(mat, data.get("settings") or None)]
        if ext == IGMAT:
            igmat = _igmat()
            if igmat is None:
                return None
            mats = igmat.load_materials(path)
            settings = _read_settings(path)
            return [(m, settings.get(m.name)) for m in mats]
        if ext == SKM:
            try:
                from formats.skm import load_skm
            except ImportError:
                return None
            return [(m, None) for m in load_skm(path)]
    except (OSError, ValueError, zipfile.BadZipFile):      # MaterialFileError and SkmError are ValueErrors
        return None
    return None


def load_materials(app, path) -> list:
    """Bring every material of the file ``path`` into the document, each under a name of its own (one undo step
    each; the selection is not painted). Returns the names, ``[]`` when it is not a material file."""
    found = read_materials(path)
    names = []
    for mat, spec in found or []:
        name, _n = create_material(app, mat.name or "Material", color=mat.color, texture=mat.texture,
                                   opacity=mat.opacity, apply=False, spec=spec, finish=mat.finish)
        names.append(name)
    return names


def load_material(app, path):
    """The first material of the file ``path`` brought into the document (see :func:`load_materials`).
    Returns ``(name, 0)`` or ``(None, 0)`` when it is not a material file."""
    names = load_materials(app, path)
    return (names[0], 0) if names else (None, 0)


def set_material_picture(app, name, path, width=1.0):
    """A picture for the material ``name``, which is a flat colour so far, everywhere it is worn (one undo step).
    The picture repeats every ``width`` metres, its height following its proportions. Returns ``(done, message)``.
    A material that has a picture already changes it with ``texture_swap.swap_picture``."""
    from pathlib import Path
    from core.history import RestampMaterialCommand
    from core.texture import cache_image, is_image_file
    from PySide6.QtGui import QImage
    from .i18n import tr
    mat = (getattr(app.scene, "materials", None) or {}).get(name)
    if mat is None:
        return False, tr("Choose a material of the model first.")
    if mat.texture:
        return False, tr("«{name}» has a picture already: change it instead.", name=name)
    p = Path(path)
    if not is_image_file(p):
        return False, tr("{name} is not an image IngeTrazo can read.", name=p.name)
    try:
        cached = cache_image(p.read_bytes(), p.name, "imported")      # the model does not depend on the file staying put
    except OSError as exc:
        return False, tr("Could not read {name}: {error}", name=p.name, error=exc)
    img = QImage(str(cached))
    ratio = img.height() / img.width() if not img.isNull() and img.width() else 1.0
    sw = max(0.01, float(width))
    new = Material(name, color=None, texture={"path": str(cached), "sw": round(sw, 3), "sh": round(sw * ratio, 3)},
                   opacity=mat.opacity, finish=getattr(mat, "finish", None))
    vp = app.viewport
    vp.history.execute(RestampMaterialCommand(name, new))
    notify = getattr(vp, "notify_scene_changed", None)
    if callable(notify):
        notify()
    vp.update()
    return True, tr("«{name}» now uses {file}, on every face that wears it. One undo step.", name=name, file=p.name)


def set_texture_size(app, name, width, height):
    """How big the picture of the material ``name`` is on the model (metres), on every face and object that wears
    it, one undo step; each face keeps its own turn, tint and placement. Returns True when it changed."""
    from core.history import EditTexturedMaterialCommand
    mat = (getattr(app.scene, "materials", None) or {}).get(name)
    if mat is None or not mat.texture:
        return False
    tex = mat.texture
    sw, sh = max(0.01, float(width)), max(0.01, float(height))
    if abs(sw - float(tex.get("sw", 1.0))) < 1e-6 and abs(sh - float(tex.get("sh", 1.0))) < 1e-6:
        return False
    vp = app.viewport
    vp.history.execute(EditTexturedMaterialCommand(name, tex.get("tint"), tex.get("tint_mode", 0),
                                                   (sw, sh, float(tex.get("rot", 0.0) or 0.0))))
    notify = getattr(vp, "notify_scene_changed", None)
    if callable(notify):
        notify()
    vp.update()
    return True


def set_material_colour(app, name, rgb, force=False):
    """The flat colour of the material ``name`` changed everywhere it is worn (every face and object, nested
    ones too), one undo step. A material with a picture is left alone, unless ``force``: it then becomes a flat
    colour. Returns True when it changed."""
    from core.history import RestampMaterialCommand
    mat = (getattr(app.scene, "materials", None) or {}).get(name)
    if mat is None or (mat.texture and not force):
        return False
    rgb = tuple(float(c) for c in rgb[:3])
    new = Material(name, color=rgb, opacity=mat.opacity, finish=getattr(mat, "finish", None))
    vp = app.viewport
    vp.history.execute(RestampMaterialCommand(name, new))
    notify = getattr(vp, "notify_scene_changed", None)
    if callable(notify):
        notify()
    vp.update()
    return True
