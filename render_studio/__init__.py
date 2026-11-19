# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Studio: Enscape-like looks for IngeTrazo's Blender render.

Looks (clear day, partly cloudy, golden hour, overcast, white model,
interior, night) with clouds, the sun's colour, automatic exposure and a
photographic finish; then live adjustments of the image (exposure,
contrast, saturation, warmth, vignette) without rendering again.

It drives the same Blender IngeTrazo's Render tab found, with IngeTrazo's
own scene script plus ``blender/studio_scene.py`` for the look.
"""
from __future__ import annotations

__version__ = "0.5.0"

import logging
import os

_log = logging.getLogger(__name__)


def setup(app):
    if getattr(app, "api_version", 0) < 2:
        raise RuntimeError("Requires IngeTrazo with Extension API 2")
    from .panel import StudioPanel
    panel = StudioPanel(app)
    dock = app.add_panel("Render Studio", panel, start_hidden=True)
    app.add_menu_action("Render Studio…", lambda: app.show_panel(dock),
                        tip="Enscape-like renders: looks, auto exposure, clouds, live adjustments.")
    app.add_menu_action("Render Studio materials…", panel.open_materials,
                        tip="How each material renders: polish, metal, relief, glass, glow.")
    if hasattr(app, "on_document_changed"):
        app.on_document_changed(panel.document_changed)
    if os.environ.get("RENDER_STUDIO_SELFTEST"):
        from . import selftest
        selftest.schedule(app, panel, os.environ["RENDER_STUDIO_SELFTEST"])
