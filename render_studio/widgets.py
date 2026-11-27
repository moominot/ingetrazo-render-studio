# SPDX-License-Identifier: GPL-3.0-or-later
"""Small widgets shared by the panel and the preview window: float sliders with a value and a
hint, and the picture view with zoom and pan."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QKeyEvent, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (QStyle, QStyleOptionToolButton, QStylePainter, QToolButton, QComboBox, QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QGroupBox, QHBoxLayout,
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
    """A slider with its current value beside it; what it does is its tip:
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
        self.hint.setVisible(False)              # (said as the tip of the whole row: the pages stay clean)
        lay.addWidget(self.hint)
        if hint:
            s.setToolTip(hint)
            self.setToolTip(hint)
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
    CHECK, CHECK_GREYS = 12, (236, 204)    # the checkerboard behind what is see-through: a square's side on screen, its greys
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
        # With a board that stays put, panning cannot just shift what is on screen: all of it is painted again.
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate if pm.hasAlphaChannel() else QGraphicsView.MinimalViewportUpdate)
        self.viewport().update()
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

    def drawBackground(self, painter: QPainter, rect) -> None:  # noqa: N802 (Qt)
        """The window's own checkerboard, seen through what the picture leaves empty. It belongs to the window, not to the
        picture: its squares keep their size and their place whatever picture comes (the live view's frames differ in size)
        and however it is zoomed or moved."""
        super().drawBackground(painter, rect)
        if self._pm.isNull() or not self._pm.hasAlphaChannel():
            return
        side = self.CHECK
        tile = QPixmap(2 * side, 2 * side)
        light, dark = (QColor(g, g, g) for g in self.CHECK_GREYS)
        tile.fill(light)
        p = QPainter(tile)
        p.fillRect(side, 0, side, side, dark)
        p.fillRect(0, side, side, side, dark)
        p.end()
        where = self.mapFromScene(self._scene.sceneRect()).boundingRect()      # only where the picture is
        painter.save()
        painter.resetTransform()                                               # in the window's pixels
        painter.fillRect(where, QBrush(tile))
        painter.restore()

    def pixmap(self) -> QPixmap:
        return self._pm

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
QToolButton { border: none; border-radius: 5px; padding: 4px 22px 4px 10px; background: rgba(128,128,128,38);
              color: palette(button-text); }
QToolButton:hover { background: rgba(128,128,128,70); }
QToolButton:pressed { background: rgba(128,128,128,100); }
QToolButton:disabled { color: palette(mid); background: rgba(128,128,128,20); }
QToolButton::menu-button { border: none; border-left: 1px solid rgba(128,128,128,90); width: 20px;
                           border-top-right-radius: 5px; border-bottom-right-radius: 5px; }
QToolButton::menu-button:hover { background: rgba(128,128,128,70); }
QToolButton::menu-arrow { width: 8px; height: 8px; }
"""
#: Every button of the panel's pages and foot (not the tab bar's arrows, which a style sheet would leave blank): flat, no frame; a faint ground, stronger under the pointer, the accent when it is the one chosen.
FLAT_STYLE = """
QPushButton, QToolButton {{ border: none; border-radius: 5px; padding: 4px 8px; background: rgba(128,128,128,38);
                           color: palette(button-text); }}
