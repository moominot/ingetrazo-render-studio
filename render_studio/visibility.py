# SPDX-License-Identifier: GPL-3.0-or-later
"""What is hidden in the drawing stays out of the model file sent to Blender.

IngeTrazo's export asks ``scene.entity_visible`` for the loose faces and the top-level
objects only. A hidden object NESTED in another (a component inside a component), one
on a hidden tag, and a face hidden inside an object were written all the same, so the
preview and the render showed what the 3D view does not. While the model file is
written (:class:`hidden_left_out`):

* a nested placement the 3D view leaves out (``core.group.visible_placements``: hidden,
  or on a hidden tag, or under one) is taken off its parent's children;
* a face hidden with Hide (``attrs["hidden"]``) is not written, wherever it is.

Both are put back as they were; nothing reaches the undo history or the drawing's version.
The model file is smaller, and the live view's export faster.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def hidden_placements(scene) -> list:
    """``[(parent, kept_children)]``: every placement with a nested child the 3D view does not
    draw, with the children it does. Empty when nothing nested is hidden."""
    from core.group import iter_placements, visible_placements
    out = []
    for top in getattr(scene, "groups", None) or ():
        if not scene.entity_visible(top):
            continue                              # the export skips it whole
        shown = {id(p) for p, _m in visible_placements(scene, top)}
        for p, _m in list(iter_placements(top)):
            kids = getattr(p, "children", None)
            if kids and any(id(c) not in shown for c in kids):
                out.append((p, [c for c in kids if id(c) in shown]))
    return out


class hidden_left_out:
    def __init__(self, scene):
        self.scene = scene
        self.detached = []                        # (placement, its original children)
        self.saved = None

    def __enter__(self):
        try:
            for p, kept in hidden_placements(self.scene):
                self.detached.append((p, p.children))
                p.children = kept
            import formats.meshexport as me
            real = self.saved = me._add_face

            def add_face(face, materials, prims, attrs=None, smoother=None):
                if (getattr(face, "attrs", None) or {}).get("hidden"):
                    return None
                return real(face, materials, prims, attrs, smoother)
            me._add_face = add_face
        except Exception:  # noqa: BLE001 - never stops a render: what the export would write anyway
            _log.exception("hidden objects not left out")
            self.__exit__()
        return self

    def __exit__(self, *exc):
        for p, children in self.detached:
            p.children = children
        self.detached = []
        if self.saved is not None:
            import formats.meshexport as me
            me._add_face = self.saved
            self.saved = None
        return False
