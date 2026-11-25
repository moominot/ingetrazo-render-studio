# SPDX-License-Identifier: GPL-3.0-or-later
"""The «New material» dialog of the material editor: a name, a flat colour or a picture, and whether to paint
what is selected with it."""
from __future__ import annotations

from . import wheel_guard
from .i18n import tr, translate_on_show  # noqa: F401

from pathlib import Path

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout)

IMAGES = "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga)"


class NewMaterialDialog(QDialog):
    def __init__(self, parent=None, default_name="Material", selected=0, start_dir=""):
        super().__init__(parent)
        self.setWindowTitle("New material")
        self._dir = start_dir
        self.colour = [0.8, 0.8, 0.8]
        self.picture = ""
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(default_name)
        form.addRow("Name", self.name)
        row = QHBoxLayout()
        self.colour_btn = QPushButton("")
        self.colour_btn.setToolTip("The material's colour (when it has no picture)")
        self.colour_btn.clicked.connect(self._pick_colour)
        row.addWidget(self.colour_btn)
        row.addStretch(1)
        form.addRow("Colour", row)
        prow = QHBoxLayout()
        self.picture_btn = QPushButton("Picture…")
        self.picture_btn.setToolTip("Use an image instead of a flat colour")
        self.picture_btn.clicked.connect(self._pick_picture)
        self.picture_label = QLabel("none")
        self.clear_btn = QPushButton("×")
        self.clear_btn.setToolTip("No picture: the flat colour")
        self.clear_btn.setMaximumWidth(26)
        self.clear_btn.clicked.connect(self.clear_picture)
        prow.addWidget(self.picture_btn)
        prow.addWidget(self.picture_label, 1)
        prow.addWidget(self.clear_btn)
        form.addRow("Picture", prow)
        self.tile = QDoubleSpinBox()
        self.tile.setRange(0.01, 100.0)
        self.tile.setDecimals(2)
        self.tile.setSingleStep(0.1)
        self.tile.setValue(1.0)
        self.tile.setSuffix(" m")
        self.tile.setToolTip("How wide the picture is on a surface; its height follows its proportions")
        form.addRow("Tile width", self.tile)
        lay.addLayout(form)
        self.apply = QCheckBox(tr("Paint the selection with it ({n} selected)", n=selected) if selected
                               else tr("Paint the selection with it (nothing selected)"))
        self.apply.setChecked(bool(selected))
        self.apply.setEnabled(bool(selected))
        lay.addWidget(self.apply)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self._refresh()
        wheel_guard.watch(self)          # (the wheel scrolls; it changes only a picked field)

    def _swatch(self):
        c = QColor.fromRgbF(*self.colour)
        self.colour_btn.setStyleSheet(f"background-color: {c.name()}; border: 1px solid gray; min-width: 60px")

    def _refresh(self):
        self._swatch()
        has = bool(self.picture)
        self.picture_label.setText(Path(self.picture).name if has else "none")
        self.tile.setEnabled(has)
        self.clear_btn.setEnabled(has)
        self.colour_btn.setEnabled(not has)

    def _pick_colour(self):
        c = QColorDialog.getColor(QColor.fromRgbF(*self.colour), self, "Colour of the material")
        if c.isValid():
            self.colour = [c.redF(), c.greenF(), c.blueF()]
            self._refresh()

    def _pick_picture(self):
        path, _f = QFileDialog.getOpenFileName(self, "Picture of the material", self._dir, IMAGES)
        if path:
            self.set_picture(path)

    def set_picture(self, path):
        self.picture = str(path)
        self._dir = str(Path(path).parent)
        self._refresh()

    def clear_picture(self):
        self.picture = ""
        self._refresh()

    def set_colour(self, rgb):
        self.colour = [float(c) for c in rgb[:3]]
        self._refresh()

    def values(self) -> dict:
        """``name``, ``color`` or ``texture`` (``{"path", "sw", "sh"}``), ``apply``."""
        out = {"name": self.name.text().strip(), "apply": self.apply.isChecked()}
        if self.picture:
            img = QImage(self.picture)
            ratio = img.height() / img.width() if not img.isNull() and img.width() else 1.0
            sw = round(self.tile.value(), 3)
            out["texture"] = {"path": self.picture, "sw": sw, "sh": round(sw * ratio, 3)}
        else:
            out["color"] = tuple(self.colour)
        return out
