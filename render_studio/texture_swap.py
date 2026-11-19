# SPDX-License-Identifier: GPL-3.0-or-later
"""Change the picture of an IngeTrazo material, in the model.

IngeTrazo already edits a material everywhere it is worn (every loose face,
every face inside nested components, every object painted whole) as one undo
step, keeping each face's own texture placement: ``EditTexturedMaterialCommand``.
It changes the colour and the tile size, not the image. This subclass changes
the image, with the same reach and the same undo; the placement of each face
(``uvw``, ``rot``) is kept, and so is the tint, re-applied to the new image.
"""
from __future__ import annotations

import logging
from pathlib import Path

from core.history import EditTexturedMaterialCommand

_log = logging.getLogger(__name__)


def _image_size(path, cache: dict):
    """(width, height) of an image file, or None."""
    if not path:
        return None
    key = str(path)
    if key not in cache:
        from PySide6.QtGui import QImage
        img = QImage(key)
        cache[key] = None if img.isNull() or img.width() <= 0 else (img.width(), img.height())
    return cache[key]


class ReplaceTextureImageCommand(EditTexturedMaterialCommand):
    """Swap the image of the textured material ``name`` for ``new_path``
    everywhere it is worn. ``keep_proportions``: the tile height follows the
    new image's proportions (each face keeps the stretch it had); otherwise
    every tile size stays as it was and a different shape is squeezed."""

    def __init__(self, name, new_path, keep_proportions: bool = True) -> None:
        super().__init__(name, None, 0, None)
        self._new_path = str(new_path)
        self._keep = bool(keep_proportions)
        self._sizes: dict = {}

    def edited(self, tex):
        if not tex:
            return tex
        from core.texture import tinted_texture, untinted_texture
        tint = tex.get("tint")
        mode = int(tex.get("tint_mode") or 0)
        old_image = tex.get("base") or tex.get("path")
        out = untinted_texture(dict(tex))
        out["path"] = self._new_path
        if self._keep:
            old = _image_size(old_image, self._sizes)
            new = _image_size(self._new_path, self._sizes)
            if old and new:
                factor = (new[1] / new[0]) / (old[1] / old[0])
                out["sh"] = float(tex.get("sh", 1.0)) * factor
        if tint is not None and tex.get("base"):
            out = tinted_texture(out, tint, mode)
        return out


def material_picture(scene, name):
    """The picture path of the registry material ``name`` (its untinted
    image), or None when it has none."""
    mat = scene.materials.get(name) if name else None
    tex = getattr(mat, "texture", None) or {}
    return tex.get("base") or tex.get("path")


def swap_picture(app, name, path, keep_proportions: bool = True) -> tuple[bool, str]:
    """Replace the picture of material ``name`` with the image file ``path``,
    as one undo step. Returns (done, message for the user)."""
    from core.texture import cache_image, is_image_file
    scene = app.scene
    mat = scene.materials.get(name) if name else None
    if mat is None:
        return False, "Choose a material of the model first."
    if not mat.texture:
        return False, (f"«{name}» has no picture, only a colour. Paint it with a texture "
                       f"first; then its picture can be changed here.")
    p = Path(path)
    if not is_image_file(p):
        return False, f"{p.name} is not an image IngeTrazo can read."
    try:
        # Into IngeTrazo's texture cache, as its own import does: the model then
        # does not depend on the file staying where it was.
        cached = cache_image(p.read_bytes(), p.name, "imported")
    except OSError as exc:
        return False, f"Could not read {p.name}: {exc}"
    vp = app.viewport
    try:
        vp.history.execute(ReplaceTextureImageCommand(name, cached, keep_proportions))
    except Exception as exc:  # noqa: BLE001 - say it, never crash the app
        _log.exception("could not replace the picture of %s", name)
        return False, f"Could not change the picture: {exc}"
    notify = getattr(vp, "notify_scene_changed", None)
    if callable(notify):
        notify()
    vp.update()
    return True, f"«{name}» now uses {p.name}, on every face that wears it. One undo step."
