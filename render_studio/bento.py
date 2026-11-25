# SPDX-License-Identifier: GPL-3.0-or-later
"""Big icon buttons for a choice: a grid of «icon over label» buttons that drives a combo box.

The idea (a bento of tiles with large, clear buttons) comes from the Croquis extension's panel
(github.com/vicc3d/croquis-ingetrazo, GPL-3.0-or-later); this is its own code and its own icons.

:class:`ChoiceGrid` keeps a ``QComboBox`` as the source of truth: it is built from the combo's items, a click sets the
combo's index, and a change of the combo (a loaded preset, a reset) checks the matching button. Every other part of the
panel keeps talking to the combo, so nothing else changes when a combo is replaced by a grid.

Icons are SVG on a 24 grid, drawn with ``currentColor``: painted in the theme's text colour and in the accent colour
when chosen, and redrawn when the theme changes.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QButtonGroup, QComboBox, QFrame, QGridLayout, QSizePolicy, QToolButton)

_HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
         'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">')

#: Icons of the render styles (presets.STYLES keys), 24 grid, ``currentColor``.
STYLE_ICONS = {
    # A picture as it is: frame, sun and hills.
    "none": '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.5"/>'
            '<path d="M3 17l5.5-5 4 4 3-3 5.5 5"/>',
    # A cube, every face the same.
    "white": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
    # The same cube with one face filled: one material for everything.
    "model": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>'
             '<path d="M4 7.5l8 4.5v9l-8-4.5z" fill="currentColor" fill-opacity=".35" stroke="none"/>',
    # A sun: the light each surface receives.
    "light": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5V5M12 19v2.5M2.5 12H5M19 12h2.5'
             'M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/>',
    # A pencil.
    "sketch": '<path d="M4 20l1-4L16 5l3 3L8 19z"/><path d="M14 7l3 3"/>',
    # A drop of paint.
    "watercolour": '<path d="M12 3S5.5 10 5.5 14.5a6.5 6.5 0 0 0 13 0C18.5 10 12 3 12 3z"/>'
                   '<path d="M9 15a3 3 0 0 0 3 3" opacity=".6"/>',
}

_cache: dict = {}


def icon_pixmap(svg_body: str, px: int, colour: QColor, dpr: float = 1.0) -> QPixmap:
    """The icon (the inside of the 24-grid SVG) at ``px`` logical pixels, in ``colour``."""
    key = (svg_body, px, colour.name(QColor.HexArgb), round(dpr, 2))
    pm = _cache.get(key)
    if pm is not None:
        return pm
    data = (_HEAD + svg_body + "</svg>").replace("currentColor", colour.name())
    renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
    pm = QPixmap(int(px * dpr), int(px * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, px * dpr, px * dpr))
    p.end()
    pm.setDevicePixelRatio(dpr)
    _cache[key] = pm
    return pm


def accent(pal: QPalette) -> QColor:
    """IngeTrazo's accent colour, or the palette's Highlight outside it."""
    try:
        from views.theme import accent_color
        c = accent_color()
        if c.isValid():
            return QColor(c)
    except Exception:  # noqa: BLE001 - an older IngeTrazo, or none (tests)
        pass
    return QColor(pal.color(QPalette.Highlight))


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


def stylesheet(pal: QPalette) -> str:
    """The grid's look, from the theme's palette: a quiet button, the chosen one in a wash of the accent."""
    win = pal.color(QPalette.Window)
    text = pal.color(QPalette.WindowText)
    acc = accent(pal)
    dark = win.lightness() < 128
    border = _mix(win, text, 0.16)
    hover = _mix(win, text, 0.07)
    on_bg = _mix(win, acc, 0.22 if dark else 0.14)
    muted = _mix(win, text, 0.65)
    return f"""
QFrame#choiceGrid {{ background: transparent; border: none; }}
QFrame#choiceGrid QToolButton {{ border: 1px solid {border.name()}; border-radius: 8px; padding: 7px 3px 5px 3px;
  background: transparent; color: {muted.name()}; font-size: 11px; }}
