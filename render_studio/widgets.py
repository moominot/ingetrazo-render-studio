# SPDX-License-Identifier: GPL-3.0-or-later
"""Small widgets shared by the panel and the preview window: float sliders with a value and a
hint, and the picture view with zoom and pan."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QLabel, QSlider, QVBoxLayout, QWidget)


def slider(lo, hi, value, steps=200):
    s = QSlider(Qt.Horizontal)
    s.setRange(0, steps)
    s.setProperty("lo", lo)
    s.setProperty("hi", hi)
    s.setValue(int(round((value - lo) / (hi - lo) * steps)))
    return s


def value(s: QSlider) -> float:
    lo, hi = float(s.property("lo")), float(s.property("hi"))
    return lo + (hi - lo) * s.value() / s.maximum()


def set_value(s: QSlider, v: float) -> None:
    lo, hi = float(s.property("lo")), float(s.property("hi"))
    s.setValue(int(round((float(v) - lo) / (hi - lo) * s.maximum())))


class SliderRow(QWidget):
    """A slider with its current value beside it and a gray line saying what it does:
    ``fmt`` turns the value into the text shown («+0.5 EV», «25 %»)."""

    def __init__(self, s: QSlider, fmt: str = "{:.2f}", hint: str = "", parent=None):
        super().__init__(parent)
        self.slider, self.fmt = s, fmt
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 2)
        lay.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(s, 1)
        self.value_label = QLabel("")
        self.value_label.setMinimumWidth(58)
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.value_label)
        lay.addLayout(top)
        self.hint = QLabel(hint)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: gray; font-size: 11px")
        self.hint.setVisible(bool(hint))
        lay.addWidget(self.hint)
        if hint:
            s.setToolTip(hint)
        s.valueChanged.connect(self.update_value)
        self.update_value()

    def update_value(self, *_a) -> None:
        self.value_label.setText(self.fmt.format(value(self.slider)))

    def setEnabled(self, on: bool) -> None:          # noqa: N802 - Qt naming
        super().setEnabled(on)
        self.slider.setEnabled(on)


class ZoomView(QGraphicsView):
    """A picture that fits the window until you zoom: the wheel zooms where the cursor is, a
    drag moves it, a double click goes between «fit» and 100 % (one picture pixel per screen
    pixel), ``+`` ``-`` ``0`` ``1`` on the keyboard. The zoom and place are kept when a new
    picture of another size arrives (the live view's frames come in 320, 480 and 960 px)."""

    zoomed = Signal(float)                 # percent of the picture's pixels
    BASE = 1000.0                          # the picture is always BASE scene units wide
    MAX_PIXEL = 16.0                       # at most 16 screen pixels per picture pixel

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.SmoothTransformation)
        self._scene.addItem(self._item)
        self._pm = QPixmap()
        self._fit = True
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setFrameShape(QFrame.NoFrame)
        self.setBackgroundBrush(QColor(36, 36, 36))
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setMinimumSize(320, 200)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("Wheel: zoom · drag: move · double click: fit / 100 %")

    # -- the picture -----------------------------------------------------------------
    def has_picture(self) -> bool:
        return not self._pm.isNull()

    def set_pixmap(self, pm: QPixmap, refit: bool = False) -> None:
        first = self._pm.isNull()
        self._pm = pm
        if pm.isNull():
            self._item.setPixmap(QPixmap())
            return
        self._item.setPixmap(pm)
        self._item.setScale(self.BASE / pm.width())
        self._scene.setSceneRect(0, 0, self.BASE, self.BASE * pm.height() / pm.width())
        if self._fit or refit or first:
            self.fit()
        else:
            self.zoomed.emit(self.percent())

    def picture_size(self) -> tuple:
        return (self._pm.width(), self._pm.height())

    # -- zoom ---------------------------------------------------------------------------
    def _fit_scale(self) -> float:
        r = self._scene.sceneRect()
        vp = self.viewport()
        if r.width() <= 0 or r.height() <= 0:
            return 1.0
        return max(1e-6, min(vp.width() / r.width(), vp.height() / r.height()))

    def percent(self) -> float:
        if self._pm.isNull():
            return 100.0
        return self.transform().m11() * self.BASE / self._pm.width() * 100.0

    def is_fitted(self) -> bool:
        return self._fit

    def fit(self) -> None:
        """The whole picture in the window (and again after each resize)."""
        if self._pm.isNull():
            return
        s = self._fit_scale()
        self.resetTransform()
        self.scale(s, s)
        self._fit = True
        self.zoomed.emit(self.percent())

    def actual_size(self, at: QPointF | None = None) -> None:
        """100 %: one picture pixel per screen pixel (around ``at``, a scene point)."""
        if self._pm.isNull():
            return
        s = self._pm.width() / self.BASE
        self.resetTransform()
        self.scale(s, s)
        self._fit = False
        self.centerOn(at if at is not None else self._scene.sceneRect().center())
        self.zoomed.emit(self.percent())

    def zoom_by(self, factor: float) -> None:
        if self._pm.isNull():
            return
        cur = self.transform().m11()
        lo = self._fit_scale() * 0.5
        hi = self.MAX_PIXEL * self._pm.width() / self.BASE
        new = max(lo, min(hi, cur * factor))
        if abs(new - cur) < 1e-9:
            return
        self.scale(new / cur, new / cur)
        self._fit = False
        self.zoomed.emit(self.percent())

    # -- the mouse and the keys -----------------------------------------------------------
    def wheelEvent(self, ev) -> None:              # noqa: N802
        dy = ev.angleDelta().y()
        if dy:
            self.zoom_by(1.0015 ** dy)
        ev.accept()

    def mouseDoubleClickEvent(self, ev) -> None:   # noqa: N802
        if self._fit:
            self.actual_size(self.mapToScene(ev.position().toPoint()))
        else:
            self.fit()
        ev.accept()

    def keyPressEvent(self, ev: QKeyEvent) -> None:  # noqa: N802
        k = ev.key()
        if k in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_by(1.25)
        elif k in (Qt.Key_Minus, Qt.Key_Underscore):
            self.zoom_by(0.8)
        elif k == Qt.Key_0:
            self.fit()
        elif k == Qt.Key_1:
            self.actual_size()
        else:
            super().keyPressEvent(ev)

    def resizeEvent(self, ev) -> None:             # noqa: N802
        super().resizeEvent(ev)
        if self._fit:
            self.fit()


class Collapsible(QWidget):
    """A section that starts closed: a header you click to show the advanced controls under it.
    ``form`` is the QFormLayout to fill; the open/closed state is remembered under ``key``."""

    def __init__(self, title: str, key: str = "", parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QFormLayout, QToolButton
        self._key = "render_studio/open_" + key if key else ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(2)
        self.header = QToolButton()
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setStyleSheet("QToolButton { border: none; font-weight: bold; text-align: left; }")
        from PySide6.QtWidgets import QSizePolicy
        self.header.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)     # a long title must not widen a narrow tray
        self.header.setMinimumWidth(90)
        lay.addWidget(self.header)
        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(12, 0, 0, 0)
        lay.addWidget(self.body)
        opened = False
        if self._key:
            try:
                opened = str(QSettings().value(self._key, "false")).lower() == "true"
            except Exception:  # noqa: BLE001
                pass
        self.header.toggled.connect(self._toggled)
        self.header.setChecked(opened)
        self._toggled(opened)

    def _toggled(self, on: bool) -> None:
        self.header.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.body.setVisible(on)
        if self._key:
            try:
                from PySide6.QtCore import QSettings
                QSettings().setValue(self._key, "true" if on else "false")
            except Exception:  # noqa: BLE001
                pass
