# SPDX-License-Identifier: GPL-3.0-or-later
"""The picture adjustments of the material editor: hue, saturation, brightness, contrast, rotation,
a colour tint and a flat colour instead of the picture.

They are kept in the material's settings (``spec["image"]``) and applied by Blender on the picture's
colour (``studio_scene._image_adjust``): the render and the preview show them, the 3D view keeps the
original picture. Only what differs from the picture as it is gets saved.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QToolButton, QVBoxLayout, QWidget)

#: key → (label, minimum, maximum, default, tooltip); the slider works in these units.
SLIDERS = (
    ("hue", "Hue", -180, 180, 0, "Turn every colour of the picture round the colour wheel, in degrees."),
    ("saturation", "Saturation", 0, 200, 100, "0 % grey, 100 % as it is, 200 % twice as vivid."),
    ("brightness", "Brightness", -100, 100, 0, "Lighter or darker, all the picture."),
    ("contrast", "Contrast", -100, 100, 0, "Spread the light and the dark parts apart, or squeeze them together."),
    ("rotation", "Rotation", -180, 180, 0, "Turn the picture on the surface, in degrees, about its middle."),
)
_SCALE = {"saturation": 100.0, "brightness": 100.0, "contrast": 100.0}     # slider → spec value


def _swatch(button, rgb):
    c = QColor.fromRgbF(*rgb) if rgb else QColor(200, 200, 200)
    button.setStyleSheet(f"background-color: {c.name()}; border: 1px solid gray; min-width: 34px")


class ImageAdjust(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self.tint = None            # a colour (floats 0-1) or None
        self.flat = None            # the colour that replaces the picture, or None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.header = QToolButton()
        self.header.setText("Picture adjustments")
        self.header.setCheckable(True)
        self.header.setArrowType(Qt.RightArrow)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setAutoRaise(True)
        self.header.setToolTip("Change the picture's hue, brightness, contrast, rotation, tint or colour in the "
                               "render and the preview. The 3D view keeps the original picture.")
        self.header.toggled.connect(self._fold)
        outer.addWidget(self.header)
        self.body = QWidget()
        form = QFormLayout(self.body)
        form.setContentsMargins(14, 0, 0, 0)
        self.form = form
        self.sliders, self.values, self._rows = {}, {}, {}
        for key, label, lo, hi, default, tip in SLIDERS:
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.setValue(default)
            s.setToolTip(tip)
            v = QLabel("")
            v.setMinimumWidth(40)
            row = QHBoxLayout()
            row.addWidget(s, 1)
            row.addWidget(v)
            s.valueChanged.connect(lambda _x, k=key: self._moved(k))
            form.addRow(label, row)
            self.sliders[key], self.values[key], self._rows[key] = s, v, row
            self._label(key)
        trow = QHBoxLayout()
        self.tint_btn = QPushButton("")
        self.tint_btn.setToolTip("The colour laid over the picture (it multiplies it). Click to choose; "
                                 "the slider is how much.")
        self.tint_btn.clicked.connect(lambda: self._pick("tint"))
        _swatch(self.tint_btn, None)
        self.tint_strength = QSlider(Qt.Horizontal)
        self.tint_strength.setRange(0, 100)
        self.tint_strength.setValue(50)
        self.tint_strength.valueChanged.connect(self._tint_moved)
        self.tint_value = QLabel("")
        self.tint_value.setMinimumWidth(40)
        trow.addWidget(self.tint_btn)
        trow.addWidget(self.tint_strength, 1)
        trow.addWidget(self.tint_value)
        form.addRow("Tint", trow)
        self._rows["tint"] = trow
        frow = QHBoxLayout()
        self.flat_check = QCheckBox("Flat colour instead of the picture")
        self.flat_check.setToolTip("Replace the picture by one colour. The other adjustments then work on it.")
        self.flat_check.toggled.connect(self._flat_toggled)
        self.flat_btn = QPushButton("")
        self.flat_btn.setToolTip("Choose the colour")
        self.flat_btn.clicked.connect(lambda: self._pick("flat"))
        _swatch(self.flat_btn, None)
        frow.addWidget(self.flat_check, 1)
        frow.addWidget(self.flat_btn)
        form.addRow(frow)
        self._rows["flat"] = frow
        self.reset_btn = QPushButton("Reset the picture")
        self.reset_btn.setToolTip("Back to the picture as it is.")
        self.reset_btn.clicked.connect(self.reset)
        form.addRow(self.reset_btn)
        outer.addWidget(self.body)
        self.body.setVisible(False)
        self._tint_moved()

    # -- values ------------------------------------------------------------------------
    def _value(self, key) -> float:
        return self.sliders[key].value() / _SCALE.get(key, 1.0)

    def _label(self, key):
        v = self.sliders[key].value()
        self.values[key].setText(f"{v}%" if key in _SCALE else f"{v}°")

    def _moved(self, key):
        self._label(key)
        self._edited()

    def _tint_moved(self, *_a):
        self.tint_value.setText(f"{self.tint_strength.value()}%")
        self._edited()

    def _edited(self, *_a):
        if not self._loading:
            self.changed.emit()

    def spec(self):
        """What differs from the picture as it is, or None."""
        out = {}
        for key, _label, _lo, _hi, default, _tip in SLIDERS:
            raw = self.sliders[key].value()
            if raw != default:
                out[key] = round(raw / _SCALE.get(key, 1.0), 3) if key in _SCALE else raw
        if self.tint is not None and self.tint_strength.value() > 0:
            out["tint"] = [round(c, 4) for c in self.tint]
            out["tint_strength"] = round(self.tint_strength.value() / 100.0, 2)
        if self.flat_check.isChecked() and self.flat is not None:
            out["flat"] = [round(c, 4) for c in self.flat]
        return out or None

    def load(self, spec, has_picture=True):
        """Show ``spec`` (a material's ``image`` settings, or None); the rotation and the flat colour
        only mean something with a picture."""
        spec = spec or {}
        self._loading = True
        for key, _label, lo, hi, default, _tip in SLIDERS:
            v = spec.get(key)
            raw = default if v is None else int(round(float(v) * _SCALE.get(key, 1.0)))
            self.sliders[key].setValue(max(lo, min(hi, raw)))
            self._label(key)
        self.tint = list(spec["tint"]) if spec.get("tint") else None
        _swatch(self.tint_btn, self.tint)
        self.tint_strength.setValue(int(round(float(spec.get("tint_strength", 0.5)) * 100)))
        self.tint_value.setText(f"{self.tint_strength.value()}%")
        self.flat = list(spec["flat"]) if spec.get("flat") else self.flat
        self.flat_check.setChecked(bool(spec.get("flat")))
        _swatch(self.flat_btn, self.flat)
        self._loading = False
        self.set_has_picture(has_picture)
        if spec:
            self.header.setChecked(True)               # something is set: show it

    def set_has_picture(self, has_picture: bool):
        for key in ("rotation", "flat"):
            self.form.setRowVisible(self._rows[key], bool(has_picture))

    def reset(self):
        self.load(None, True)
        self.changed.emit()

    # -- colours -----------------------------------------------------------------------
    def _fold(self, on):
        self.header.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.body.setVisible(bool(on))

    def _pick(self, which):
        current = getattr(self, which)
        c = QColorDialog.getColor(QColor.fromRgbF(*current) if current else QColor(255, 255, 255), self,
                                  "Tint colour" if which == "tint" else "Flat colour")
        if c.isValid():
            self.set_colour(which, (c.redF(), c.greenF(), c.blueF()))

    def set_colour(self, which, rgb):
        """Choose the tint or the flat colour without the dialog (also what the buttons do)."""
        rgb = [float(x) for x in rgb[:3]]
        if which == "tint":
            self.tint = rgb
            _swatch(self.tint_btn, rgb)
        else:
            self.flat = rgb
            _swatch(self.flat_btn, rgb)
            self._loading = True
            self.flat_check.setChecked(True)
            self._loading = False
        self._edited()

    def _flat_toggled(self, on):
        if on and self.flat is None:
            self.flat = [0.8, 0.8, 0.8]
            _swatch(self.flat_btn, self.flat)
        self._edited()