QFrame#choiceGrid QToolButton:hover {{ background: {hover.name()}; }}
QFrame#choiceGrid QToolButton:checked {{ background: {on_bg.name()}; border-color: {acc.name()}; color: {text.name()}; }}
"""


class ChoiceButton(QToolButton):
    """A checkable button with its icon over its label."""

    def __init__(self, svg_body: str | None, text: str, px: int, parent=None) -> None:
        super().__init__(parent)
        self._svg = svg_body
        self._px = px
        self.setText(text)
        self.setCheckable(True)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon if svg_body else Qt.ToolButtonTextOnly)
        self.setIconSize(QSize(px, px))
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)     # equal columns, whatever the labels
        self.setMinimumWidth(54)
        self.setCursor(Qt.PointingHandCursor)
        self.refresh_icon()

    def refresh_icon(self) -> None:
        if not self._svg:
            return
        pal = QApplication.palette()
        dpr = self.devicePixelRatioF()
        ic = QIcon()
        ic.addPixmap(icon_pixmap(self._svg, self._px, pal.color(QPalette.WindowText), dpr), QIcon.Normal, QIcon.Off)
        ic.addPixmap(icon_pixmap(self._svg, self._px, accent(pal), dpr), QIcon.Normal, QIcon.On)
        dim = QColor(pal.color(QPalette.WindowText))
        dim.setAlpha(110)
        ic.addPixmap(icon_pixmap(self._svg, self._px, dim, dpr), QIcon.Disabled, QIcon.Off)
        self.setIcon(ic)


class ChoiceGrid(QFrame):
    """A grid of big buttons, one per item of ``combo``, kept in step with it (the combo stays the value; hide it)."""

    def __init__(self, combo: QComboBox, icons: dict | None = None, columns: int = 3, icon_px: int = 26,
                 parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("choiceGrid")
        self._combo = combo
        self._icons = icons or {}
        self._columns = max(1, columns)
        self._icon_px = icon_px
        self._buttons: list[ChoiceButton] = []
        self._busy = False
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(5)
        self._group.idClicked.connect(self._to_combo)
        self.rebuild()
        combo.currentIndexChanged.connect(self._from_combo)
        self._restyle()

    def rebuild(self) -> None:
        """The buttons from the combo's items (call it again if the items change)."""
        for b in self._buttons:
            self._group.removeButton(b)
            self._grid.removeWidget(b)
            b.deleteLater()
        self._buttons = []
        for i in range(self._combo.count()):
            key = self._combo.itemData(i)
            b = ChoiceButton(self._icons.get(key), self._combo.itemText(i), self._icon_px, self)
            tip = self._combo.itemData(i, Qt.ToolTipRole)
            b.setToolTip(tip or self._combo.toolTip())
            self._group.addButton(b, i)
            self._grid.addWidget(b, i // self._columns, i % self._columns)
            self._buttons.append(b)
        for c in range(self._columns):
            self._grid.setColumnStretch(c, 1)
        self._from_combo()

    def _to_combo(self, index: int) -> None:
        if self._combo.currentIndex() != index:
            self._combo.setCurrentIndex(index)

    def _from_combo(self, *_a) -> None:
        i = self._combo.currentIndex()
        for k, b in enumerate(self._buttons):
            b.setChecked(k == i)

    def _restyle(self) -> None:
        if self._busy:                          # a stylesheet can touch the palette: no loop
            return
        self._busy = True
        try:
            # The application's palette (the theme's), not the widget's own, which the stylesheet itself changes.
            sheet = stylesheet(QApplication.palette())
            if sheet != self.styleSheet():
                self.setStyleSheet(sheet)
            for b in self._buttons:
                b.refresh_icon()
        finally:
            self._busy = False

    def changeEvent(self, ev) -> None:        # noqa: N802 (Qt)
        if ev.type() in (QEvent.PaletteChange, QEvent.ApplicationPaletteChange):
            self._restyle()
        super().changeEvent(ev)

    def buttons(self) -> list[QAbstractButton]:
        return list(self._buttons)
