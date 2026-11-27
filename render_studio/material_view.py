# SPDX-License-Identifier: GPL-3.0-or-later
"""The pieces the material editor's window is made of, as the style guide asks: a setting is a BLOCK (its name
above, its value at the right, its control under them), big buttons with an icon for a choice among a few, and an
EYE per setting in the Expert tab that says whether it is also in the Material tab (the same idea as the panel's
Expert page; the eyes change what is in view, never a value of the material)."""
from __future__ import annotations

import json
import unicodedata

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from . import icons, widgets
from .expert import EYE_STYLE
from .i18n import tr

_EYES = "render_studio/material_eyes"

#: The settings that start hidden in the Material tab (the finer ones).
HIDDEN = {"ior", "coat", "coat_roughness", "sheen", "relief_height", "rough_min", "rough_max", "ao_strength",
          "variation", "translucency"}
#: …except where one is what the type is about.
SHOWN_FOR = {"foliage": {"translucency"}}

#: The finer settings: kept in a material only once they are chosen (else the finish's own).
#: key → (label, lowest, highest, where the slider rests while automatic, tip)
OPTIONAL = {
    "set_relief": ("Amount", 0.0, 2.0, 1.0, "How strong the texture set's own relief is: 100 % as the set draws it."),
    "relief_height": ("Relief height", 1.0, 50.0, 8.0, "The true depth of a relief drawn from a picture, a height map or the "
                                                       "fine grain, from its lowest to its highest point."),
    "ior": ("Refraction index (IOR)", 1.0, 2.0, 1.5, "How strong the reflection is, and how much glass or water bend the "
                                                     "light: water 1.33, glass 1.45 to 1.52."),
    "coat": ("Varnish", 0.0, 1.0, 0.0, "A clear glossy layer over the material: varnished wood, car paint, glazed tiles."),
    "coat_roughness": ("Varnish roughness", 0.0, 1.0, 0.05, "0 a mirror-like varnish, higher a satin one."),
    "sheen": ("Sheen", 0.0, 1.0, 0.0, "The soft light at grazing angles of velvet and cloth."),
    "rough_min": ("Roughness: lowest", 0.0, 1.0, 0.0, "With a roughness map: the roughness its black stands for."),
    "rough_max": ("Roughness: highest", 0.0, 1.0, 1.0, "With a roughness map: the roughness its white stands for. "
                                                        "Below the lowest, the map is turned over."),
    "ao_strength": ("Ambient occlusion", 0.0, 1.0, 0.75, "How much the texture set's occlusion map darkens the "
                                                          "joints and hollows."),
    "variation": ("Tone variation", 0.0, 1.0, 0.0, "Large soft patches a little lighter and darker, so a big surface "
                                                    "is not one even tone."),
    "translucency": ("Translucency", 0.0, 1.0, 0.0, "Light that comes through a thin surface: leaves, curtains, paper, "
                                                     "lamp shades."),
}


def shown_value(key: str, v: float) -> str:
    if key in ("set_relief", "ao_strength", "variation", "translucency"):
        return f"{v * 100:.0f}%"
    if key == "relief_height":
        return f"{v:.0f} mm"
    return f"{v:.2f}"


def plain(text: str) -> str:
    """Without accents or capitals, to search."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))


class StatusLine(QLabel):
    """A message line that takes no room while it has nothing to say."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setStyleSheet("color: gray")
        self.setVisible(False)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt)
        super().setText(text)
        self.setVisible(bool(text))


class Eyes:
    """Which settings the Material tab shows: the default, plus what the person opened or closed."""

    def __init__(self, setting: str = _EYES, hidden=None, shown_for=None):
        """``setting``: where the person's choices are kept; ``hidden``: what starts out of sight;
        ``shown_for``: {kind: what is in view for it although it starts hidden}."""
        self.setting = setting
        self.hidden = HIDDEN if hidden is None else set(hidden)
        self.shown_for = SHOWN_FOR if shown_for is None else shown_for
        try:
            raw = json.loads(str(QSettings().value(self.setting, "") or "{}"))
            self.own = {str(k): bool(v) for k, v in raw.items()}
        except (ValueError, AttributeError, TypeError):
            self.own = {}

    def on(self, key: str, kind: str = "") -> bool:
        return self.own.get(key, key not in self.hidden or key in self.shown_for.get(kind, ()))

    def set(self, key: str, on: bool) -> None:
        self.own[key] = bool(on)
        if self.own[key] == (key not in self.hidden):
            del self.own[key]
        QSettings().setValue(self.setting, json.dumps(self.own))

    def reset(self) -> None:
        self.own = {}
        QSettings().setValue(self.setting, "{}")