QPushButton:hover, QToolButton:hover {{ background: rgba(128,128,128,70); }}
QPushButton:pressed, QToolButton:pressed {{ background: rgba(128,128,128,100); }}
QPushButton:checked, QToolButton:checked {{ background: rgba({r},{g},{b},80); }}
QPushButton:disabled, QToolButton:disabled {{ color: palette(mid); background: rgba(128,128,128,20); }}
QToolButton::menu-indicator {{ image: none; width: 0px; }}
"""


#: The two buttons of the tray's header: as low as its one line of text.
SMALL_BUTTON = """
QToolButton { padding: 2px 6px; font-size: 11px; }
"""


def flat_style() -> str:
    from . import icons
    c = icons._accent()
    return FLAT_STYLE.format(r=c.red(), g=c.green(), b=c.blue())


class CentredButton(QToolButton):
    """A tool button with its icon and its words together in the middle of it (Qt puts them at its left edge). The middle is
    the whole button's, arrow or no arrow, so buttons one above another line up."""

    GAP = 6
    ARROW = 24                                  # what the menu's arrow takes at the right

    def paintEvent(self, _ev) -> None:  # noqa: N802 (Qt)
        painter = QStylePainter(self)
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        text, icon = option.text, QIcon(option.icon)      # (a copy: PySide hands out the option's own, emptied below)
        option.text, option.icon = "", QIcon()
        painter.drawComplexControl(QStyle.CC_ToolButton, option)        # the button itself, empty
        size = self.iconSize() if not icon.isNull() else QSize(0, 0)
        gap = self.GAP if size.width() and text else 0
        words = painter.fontMetrics().horizontalAdvance(text)
        content = size.width() + gap + words
        x = (self.width() - content) // 2
        if self.popupMode() == QToolButton.MenuButtonPopup:           # never over the arrow (a half-width button has no room
            x = min(x, self.width() - self.ARROW - content)           # to spare: it moves left)
        x = max(4, x)
        if size.width():
            icon.paint(painter, QRect(x, (self.height() - size.height()) // 2, size.width(), size.height()), Qt.AlignCenter,
                       QIcon.Normal if self.isEnabled() else QIcon.Disabled)
        group = QPalette.Active if self.isEnabled() else QPalette.Disabled
        painter.setPen(self.palette().color(group, QPalette.ButtonText))
        painter.drawText(QRect(x + size.width() + gap, 0, words + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, text)


def split_button(text: str, main_slot, tip: str, actions):
    """A button whose arrow opens a menu of ``actions`` (QActions): the button itself does ``main_slot``."""
    from PySide6.QtWidgets import QMenu, QSizePolicy
    b = CentredButton()
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


QWIDGETSIZE_MAX = (1 << 24) - 1                  # Qt's «no maximum»

#: A card's «+»: flat, with a ground only under the pointer (the header has its own colour).
MORE_STYLE = """
QToolButton { border: none; background: transparent; padding: 1px; }
QToolButton:hover { background: rgba(128,128,128,60); border-radius: 4px; }
QToolButton:pressed { background: rgba(128,128,128,100); border-radius: 4px; }
"""


class Card(QGroupBox):
    """A group of the panel: a card whose header, in a colour of its own, has the group's icon and name and folds it away
    with a click; whether it is open is remembered under ``key``. Fill ``form`` (``kind`` "form") or ``body_layout``
    ("column"): both are in the card's body, so what the code shows or hides row by row is not disturbed by folding."""

    unfolded = Signal()                         # it has just been opened (by a click or by the program)

    def __init__(self, title: str, key: str = "", parent=None, icon: str = "", kind: str = "form"):
        super().__init__(title, parent)
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QFormLayout
        self._key = "render_studio/fold_" + key if key else ""
        self.icon_key = icon
        self._forced = False
        self._lay = QVBoxLayout(self)
        self.body = QWidget(self)
        self._lay.addWidget(self.body)
        if kind == "form":
            self.form = QFormLayout(self.body)
            self.form.setContentsMargins(0, 0, 0, 0)
            self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        else:
            self.body_layout = QVBoxLayout(self.body)
            self.body_layout.setContentsMargins(0, 0, 0, 0)
        opened = True
        if self._key:
            try:
                opened = str(QSettings().value(self._key, "true")).lower() != "false"
            except Exception:  # noqa: BLE001
                pass
        self._open = opened
        self.body.setVisible(opened)
        self._fit()
        self.setToolTip(tr("Click the title to fold or unfold this group"))
        self.body.setToolTip(" ")                     # (what is inside does not wear the header's tip)
        self.body.setToolTipDuration(1)

    def _title_height(self) -> int:
        return max(28, self.fontMetrics().height() + 12)

    #: What the header keeps at the right for its «+», when it has one.
    MORE_ROOM = 24

    def add_more_button(self, tip: str, slot) -> QToolButton:
        """A «+» in the header, beside the fold's arrow: ``slot()`` when it is pressed (the click does not fold the card)."""
        from . import icons
        button = QToolButton(self)
        button.setIcon(icons.icon("plus"))
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(22, 22)
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet(MORE_STYLE)
        button.clicked.connect(lambda _checked=False: slot())
        self.more_button = button
        self._place_more()
        self.update()
        return button

    def _place_more(self) -> None:
        button = getattr(self, "more_button", None)
        if button is not None:
            button.move(self.width() - 24 - button.width(), (self._title_height() - button.height()) // 2)

    def resizeEvent(self, ev) -> None:          # noqa: N802 (Qt)
        super().resizeEvent(ev)
        self._place_more()

    def minimumSizeHint(self) -> QSize:         # noqa: N802 (Qt)
        """As narrow as what is inside: Qt would keep room for the whole title, which is cut short when it does not fit."""
        return QSize(self._lay.totalMinimumSize().width(), super().minimumSizeHint().height())

    def _fit(self) -> None:
        """The body below the header (Qt keeps some room of its own for a group box's title: only the rest is added)."""
        own = self.contentsMargins().top()
        shown = self._open or self._forced
        margins = (8, max(0, self._title_height() - own) + (6 if shown else 0), 8, 8 if shown else 0)
        if self._lay.getContentsMargins() != margins:
            self._lay.setContentsMargins(*margins)
        # folded, it is exactly as tall as its header (Qt would give a group box a little more)
        self.setMaximumHeight(QWIDGETSIZE_MAX if shown else self._title_height())

    def changeEvent(self, ev) -> None:          # noqa: N802 (Qt: another font or style, other margins)
        super().changeEvent(ev)
        if hasattr(self, "_lay"):
            self._fit()

    def showEvent(self, ev) -> None:            # noqa: N802 (Qt)
        self._fit()
        super().showEvent(ev)

    def is_open(self) -> bool:
        return self._open

    def set_open(self, on: bool) -> None:
        on = bool(on)
        if on == self._open:
            return
        self._open = on
        self.body.setVisible(on or self._forced)
        self._fit()
        if self._key:
            try:
                from PySide6.QtCore import QSettings
                QSettings().setValue(self._key, "true" if on else "false")
            except Exception:  # noqa: BLE001
                pass
        self.update()
        if on:
            self.unfolded.emit()

    def force_open(self, on: bool) -> None:
        """Open while ``on`` whatever was chosen (a search shows what it finds); the choice is kept."""
        self._forced = bool(on)
        self.body.setVisible(self._open or self._forced)
        self._fit()
        self.update()

    def mousePressEvent(self, ev) -> None:      # noqa: N802 (Qt)
        if ev.button() == Qt.LeftButton and ev.position().y() <= self._title_height():
            self.set_open(not self._open)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def paintEvent(self, ev) -> None:           # noqa: N802 (Qt)
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QPainter, QPainterPath, QPen
        from . import icons
        palette, accent = self.palette(), icons._accent()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        whole = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        head = float(self._title_height())
        card = QPainterPath()
        card.addRoundedRect(whole, 6, 6)
        p.fillPath(card, palette.color(QPalette.Base))
        p.save()                                                    # the header: the accent, faint, over the card
        p.setClipPath(card)
        tint = QColor(accent)
        tint.setAlpha(46)
        p.fillRect(QRectF(0, 0, self.width(), head), tint)
        p.restore()
        edge = palette.color(QPalette.WindowText)
        edge.setAlpha(40)
        p.setPen(QPen(edge, 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(card)
        x = 8
        if self.icon_key:
            icons.icon(self.icon_key).paint(p, QRect(x, int((head - 18) / 2), 18, 18))
            x += 24
        font = p.font()
        font.setBold(True)
        p.setFont(font)
        ink = palette.color(QPalette.WindowText)
        p.setPen(ink)
        right = 28 + (self.MORE_ROOM if getattr(self, "more_button", None) is not None else 0)
        title = p.fontMetrics().elidedText(self.title(), Qt.ElideRight, max(10, self.width() - x - right))
        p.drawText(QRectF(x, 0, max(10, self.width() - x - right + 4), head), Qt.AlignVCenter | Qt.AlignLeft, title)
        ink.setAlpha(170)
        pen = QPen(ink, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        cx, cy = self.width() - 14.0, head / 2.0
        if self._open or self._forced:
            p.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])
        else:
            p.drawPolyline([QPointF(cx - 2, cy - 4), QPointF(cx + 2, cy), QPointF(cx - 2, cy + 4)])
        p.end()


FoldBox = Card                                                      # (the name the Environment page's groups were made with)


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

    def __init__(self, labels, parent=None, icons=(), per_row: int = 0):
        """``per_row``: more than one row, so many buttons in each (0: all in one)."""
        super().__init__(parent)
        from PySide6.QtWidgets import QButtonGroup, QGridLayout, QToolButton
        lay = QGridLayout(self) if per_row else QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.icon_keys = tuple(icons)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = []
        for i, text in enumerate(labels):
            b = QToolButton()
            b.setText(text)
            if i < len(self.icon_keys):
                from . import icons as drawings
                b.setIcon(drawings.icon(self.icon_keys[i]))
                b.setIconSize(QSize(20, 20))
                b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)        # (beside it, three would not fit a narrow tray)
                font = b.font()
                font.setPixelSize(10)
                b.setFont(font)
            b.setCheckable(True)
            b.setSizePolicy(QSizePolicy.Ignored if self.icon_keys else QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setMinimumHeight(48 if self.icon_keys else 28)
            self._group.addButton(b, i)
            self._buttons.append(b)
            if per_row:
                lay.addWidget(b, i // per_row, i % per_row)
            else:
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
