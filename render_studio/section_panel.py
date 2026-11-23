# SPDX-License-Identifier: GPL-3.0-or-later
"""The Section tab of Render Studio's panel: how the model's section looks in the render.

The cut itself is IngeTrazo's active section plane (the Section tool); here: whether the
cut is closed with a face, its colour, and whether the removed part still blocks the light.
"""
from __future__ import annotations

from .i18n import tr, translate_on_show  # noqa: F401

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from . import section as S
from .widgets import NumberSlider


def _note(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet("color: gray; font-size: 11px")
    return lab


class ColourButton(QPushButton):
    """A button that is its colour: click to choose another."""
    changed = Signal()

    def __init__(self, rgb, title="Colour", parent=None, linear=False):
        super().__init__(parent)
        self._title = title
        self._linear = linear                 # the values are Blender's (linear light): the swatch and the chooser show them as the eye sees them
        self.set_rgb(rgb)
        self.clicked.connect(self._pick)

    def rgb(self) -> list:
        return list(self._rgb)

    def set_rgb(self, rgb) -> None:
        self._rgb = [float(c) for c in rgb][:3]
        c = QColor.fromRgbF(*self._shown(self._rgb))
        # Only THIS button: a stylesheet with a plain «QPushButton» rule reaches every button of its children, and the colour dialog was one
        # (its OK and Cancel took the colour chosen).
        self.setObjectName("colourSwatch")
        self.setStyleSheet(f"QPushButton#colourSwatch {{ background-color: {c.name()}; border: 1px solid gray; min-height: 18px; }}")

    def _shown(self, rgb) -> list:
        """The colour as the screen shows it: linear values are encoded (a linear 0.2 is a mid grey, not a dark one)."""
        if not self._linear:
            return [max(0.0, min(1.0, c)) for c in rgb]
        return [max(0.0, min(1.0, 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055)) for c in rgb]

    @staticmethod
    def _decode(rgb) -> list:
        return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor.fromRgbF(*self._shown(self._rgb)), self.window(), tr(self._title))     # (not a child of the swatch)
        if c.isValid():
            got = (c.redF(), c.greenF(), c.blueF())
            self.set_rgb(self._decode(got) if self._linear else got)
            self.changed.emit()


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
        self.style = QComboBox()
        self.style.addItem(tr("Material of the drawing"), "material")
        self.style.addItem(tr("Flat colour"), "flat")
        self.style.addItem(tr("Hatch pattern"), "hatch")
        self.style.addItem(tr("Like the drawing"), "drawing")
        self.style.setToolTip("What the cap is made of: a material of the drawing (with its picture and finish), "
                              "one plain colour, a pattern of lines or dots over a colour, or what IngeTrazo itself fills the cut with "
                              "(the section's own fill, or Styles › Section fill): what you see in the 3D view is what renders.")
        self.style.currentIndexChanged.connect(self._edited)
        form.addRow("Cap", self.style)
        self.material = QComboBox()
        self.material.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.material.setMinimumContentsLength(8)
        self.material.setToolTip("The cap is made of this material of the drawing, so it takes its "
                                 "picture, finish and the settings of the material editor.")
        self.material.currentIndexChanged.connect(self._edited)
        form.addRow("Material", self.material)
        self.drawing_note = _note("The cap is filled as the drawing fills its cut: the plane's or the box's own fill, else the style's "
                                  "Section fill (a solid colour, a hatch, a cross hatch, or none).")
        form.addRow(self.drawing_note)
        self.colour = ColourButton(S.DEFAULT["color"], "Cap colour")
        self.colour.setToolTip("The cap's colour (the ground of a hatch).")
        self.colour.changed.connect(self._edited)
        form.addRow("Colour", self.colour)
        self.pattern = QComboBox()
        for key, label in (("diagonal", "Diagonal lines"), ("cross", "Cross hatch"), ("grid", "Grid"), ("dots", "Dots")):
            self.pattern.addItem(tr(label), key)
        self.pattern.currentIndexChanged.connect(self._edited)
        form.addRow("Pattern", self.pattern)
        self.line = ColourButton(S.DEFAULT["line"], "Line colour")
        self.line.setToolTip("The colour of the lines or dots.")
        self.line.changed.connect(self._edited)
        form.addRow("Lines", self.line)
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(0.5, 500.0)
        self.spacing.setDecimals(1)
        self.spacing.setSingleStep(1.0)
        self.spacing.setSuffix(" cm")
        self.spacing.setValue(S.DEFAULT["spacing"] * 100.0)
        self.spacing.setKeyboardTracking(False)
        self.spacing.setToolTip("The distance between lines (or dots), in the real size of the drawing.")
        self.spacing.valueChanged.connect(self._edited)
        form.addRow("Spacing", self.spacing)
        self.outline = QCheckBox("Outline of the cap")
        self.outline.setChecked(True)
        self.outline.setToolTip("Draws the rim of the cap: a line round every cut wall and slab, with its own colour and thickness. In the "
                                "finished picture it stays a line you can restyle (colour, thickness) until you save.")
        self.outline.toggled.connect(self._edited)
        form.addRow(self.outline)
        self.outline_colour = ColourButton(S.DEFAULT["outline_color"], "Colour of the cap's outline")
        self.outline_colour.setToolTip("The colour of the cap's outline.")
        self.outline_colour.changed.connect(self._edited)
        form.addRow("Outline colour", self.outline_colour)
        self.outline_width = NumberSlider(0.5, 10.0, 0.1, "{:.1f} px")
        self.outline_width.setValue(S.DEFAULT["outline_width"])
        self.outline_width.setToolTip("The thickness of the cap's outline, in pixels of the finished picture.")
        self.outline_width.valueChanged.connect(self._edited)
        form.addRow("Outline thickness", self.outline_width)
        self.outline.toggled.connect(lambda on: (self.outline_colour.setEnabled(on), self.outline_width.setEnabled(on)))
        self.shadows = QCheckBox("No shadows on the cap")
        self.shadows.setToolTip("The cap neither casts nor receives shadows: it keeps its colour evenly, "
                                "as a drawn section, whatever the sun does.")
        self.shadows.toggled.connect(self._edited)
        form.addRow(self.shadows)
        self.form = form
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
        lay.addWidget(_note("The cut is the drawing's active section plane and section box (the Section tools place and flip them). "
                            "It is read again whenever the preview reloads."))
        lay.addStretch(1)
        self._fill()
        self._paint()

    # -- values -----------------------------------------------------------------------
    def settings(self) -> dict:
        return {"cap": self.cap.isChecked(), "style": self.style.currentData(), "material": self._wanted,
                "color": self.colour.rgb(), "pattern": self.pattern.currentData(), "line": self.line.rgb(),
                "spacing": round(self.spacing.value() / 100.0, 4), "shadows": not self.shadows.isChecked(),
                "light": self.light.currentData(), "outline": self.outline.isChecked(),
                "outline_color": self.outline_colour.rgb(), "outline_width": round(self.outline_width.value(), 2)}

    def apply(self, raw) -> None:
        d = S.clean(raw)
        mine = (self.cap, self.material, self.light, self.style, self.pattern, self.spacing, self.shadows, self.outline,
                self.outline_width)
        for w in mine:
            w.blockSignals(True)
        self.cap.setChecked(d["cap"])
        self.style.setCurrentIndex(max(0, self.style.findData(d["style"])))
        self.pattern.setCurrentIndex(max(0, self.pattern.findData(d["pattern"])))
        self.colour.set_rgb(d["color"])
        self.line.set_rgb(d["line"])
        self.spacing.setValue(d["spacing"] * 100.0)
        self.shadows.setChecked(not d["shadows"])
        self.outline.setChecked(d["outline"])
        self.outline_colour.set_rgb(d["outline_color"])
        self.outline_width.setValue(d["outline_width"])
        self.outline_colour.setEnabled(d["outline"])
        self.outline_width.setEnabled(d["outline"])
        self._wanted = d["material"]
        self.light.setCurrentIndex(max(0, self.light.findData(d["light"])))
        self._fill()
        for w in mine:
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
        kind = S.describe(self.app.scene)
        self.state.setText({
            "plane": tr("Cut by the active section plane."),
            "box": tr("Cut by the active section box (its six faces)."),
            "both": tr("Cut by the active section plane and the active section box."),
            "off": tr("Section cuts are switched off in the 3D view (View ▸ Section Cuts): the render shows the whole model."),
        }.get(kind, tr("No active section plane or box: the render shows the whole model.")))
        capped = self.cap.isChecked()
        style = self.style.currentData()
        self.drawing_note.setVisible(style == "drawing")
        for w, shown in ((self.style, True), (self.material, style == "material"), (self.colour, style in ("flat", "hatch")),
                         (self.pattern, style == "hatch"), (self.line, style == "hatch"),
                         (self.spacing, style == "hatch"), (self.shadows, True)):
            self.form.setRowVisible(w, shown)
            w.setEnabled(capped)
        name = self.material.currentData() if style == "material" else None
        if name and not (getattr(self, "_counts", {}) or {}).get(name):
            self.state.setText(self.state.text() + "\n" + tr("The cap material is in no face of the model: "
                               "only its colour is used (no picture). Paint something with it to get it whole."))

    def _edited(self, *_a) -> None:
        self._wanted = self.material.currentData()
        self._paint()
        self.changed.emit()
