# SPDX-License-Identifier: GPL-3.0-or-later
"""What the Section page shows of the cap: the drawing's materials as a grid of their pictures to pick one from, and a
picture of the hatching with its rim as they will be drawn."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate, QWidget

from . import icons
from .i18n import tr

TILE = 52


class _Tile(QStyledItemDelegate):
    """A material's picture filling its square, all the same size; the chosen one framed in the accent."""

    def paint(self, painter, option, index) -> None:  # noqa: N802 (Qt)
        icon = index.data(Qt.DecorationRole)
        square = option.rect.adjusted(3, 3, -3, -3)
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if icon is not None:
            picture = icon.pixmap(96, 96)
            if not picture.isNull():
                painter.drawPixmap(square, picture)
        edge = option.palette.windowText().color()
        edge.setAlpha(60)
        if option.state & QStyle.State_Selected:
            painter.setPen(QPen(icons._accent(), 3))
            painter.drawRect(square.adjusted(-1, -1, 0, 0))
        else:
            painter.setPen(QPen(edge, 1))
            painter.drawRect(square.adjusted(0, 0, -1, -1))
        painter.restore()

    def sizeHint(self, _option, _index) -> QSize:  # noqa: N802 (Qt)
        return QSize(TILE, TILE)


class MaterialGrid(QListWidget):
    """The materials as pictures. It shows what a list box holds (``follow``): choosing a picture chooses it there."""

    picked = Signal(int)                       # the index in the list box

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(_Tile(self))
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setIconSize(QSize(TILE - 8, TILE - 8))
        self.setGridSize(QSize(TILE, TILE))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumHeight(2 * TILE + 8)
        self.setMaximumHeight(3 * TILE + 8)
        self.itemClicked.connect(lambda item: self.picked.emit(self.row(item)))

    def follow(self, combo, picture) -> None:
        """The same entries as ``combo``, each with ``picture(data)`` (a QIcon) and its name as its tip."""
        names = [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]
        if names != getattr(self, "_shown", None):
            self._shown = names
            self.clear()
            for text, data in names:
                item = QListWidgetItem(picture(data), "")
                item.setToolTip(text)
                item.setSizeHint(QSize(TILE, TILE))
                self.addItem(item)
        self.setCurrentRow(combo.currentIndex())


def plain_tile(rgb) -> QIcon:
    pm = QPixmap(TILE - 8, TILE - 8)
    pm.fill(QColor.fromRgbF(*[max(0.0, min(1.0, float(c))) for c in rgb[:3]]))
    return QIcon(pm)


def hand_line(path: QPainterPath, a: QPointF, b: QPointF, hand: float, amount: float, phase: float) -> None:
    """A line from ``a`` to ``b`` into ``path``, wavering by up to ``amount`` pixels at full ``hand``."""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    steps = max(2, int(length / 6.0))
    for i in range(steps + 1):
        t = i / steps
        wave = hand * amount * (math.sin(t * length / 13.0 + phase) + 0.5 * math.sin(t * length / 5.3 + 2.1 * phase))
        point = QPointF(a.x() + dx * t + nx * wave, a.y() + dy * t + ny * wave)
        path.moveTo(point) if i == 0 else path.lineTo(point)


class CapPreview(QWidget):
    """A piece of the cap, 80 cm tall: its colour, its hatching and its rim, as the settings say (``show_cap``)."""

    SPAN_CM = 80.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings: dict = {}
        self.setMinimumHeight(96)
        self.setToolTip(tr("The cap and its outline, as they will be drawn (a piece 80 cm tall)."))

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt)
        return QSize(160, 96)

    def show_cap(self, settings: dict) -> None:
        self.settings = dict(settings)
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802 (Qt)
        s = self.settings
        if not s:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), self.palette().base())
        face = QRectF(10, 10, max(10, self.width() - 20), max(10, self.height() - 20))
        ground = QColor.fromRgbF(*s.get("color", (0.35, 0.37, 0.41))[:3])
        p.fillRect(face, ground)
        per_cm = face.height() / self.SPAN_CM
        if s.get("style") == "hatch":
            ink = QColor.fromRgbF(*s.get("line", (0.1, 0.1, 0.1))[:3])
            ink.setAlphaF(max(0.0, min(1.0, float(s.get("line_opacity", 1.0)))))
            spacing = max(3.0, float(s.get("spacing", 0.1)) * 100.0 * per_cm)
            thick = max(0.6, spacing * float(s.get("line_width", 0.14)))
            hand = float(s.get("line_hand", 0.0))
            p.save()
            p.setClipRect(face)
            pattern = s.get("pattern", "diagonal")
            if pattern == "dots":
                p.setPen(Qt.NoPen)
                p.setBrush(ink)
                r = max(0.8, spacing * 0.2 * float(s.get("line_width", 0.14)) / 0.14)
                for j in range(int(face.height() / spacing) + 2):
                    for i in range(int(face.width() / spacing) + 2):
                        wob = hand * spacing * 0.18
                        p.drawEllipse(QPointF(face.left() + i * spacing + wob * math.sin(i * 2.3 + j),
                                              face.top() + j * spacing + wob * math.cos(i + j * 1.7)), r, r)
            else:
                path = QPainterPath()
                angles = {"diagonal": (45.0,), "cross": (45.0, -45.0), "grid": (0.0, 90.0)}.get(pattern, (45.0,))
                reach = math.hypot(face.width(), face.height())
                centre = face.center()
                for angle in angles:
                    a = math.radians(angle)
                    along = QPointF(math.sin(a), -math.cos(a))          # the lines run this way…
                    across = QPointF(math.cos(a), math.sin(a))          # …and follow one another this way
                    count = int(reach / spacing) + 1
                    for k in range(-count // 2 - 1, count // 2 + 2):
                        mid = centre + across * (k * spacing)
                        hand_line(path, mid - along * (reach / 2), mid + along * (reach / 2), hand, spacing * 0.16, k * 1.9 + angle)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(ink, thick, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin))
                p.drawPath(path)
            p.restore()
        if s.get("outline", True):
            ink = QColor.fromRgbF(*s.get("outline_color", (0.05, 0.05, 0.05))[:3])
            ink.setAlphaF(max(0.05, min(1.0, float(s.get("outline_opacity", 1.0)))))
            rim = QPainterPath()
            corners = (face.topLeft(), face.topRight(), face.bottomRight(), face.bottomLeft(), face.topLeft())
            for n, (a, b) in enumerate(zip(corners, corners[1:])):
                hand_line(rim, a, b, float(s.get("outline_hand", 0.0)), 1.6, n * 2.7)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(ink, max(0.6, float(s.get("outline_width", 2.4))), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(rim)
        p.end()
