# SPDX-License-Identifier: GPL-3.0-or-later
"""Small widgets shared by the panel and the preview window: float sliders with a value and a
hint, and the picture view with zoom and pan."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QGroupBox, QHBoxLayout,
                               QLabel, QSizePolicy, QSlider, QVBoxLayout, QWidget)


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
        v = value(self.slider)
        if self.fmt.startswith("auto|"):                 # «auto|{:.1f} m»: the lowest value reads «Auto»
            self.value_label.setText(tr("Auto") if v <= 1e-6 else self.fmt[5:].format(v))
            return
        self.value_label.setText(self.fmt.format(v))

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


from .i18n import tr  # noqa: E402


SPLIT_STYLE = """
QToolButton { border: 1px solid palette(mid); border-radius: 4px; padding: 4px 22px 4px 10px;
              background: palette(button); color: palette(button-text); }
QToolButton:hover { background: palette(light); }
QToolButton:pressed { background: palette(midlight); }
QToolButton:disabled { color: palette(mid); }
QToolButton::menu-button { border: none; border-left: 1px solid palette(mid); width: 20px;
                           border-top-right-radius: 3px; border-bottom-right-radius: 3px; }
QToolButton::menu-button:hover { background: palette(light); }
QToolButton::menu-arrow { width: 8px; height: 8px; }
"""


def split_button(text: str, main_slot, tip: str, actions):
    """A button whose arrow opens a menu of ``actions`` (QActions): the button itself does ``main_slot``."""
    from PySide6.QtWidgets import QMenu, QSizePolicy, QToolButton
    b = QToolButton()
    b.setText(text)
    b.setToolTip(tip)
    b.setPopupMode(QToolButton.MenuButtonPopup)
    b.setToolButtonStyle(Qt.ToolButtonTextOnly)
    b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    b.setMinimumHeight(28)
    # one rounded rectangle, with a plain divider before the arrow: no rounding where the two parts meet
    b.setStyleSheet(SPLIT_STYLE)
    menu = QMenu(b)
    for a in actions:
        menu.addAction(a)
    b.setMenu(menu)
    b.clicked.connect(lambda _c=False: main_slot())
    return b


class RadiusSlider(QWidget):
    """A slider in metres with its value beside it («Automatic» at 0): ``value()``, ``setValue()`` and
    ``valueChanged`` (a float) like a number box."""
    valueChanged = Signal(float)

    def __init__(self, maximum: float = 500.0, step: float = 5.0, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QSlider
        self._step = float(step)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, int(round(maximum / step)))
        self.slider.valueChanged.connect(self._moved)
        self.label = QLabel("")
        self.label.setMinimumWidth(70)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self._moved()

    def value(self) -> float:
        return self.slider.value() * self._step

    def setValue(self, metres: float) -> None:
        self.slider.setValue(int(round(float(metres) / self._step)))

    def maximum(self) -> float:
        return self.slider.maximum() * self._step

    def _moved(self, *_a) -> None:
        v = self.value()
        self.label.setText(tr("Automatic") if v <= 0 else f"{v:.0f} m")
        self.valueChanged.emit(v)


class NumberSlider(QWidget):
    """A slider over a range of numbers with its value beside it (``fmt``): ``value()``, ``setValue()``, ``valueChanged``."""
    valueChanged = Signal(float)

    def __init__(self, lo: float, hi: float, step: float, fmt: str = "{:.1f}", parent=None, special: str = ""):
        super().__init__(parent)
        from PySide6.QtWidgets import QSlider
        self._lo, self._step, self._fmt, self._special = float(lo), float(step), fmt, special
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, int(round((hi - lo) / step)))
        self.slider.valueChanged.connect(self._moved)
        self.label = QLabel("")
        self.label.setMinimumWidth(52)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self._fit_label()
        self._moved()

    def _fit_label(self) -> None:
        """The value's label as wide as the widest thing it will ever say («No outlines», «4.0 px»…): a text that changes its width while
        the slider is dragged would resize the slider under the hand."""
        fm = self.label.fontMetrics()
        texts = [self._fmt.format(self._lo), self._fmt.format(self._lo + self.slider.maximum() * self._step)]
        if self._special:
            texts.append(tr(self._special))
        self.label.setFixedWidth(max(52, max(fm.horizontalAdvance(t) for t in texts) + 10))

    def showEvent(self, ev) -> None:        # noqa: N802 (Qt: the font is known once shown)
        self._fit_label()
        super().showEvent(ev)

    def value(self) -> float:
        return self._lo + self.slider.value() * self._step

    def setValue(self, v: float) -> None:
        self.slider.setValue(int(round((float(v) - self._lo) / self._step)))

    def _moved(self, *_a) -> None:
        v = self.value()
        self.label.setText(tr(self._special) if (self._special and v <= self._lo) else self._fmt.format(v))
        self.valueChanged.emit(v)


class ClockLabel(QWidget):
    """The render's stopwatch: the clock icon (drawn as the extension's others, in the theme's ink) and the elapsed time. Hidden until a
    render runs: ``set_text("1:05")`` shows it, ``set_text(None)`` hides it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.icon_label = QLabel("")
        self.icon_label.setFixedSize(18, 18)
        self.time_label = QLabel("")
        self.time_label.setMinimumWidth(40)
        lay.addWidget(self.icon_label)
        lay.addWidget(self.time_label)
        self._draw_icon()
        self.setVisible(False)

    def _draw_icon(self) -> None:
        from .icons import icon
        self.icon_label.setPixmap(icon("clock").pixmap(18, 18))

    def set_text(self, text) -> None:
        if text:
            self.time_label.setText(str(text))
            self.setVisible(True)
        else:
            self.setVisible(False)

    def changeEvent(self, ev) -> None:        # noqa: N802 (Qt: a new theme, a new ink)
        from PySide6.QtCore import QEvent
        if ev.type() in (QEvent.PaletteChange, QEvent.ApplicationPaletteChange) and hasattr(self, "icon_label"):
            self._draw_icon()
        super().changeEvent(ev)


