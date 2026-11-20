# SPDX-License-Identifier: GPL-3.0-or-later
"""The Section tab of Render Studio's panel: how the model's section looks in the render.

The cut itself is IngeTrazo's active section plane (the Section tool); here: whether the
cut is closed with a face, its colour, and whether the removed part still blocks the light.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from . import section as S


def _note(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet("color: gray; font-size: 11px")
    return lab


class SectionTab(QWidget):
    changed = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._color = None                      # None: IngeTrazo's own colour for the cut
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.state = _note()
        lay.addWidget(self.state)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.cap = QCheckBox("Close the cut with a face")
        self.cap.setChecked(True)
        self.cap.setToolTip("Without it the cut is open and the inside of the walls shows.")
        self.cap.toggled.connect(self._edited)
        form.addRow(self.cap)
        row = QHBoxLayout()
        self.own = QCheckBox("As in IngeTrazo")
        self.own.setChecked(True)
        self.own.setToolTip("The colour the cut is filled with in the 3D view (the Section's own fill).")
        self.own.toggled.connect(self._edited)
        self.pick = QPushButton("Colour…")
        self.pick.clicked.connect(self._choose)
        row.addWidget(self.own)
        row.addWidget(self.pick)
        form.addRow("Cap colour", row)
        self.light = QComboBox()
        self.light.addItem("Light enters the cut (open)", "open")
        self.light.addItem("The removed part still blocks light", "blocked")
        self.light.setToolTip(
            "Open: what is cut away is gone, so sun and sky light the inside (an interior "
            "section brighter than the building really is).\nBlocked: the removed part stays "
            "out of the picture but still casts shadow and bounces light, so the inside is "
            "lit as in the real building (Cycles; EEVEE may show it).")
        self.light.currentIndexChanged.connect(self._edited)
        form.addRow("Light", self.light)
        lay.addLayout(form)
        lay.addWidget(_note("The cut is the active Section plane of the drawing; the Section tool "
                            "places and flips it. It is read again whenever the preview reloads."))
        lay.addStretch(1)
        self._paint()

    # -- values -----------------------------------------------------------------------
    def settings(self) -> dict:
        return {"cap": self.cap.isChecked(), "color": None if self.own.isChecked() else list(self._color or S.FALLBACK_COLOR),
                "light": self.light.currentData()}

    def apply(self, raw) -> None:
        d = S.clean(raw)
        for w in (self.cap, self.own, self.light):
            w.blockSignals(True)
        self.cap.setChecked(d["cap"])
        self._color = d["color"]
        self.own.setChecked(d["color"] is None)
        self.light.setCurrentIndex(max(0, self.light.findData(d["light"])))
        for w in (self.cap, self.own, self.light):
            w.blockSignals(False)
        self._paint()

    def document_changed(self) -> None:
        self._paint()

    # -- ui -----------------------------------------------------------------------------
    def _paint(self) -> None:
        has = False
        try:
            has = self.app.scene.active_section() is not None
        except Exception:  # noqa: BLE001
            pass
        self.state.setText("Active section: the render is cut." if has else
                           "No active section plane: the render shows the whole model.")
        self.own.setEnabled(self.cap.isChecked())
        self.pick.setEnabled(self.cap.isChecked() and not self.own.isChecked())
        c = self._color or S.FALLBACK_COLOR
        self.pick.setStyleSheet("" if self.own.isChecked() else
                                f"border-left: 14px solid {QColor.fromRgbF(*c).name()}")

    def _choose(self) -> None:
        c = QColor.fromRgbF(*(self._color or S.FALLBACK_COLOR))
        c = QColorDialog.getColor(c, self, "Cap colour")
        if c.isValid():
            self._color = [c.redF(), c.greenF(), c.blueF()]
            self._edited()

    def _edited(self, *_a) -> None:
        self._paint()
        self.changed.emit()
