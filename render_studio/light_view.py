# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Studio's lights in IngeTrazo's 3D view.

* An overlay draws every light: a bulb for a point light, a cone for a spot,
  the outline of an area light and the way it faces, a sun's incoming rays.
  Its colour is the light's, grey when it is off; the one chosen in the
  Lights tab is ringed and named.
* The Select tool picks them (``add_pickable``) and Supr deletes them.
* A one-click tool places, moves or aims a light: it gives the snapped point,
  the face under it (its normal, turned toward the camera) and the object
  that face belongs to.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF

from . import lights as L

PICK_PX = 12.0
SELECTED = QColor(54, 137, 230)
VIEW_PICK = QColor(242, 115, 41)


def _project(viewport, pts):
    import numpy as np
    px, py, front = viewport.world_to_pixels(np.asarray(pts, dtype=float).reshape(-1, 3))
    return [(float(a), float(b)) if f else None for a, b, f in zip(px, py, front)]


def _tint(light) -> QColor:
    if not light["on"]:
        return QColor(150, 150, 150)
    r, g, b = light["color"]
    return QColor.fromRgbF(r, g, b)


def _label(light, n: int) -> str:
    kinds = {"point": "Point light", "spot": "Spot", "area": "Area light", "sun": "Sun"}
    return f"{light['name'] or kinds[light['type']] + ' ' + str(n)} · {L.power_label(light)}"


def draw(tab, viewport, painter) -> None:
    """The overlay: every light of the document over the model."""
    if not tab.show_in_view():
        return
    entries = L.all_lights(viewport.scene)
    if not entries:
        return
    chosen = tab.selected_key()
    picked = tab.view_pick
    painter.setRenderHint(QPainter.Antialiasing)
    font = QFont()
    font.setPointSize(8)
    painter.setFont(font)
    for n, e in enumerate(entries, 1):
        lt = e["world"]
        tint = _tint(lt)
        marker = _project(viewport, [lt["pos"]])[0]
        # The shape in the world: cone, outline, rays.
        pen = QPen(tint.darker(125), 1.4, Qt.DashLine if e["source"] == "tab" else Qt.SolidLine)
        if e["key"] == chosen:
            pen = QPen(SELECTED, 1.8)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for pts, closed in L.gizmo_lines(lt):
            scr = _project(viewport, pts)
            if any(p is None for p in scr):
                continue
            poly = QPolygonF([QPointF(*p) for p in scr])
            if closed:
                painter.drawPolygon(poly)
            else:
                painter.drawPolyline(poly)
        if marker is None:
            continue
        c = QPointF(*marker)
        painter.setPen(QPen(QColor(40, 40, 40), 1.2))
        painter.setBrush(tint)
        kind = lt["type"]
        if kind == "area":
            painter.drawRect(int(c.x() - 5), int(c.y() - 5), 10, 10)
        elif kind == "spot":
            painter.drawPolygon(QPolygonF([QPointF(c.x(), c.y() - 7), QPointF(c.x() + 6, c.y() + 5),
                                           QPointF(c.x() - 6, c.y() + 5)]))
        else:
            painter.drawEllipse(c, 6.0, 6.0)
        if kind in ("point", "sun"):
            rays, inner, outer = (8, 8, 11) if kind == "point" else (12, 9, 15)
            painter.setPen(QPen(tint.darker(140), 1.4))
            for k in range(rays):
                a = 2 * math.pi * k / rays
                painter.drawLine(QPointF(c.x() + inner * math.cos(a), c.y() + inner * math.sin(a)),
                                 QPointF(c.x() + outer * math.cos(a), c.y() + outer * math.sin(a)))
        if e["source"] == "object":
            # A light on an object: a small link mark.
            painter.setPen(QPen(QColor(40, 40, 40), 1.0))
            painter.setBrush(QColor(255, 255, 255))
            painter.drawEllipse(QPointF(c.x() + 7, c.y() + 7), 3.0, 3.0)
        if e["key"] == picked:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(VIEW_PICK, 3.0))
            painter.drawEllipse(c, 15.0, 15.0)
        if e["key"] == chosen:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(SELECTED, 2.0))
            painter.drawEllipse(c, 14.0, 14.0)
            painter.setPen(QPen(QColor(20, 20, 20)))
            painter.drawText(QPointF(c.x() + 16, c.y() - 10), _label(lt, n))


def pick(tab, viewport, px: float, py: float):
    """The key of the light whose marker is under the pixel, or None."""
    if not tab.show_in_view():
        return None
    entries = L.all_lights(viewport.scene)
    if not entries:
        return None
    scr = _project(viewport, [e["world"]["pos"] for e in entries])
    best, best_d = None, PICK_PX
    for e, p in zip(entries, scr):
        if p is None:
            continue
        d = math.hypot(p[0] - px, p[1] - py)
        if d <= best_d:
            best, best_d = e["key"], d
    return best


def face_under(viewport, x: float, y: float):
    """``(normal, owner)`` at a pixel: the world normal of the face there, turned
    toward the camera, and the top-level object it belongs to (None for the
    loose model). ``(None, None)`` over empty space."""
    normal, owner = None, None
    try:
        face, place = viewport.pick_face_placement(x, y)
        _f, owner = viewport.pick_face_any(x, y)
        if face is not None:
            n = face.normal()
            m = getattr(place, "xform", None) if place is not None else None
            if m is not None:
                n = m.mapVector(n)
            n = [n.x(), n.y(), n.z()]
            length = math.sqrt(sum(c * c for c in n))
            if length > 1e-9:
                n = [c / length for c in n]
                _o, ray = viewport._pixel_to_ray(x, y)
                if ray is not None and n[0] * ray.x() + n[1] * ray.y() + n[2] * ray.z() > 0:
                    n = [-c for c in n]
                normal = n
    except Exception:  # noqa: BLE001 - an older viewport: the point alone
        normal, owner = None, None
    scene = getattr(viewport, "scene", None)
    if owner is not None and scene is not None and owner not in (getattr(scene, "groups", None) or ()):
        owner = getattr(owner, "owner", None) or None
        if owner is not None and owner not in scene.groups:
            owner = None
    return normal, owner


def make_pick_tool(prompt: str, done, cancelled):
    """A one-click tool: ``done(point, normal, owner)`` with the SNAPPED point
    (an endpoint, a ceiling), the face's normal there (or None) and its object;
    ``cancelled()`` on Esc. Built on demand: a module-level Tool would get its
    own entry in the Extensions menu."""
    from tools.base import Tool

    class _PlaceLight(Tool):
        name = prompt
        shortcut = None
        uses_snap = True

        def __init__(self) -> None:
            self.hover_point = None

        def on_activate(self, viewport) -> None:
            self.hover_point = None

        def on_deactivate(self, viewport) -> None:
            self.hover_point = None

        def on_hover(self, ctx) -> None:
            self.hover_point = ctx.world
            ctx.viewport.update()

        def on_click(self, ctx) -> None:
            normal, owner = face_under(ctx.viewport, ctx.screen.x(), ctx.screen.y())
            w = ctx.world
            done([w.x(), w.y(), w.z()], normal, owner)

        def on_key(self, viewport, key, modifiers) -> bool:
            if key == Qt.Key_Escape:
                cancelled()
                return True
            return False

        def rubber_band_lines(self):
            return []

    return _PlaceLight()
