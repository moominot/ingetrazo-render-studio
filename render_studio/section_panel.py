# SPDX-License-Identifier: GPL-3.0-or-later
"""The Section tab of Render Studio's panel: how the model's section looks in the render.

The cut itself is IngeTrazo's active section plane (the Section tool); here: whether the
cut is closed with a face, its colour, and whether the removed part still blocks the light.
"""
from __future__ import annotations

from .i18n import tr, translate_on_show  # noqa: F401

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QInputDialog, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from . import section as S
from . import icons, widgets
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
        self._building = False                  # the list of sections is being filled: its ticks are not the person's
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 4, 0)
        self.state = _note()                    # what cuts now, over the cards
        lay.addWidget(self.state)
        found_box = widgets.Card("Sections in the drawing", "section_list", icon="grp_section", kind="column")
        found_box.setToolTip("The cut is the drawing's active section plane and section box (the Section tools place and flip them). "
                             "It is read again whenever the preview reloads.")
        self.sections_title = found_box         # (the whole card: gone with an IngeTrazo that has no sections)
        lay.addWidget(found_box)
        self.sections = QListWidget()
        self.sections.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.sections.setMaximumHeight(130)
        self.sections.setToolTip("The section planes and section boxes of the drawing. Tick one to make it cut; untick it to see the whole "
                                 "model. One plane and one box can cut at the same time, so ticking one takes the cut off the other of "
                                 "its kind. Double-click a row to rename it.")
        self.sections.itemChanged.connect(self._ticked)
        self.sections.itemDoubleClicked.connect(lambda _item: self._rename())
        self.sections.itemSelectionChanged.connect(self._sections_buttons)
        found_box.body_layout.addWidget(self.sections)
        srow = QHBoxLayout()
        self.rename_btn = QPushButton("Rename…")
        self.rename_btn.setIcon(icons.icon("pencil"))
        self.rename_btn.setToolTip("Give the chosen section a name of its own (a section plane keeps its letter).")
        self.rename_btn.clicked.connect(lambda: self._rename())
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setIcon(icons.icon("trash"))
        self.delete_btn.setToolTip("Take the chosen sections out of the drawing. Undo (Ctrl+Z) in IngeTrazo brings them back.")
        self.delete_btn.clicked.connect(lambda: self._delete())
        srow.addWidget(self.rename_btn)
        srow.addWidget(self.delete_btn)
        srow.addStretch(1)
        found_box.body_layout.addLayout(srow)
        self.sections_note = _note("No sections in the drawing: place them with the Section tools.")
        found_box.body_layout.addWidget(self.sections_note)
        cap_box = widgets.Card("Cap", "section_cap", icon="grp_cap")
        rim_box = widgets.Card("Cap outline", "section_rim", icon="grp_outline")
        light_box = widgets.Card("Light", "section_light", icon="grp_light")
        for box in (cap_box, rim_box, light_box):
            lay.addWidget(box)
        form = cap_box.form
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
        form.addRow("Type", self.style)
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
        rim_box.form.addRow(self.outline)
        self.outline_colour = ColourButton(S.DEFAULT["outline_color"], "Colour of the cap's outline")
        self.outline_colour.setToolTip("The colour of the cap's outline.")
        self.outline_colour.changed.connect(self._edited)
        rim_box.form.addRow("Colour", self.outline_colour)
        self.outline_width = NumberSlider(0.5, 10.0, 0.1, "{:.1f} px")
        self.outline_width.setValue(S.DEFAULT["outline_width"])
        self.outline_width.setToolTip("The thickness of the cap's outline, in pixels of the finished picture.")
        self.outline_width.valueChanged.connect(self._edited)
        rim_box.form.addRow("Thickness", self.outline_width)
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
        light_box.form.addRow(self.light)
        lay.addStretch(1)
        self._fill()
        self._fill_sections()
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
        self._fill_sections()
        self._paint()

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if self._stale:
            self.catch_up()

    # -- the sections of the drawing: tick the one that cuts, rename, delete ---------------------
    def _section_text(self, e) -> str:
        """The row of a section: its name (a plane's letter too), and what kind it is."""
        if e["kind"] == "plane":
            name, symbol = e["name"], e["symbol"]
            if name and symbol and name != symbol:
                label = f"{name} ({symbol})"
            else:
                label = name or (tr("Section {symbol}", symbol=symbol) if symbol else tr("Section {n}", n=e["index"] + 1))
            return f"{label}  ·  {tr('plane')}"
        return f"{e['name'] or tr('Box {n}', n=e['index'] + 1)}  ·  {tr('box')}"

    def _fill_sections(self) -> None:
        """The list: every section plane and section box of the drawing, ticked when it cuts."""
        scene = self.app.scene
        shown = S.has_sections(scene)
        found = S.entries(scene) if shown else []
        chosen = {id(it.data(Qt.UserRole)[1]) for it in self.sections.selectedItems() if it.data(Qt.UserRole)}
        self._building = True
        self.sections.clear()
        for e in found:
            item = QListWidgetItem(self._section_text(e))
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if e["active"] else Qt.Unchecked)
            item.setData(Qt.UserRole, (e["kind"], e["obj"]))
            item.setToolTip(tr("Cutting the model now: untick it to see the whole model.") if e["active"]
                            else tr("Tick it to make it cut the model."))
            self.sections.addItem(item)
            if id(e["obj"]) in chosen:
                item.setSelected(True)
        self._building = False
        for w in (self.sections, self.rename_btn, self.delete_btn):
            w.setVisible(bool(found))
        self.sections_title.setVisible(shown)
        self.sections_note.setVisible(shown and not found)
        self._sections_buttons()

    def _sections_buttons(self) -> None:
        n = len(self.sections.selectedItems())
        self.rename_btn.setEnabled(n == 1)
        self.delete_btn.setEnabled(n >= 1)

    def _row(self, item):
        data = item.data(Qt.UserRole) if item is not None else None
        return tuple(data) if data else None

    def _execute(self, cmd) -> None:
        """One of IngeTrazo's own commands, as one undo step of the drawing; the list and the 3D view follow."""
        if cmd is None:
            return
        vp = self.app.viewport
        vp.history.execute(cmd)
        notify = getattr(vp, "notify_scene_changed", None)
        if callable(notify):
            notify()
        vp.update()
        self.catch_up()

    def _ticked(self, item) -> None:
        if self._building:
            return
        row = self._row(item)
        if row is None:
            return
        kind, obj = row
        on = item.checkState() == Qt.Checked
        if bool(getattr(obj, "active", False)) == on:
            return
        self._execute(S.cut_command(self.app.scene, kind, obj, on))

    def _rename(self) -> None:
        chosen = self.sections.selectedItems()
        row = self._row(chosen[0] if len(chosen) == 1 else self.sections.currentItem())     # (the list is made again after each change: its current row is lost, its chosen one is kept)
        if row is None:
            return
        kind, obj = row
        name = str(getattr(obj, "name", "") or "").strip()
        text, ok = QInputDialog.getText(self, tr("Rename the section"), tr("Name"), text=name)
        if not ok or text.strip() == name:
            return
        self._execute(S.rename_command(self.app.scene, kind, obj, text))

    def _delete(self) -> None:
        rows = [r for r in (self._row(it) for it in self.sections.selectedItems()) if r is not None]
        self._execute(S.delete_command(self.app.scene, rows))

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
