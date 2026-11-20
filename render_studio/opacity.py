# SPDX-License-Identifier: GPL-3.0-or-later
"""Set the transparency of an IngeTrazo material, in the model.

In IngeTrazo, how much a material lets light through is its opacity: a value
on the registry material and on every face (and every object painted whole)
that wears it. This command changes it everywhere at once, as one undo step,
the same way IngeTrazo's own «edit a material everywhere» does, so the 3D view
and the render (which read the same value) agree.
"""
from __future__ import annotations

import logging

from core.history import RestampMaterialCommand

_log = logging.getLogger(__name__)

MIN_OPACITY = 0.05          # a fully invisible material cannot be picked in the view


def clean_opacity(opacity):
    """None (opaque) or a value in [MIN_OPACITY, 0.999]."""
    if opacity is None:
        return None
    o = float(opacity)
    return None if o >= 0.999 else round(max(MIN_OPACITY, o), 3)


class SetMaterialOpacityCommand(RestampMaterialCommand):
    """Make the material ``name`` more or less transparent (``opacity`` 1 =
    opaque) on the registry entry, every face and every object painted whole."""

    def __init__(self, name, opacity) -> None:
        super().__init__(name, None)
        self._opacity = clean_opacity(opacity)

    def _edit(self, attrs: dict) -> dict:
        out = dict(attrs)
        if self._opacity is None:
            out.pop("opacity", None)
        else:
            out["opacity"] = self._opacity
        return out

    def do(self, scene) -> None:
        from core.history import _dirty_group_chunks
        from core.materials import Material
        if self._old_faces is None:
            self._old_material = scene.materials.get(self._name)
            self._old_faces = [(f, {k: f.attrs.get(k) for k in self._KEYS})
                               for f in self._targets(scene)]
            self._old_groups = [(g, g.material) for g in self._painted_groups(scene)]
            old = self._old_material
            self._new = (Material(self._name, color=old.color, texture=old.texture,
                                  opacity=self._opacity, finish=old.finish)
                         if old is not None else None)
        if not hasattr(self, "_glass"):
            from .materials import material_kind
            # A glass material is made see-through by its own Transparency setting (the opacity the
            # model gave it is not read), so this is no change of the model for the live view.
            self._glass = material_kind(scene, self._name) == "glass"
        if self._new is not None:
            scene.materials[self._name] = self._new
        for f, _before in self._old_faces:
            if self._opacity is None:
                f.attrs.pop("opacity", None)
            else:
                f.attrs["opacity"] = self._opacity
        for g, before in self._old_groups or []:
            if isinstance(before, dict):
                g.material = self._edit(before)
        self._count_meshes(scene)
        _dirty_group_chunks(scene)
        scene.version += 1
        if self._glass:
            from .light_ops import _not_model
            _not_model(scene)

    def undo(self, scene) -> None:
        from core.history import _dirty_group_chunks
        if self._old_faces is None:
            return
        if self._old_material is None:
            scene.materials.pop(self._name, None)
        else:
            scene.materials[self._name] = self._old_material
        for f, old in self._old_faces:
            for k in self._KEYS:
                if old[k] is None:
                    f.attrs.pop(k, None)
                else:
                    f.attrs[k] = old[k]
        for g, old in self._old_groups or []:
            g.material = old
        self._count_meshes(scene)
        _dirty_group_chunks(scene)
        scene.version += 1
        if getattr(self, "_glass", False):
            from .light_ops import _not_model
            _not_model(scene)


def material_opacity(scene, name):
    """The opacity of the registry material ``name`` (1 = opaque)."""
    mat = scene.materials.get(name) if name else None
    o = getattr(mat, "opacity", None) if mat is not None else None
    return 1.0 if o is None else float(o)


def set_opacity(app, name, opacity) -> tuple[bool, str]:
    """Apply the new opacity to material ``name`` as one undo step."""
    scene = app.scene
    if not name:
        return False, "Choose a material of the model first."
    new = clean_opacity(opacity)
    if abs((1.0 if new is None else new) - material_opacity(scene, name)) < 1e-6 and name in scene.materials:
        return True, ""                                   # nothing to change
    vp = app.viewport
    try:
        vp.history.execute(SetMaterialOpacityCommand(name, opacity))
    except Exception as exc:  # noqa: BLE001 - say it, never crash the app
        _log.exception("could not change the opacity of %s", name)
        return False, f"Could not change the transparency: {exc}"
    notify = getattr(vp, "notify_scene_changed", None)
    if callable(notify):
        notify()
    vp.update()
    pct = round((1.0 - (1.0 if new is None else new)) * 100)
    return True, f"«{name}» is now {pct} % transparent, in the model and in the render. One undo step."
