# SPDX-License-Identifier: GPL-3.0-or-later
"""A quick preview of a material on a one-metre cube, drawn on the CPU.

Meant to give an idea while the sliders move, instantly and without Blender.
It is an approximation: the texture and its tile size, the colour, how polished
or metallic the surface is, glass and water as see-through, a glow halo and a
fine relief. It does not read the maps (roughness, metal, relief, glow images)
nor light the cube as Blender will; the render is the reference.
"""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF, QRadialGradient, QTransform)

# Light from the upper left: how much each visible face receives.
_SHADE = {"top": 1.0, "left": 0.78, "right": 0.55}
_noise_cache: dict = {}


def _noise(size: int = 64) -> QImage:
    """A tiny, deterministic grain (the same every time)."""
    if size not in _noise_cache:
        img = QImage(size, size, QImage.Format_ARGB32)
        seed = 12345
        for y in range(size):
            for x in range(size):
                seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
                v = (seed >> 16) & 0xFF
                img.setPixelColor(x, y, QColor(v, v, v, 255))
        _noise_cache[size] = img
    return _noise_cache[size]


def _geometry(size: int):
    """The three faces as polygons and the affine maps unit square → face."""
    s = size
    e = s * 0.22
    cx, cy = s / 2, s * 0.50
    dx, dy = e * math.sqrt(3), e
    h = 2 * e
    top = QPointF(cx, cy - h)
    left_top = QPointF(cx - dx, cy - h + dy)
    right_top = QPointF(cx + dx, cy - h + dy)
    center = QPointF(cx, cy - h + 2 * dy)
    left_bot = QPointF(cx - dx, cy + dy)
    right_bot = QPointF(cx + dx, cy + dy)
    bottom = QPointF(cx, cy + 2 * dy)
    faces = {
        # unit square (0,0)-(1,0)-(1,1)-(0,1) → polygon
        "top": (top, right_top, center, left_top),
        "left": (left_top, center, bottom, left_bot),
        "right": (center, right_top, right_bot, bottom),
    }
    maps = {}
    for name, (p0, p1, p2, p3) in faces.items():
        # QTransform maps (x, y) → (m11 x + m21 y + dx, m12 x + m22 y + dy)
        ux, uy = p1.x() - p0.x(), p1.y() - p0.y()
        vx, vy = p3.x() - p0.x(), p3.y() - p0.y()
        maps[name] = QTransform(ux, uy, vx, vy, p0.x(), p0.y())
    return faces, maps, (cx, cy + dy, dx, e)


