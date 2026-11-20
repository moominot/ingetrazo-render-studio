# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Studio's own writes into the document (its settings, the materials' settings).

They go through IngeTrazo's ``set_document_data`` (one undo step), which bumps the document's
version like any edit. The live view reads that version as «the model changed» and exports the
whole model again: with a 588 000-face model, every slider of the material editor started a
new export. These writes are not the model's (the model file does not change; the look and
the materials' settings travel in the job), so the command marks its bump as ours, as
``light_ops.LightsCommand`` does for the lights: see ``panel.live_model_key`` and
``materials.model_version``.
"""
from __future__ import annotations

from .light_ops import _not_model

try:
    from core.history import SetPluginDataCommand as _Base
except Exception:  # noqa: BLE001 - an old IngeTrazo: no such command, the plain call is used
    _Base = None

if _Base is not None:
    class StudioDataCommand(_Base):
        """``SetPluginDataCommand`` that does not count as a change of the model."""

        def do(self, scene) -> None:
            super().do(scene)
            _not_model(scene)

        def undo(self, scene) -> None:
            super().undo(scene)
            _not_model(scene)


def write(app, value) -> None:
    """``app.set_document_data(value)``, as one undo step, without it counting as a change of
    the model. Falls back to the plain call where the extension handle is not IngeTrazo's."""
    if _Base is None:
        app.set_document_data(value)
        return
    try:
        vp = app.viewport
        key = app.key
        history = vp.history
    except AttributeError:
        app.set_document_data(value)
        return
    history.execute(StudioDataCommand(key, value))
    notify = getattr(vp, "notify_scene_changed", None)
    if callable(notify):
        notify()
    vp.update()
