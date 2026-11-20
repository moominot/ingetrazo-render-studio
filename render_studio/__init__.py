# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Studio: Enscape-like looks for IngeTrazo's Blender render.

Looks (clear day, partly cloudy, golden hour, overcast, white model,
interior, night) with clouds, the sun's colour, automatic exposure and a
photographic finish; then live adjustments of the image (exposure,
contrast, saturation, warmth, vignette) without rendering again.

It drives the same Blender IngeTrazo's Render tab found, with IngeTrazo's
own scene script plus ``blender/studio_scene.py`` for the look. Proxies
(light stand-ins whose full model is in an .igz of its own) are rendered as
their full models, placed by Blender as instances (proxies.py).
"""
from __future__ import annotations

__version__ = "0.16.2"

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
                        tip="Photographic renders: looks, auto exposure, clouds, live adjustments.")
    app.add_menu_action("Render Studio materials…", panel.open_materials,
                        tip="How each material renders: polish, metal, relief, glass, glow.")
    if hasattr(app, "on_document_changed"):
        app.on_document_changed(panel.document_changed)

    # The lights in the 3D view: drawn over the model, picked by the Select tool, Supr deletes.
    from . import light_view

    def show_lights():
        app.show_panel(dock)
        panel.tabs.setCurrentWidget(panel.tabs.widget(1))

    app.add_menu_action("Render Studio lights…", show_lights,
                        tip="Point, spot, area and sun lights for the render, placed in the model.")
    tab = panel.lights_tab
    if hasattr(app, "add_overlay"):
        app.add_overlay(lambda viewport, painter: light_view.draw(tab, viewport, painter))
    if hasattr(app, "add_pickable"):
        app.add_pickable(pick=lambda viewport, px, py: light_view.pick(tab, viewport, px, py),
                         on_select=tab.on_view_pick, delete=tab.delete_key)
    if os.environ.get("RENDER_STUDIO_SELFTEST"):
        from . import selftest
        selftest.schedule(app, panel, os.environ["RENDER_STUDIO_SELFTEST"])
