# SPDX-License-Identifier: GPL-3.0-or-later
"""Which control of the panel holds each setting of the register, the filter that keeps out of the pages what the layout does
not show, and the mirrors the Expert page puts beside each setting.

The panel's control is the only place a value lives: a mirror copies it, and what a person does in a mirror is done to the
control, which then acts as if it had been used itself."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QSizePolicy,
                               QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from . import params, widgets
from .i18n import tr
from .section_panel import ColourButton


def controls(panel) -> dict:
    """``{key: control}``, in the register's order. Settings with no control of their own are left out: the paper behind (it
    goes with the background), and the width, which lives in the Output page."""
    g, s = panel.style_groups, panel.sliders
    out = {
        "ambient.look": panel.ambient, "camera.dof": s["dof"], "camera.focus": s["focus"], "quality.level": panel.quality,
        "quality.engine": panel.engine, "quality.preview_engine": panel.preview_engine,
        "quality.preview_quality": panel.preview_quality,
        "surface.kind": g.surface, "surface.material": g.material, "surface.colour": g.colour, "surface.keep_glass": g.keep_glass,
        "surface.lux_max": g.lux, "outline.on": g.outline, "outline.width": g.width, "outline.colour": g.line_colour,
        "outline.hand": g.hand, "outline.extend": g.extend, "finish.kind": g.finish, "finish.wetness": g.wetness,
        "finish.edges": g.edges, "finish.paper": g.paper,
        "image.exposure_bias": s["exposure_bias"], "image.warmth": s["warmth"], "image.saturation": s["saturation"],
        "image.vignette": s["vignette"], "image.ao": s["ao"], "image.ao_distance": s["ao_distance"],
        "sky.sun_scale": s["sun_scale"], "sky.clouds": s["clouds"], "sky.stars": s["stars"], "sky.moon": s["moon"],
        "shadows.draw": panel.shadow_draw, "shadows.colour": panel.shadow_colour, "shadows.opacity": panel.shadow_opacity,
        "shadows.spacing": panel.shadow_spacing, "shadows.angle": panel.shadow_angle, "shadows.floor": panel.ground_shadow,
        "background.kind": panel.bg_mode, "pano.path": panel.hdri, "pano.rotation": panel.hdri_rotation,
        "pano.brightness": panel.hdri_strength, "pano.height": panel.hdri_height, "pano.light": panel.hdri_light,
        "picture.path": panel.backdrop, "picture.fit": panel.backdrop_fit, "picture.brightness": panel.backdrop_strength,
        "flat.colour": panel.flat_colour,
        "ground.on": panel.ground, "ground.type": panel.ground_type, "ground.colour": panel.ground_colour,
        "ground.roughness": panel.ground_rough, "ground.offset": panel.ground_offset, "ground.radius": panel.ground_radius,
        "ground.grass_radius": panel.ground_grass, "ground.material": panel.ground_material,
        "ground.material_tile": panel.ground_tile,
        "skyline.type": panel.skyline_type, "skyline.height": panel.skyline_height, "skyline.distance": panel.skyline_distance,
        "skyline.seed": panel.skyline_seed, "skyline.colour": panel.skyline_colour,
        "fog.amount": s["fog"], "fog.start": s["fog_start"], "fog.ground_haze": panel.ground_haze,
    }
    sun, quick = panel.sun_tab, panel.sun_quick
    out.update({"sun.date": quick.date_slider, "sun.hour": quick.hour_slider, "site.location": sun.map_btn,
                "site.coords": sun.coords, "site.north": sun.north, "site.zone": sun.zone, "site.shadows": sun.shadows,
                "site.info": sun.sun_now})
    out.update({key: control for key, (control, _form) in panel.fine.rows.items()})
    return {p.key: out[p.key] for p in params.PARAMS if p.key in out}


def _holds(item, widget) -> bool:
    if item is None:
        return False
    if item.widget() is not None:
        return item.widget() is widget
    layout = item.layout()
    return layout is not None and any(_holds(layout.itemAt(i), widget) for i in range(layout.count()))


def row_of(widget):
    """``(form, row number)`` of the form row ``widget`` is in (directly, or inside the row's widget or layout), or None."""
    node = widget
    while node is not None and node.parentWidget() is not None:
        parent = node.parentWidget()
        forms = ([parent.layout()] if isinstance(parent.layout(), QFormLayout) else []) +             [f for f in parent.findChildren(QFormLayout) if f.parentWidget() is parent]      # (a form inside another layout too)
        for form in forms:
            for row in range(form.rowCount()):
                for role in (QFormLayout.FieldRole, QFormLayout.SpanningRole):
                    if _holds(form.itemAt(row, role), node):
                        return form, row
        node = parent
    return None


def _box_of(widget):
    node = widget.parentWidget()
    while node is not None and not isinstance(node, QGroupBox):
        node = node.parentWidget()
    return node


def _counts(form, row) -> bool:
    """Whether a row left in view keeps its group in view: a note, or a block whose own rows are counted apart, does not."""
    for role in (QFormLayout.FieldRole, QFormLayout.SpanningRole):
        item = form.itemAt(row, role)
        if item is not None and isinstance(item.widget(), (QLabel, widgets.Section)):
            return False
    return True


class LayoutFilter:
    """Hides in the pages what the layout does not show. What a setting's own condition hides stays hidden: the filter only
    ever takes away, after the panel has said what applies."""

    def __init__(self, panel, controls_: dict):
        self.panel = panel
        self.shown: set = set(controls_)
        self.rows = {}
        for key, control in controls_.items():
            if key == "ambient.look":
                continue                                   # a whole box, not a row
            found = row_of(control)
            if found is not None:
                self.rows[key] = found
        self.controls = controls_
        self._hidden_boxes: list = []
        self._busy = False

    def set_shown(self, shown) -> None:
        """A new layout: everything comes back, the panel says again what applies, and what the layout leaves out goes."""
        self.shown = set(shown)
        if self._busy:
            return
        self._busy = True
        try:
            for form, row in self.rows.values():
                form.setRowVisible(row, True)
            for box in self._hidden_boxes:
                box.setVisible(True)
            self._hidden_boxes = []
            self.panel.reapply_conditions()
        finally:
            self._busy = False
        self.apply()

    def apply(self, *_a) -> None:
        if self._busy:
            return
        boxes: dict = {}
        for key, (form, row) in self.rows.items():
            if key not in self.shown:
                form.setRowVisible(row, False)
            box = _box_of(self.controls[key])
            if box is not None:
                boxes.setdefault(box, []).append((key, form))
        for box, rows in boxes.items():
            forms = {form for _k, form in rows}
            left = any(form.isRowVisible(r) and _counts(form, r) for form in forms for r in range(form.rowCount()))
            none_wanted = not any(key in self.shown for key, _f in rows)
            if none_wanted and not left:
                if not box.isHidden():
                    box.setVisible(False)
                    self._hidden_boxes.append(box)
            elif box in self._hidden_boxes:
                box.setVisible(True)
                self._hidden_boxes.remove(box)
        ambient = self.controls.get("ambient.look")
        if ambient is not None:
            ambient.setVisible("ambient.look" in self.shown)


# ---- mirrors ------------------------------------------------------------------------------------
class Mirror:
    """A copy of ``control`` to put somewhere else: ``widget`` is the copy, ``pull()`` takes the control's state."""

    def __init__(self, panel, key: str, control):
        self.panel, self.key, self.control = panel, key, control
        self.widget: QWidget
        self.label = None
        if key in ("sun.date", "sun.hour"):
            self._marked(panel.sun_quick, control, panel.sun_quick.date_label if key == "sun.date" else panel.sun_quick.hour_label)
        elif key == "site.location":
            self.widget = widgets.CentredButton()
            self.widget.setText(control.text())
            self.widget.setIcon(control.icon())
            self.widget.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self.widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            self.widget.clicked.connect(lambda _c=False: control.click())
            self.pull = lambda: self.widget.setText(control.text())
        elif key == "site.coords":
            self._coords(panel.sun_tab)
        elif key == "site.info":
            self.widget = QLabel("")
            self.widget.setWordWrap(True)
            self.pull = lambda: self.widget.setText(control.text())
        elif key == "ambient.look":
            self._combo(panel.preset, after=lambda i: panel.set_ambient(panel.preset.itemData(i)), set_real=False)
        elif isinstance(control, widgets.ChoiceButtons):
            self.widget = widgets.ChoiceButtons([button.text() for button in control._buttons], icons=control.icon_keys)
            self.widget.currentIndexChanged.connect(control.setCurrentIndex)
            self.pull = lambda: self._quietly(lambda: self.widget.setCurrentIndex(control.currentIndex()))
        elif isinstance(control, QComboBox):
            self._combo(control)                                    # (a file box too: choosing in the copy opens its dialog)
        elif isinstance(control, QCheckBox):
            self.widget = QCheckBox(tr("Enabled"))                  # (the row above already says what)
            self.widget.clicked.connect(lambda on: control.setChecked(on))
            self.pull = lambda: self._quietly(lambda: self.widget.setChecked(control.isChecked()))
        elif isinstance(control, ColourButton):
            self.widget = ColourButton(control.rgb(), "Colour", linear=control._linear)

            def picked():
                control.set_rgb(self.widget.rgb())
                control.changed.emit()
            self.widget.changed.connect(picked)
            self.pull = lambda: self.widget.set_rgb(control.rgb())
        elif isinstance(control, widgets.NumberSlider):
            hi = control._lo + control.slider.maximum() * control._step
            self.widget = widgets.NumberSlider(control._lo, hi, control._step, control._fmt, special=control._special)
            self.widget.valueChanged.connect(control.setValue)
            self.pull = lambda: self._quietly(lambda: (self.widget.setValue(control.value()), self.widget._moved()))
        elif isinstance(control, widgets.RadiusSlider):
            self.widget = widgets.RadiusSlider(control.maximum(), control._step)
            self.widget.valueChanged.connect(control.setValue)
            self.pull = lambda: self._quietly(lambda: (self.widget.setValue(control.value()), self.widget._moved()))
        elif isinstance(control, QSlider):
            self._slider(control)
        elif isinstance(control, (QSpinBox, QDoubleSpinBox)):
            self.widget = type(control)()
            self.widget.setRange(control.minimum(), control.maximum())
            if isinstance(control, QDoubleSpinBox):
                self.widget.setDecimals(control.decimals())
            self.widget.setSingleStep(control.singleStep())
            self.widget.setSuffix(control.suffix())
            self.widget.setSpecialValueText(control.specialValueText())
            self.widget.setKeyboardTracking(False)
            self.widget.valueChanged.connect(control.setValue)
            self.pull = lambda: self._quietly(lambda: self.widget.setValue(control.value()))
        else:
            raise TypeError(f"no mirror for {key}: {type(control).__name__}")

    def _marked(self, quick, control, label) -> None:
        """The date's or the hour's slider with its marks and the words under it."""
        from .sun_panel import MarkedSlider
        self.widget = QWidget()
        lay = QVBoxLayout(self.widget)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        copy = MarkedSlider(snap=control.snap)
        copy.setRange(control.minimum(), control.maximum())
        copy.setMinimumWidth(40)
        words = QLabel("")
        words.setWordWrap(True)
        words.setStyleSheet(label.styleSheet())
        lay.addWidget(copy)
        lay.addWidget(words)

        def pull():
            was = copy.blockSignals(True)
            try:
                copy.set_marks(control.marks)
                copy.setValue(control.value())
            finally:
                copy.blockSignals(was)
            words.setText(label.text())

        def moved(v):
            control.setValue(v)
            pull()
        copy.valueChanged.connect(moved)
        copy.sliderReleased.connect(copy._snap_to_mark)
        self.pull = pull

    def _coords(self, sun) -> None:
        self.widget = QWidget()
        lay = QHBoxLayout(self.widget)
        lay.setContentsMargins(0, 0, 0, 0)
        pairs = []
        for real in (sun.lat, sun.lon):
            box = QDoubleSpinBox()
            box.setRange(real.minimum(), real.maximum())
            box.setDecimals(real.decimals())
            box.setSuffix(real.suffix())
            box.setButtonSymbols(QDoubleSpinBox.NoButtons)
            box.setKeyboardTracking(False)
            box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            box.valueChanged.connect(real.setValue)
            lay.addWidget(box)
            pairs.append((box, real))

        def pull():
            for box, real in pairs:
                was = box.blockSignals(True)
                box.setValue(real.value())
                box.blockSignals(was)
        self.pull = pull

    def _quietly(self, fn) -> None:
        was = self.widget.blockSignals(True)
        try:
            fn()
        finally:
            self.widget.blockSignals(was)

    def _combo(self, control, after=None, set_real=True) -> None:
        self.widget = QComboBox()
        self.widget.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.widget.setMinimumContentsLength(8)

        def pull():
            def copy():
                items = [(control.itemText(i), control.itemData(i)) for i in range(control.count())]
                if [(self.widget.itemText(i), self.widget.itemData(i)) for i in range(self.widget.count())] != items:
                    self.widget.clear()
                    for text, data in items:
                        self.widget.addItem(text, data)
                self.widget.setCurrentIndex(control.currentIndex())
            self._quietly(copy)

        def chosen(i):
            if set_real:
                control.setCurrentIndex(i)
                control.activated.emit(i)               # (as a person's choice, which some controls listen for)
            if after is not None:
                after(i)
        self.widget.activated.connect(chosen)
        self.pull = pull

    def _slider(self, control) -> None:
        row = control.parentWidget()
        while row is not None and not isinstance(row, widgets.SliderRow):
            row = row.parentWidget()
        copy = QSlider(Qt.Horizontal)
        copy.setRange(control.minimum(), control.maximum())
        for name in ("lo", "hi"):                    # what the row reads its text from
            copy.setProperty(name, control.property(name))
        self.widget = widgets.SliderRow(copy, "{}")
        copy.valueChanged.connect(control.setValue)

        def pull():
            was = copy.blockSignals(True)
            try:
                copy.setValue(control.value())
            finally:
                copy.blockSignals(was)
            if row is not None:
                self.widget.value_label.setText(row.value_label.text())
        copy.valueChanged.connect(lambda _v: pull())
        self.pull = pull


def change_signals(control) -> list:
    """The signals that say ``control`` changed."""
    for name in ("currentIndexChanged", "toggled", "valueChanged", "changed", "chosen"):
        signal = getattr(control, name, None)
        if signal is not None:
            return [signal]
    return []