class Block(QWidget):
    """One setting: the name above, the value at the right, the control under them."""

    eye_clicked = Signal(str, bool)
    reset_clicked = Signal(str)

    def __init__(self, key: str, label: str, control=None, value: QLabel | None = None, extra=None, parent=None):
        super().__init__(parent)
        self.key = key
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 4)
        lay.setSpacing(3)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)
        self.name = QLabel(tr(label) if label else "")
        if not label:
            self.name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.value = value if value is not None else QLabel("")
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.reset = QToolButton()
        self.reset.setIcon(icons.icon("undo"))
        self.reset.setAutoRaise(True)
        self.reset.setToolTip(tr("Back to automatic"))
        self.reset.setVisible(False)
        self.reset.clicked.connect(lambda _c=False: self.reset_clicked.emit(self.key))
        self.eye = QToolButton()
        self.eye.setCheckable(True)
        self.eye.setAutoRaise(True)
        self.eye.setIconSize(QSize(18, 18))
        self.eye.setStyleSheet(EYE_STYLE)
        self.eye.setCursor(Qt.PointingHandCursor)
        self.eye.setVisible(False)
        self.eye.clicked.connect(lambda on: self.eye_clicked.emit(self.key, on))
        top.addWidget(self.name, 1)
        top.addWidget(self.value)
        if not label:
            self.value.setVisible(False)
        top.addWidget(self.reset)
        if extra is not None:
            top.addWidget(extra)
        top.addWidget(self.eye)
        lay.addLayout(top)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(4)
        lay.addLayout(self.body)
        if control is not None and not label and isinstance(control, QWidget):
            top.insertWidget(0, control, 1)                # no name: the eye shares the control's row
            self.name.setVisible(False)
            top.setAlignment(self.eye, Qt.AlignTop)
        elif control is not None:
            self.add(control)

    def add(self, item):
        if isinstance(item, QWidget):
            self.body.addWidget(item)
        else:
            self.body.addLayout(item)
        return item

    def show_eye(self, expert: bool, on: bool) -> None:
        self.eye.setVisible(expert)
        self.eye.setChecked(on)
        self.eye.setIcon(icons.icon("eye" if on else "eye_off"))
        self.eye.setToolTip(tr("In the Material tab: click to hide it there") if on
                            else tr("Only here: click to show it in the Material tab"))


class DataButtons(widgets.ChoiceButtons):
    """Big buttons with an icon, one chosen, each with its datum: what a combo box offers
    (``currentData``, ``findData``), and ``activated`` when the person presses one."""

    activated = Signal(int)

    def __init__(self, entries, parent=None, per_row: int = 0):
        """``entries``: (datum, words, icon key). ``per_row``: more than one row, so many in each."""
        super().__init__([e[1] for e in entries], parent, icons=[e[2] for e in entries], per_row=per_row)
        self._data = [e[0] for e in entries]
        self.setStyleSheet(widgets.flat_style())
        for i, b in enumerate(self._buttons):
            b.setToolTip(entries[i][1])
            b.clicked.connect(lambda _c=False, n=i: self.activated.emit(n))

    def currentData(self):
        return self._data[self.currentIndex()]

    def findData(self, datum) -> int:
        return self._data.index(datum) if datum in self._data else -1

    def button(self, datum) -> QToolButton:
        return self._buttons[self._data.index(datum)]


def tool_button(text: str, icon: str, tip: str = "", *, under: bool = False, checkable: bool = False) -> QToolButton:
    """A flat button with an icon: beside its words, or above them (buttons side by side)."""
    b = QToolButton() if under else widgets.CentredButton()
    b.setText(text)
    b.setIcon(icons.icon(icon))
    b.setToolTip(tip)
    b.setCheckable(checkable)
    if under:
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setIconSize(QSize(20, 20))
        font = b.font()
        font.setPixelSize(10)
        b.setFont(font)
        b.setMinimumHeight(46)
    else:
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setIconSize(QSize(18, 18))
        b.setMinimumHeight(30)
    b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    b.setStyleSheet(widgets.flat_style())
    return b
