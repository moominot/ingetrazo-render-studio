# SPDX-License-Identifier: GPL-3.0-or-later
"""The Section tab of Render Studio's panel: how the model's section looks in the render.

The cut itself is IngeTrazo's active section plane (the Section tool); here: whether the
cut is closed with a face, its colour, and whether the removed part still blocks the light.
"""
from __future__ import annotations

from .i18n import tr, translate_on_show  # noqa: F401

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QVBoxLayout, QWidget)

from . import section as S


def _note(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet("color: gray; font-size: 11px")
    return lab


class SectionTab(QWidget):
    changed = Signal()

    def __init__(self, app, parent=None, live=None):
        super().__init__(parent)
        self.app = app
        self._live = live                       # () -> bool: the preview window is open
        self._stale = False                     # the model changed while nobody needed the list
        self._wanted = None                     # the material chosen (kept while it is not in the list)
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
        self.material = QComboBox()
        self.material.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.material.setMinimumContentsLength(8)
        self.material.setToolTip("The cap is made of this material of the drawing, so it takes its "
                                 "picture, finish and the settings of the material editor.")
        self.material.currentIndexChanged.connect(self._edited)
        form.addRow("Cap material", self.material)
        self.light = QComboBox()
        self.light.addItem(tr("Light enters the cut (open)"), "open")
        self.light.addItem(tr("The removed part still blocks light"), "blocked")
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
        self._fill()
        self._paint()

    # -- values -----------------------------------------------------------------------
    def settings(self) -> dict:
        return {"cap": self.cap.isChecked(), "material": self._wanted,
                "light": self.light.currentData()}

    def apply(self, raw) -> None:
        d = S.clean(raw)
        for w in (self.cap, self.material, self.light):
            w.blockSignals(True)
        self.cap.setChecked(d["cap"])
        self._wanted = d["material"]
        self.light.setCurrentIndex(max(0, self.light.findData(d["light"])))
        self._fill()
        for w in (self.cap, self.material, self.light):
            w.blockSignals(False)
        self._paint()

    def _fill(self) -> None:
        """The document's materials in the list (the chosen one stays even if it is gone)."""
        from . import materials as mats
        try:
            counts = mats.used_materials(self.app.scene)
        except Exception:  # noqa: BLE001
            counts = {}
        names = sorted(counts, key=str.lower)
        if self._wanted and self._wanted not in names:
            names.append(self._wanted)
        self.material.blockSignals(True)
        self.material.clear()
        self.material.addItem(tr("None (plain grey)"), None)
        for n in names:
            self.material.addItem(n if counts.get(n) else tr("{name} (not in the model)", name=n), n)
        self.material.setCurrentIndex(max(0, self.material.findData(self._wanted)))
        self.material.blockSignals(False)
        self._counts = counts

    def matters(self) -> bool:
        """Whether the model's changes are worth following here: the preview window is open and a
        section plane is active (that is when the cap exists), or the tab is on screen (someone
        is about to choose the cap material). Otherwise it did nothing but read every face's
        paint on every edit and selection."""
        if self.isVisible() or self._live is None:
            return True
        try:
            return bool(self._live()) and self.app.scene.active_section() is not None
        except Exception:  # noqa: BLE001 - an old IngeTrazo: no sections, nothing to follow
            return False

    def document_changed(self) -> None:
        if not self.matters():
            self._stale = True
            return
        self.catch_up()

    def catch_up(self) -> None:
        self._stale = False
        self._fill()
        self._paint()

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if self._stale:
            self.catch_up()

    # -- ui -----------------------------------------------------------------------------
    def _paint(self) -> None:
        has = False
        try:
            has = self.app.scene.active_section() is not None
        except Exception:  # noqa: BLE001
            pass
        self.state.setText(tr("Active section: the render is cut.") if has else
                           tr("No active section plane: the render shows the whole model."))
        self.material.setEnabled(self.cap.isChecked())
        name = self.material.currentData()
        if name and not (getattr(self, "_counts", {}) or {}).get(name):
            self.state.setText(self.state.text() + "\n" + tr("The cap material is in no face of the model: "
                               "only its colour is used (no picture). Paint something with it to get it whole."))

    def _edited(self, *_a) -> None:
        self._wanted = self.material.currentData()
        self._paint()
        self.changed.emit()
