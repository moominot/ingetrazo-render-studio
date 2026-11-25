# SPDX-License-Identifier: GPL-3.0-or-later
"""The Style tab's three groups, each independent of the others: the SURFACE of the model, its OUTLINE and the FINISH of the
picture. The controls hold the settings' new model (look_model.py); their limits and defaults come from the register
(params.py). Only what the choice needs is in view."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QLabel

from . import materials as mats
from . import outlines, params, widgets
from .i18n import tr
from .section_panel import ColourButton

SURFACES = {"real": "Real materials", "mono": "One colour or material", "paper": "None (paper)", "lux": "Light analysis (lux)"}
FINISHES = {"none": "None", "watercolour": "Watercolour"}
#: The outline a person gets on switching it on (pixels).
FIRST_WIDTH = 0.8


def _group(title: str):
    box = QGroupBox(title)
    form = QFormLayout(box)
    form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    return box, form


def _default(key):
    return params.defaults()[key]


class StyleGroups(QObject):
    changed = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.keep_glass_value = True
        self.boxes = []

        # -- surface
        box, form = _group("Surface")
        self.surface_form = form
        self.surface = QComboBox()
        for key, label in SURFACES.items():
            self.surface.addItem(tr(label), key)
        self.surface.setToolTip("What the model looks like: its own materials, everything in one colour or material (white, for a "
                                "maquette), nothing at all (only lines and shadows on paper), or the light each surface receives.")
        form.addRow("Surface", self.surface)
        self.material = widgets.RefreshCombo(self.fill_materials)
        self.material.setToolTip("The material every object wears: a plain colour, or a material of the drawing "
                                 "(with its picture and settings).")
        form.addRow("Material", self.material)
        self.colour = ColourButton(list(_default("surface.colour")), "Model colour", linear=True)
        self.colour.setToolTip("The colour of the model (when the material is «A colour»).")
        form.addRow("Colour", self.colour)
        self.keep_glass = QCheckBox("Keep glass and water")
        self.keep_glass.setToolTip("On: glass and water stay as they are, see-through.")
        self.keep_glass.setChecked(True)
        form.addRow(self.keep_glass)
        self.lux = widgets.NumberSlider(0.0, 200000.0, 1000.0, "{:,.0f} lx", special="Automatic")
        self.lux.setToolTip("The top of the colour scale, in lux. Automatic: round numbers chosen from the picture. The light "
                            "is a clear day's sun (about 100 000 lx) and the lamps in lumens; a white matte surface is assumed.")
        form.addRow("Scale up to", self.lux)
        self.surface_note = self._note(form)
        self.boxes.append(box)

        # -- outline
        box, form = _group("Outline")
        self.outline_form = form
        self.outline = QCheckBox("Outlines")
        self.outline.setToolTip("Ink lines over the picture, with any surface.")
        form.addRow(self.outline)
        self.width = widgets.NumberSlider(0.0, 4.0, 0.1, "{:.1f} px", special="Automatic")
        self.width.setToolTip("The thickness of the outlines, in pixels of the picture.")
        form.addRow("Thickness", self.width)
        self.line_colour = ColourButton(list(_default("outline.colour")), "Outline colour", linear=True)
        self.line_colour.setToolTip("The colour of the outlines.")
        form.addRow("Colour", self.line_colour)
        self.hand = widgets.NumberSlider(0.0, 1.0, 0.05, "{:.0%}")
        self.hand.setToolTip("How irregular the stroke is: straight, or wobbling and gone over twice like a pencil.")
        form.addRow("Irregular stroke", self.hand)
        self.extend = widgets.NumberSlider(0.0, outlines.EXTEND_MAX_CM, 1.0, "{:.0f} cm")
        self.extend.setToolTip("How far the lines run past their corners, as a draughtsman's do: in centimetres of the model "
                               "(estimated at the model's own distance from the camera).")
        form.addRow("Line extension", self.extend)
        self.boxes.append(box)

        # -- finish
        box, form = _group("Finish")
        self.finish_form = form
        self.finish = QComboBox()
        for key, label in FINISHES.items():
            self.finish.addItem(tr(label), key)
        self.finish.setToolTip("A treatment of the whole picture.")
        form.addRow("Finish", self.finish)
        self.wetness = widgets.NumberSlider(0.0, 1.0, 0.05, "{:.0%}")
        self.wetness.setToolTip("How far the colour spreads: dry and detailed ← → wet washes.")
        form.addRow("Wetness", self.wetness)
        self.edges = widgets.NumberSlider(0.0, 1.0, 0.05, "{:.0%}")
        self.edges.setToolTip("How dark the pigment pools along the edges.")
        form.addRow("Edges", self.edges)
        self.paper = widgets.NumberSlider(0.0, 1.0, 0.05, "{:.0%}")
        self.paper.setToolTip("How rough the paper is: its grain shows in the colour.")
        form.addRow("Paper", self.paper)
        self.finish_note = self._note(form)
        self.boxes.append(box)

        self.fill_materials()
        self.set_values(params.defaults())
        self.surface.currentIndexChanged.connect(self._surface_chosen)
        self.outline.toggled.connect(self._outline_toggled)
        for signal in (self.surface.currentIndexChanged, self.material.currentIndexChanged, self.colour.changed,
                       self.keep_glass.toggled, self.lux.valueChanged, self.outline.toggled, self.width.valueChanged,
                       self.line_colour.changed, self.hand.valueChanged, self.extend.valueChanged,
                       self.finish.currentIndexChanged, self.wetness.valueChanged, self.edges.valueChanged, self.paper.valueChanged):
            signal.connect(self._changed)

    @staticmethod
    def _note(form):
        label = QLabel("")
        label.setWordWrap(True)
        label.setStyleSheet("color: gray; font-size: 11px")
        form.addRow(label)
        return label

    def widgets_(self):
        return (self.surface, self.material, self.colour, self.keep_glass, self.lux, self.outline, self.width, self.line_colour,
                self.hand, self.extend, self.finish, self.wetness, self.edges, self.paper)

    def fill_materials(self):
        """«A colour» and the drawing's materials (the one chosen stays)."""
        combo = self.material
        keep = combo.currentData() if combo.count() else ""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("A colour"), "")
        try:
            names = sorted(mats.used_materials(self.app.scene), key=str.lower)
        except Exception:  # noqa: BLE001
            names = []
        for name in names:
            combo.addItem(name, name)
        if keep and combo.findData(keep) < 0:
            combo.addItem(keep, keep)
        combo.setCurrentIndex(max(0, combo.findData(keep)))
        combo.blockSignals(False)

    # -- the model ------------------------------------------------------------------------
    def values(self) -> dict:
        """The surface, outline and finish, by the register's keys."""
        return {"surface.kind": self.surface.currentData() or "real", "surface.material": self.material.currentData() or "",
                "surface.colour": self.colour.rgb(), "surface.keep_glass": self.keep_glass.isChecked(),
                "surface.lux_max": round(self.lux.value(), 0), "outline.on": self.outline.isChecked(),
                "outline.width": round(self.width.value(), 2), "outline.colour": self.line_colour.rgb(),
                "outline.hand": round(self.hand.value(), 3),
                "outline.extend": round(self.extend.value() / outlines.EXTEND_MAX_CM, 3),
                "finish.kind": self.finish.currentData() or "none", "finish.wetness": round(self.wetness.value(), 3),
                "finish.edges": round(self.edges.value(), 3), "finish.paper": round(self.paper.value(), 3)}

    def set_values(self, model: dict) -> None:
        """Put ``model`` in the controls without saying anything changed."""
        blocked = [(w, w.blockSignals(True)) for w in self.widgets_()]
        try:
            self.surface.setCurrentIndex(max(0, self.surface.findData(model["surface.kind"])))
            name = model["surface.material"]
            if name and self.material.findData(name) < 0:
                self.material.addItem(name, name)
            self.material.setCurrentIndex(max(0, self.material.findData(name)))
            self.colour.set_rgb(list(model["surface.colour"]))
            self.keep_glass.setChecked(bool(model["surface.keep_glass"]))
            self.lux.setValue(model["surface.lux_max"])
            self.outline.setChecked(bool(model["outline.on"]))
            self.width.setValue(model["outline.width"])
            self.line_colour.set_rgb(list(model["outline.colour"]))
            self.hand.setValue(model["outline.hand"])
            self.extend.setValue(model["outline.extend"] * outlines.EXTEND_MAX_CM)
            self.finish.setCurrentIndex(max(0, self.finish.findData(model["finish.kind"])))
            self.wetness.setValue(model["finish.wetness"])
            self.edges.setValue(model["finish.edges"])
            self.paper.setValue(model["finish.paper"])
        finally:
            for w, was in blocked:
                w.blockSignals(was)
        self.enable()

    # -- what shows ------------------------------------------------------------------------
    def enable(self, *_a) -> None:
        v = self.values()
        for form, rows in ((self.surface_form, ((self.material, "surface.material"), (self.colour, "surface.colour"),
                                                (self.keep_glass, "surface.keep_glass"), (self.lux, "surface.lux_max"))),
                           (self.outline_form, ((self.width, "outline.width"), (self.line_colour, "outline.colour"),
                                                (self.hand, "outline.hand"), (self.extend, "outline.extend"))),
                           (self.finish_form, ((self.wetness, "finish.wetness"), (self.edges, "finish.edges"),
                                               (self.paper, "finish.paper")))):
            for widget, key in rows:
                form.setRowVisible(widget, params.applies(params.BY_KEY[key], v))
        self.colour.setEnabled(not v["surface.material"])
        lux = v["surface.kind"] == "lux"
        self.finish.setEnabled(not lux)
        self._say(self.surface_form, self.surface_note, {
            "paper": tr("Only the lines and the shadows, on paper (or on the plain colour of the background)."),
            "lux": tr("The picture shows lux, not colour. Approximate: white matte surfaces, a clear day's sun, the lamps' lumens."),
        }.get(v["surface.kind"], ""))
        self._say(self.finish_form, self.finish_note,
                  tr("Not on the light analysis.") if lux else
                  (tr("Washes of colour on paper; the outlines are painted first.") if v["finish.kind"] == "watercolour" else ""))

    @staticmethod
    def _say(form, label, text):
        label.setText(text)
        form.setRowVisible(label, bool(text))

    def _surface_chosen(self, _i) -> None:
        if self.surface.currentData() == "paper" and not self.outline.isChecked():
            self.outline.setChecked(True)                 # with no surface, the lines are the drawing

    def _outline_toggled(self, on: bool) -> None:
        if on and self.width.value() <= 0.0 and self.surface.currentData() != "paper":
            self.width.setValue(FIRST_WIDTH)

    def _changed(self, *_a) -> None:
        self.enable()
        self.changed.emit()
