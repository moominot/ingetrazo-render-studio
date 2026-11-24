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

__version__ = "0.28.1"

import logging
import os

_log = logging.getLogger(__name__)


def setup(app):
    if getattr(app, "api_version", 0) < 2:
        raise RuntimeError("Requires IngeTrazo with Extension API 2")
    from .i18n import tr, translate_on_show
    from .icons import panel_icon
    from .panel import StudioPanel
    panel = StudioPanel(app)
    translate_on_show(panel)
    dock = app.add_panel(tr("Render Studio"), panel, start_hidden=True,
                         **panel_icon(app, "render_studio"))
    app.add_menu_action(tr("Render Studio…"), lambda: app.show_panel(dock),
                        tip=tr("Photographic renders: looks, auto exposure, clouds, live adjustments."))
    app.add_menu_action(tr("Render Studio materials…"), panel.open_materials,
                        tip=tr("How each material renders: polish, metal, relief, glass, glow."))
    if hasattr(app, "on_document_changed"):
        app.on_document_changed(panel.document_changed)

    # The lights in the 3D view: drawn over the model, picked by the Select tool, Supr deletes.
    from . import light_view

    app.add_menu_action(tr("Render Studio lights…"), panel.open_lights,
                        tip=tr("Point, spot, area and sun lights for the render, placed in the model."))
    tab = panel.lights_tab
    if hasattr(app, "add_overlay"):
        app.add_overlay(lambda viewport, painter: light_view.draw(tab, viewport, painter))
    if hasattr(app, "add_pickable"):
        app.add_pickable(pick=lambda viewport, px, py: light_view.pick(tab, viewport, px, py),
                         on_select=tab.on_view_pick, delete=tab.delete_key)
    if os.environ.get("RENDER_STUDIO_SELFTEST"):
        from . import selftest
        selftest.schedule(app, panel, os.environ["RENDER_STUDIO_SELFTEST"])
