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
from core.history import (CompoundCommand, SetFaceColorCommand, SetFaceMaterialTagCommand,
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


def create_material(app, name, *, color=None, texture=None, opacity=None, apply=True, spec=None):
    """A new material in the document, one undo step; painted on the selection when ``apply``.
    ``texture``: ``{"path", "sw", "sh"}`` (a picture), else ``color`` (RGB floats). Returns
    ``(final name, how many faces and objects it was painted on)``."""
    scene = app.scene
    name = unique_name(scene, name, _specs(app))
    mat = Material(name, color=None if texture else tuple(color or (0.8, 0.8, 0.8)),
                   texture=dict(texture) if texture else None, opacity=opacity)
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