def render(params: dict, size: int = 180) -> QPixmap:
    """The preview as a ``size``-px square pixmap (transparent around the cube).

    ``params``: ``color`` (r, g, b in 0-1) or None; ``texture`` (image path),
    ``tile`` ((sw, sh) metres); ``kind`` generic/glass/water/glow/grass; ``roughness``,
    ``metallic``, ``bump`` (0-1) and ``glow`` (0-50)."""
    kind = params.get("kind", "generic")
    rough = max(0.0, min(1.0, float(params.get("roughness", 0.5))))
    metal = max(0.0, min(1.0, float(params.get("metallic", 0.0))))
    bump = max(0.0, min(1.0, float(params.get("bump", 0.0))))
    glow = max(0.0, float(params.get("glow", 0.0))) if kind == "glow" else 0.0
    color = params.get("color") or (0.8, 0.8, 0.8)
    base = QColor.fromRgbF(*[max(0.0, min(1.0, float(c))) for c in tuple(color)[:3]])
    alpha = max(0.05, min(1.0, float(params.get("opacity", 1.0))))
    clear = kind in ("glass", "water") or alpha < 0.97

    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    faces, maps, (gx, gy, gdx, ge) = _geometry(size)

    # the ground it stands on: a soft contact shadow
    shadow = QRadialGradient(QPointF(gx, gy + ge * 0.35), gdx * 1.15)
    shadow.setColorAt(0.0, QColor(0, 0, 0, 90))
    shadow.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(shadow))
    p.drawEllipse(QPointF(gx, gy + ge * 0.35), gdx * 1.15, ge * 0.75)

    # a glow lights up the air around it
    if glow > 0.0:
        k = min(1.0, glow / 20.0)
        halo = QRadialGradient(QPointF(size / 2, size * 0.50), size * 0.55)
        c = QColor(base)
        c.setAlphaF(0.85 * k)
        halo.setColorAt(0.25, c)
        c2 = QColor(base)
        c2.setAlphaF(0.0)
        halo.setColorAt(1.0, c2)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(size / 2, size * 0.50), size * 0.55, size * 0.55)

    # see-through materials show a light checkerboard through the cube
    if clear:
        cell = max(6, size // 18)
        p.save()
        p.setClipRegion(_union_region(faces))
        for y in range(0, size, cell):
            for x in range(0, size, cell):
                shade = 215 if ((x // cell) + (y // cell)) % 2 == 0 else 240
                p.fillRect(QRectF(x, y, cell, cell), QColor(shade, shade, shade))
        p.restore()

    texture = _load_texture(params.get("texture"))
    sw, sh = params.get("tile") or (1.0, 1.0)
    sw, sh = max(0.01, float(sw)), max(0.01, float(sh))

    face_alpha = (alpha if alpha < 0.97 else 0.35) if clear else 1.0
    for name in ("left", "right", "top"):
        poly = QPolygonF(list(faces[name]))
        tf = maps[name]
        p.save()
        p.setClipRegion(_region(poly))
        p.setOpacity(face_alpha)
        if texture is not None:
            # the cube is 1 m: the image repeats 1/sw by 1/sh times over a face
            brush = QBrush(texture)
            brush.setTransform(_tile_to_face(tf, sw, sh, texture))
            p.setBrush(brush)
            p.setPen(Qt.NoPen)
            p.drawPolygon(poly)
        else:
            p.setBrush(base)
            p.setPen(Qt.NoPen)
            p.drawPolygon(poly)
        p.setOpacity(1.0)
        # the face's own light
        dark = int(255 * (1.0 - _SHADE[name]) * (1.0 - 0.6 * min(1.0, glow / 10.0)))
        p.setBrush(QColor(0, 0, 0, int(dark * (0.5 if clear else 1.0))))
        p.drawPolygon(poly)
        # a fine relief: grain, stronger with the slider
        if bump > 0.0:
            if texture is not None:
                # relief from the picture itself: its light and dark, lit from the
                # upper left (what the render reads), over the same tiles
                relief = QBrush(_emboss(texture, params.get("texture")))
                relief.setTransform(_tile_to_face(tf, sw, sh, texture))
                p.setCompositionMode(QPainter.CompositionMode_HardLight)
                p.setOpacity(min(1.0, 1.1 * bump))
                p.setBrush(relief)
                p.drawPolygon(poly)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            else:
                grain = QBrush(_noise())
                grain.setTransform(QTransform.fromScale(1.4, 1.4))
                p.setOpacity(0.28 * bump)
                p.setBrush(grain)
                p.drawPolygon(poly)
            p.setOpacity(1.0)
        # metals: dark body, mirror-like sheen of a sky over a ground
        if metal > 0.0 and not clear:
            sheen = QLinearGradient(poly.boundingRect().topLeft(), poly.boundingRect().bottomLeft())
            sheen.setColorAt(0.0, QColor(190, 215, 245, int(150 * metal * (1.0 - 0.5 * rough))))
            sheen.setColorAt(0.5, QColor(235, 235, 235, int(110 * metal * (1.0 - 0.5 * rough))))
            sheen.setColorAt(0.55, QColor(70, 58, 48, int(150 * metal * (1.0 - 0.5 * rough))))
            sheen.setColorAt(1.0, QColor(40, 34, 30, int(160 * metal * (1.0 - 0.5 * rough))))
            p.setBrush(QBrush(sheen))
            p.drawPolygon(poly)
            p.setBrush(QColor(0, 0, 0, int(70 * metal)))
            p.drawPolygon(poly)
        p.restore()

    # polish: a bright reflection of the light on the top and the left face
    shine = (1.0 - rough) ** 1.5 * (0.55 + 0.45 * (1 - metal))
    if shine > 0.02 and not glow:
        for name, spot, radius in (("top", 0.30, 0.55), ("left", 0.25, 0.45)):
            poly = QPolygonF(list(faces[name]))
            r = poly.boundingRect()
            centre = QPointF(r.left() + r.width() * 0.34, r.top() + r.height() * (0.40 if name == "top" else 0.30))
            g = QRadialGradient(centre, max(r.width(), r.height()) * radius * (0.45 + 0.55 * rough))
            g.setColorAt(0.0, QColor(255, 255, 255, int(255 * min(1.0, shine * (1.1 if clear else 0.85)))))
            g.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.save()
            p.setClipRegion(_region(poly))
            p.setBrush(QBrush(g))
            p.setPen(Qt.NoPen)
            p.drawPolygon(poly)
            p.restore()

    if kind == "grass":
        _grass(p, faces, size, float(params.get("grass_height", 0.08)), base, texture,
               params.get("grass_density"))

    # the edges
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(0, 0, 0, 70 if not clear else 110), max(1.0, size / 150)))
    for name in ("top", "left", "right"):
        p.drawPolygon(QPolygonF(list(faces[name])))
    p.end()
    return px


def _grass(p: QPainter, faces, size: int, height: float, base: QColor, texture,
           density=None) -> None:
    """Blades on the top face, ``height`` metres tall (the cube is 1 m), in the
    material's colour (its picture's average when it has one), back to front;
    ``density`` (tufts per m²) sets how many."""
    import random
    if texture is not None and not texture.isNull():
        avg = texture.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
    else:
        avg = QColor(base)
    rng = random.Random(7)
    t0, t1, t2, t3 = faces["top"]                       # back, right, front, left corners
    metre = (faces["left"][2].y() - faces["left"][1].y())    # the cube's vertical edge: 1 m
    length = max(3.0, metre * max(0.0, height))
    pts = []
    count = (int(260 + 900 * min(1.0, 0.12 / max(height, 0.01))) if not density
             else int(max(40.0, min(2400.0, 4.0 * float(density)))))
    for _ in range(count):
        u, v = rng.random(), rng.random()
        x = t0.x() + (t1.x() - t0.x()) * u + (t3.x() - t0.x()) * v
        y = t0.y() + (t1.y() - t0.y()) * u + (t3.y() - t0.y()) * v
        pts.append((y, x))
    pts.sort()
    p.save()
    p.setBrush(Qt.NoBrush)
    for y, x in pts:
        k = 0.55 + 0.6 * rng.random()
        c = QColor.fromRgbF(min(1.0, avg.redF() * k), min(1.0, avg.greenF() * k), min(1.0, avg.blueF() * k))
        p.setPen(QPen(c, max(1.0, size / 160.0), Qt.SolidLine, Qt.RoundCap))
        h = length * (0.6 + 0.4 * rng.random())
        lean = (rng.random() - 0.5) * h * 0.7
        tip = QPointF(x + lean, y - h)
        path = QPainterPath(QPointF(x, y))
        path.quadTo(QPointF(x + lean * 0.2, y - h * 0.6), tip)
        p.drawPath(path)
    p.restore()


def _tile_to_face(tf: QTransform, sw: float, sh: float, texture: QImage) -> QTransform:
    """Brush transform: image pixels → face, the image covering sw × sh metres
    of a one-metre face (tf maps the face's unit square onto the screen)."""
    to_unit = QTransform.fromScale(sw / texture.width(), sh / texture.height())
    return to_unit * tf


def _region(poly: QPolygonF):
    from PySide6.QtGui import QRegion
    return QRegion(poly.toPolygon())


def _union_region(faces):
    from PySide6.QtGui import QRegion
    reg = QRegion()
    for poly in faces.values():
        reg = reg.united(QRegion(QPolygonF(list(poly)).toPolygon()))
    return reg


_emboss_cache: dict = {}


def _emboss(img: QImage, key) -> QImage:
    """The picture's light and dark as a relief lit from the upper left: grey
    (neutral) where it is flat, lighter on slopes that face the light, darker on
    the others."""
    try:
        stamp = Path(str(key)).stat().st_mtime_ns
    except OSError:
        stamp = 0
    ck = (str(key), stamp, img.width(), img.height())
    if ck not in _emboss_cache:
        small = img if max(img.width(), img.height()) <= 256 else img.scaled(
            256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        w, h = small.width(), small.height()
        lum = [[small.pixelColor(x, y).lightnessF() for x in range(w)] for y in range(h)]
        out = QImage(w, h, QImage.Format_ARGB32)
        for y in range(h):
            for x in range(w):
                d = lum[(y + 1) % h][(x + 1) % w] - lum[(y - 1) % h][(x - 1) % w]
                v = max(0, min(255, int(128 - 255 * 0.9 * d)))
                out.setPixelColor(x, y, QColor(v, v, v, 255))
        if len(_emboss_cache) > 16:
            _emboss_cache.clear()
        _emboss_cache[ck] = out.scaled(img.width(), img.height(), Qt.IgnoreAspectRatio,
                                       Qt.SmoothTransformation) if out.size() != img.size() else out
    return _emboss_cache[ck]


def _load_texture(path):
    if not path or not Path(str(path)).is_file():
        return None
    img = QImage(str(path))
    return None if img.isNull() or img.width() <= 0 else img