class RefreshCombo(QComboBox):
    """A combo box that asks for its list just before it opens (a list that changes with the drawing)."""

    def __init__(self, refresh=None, parent=None):
        super().__init__(parent)
        self.refresh = refresh

    def showPopup(self):  # noqa: N802
        if callable(self.refresh):
            self.refresh()
        super().showPopup()


class FoldBox(QGroupBox):
    """A group box that folds away with a click on its title (a chevron at the right end of the title row says which way it goes); whether it
    is open is remembered under ``key``. Fill ``form`` (a QFormLayout in the box's body: the title stays, the body goes), so what the code
    shows or hides row by row inside it is not disturbed by folding."""

    def __init__(self, title: str, key: str = "", parent=None):
        super().__init__(title, parent)
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QFormLayout
        self._key = "render_studio/fold_" + key if key else ""
        lay = QVBoxLayout(self)
        self.body = QWidget(self)
        lay.addWidget(self.body)
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        opened = True
        if self._key:
            try:
                opened = str(QSettings().value(self._key, "true")).lower() != "false"
            except Exception:  # noqa: BLE001
                pass
        self._open = opened
        self.body.setVisible(opened)
        self.setToolTip(tr("Click the title to fold or unfold this group"))

    def is_open(self) -> bool:
        return self._open

    def set_open(self, on: bool) -> None:
        on = bool(on)
        if on == self._open:
            return
        self._open = on
        self.body.setVisible(on)
        if self._key:
            try:
                from PySide6.QtCore import QSettings
                QSettings().setValue(self._key, "true" if on else "false")
            except Exception:  # noqa: BLE001
                pass
        self.update()

    def _title_height(self) -> int:
        return self.fontMetrics().height() + 8

    def mousePressEvent(self, ev) -> None:      # noqa: N802 (Qt)
        if ev.button() == Qt.LeftButton and ev.position().y() <= self._title_height():
            self.set_open(not self._open)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def paintEvent(self, ev) -> None:           # noqa: N802 (Qt)
        super().paintEvent(ev)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPainter, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        c = self.palette().windowText().color()
        c.setAlpha(170)
        pen = QPen(c, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        cx, cy = self.width() - 16.0, self._title_height() / 2.0
        if self._open:
            p.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])
        else:
            p.drawPolyline([QPointF(cx - 2, cy - 4), QPointF(cx + 2, cy), QPointF(cx - 2, cy + 4)])
        p.end()


class Section(QWidget):
    """A block of rows that is always in view: what used to be folded under «Advanced» (there is room for it). ``form`` is the QFormLayout
    to fill; the block is one widget, so a whole block can be enabled, disabled or shown by context."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QFormLayout
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)


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


class ChoiceButtons(QWidget):
    """A few buttons in one row, one of them chosen (a list of choices that all show): the interface of a combo box
    (``currentIndex``, ``setCurrentIndex``, ``currentIndexChanged``, ``currentText``)."""

    currentIndexChanged = Signal(int)

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QButtonGroup, QToolButton
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = []
        for i, text in enumerate(labels):
            b = QToolButton()
            b.setText(text)
            b.setCheckable(True)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setMinimumHeight(28)
            self._group.addButton(b, i)
            self._buttons.append(b)
            lay.addWidget(b, 1)
        self._buttons[0].setChecked(True)
        self._group.idToggled.connect(lambda i, on: self.currentIndexChanged.emit(i) if on else None)

    def currentIndex(self) -> int:
        return max(0, self._group.checkedId())

    def setCurrentIndex(self, i: int) -> None:
        i = max(0, min(len(self._buttons) - 1, int(i)))
        self._buttons[i].setChecked(True)

    def currentText(self) -> str:
        return self._buttons[self.currentIndex()].text()
