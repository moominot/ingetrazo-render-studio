# SPDX-License-Identifier: GPL-3.0-or-later
"""The Lights tab of Render Studio's panel.

The list shows every light of the document: Render Studio's own (free, and
those on objects — a floor lamp, a wall light, every copy of a component)
and the Render tab's. The tick switches one on or off. Under it, the chosen
light's settings, which change with its kind:

* point — power, colour, size of the bulb;
* spot — the same, its cone's angle and soft edge, and where it aims;
* area — shape (square, rectangle, disc, ellipse), size, spread, and where it faces;
* sun — strength in W/m², colour, the disc's size, and where it comes from.

New lights are placed with a click in the 3D view: on a face, a point light
sits a hand away from it and spots and areas shine away from it (a downlight
on a ceiling shines down). With «On the object clicked» the light goes on that
object and moves, turns and copies with it.

Every change is one undo step, a moment after the last touch.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSizePolicy, QSlider, QSpinBox, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import light_ops as ops, light_view, lights as L

_SETTINGS = "render_studio/lights_"
KIND_LABEL = {"point": "Point light", "spot": "Spot", "area": "Area light", "sun": "Sun"}
SECTION = {"free": "Lights", "object": "On objects", "tab": "From IngeTrazo's Render tab"}
IES_FILTER = "IES profiles (*.ies *.IES)"


def _narrow(w, least: int = 48):
    """A number box as narrow as the tray needs: Qt sizes it for its widest value
    (a range of ±1 000 000 asks for a lot), and a row of them would overflow."""
    w.setMinimumWidth(least)
    w.setSizePolicy(QSizePolicy.Ignored, w.sizePolicy().verticalPolicy())
    return w


def _spin(lo, hi, decimals, step, suffix="", tip=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)        # one change when the typing ends, not one per digit
    s.setToolTip(tip)
    return _narrow(s)


def _kelvin_groove() -> str:
    stops = []
    for i in range(9):
        k = L.MIN_KELVIN + (L.MAX_KELVIN - L.MIN_KELVIN) * i / 8
        r, g, b = L.kelvin_to_rgb(k)
        stops.append(f"stop:{i / 8:.3f} rgb({int(r * 255)},{int(g * 255)},{int(b * 255)})")
    return ("QSlider::groove:horizontal { height: 8px; border-radius: 4px; background: "
            "qlineargradient(x1:0, y1:0, x2:1, y2:0, " + ", ".join(stops) + "); }"
            "QSlider::handle:horizontal { width: 10px; margin: -4px 0; border-radius: 5px; "
            "background: palette(button); border: 1px solid palette(mid); }")


def kelvin_name(k: int) -> str:
    for top, name in ((1900, "candle"), (2400, "very warm (sodium, flame)"), (3000, "warm white (home)"),
                      (3600, "soft white"), (4500, "neutral white (office)"), (5600, "daylight"),
                      (7000, "cool daylight"), (99999, "blue sky")):
        if k <= top:
            return name
    return ""


class LightsTab(QWidget):
    """The tab. ``app`` is IngeTrazo's ExtensionApp."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.view_pick = None               # the light selected in the 3D view
        self._picking = None                # (purpose, kind or preset key)
        self._filling = False
        self._key = None                    # the light the editor shows
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self._commit)
        st = QSettings()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        self.show_box = QCheckBox("Show in the 3D view")
        self.show_box.setChecked(str(st.value(_SETTINGS + "show", "true")).lower() in ("true", "1"))
        self.show_box.toggled.connect(self._show_toggled)
        top.addWidget(self.show_box)
        top.addStretch(1)
        help_btn = QToolButton()
        help_btn.setText("?")
        help_btn.setToolTip("The kinds of light, placing them, lights on objects, power, IES profiles")
        help_btn.clicked.connect(self._help)
        top.addWidget(help_btn)
        lay.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setMinimumHeight(110)
        self.tree.setMaximumHeight(200)
        self.tree.currentItemChanged.connect(self._chosen)
        self.tree.itemChanged.connect(self._ticked)
        lay.addWidget(self.tree)

        add = QGridLayout()
        for i, kind in enumerate(L.TYPES):
            b = QPushButton("+ " + {"point": "Point", "spot": "Spot", "area": "Area", "sun": "Sun"}[kind])
            b.setToolTip({"point": "A bulb that lights all round. Click where it goes.",
                          "spot": "A cone of light (downlight, track spot, street lamp). Click where it goes: "
                                  "on a ceiling it shines down.",
                          "area": "A glowing rectangle, square or disc (LED panel, tube, window fill). Click "
                                  "a face: it lies on it and shines away from it.",
                          "sun": "Parallel light from far away, in W/m² (a second sun, moonlight). Added "
                                 "over the model."}[kind])
            b.clicked.connect(lambda _c=False, k=kind: self.begin_add(k))
            add.addWidget(b, i // 2, i % 2)
        lay.addLayout(add)
        prow = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItem("Add a ready-made light…", "")
        for key, kind, label, _v in L.PRESETS:
            self.preset.addItem(f"{label}", key)
        self.preset.activated.connect(self._preset_chosen)
        self.preset.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.preset.setMinimumContentsLength(8)
        prow.addWidget(self.preset, 1)
        lay.addLayout(prow)
        self.on_object = QCheckBox("On the object clicked")
        self.on_object.setToolTip("The new light goes on the object (group or component) whose face you click: "
                                  "it moves, turns and is copied with it. Off: it stays where it is put.")
        self.on_object.setChecked(str(st.value(_SETTINGS + "on_object", "false")).lower() in ("true", "1"))
        self.on_object.toggled.connect(lambda on: QSettings().setValue(_SETTINGS + "on_object", bool(on)))
        lay.addWidget(self.on_object)

        # -- the chosen light ------------------------------------------------------------
        # The chosen light (a plain frame: the Settings tab's boxes are its groups).
        self.editor_title = QLabel("Light")
        f = self.editor_title.font()
        f.setBold(True)
        self.editor_title.setFont(f)
        lay.addWidget(self.editor_title)
        self.editor = QFrame()
        self.editor.setFrameShape(QFrame.StyledPanel)
        ef = QFormLayout(self.editor)
        ef.setContentsMargins(6, 6, 6, 6)
        ef.setRowWrapPolicy(QFormLayout.WrapLongRows)       # a narrow tray: labels above their fields
        self.where = QLabel("")
        self.where.setWordWrap(True)
        self.where.setStyleSheet("color: gray; font-size: 11px")
        ef.addRow(self.where)
        self.name = QLineEdit()
        self.name.setPlaceholderText("(no name)")
        self.name.editingFinished.connect(self._changed)
        ef.addRow("Name", self.name)
        self.kind = QComboBox()
        for k in L.TYPES:
            self.kind.addItem(KIND_LABEL[k], k)
        self.kind.setToolTip("Changing the kind keeps the place, aim, power and colour.")
        self.kind.currentIndexChanged.connect(self._changed)
        ef.addRow("Kind", self.kind)

        prow = QHBoxLayout()
        self.power = _spin(0.0, 1e7, 2, 50.0)
        self.power.valueChanged.connect(self._changed)
        self.unit = QComboBox()
        self.unit.addItem("lm", "lm")
        self.unit.addItem("W (Blender)", "W")
        self.unit.setToolTip("Lumens, as a lamp's box says; or Blender's own watts (radiant power, not the "
                             "electrical watts of a bulb). Switching keeps the brightness.")
        self.unit.currentIndexChanged.connect(self._unit_changed)
        prow.addWidget(self.power, 1)
        prow.addWidget(self.unit)
        self.power_row = QWidget()
        self.power_row.setLayout(prow)
        prow.setContentsMargins(0, 0, 0, 0)
        ef.addRow("Power", self.power_row)
        self.power_note = QLabel("")
        self.power_note.setWordWrap(True)          # the sun's note is a sentence: never wider than the tray
        self.power_note.setStyleSheet("color: gray; font-size: 11px")
        ef.addRow("", self.power_note)

        # Two lines, so the row never asks for more width than the tray has: the
        # temperature bar across, then the kelvins, the tone's name and «…».
        krow = QVBoxLayout()
        krow.setContentsMargins(0, 0, 0, 0)
        krow.setSpacing(2)
        self.kelvin = QSlider(Qt.Horizontal)
        self.kelvin.setRange(L.MIN_KELVIN, L.MAX_KELVIN)
        self.kelvin.setSingleStep(100)
        self.kelvin.setPageStep(500)
        self.kelvin.setStyleSheet(_kelvin_groove())
        self.kelvin.setMinimumWidth(40)
        self.kelvin.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.kelvin_spin = QSpinBox()
        self.kelvin_spin.setRange(L.MIN_KELVIN, L.MAX_KELVIN)
        self.kelvin_spin.setSingleStep(100)
        self.kelvin_spin.setSuffix(" K")
        self.kelvin_spin.setKeyboardTracking(False)
        self.kelvin.valueChanged.connect(self.kelvin_spin.setValue)
        self.kelvin_spin.valueChanged.connect(self.kelvin.setValue)
        self.kelvin_spin.valueChanged.connect(self._kelvin_named)
        self.kelvin_spin.valueChanged.connect(self._changed)
        krow.addWidget(self.kelvin)
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.kelvin_spin)
        self.kelvin_label = QLabel("")
        self.kelvin_label.setStyleSheet("color: gray; font-size: 11px")
        self.kelvin_label.setWordWrap(True)
        self.kelvin_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        line.addStretch(1)
        self.colour_btn = QToolButton()
        self.colour_btn.setText("…")
        self.colour_btn.setToolTip("A colour of your own instead of a temperature")
        self.colour_btn.clicked.connect(self._pick_colour)
        line.addWidget(self.colour_btn)
        krow.addLayout(line)
        krow.addWidget(self.kelvin_label)
        self.kelvin_row = QWidget()
        self.kelvin_row.setLayout(krow)
        ef.addRow("Colour", self.kelvin_row)
        self.custom = None                  # [r, g, b] when a colour of its own was chosen

        self.radius = _spin(0.0, 10.0, 3, 0.01, " m", "The bulb's size: bigger gives softer shadows.")
        self.radius.valueChanged.connect(self._changed)
        ef.addRow("Bulb size", self.radius)
        self.spot_angle = _spin(1.0, 180.0, 1, 5.0, "°", "How wide the cone opens.")
        self.spot_angle.valueChanged.connect(self._changed)
        ef.addRow("Beam angle", self.spot_angle)
        self.spot_blend = _spin(0.0, 1.0, 2, 0.05, "", "0 = a hard edge, 1 = it fades from the centre.")
        self.spot_blend.valueChanged.connect(self._changed)
        ef.addRow("Soft edge", self.spot_blend)
        self.shape = QComboBox()
        for s in L.SHAPES:
            self.shape.addItem(s.capitalize(), s)
        self.shape.currentIndexChanged.connect(self._changed)
        ef.addRow("Shape", self.shape)
        self.size = _spin(0.001, 100.0, 3, 0.05, " m", "Its width (the diameter of a disc).")
        self.size.valueChanged.connect(self._changed)
        ef.addRow("Width", self.size)
        self.size_y = _spin(0.001, 100.0, 3, 0.05, " m", "Its length (rectangle, ellipse).")
        self.size_y.valueChanged.connect(self._changed)
        ef.addRow("Length", self.size_y)
        self.spread = _spin(1.0, 180.0, 1, 5.0, "°", "How widely it spreads its light: 180° all over, less "
                            "like a grid louvre (Cycles only).")
        self.spread.valueChanged.connect(self._changed)
        ef.addRow("Spread", self.spread)
        self.sun_angle = _spin(0.0, 90.0, 2, 0.1, "°", "The sun's disc: bigger gives softer shadows "
                               "(the real sun: 0.53°).")
        self.sun_angle.valueChanged.connect(self._changed)
        ef.addRow("Disc", self.sun_angle)

        arow = QHBoxLayout()
        arow.setContentsMargins(0, 0, 0, 0)
        self.heading = _spin(0.0, 360.0, 1, 5.0, "°", "Compass heading: 0° north (+Y), 90° east.")
        self.heading.setWrapping(True)
        self.tilt = _spin(-90.0, 90.0, 1, 5.0, "°", "Below the horizon: 90° straight down, 0° level, "
                          "-90° straight up.")
        for w in (self.heading, self.tilt):
            w.valueChanged.connect(self._changed)
        arow.addWidget(self.heading)
        arow.addWidget(self.tilt)
        self.aim_row = QWidget()
        self.aim_row.setLayout(arow)
        ef.addRow("Aim: heading, tilt", self.aim_row)
        self.spin = _spin(-360.0, 360.0, 1, 15.0, "°", "Turns an area light about the way it faces.")
        self.spin.valueChanged.connect(self._changed)
        ef.addRow("Turn", self.spin)

        prow2 = QHBoxLayout()
        prow2.setContentsMargins(0, 0, 0, 0)
        self.xyz = [_spin(-1e6, 1e6, 2, 0.1) for _ in range(3)]
        for w, axis in zip(self.xyz, "XYZ"):
            w.setToolTip(f"{axis} in the world, in metres")
            w.setButtonSymbols(QDoubleSpinBox.NoButtons)
            w.valueChanged.connect(self._changed)
            prow2.addWidget(w)
        self.pos_row = QWidget()
        self.pos_row.setLayout(prow2)
        ef.addRow("Place X Y Z (m)", self.pos_row)
        mrow = QHBoxLayout()
        mrow.setContentsMargins(0, 0, 0, 0)
        self.move_btn = QPushButton("Move…")
        self.move_btn.setToolTip("Click its new place in the 3D view")
        self.move_btn.clicked.connect(lambda: self.begin_pick("move"))
        self.aim_btn = QPushButton("Aim…")
        self.aim_btn.setToolTip("Click the point it should look at")
        self.aim_btn.clicked.connect(lambda: self.begin_pick("aim"))
        mrow.addWidget(self.move_btn)
        mrow.addWidget(self.aim_btn)
        self.pick_row = QWidget()
        self.pick_row.setLayout(mrow)
        ef.addRow("", self.pick_row)

        self.shadow = QCheckBox("Casts shadows")
        self.shadow.toggled.connect(self._changed)
        ef.addRow("", self.shadow)
        irow = QHBoxLayout()
        irow.setContentsMargins(0, 0, 0, 0)
        self.ies = QLineEdit()
        self.ies.setReadOnly(True)
        self.ies.setPlaceholderText("none")
        ies_btn = QToolButton()
        ies_btn.setText("…")
        ies_btn.setToolTip("A manufacturer's photometric file (.ies): the shape of its light")
        ies_btn.clicked.connect(self._choose_ies)
        ies_clear = QToolButton()
        ies_clear.setText("×")
        ies_clear.setToolTip("No profile")
        ies_clear.clicked.connect(lambda: (self.ies.setText(""), self._changed()))
        irow.addWidget(self.ies, 1)
        irow.addWidget(ies_btn)
        irow.addWidget(ies_clear)
        self.ies_row = QWidget()
        self.ies_row.setLayout(irow)
        ef.addRow("IES profile", self.ies_row)
        self.ies_note = QLabel("Cycles only (EEVEE lights it evenly). The power set here stays the total; "
                               "the profile gives its shape.")
        self.ies_note.setWordWrap(True)
        self.ies_note.setStyleSheet("color: gray; font-size: 11px")
        ef.addRow("", self.ies_note)
        self.all_copies = QCheckBox("Every copy of the component")
        self.all_copies.setToolTip("A change reaches this light on every copy of the component (each keeps its "
                                   "own place unless you move it inside the object).")
        self.all_copies.setChecked(True)
        ef.addRow("", self.all_copies)

        brow = QGridLayout()
        brow.setContentsMargins(0, 0, 0, 0)
        self.dup_btn = QPushButton("Duplicate")
        self.dup_btn.clicked.connect(self.duplicate)
        self.attach_btn = QPushButton("Put on selected object")
        self.attach_btn.setToolTip("The light goes on the object selected in the model (it stays where it is)")
        self.attach_btn.clicked.connect(self.attach_to_selection)
        self.detach_btn = QPushButton("Free it")
        self.detach_btn.setToolTip("The light leaves its object and stays where it is")
        self.detach_btn.clicked.connect(self.detach)
        self.convert_btn = QPushButton("Make it a Render Studio light")
        self.convert_btn.setToolTip("It moves out of IngeTrazo's Render tab (which then no longer renders it) "
                                    "and gets every setting of this tab")
        self.convert_btn.clicked.connect(self.convert)
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self.delete)
        brow.addWidget(self.dup_btn, 0, 0)
        brow.addWidget(self.del_btn, 0, 1)
        brow.addWidget(self.attach_btn, 1, 0, 1, 2)
        brow.addWidget(self.detach_btn, 2, 0, 1, 2)
        brow.addWidget(self.convert_btn, 3, 0, 1, 2)
        self.buttons = QWidget()
        self.buttons.setLayout(brow)
        ef.addRow(self.buttons)
        lay.addWidget(self.editor)
        lay.addStretch(1)
        self.refresh()

    def _help(self):
        from . import ui_help
        ui_help.show(self, "lights")

    # ---- the list ------------------------------------------------------------------------
    def show_in_view(self) -> bool:
        return self.show_box.isChecked()

    def _show_toggled(self, on):
        QSettings().setValue(_SETTINGS + "show", bool(on))
        self.app.viewport.update()

    def selected_key(self):
        return self._key

    def refresh(self, select=None) -> None:
        """Show the document's lights (after an edit, an undo, another tab)."""
        if self._timer.isActive():
            return                          # an edit of ours is still to be written
        want = select if select is not None else self._key
        entries = L.all_lights(self.app.scene)
        self._filling = True
        self.tree.blockSignals(True)
        self.tree.clear()
        found = None
        sections = {}
        for n, e in enumerate(entries, 1):
            src = e["source"]
            if src not in sections:
                head = QTreeWidgetItem([SECTION[src]])
                head.setFlags(Qt.ItemIsEnabled)
                f = head.font(0)
                f.setBold(True)
                head.setFont(0, f)
                self.tree.addTopLevelItem(head)
                head.setExpanded(True)
                sections[src] = head
            lt = e["world"]
            text = light_view._label(lt, n)
            if src == "object" and e["group"] is not None:
                text += f"  — on «{e['group'].name}»"
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.UserRole, e["key"])
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if lt["on"] else Qt.Unchecked)
            r, g, b = lt["color"]
            item.setForeground(0, QColor.fromRgbF(0.35 * r, 0.35 * g, 0.35 * b) if lt["on"] else QColor(140, 140, 140))
            sections[src].addChild(item)
            if e["key"] == want:
                found = item
        if not entries:
            empty = QTreeWidgetItem(["No lights yet: add one with the buttons below."])
            empty.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(empty)
        self.tree.blockSignals(False)
        self._filling = False
        if found is not None:
            self.tree.setCurrentItem(found)
        self._show(found and found.data(0, Qt.UserRole))
        self.app.viewport.update()

    def select(self, key) -> None:
        """Choose the light ``key`` in the list (from the 3D view, say)."""
        if getattr(self, "_stale", False):      # changed while out of sight
            self._stale = False
            self.refresh()
        it = self._item(key)
        if it is not None:
            self.tree.setCurrentItem(it)
        else:
            self._show(None)

    def _item(self, key):
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            for j in range(head.childCount()):
                if head.child(j).data(0, Qt.UserRole) == key:
                    return head.child(j)
        return None

    def _chosen(self, item, _prev=None):
        if self._filling:
            return
        self._flush()
        key = item.data(0, Qt.UserRole) if item is not None else None
        self._show(key)
        self.app.viewport.update()

    def _ticked(self, item, _col):
        key = item.data(0, Qt.UserRole)
        if self._filling or key is None:
            return
        on = item.checkState(0) == Qt.Checked
        # The edit tells the document it changed, and the list is rebuilt
        # (``refresh`` clears the tree): that deleted ``item`` while Qt was
        # still inside its own signal, and the app crashed. So it waits for
        # the next turn, when Qt is out of the item.
        QTimer.singleShot(0, lambda: self._tick_apply(key, on))

    def _tick_apply(self, key, on) -> None:
        e = ops.entry(self.app.scene, key)
        if e is None:
            return
        if on != e["world"]["on"]:
            self._flush()
            ops.update(self.app, key, dict(e["world"], on=on), self._copies(e))

    # ---- the editor ------------------------------------------------------------------------
    def _show(self, key) -> None:
        """Fill the editor with the light ``key`` (None: nothing chosen)."""
        self._key = key
        e = ops.entry(self.app.scene, key) if key is not None else None
        self.editor.setEnabled(e is not None)
        if e is None:
            self.editor_title.setText("Light")
            self.where.setText("Choose a light in the list, or click one in the 3D view.")
            return
        lt = e["world"]
        self._filling = True
        widgets = [self.name, self.kind, self.power, self.unit, self.kelvin, self.kelvin_spin, self.radius,
                   self.spot_angle, self.spot_blend, self.shape, self.size, self.size_y, self.spread,
                   self.sun_angle, self.heading, self.tilt, self.spin, *self.xyz, self.shadow]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.editor_title.setText(KIND_LABEL[lt["type"]])
            self.name.setText(lt["name"])
            self.kind.setCurrentIndex(self.kind.findData(lt["type"]))
            self.unit.setCurrentIndex(self.unit.findData(lt["unit"]))
            self.power.setValue(lt["power"])
            k = lt["kelvin"] if lt["kelvin"] is not None else L.DEFAULT_KELVIN
            self.custom = None if lt["kelvin"] is not None else list(lt["color"])
            self.kelvin.setValue(k)
            self.kelvin_spin.setValue(k)
            self.radius.setValue(lt["radius"])
            self.spot_angle.setValue(lt["spot_angle"])
            self.spot_blend.setValue(lt["spot_blend"])
            self.shape.setCurrentIndex(self.shape.findData(lt["shape"]))
            self.size.setValue(lt["size"])
            self.size_y.setValue(lt["size_y"])
            self.spread.setValue(lt["spread"])
            self.sun_angle.setValue(lt["sun_angle"])
            heading, tilt = L.angles_from_aim(lt["dir"])
            self.heading.setValue(heading)
            self.tilt.setValue(tilt)
            self.spin.setValue(lt["spin"])
            for w, v in zip(self.xyz, lt["pos"]):
                w.setValue(v)
            self.shadow.setChecked(lt["shadow"])
            self.ies.setText(lt["ies"])
        finally:
            for w in widgets:
                w.blockSignals(False)
            self._filling = False
        self._kelvin_named(k)
        src = e["source"]
        self.where.setText({
            "free": "A Render Studio light, where it is placed.",
            "object": f"On «{e['group'].name if e['group'] is not None else '?'}»: it moves, turns and is "
                      "copied with it. Place and aim are in the world.",
            "tab": "A light of IngeTrazo's Render tab: both renders use it. Here only what that tab knows "
                   "can change (place, aim, power, colour, beam); make it a Render Studio light for the rest.",
        }[src])
        self._layout_for(lt, src, e)

    def _layout_for(self, lt, src, e) -> None:
        kind = lt["type"]
        form = self.editor.layout()

        def show(widget, on):
            widget.setVisible(on)
            label = form.labelForField(widget)
            if label is not None:
                label.setVisible(on)

        tab = src == "tab"
        show(self.kind, not tab)
        show(self.radius, kind in ("point", "spot") and not tab)
        show(self.spot_angle, kind == "spot")
        show(self.spot_blend, kind == "spot" and not tab)
        for w in (self.shape, self.size, self.spread):
            show(w, kind == "area")
        show(self.size_y, kind == "area" and lt["shape"] in ("rectangle", "ellipse"))
        show(self.sun_angle, kind == "sun")
        show(self.aim_row, kind != "point")
        self.aim_btn.setVisible(kind != "point")
        show(self.spin, kind == "area")
        show(self.shadow, not tab)
        show(self.ies_row, kind in L.IES_TYPES and not tab)
        self.ies_note.setVisible(kind in L.IES_TYPES and not tab and bool(lt["ies"]))
        self.colour_btn.setVisible(not tab)
        self.unit.setVisible(kind != "sun" and not tab)
        self.power.setSuffix(" W/m²" if kind == "sun" else (" W" if tab else ""))
        self.power.setDecimals(3 if kind == "sun" or lt["unit"] == "W" else 0)
        self.power.setSingleStep(0.5 if kind == "sun" else (10.0 if lt["unit"] == "W" else 50.0))
        if kind == "sun":
            self.power_note.setText("Blender's sun strength: a clear day's sun is 1000 W/m² of real light; "
                                    "the looks use a few W/m². Moonlight ≈ 0.05.")
        elif lt["unit"] == "lm":
            self.power_note.setText(f"≈ {L.blender_watts(lt):.3g} W in Blender")
        else:
            self.power_note.setText(f"≈ {L.lumens(lt):,.0f} lm".replace(",", " "))
        on_obj = src == "object"
        copies = on_obj and len(e["key"][1]) == 1 and len(L.siblings(self.app.scene, e["group"])) > 1
        self.all_copies.setVisible(copies)
        self.attach_btn.setVisible(not tab)
        self.detach_btn.setVisible(on_obj)
        self.convert_btn.setVisible(tab)
        self.dup_btn.setVisible(not tab)

    def _kelvin_named(self, k):
        if self.custom is not None:
            r, g, b = self.custom
            self.kelvin_label.setText(f"Own colour ({int(r * 255)}, {int(g * 255)}, {int(b * 255)}); "
                                      "move the slider for a temperature again")
        else:
            self.kelvin_label.setText(kelvin_name(int(k)))

    def _pick_colour(self):
        e = ops.entry(self.app.scene, self._key)
        if e is None:
            return
        r, g, b = e["world"]["color"]
        c = QColorDialog.getColor(QColor.fromRgbF(r, g, b), self, "Light colour")
        if c.isValid():
            self.custom = [round(c.redF(), 4), round(c.greenF(), 4), round(c.blueF(), 4)]
            self._kelvin_named(0)
            self._changed()
            self._flush()

    def _choose_ies(self):
        start = str(QSettings().value(_SETTINGS + "ies_dir", "") or "")
        path, _f = QFileDialog.getOpenFileName(self, "IES profile", start, IES_FILTER)
        if not path:
            return
        if L.read_ies(path) is None:
            self.ies_note.setText("That file is not an IES profile Render Studio can read.")
            self.ies_note.setVisible(True)
            return
        QSettings().setValue(_SETTINGS + "ies_dir", os.path.dirname(path))
        self.ies.setText(path)
        self._changed()
        self._flush()

    def _unit_changed(self, _i):
        if self._filling:
            return
        e = ops.entry(self.app.scene, self._key)
        if e is None:
            return
        self._flush()
        new = L.convert_unit(e["world"], self.unit.currentData())
        ops.update(self.app, self._key, new, self._copies(e))

    def _changed(self, *_a):
        if self._filling or self._key is None:
            return
        if self.sender() is self.kelvin_spin:
            self.custom = None
            self._kelvin_named(self.kelvin_spin.value())
        self._timer.start()

    def _flush(self):
        if self._timer.isActive():
            self._timer.stop()
            self._commit()

    def _copies(self, e) -> bool:
        return e["source"] == "object" and self.all_copies.isChecked()

    def edited_light(self, e) -> dict:
        """The light as the editor now shows it (world coordinates)."""
        lt = dict(e["world"])
        kind = self.kind.currentData() if e["source"] != "tab" else lt["type"]
        if kind != lt["type"]:
            d = L.DEFAULTS[kind]
            lt.update({k: v for k, v in d.items() if k not in ("power", "unit", "kelvin")})
            if kind == "sun":
                lt["unit"], lt["power"] = "W", d["power"]
            elif lt["type"] == "sun":
                lt["unit"], lt["power"] = d["unit"], d["power"]
            lt["type"] = kind
        else:
            lt["power"] = self.power.value()
        lt["name"] = self.name.text().strip()
        if self.custom is not None:
            lt["kelvin"], lt["color"] = None, list(self.custom)
        else:
            lt["kelvin"] = int(self.kelvin_spin.value())
        lt.update(radius=self.radius.value(), spot_angle=self.spot_angle.value(),
                  spot_blend=self.spot_blend.value(), shape=self.shape.currentData(),
                  size=self.size.value(), size_y=self.size_y.value(), spread=self.spread.value(),
                  sun_angle=self.sun_angle.value(), spin=self.spin.value(),
                  shadow=self.shadow.isChecked(), ies=self.ies.text().strip())
        heading, tilt = L.angles_from_aim(e["world"]["dir"])
        if abs(heading - self.heading.value()) > 0.05 or abs(tilt - self.tilt.value()) > 0.05:
            lt["dir"] = L.aim_from_angles(self.heading.value(), self.tilt.value())
        pos = [w.value() for w in self.xyz]
        if any(abs(a - b) > 5e-4 for a, b in zip(pos, e["world"]["pos"])):
            lt["pos"] = pos
        return lt

    def _commit(self):
        e = ops.entry(self.app.scene, self._key)
        if e is None:
            return
        new = L.clean_light(self.edited_light(e))
        if new == L.clean_light(e["world"]):
            return
        self._key = ops.update(self.app, self._key, new, self._copies(e))

    # ---- adding, moving, aiming ------------------------------------------------------------
    def _preset_chosen(self, i):
        key = self.preset.itemData(i)
        self.preset.setCurrentIndex(0)
        if key:
            kind = L.PRESET_BY_KEY[key][1]
            if kind == "sun":
                self._place_sun(L.from_preset(key))
            else:
                self.begin_pick("new", key)

    def begin_add(self, kind: str):
        if kind == "sun":
            self._place_sun(L.new_light("sun"))
        else:
            self.begin_pick("new", kind)

    def _place_sun(self, light):
        """A sun needs no place (its light comes from far away): it is drawn
        over the model, coming from the south-east at 45°."""
        pos = [0.0, 0.0, 5.0]
        try:
            lo, hi = self.app.scene.bounds()
            if lo is not None:
                pos = [(lo.x() + hi.x()) / 2, (lo.y() + hi.y()) / 2, hi.z() + 2.0]
        except Exception:  # noqa: BLE001
            pass
        light = dict(light, pos=pos, dir=L.aim_from_angles(315.0, 45.0))
        self._flush()
        self.refresh(select=ops.add_free(self.app, light))

    def begin_pick(self, purpose: str, what=None):
        if purpose != "new" and self._key is None:
            return
        self._flush()
        self._picking = (purpose, what)
        prompts = {"new": "Click where the light goes",
                   "move": "Click the light's new place",
                   "aim": "Click the point the light looks at"}
        tool = light_view.make_pick_tool(prompts[purpose], self._picked, self._end_pick)
        vp = self.app.viewport
        vp.set_active_tool(tool)
        win = getattr(self.app, "window", None)
        if win is not None and hasattr(win, "statusBar"):
            win.statusBar().showMessage(prompts[purpose] + " — Esc cancels")
        vp.setFocus()

    def place(self, light, point, normal):
        """``light`` set at a clicked ``point``: off a face it was clicked on by a
        little (a hand for a bulb, a centimetre for a panel), and shining away from
        it; in the air, a spot or a panel shines down."""
        out = dict(light)
        n = normal
        off = {"point": 0.1, "spot": 0.03, "area": 0.01}.get(light["type"], 0.0)
        if n is not None:
            out["pos"] = [p + off * c for p, c in zip(point, n)]
            if light["type"] in ("spot", "area"):
                out["dir"] = list(n)
        else:
            out["pos"] = list(point)
        return out

    def _picked(self, point, normal, owner):
        purpose, what = self._picking or (None, None)
        try:
            if purpose == "new":
                base = (L.from_preset(what) if what in L.PRESET_BY_KEY else L.new_light(what))
                light = self.place(base, point, normal)
                if self.on_object.isChecked() and owner is not None:
                    key = ops.add_to_object(self.app, owner, light)
                else:
                    key = ops.add_free(self.app, light)
                self.refresh(select=key)
            elif purpose in ("move", "aim"):
                e = ops.entry(self.app.scene, self._key)
                if e is not None:
                    lt = dict(e["world"])
                    if purpose == "move":
                        lt = self.place(lt, point, normal if lt["type"] != "sun" else None)
                        if lt["type"] in ("spot", "sun") and normal is not None:
                            lt["dir"] = e["world"]["dir"]       # a moved spot keeps its aim
                    else:
                        d = [a - b for a, b in zip(point, lt["pos"])]
                        if sum(c * c for c in d) > 1e-12:
                            lt["dir"] = d
                    self._key = ops.update(self.app, self._key, lt, self._copies(e))
                    self.refresh()
        finally:
            self._end_pick()

    def _end_pick(self):
        self._picking = None
        win = getattr(self.app, "window", None)
        if win is not None and hasattr(win, "statusBar"):
            win.statusBar().clearMessage()
            activate = getattr(win, "_activate_tool", None)
            if callable(activate):
                activate("select")

    # ---- the buttons -----------------------------------------------------------------------
    def duplicate(self):
        e = ops.entry(self.app.scene, self._key)
        if e is None or e["source"] == "tab":
            return
        self._flush()
        e = ops.entry(self.app.scene, self._key)
        copy_ = dict(e["world"], id=L.new_id(), pos=[c + d for c, d in zip(e["world"]["pos"], (0.5, 0.0, 0.0))])
        if e["source"] == "object" and e["group"] is not None and len(e["key"][1]) == 1:
            key = ops.add_to_object(self.app, e["group"], copy_)
        else:
            key = ops.add_free(self.app, copy_)
        self.refresh(select=key)

    def delete(self):
        if self._key is None:
            return
        self._timer.stop()
        e = ops.entry(self.app.scene, self._key)
        if e is not None:
            ops.delete(self.app, self._key, self._copies(e))
        self._key = None
        self.refresh()

    def delete_key(self, key):
        """Supr on a light picked in the 3D view."""
        self._timer.stop()
        e = ops.entry(self.app.scene, key)
        if e is not None:
            ops.delete(self.app, key, self._copies(e))
        if key == self._key:
            self._key = None
        self.view_pick = None
        self.refresh()

    def selected_object(self):
        scene = self.app.scene
        groups = [g for g in getattr(scene, "selection", ()) or () if g in (scene.groups or ())]
        return groups[0] if len(groups) == 1 else None

    def attach_to_selection(self):
        group = self.selected_object()
        if group is None:
            self.where.setText("Select ONE object (a group or a component) in the model first.")
            return
        self._flush()
        self.refresh(select=ops.attach(self.app, self._key, group))

    def detach(self):
        self._flush()
        self.refresh(select=ops.detach(self.app, self._key))

    def convert(self):
        if self._key is None or self._key[0] != "tab":
            return
        self.refresh(select=ops.convert_tab(self.app, self._key[1]))

    # ---- the 3D view's pick -------------------------------------------------------------
    def on_view_pick(self, key):
        self.view_pick = key
        if key is not None:
            self.select(key)
        self.app.viewport.update()

    def document_changed(self):
        self.view_pick = None
        if not self.isVisible():
            # Called on every edit and selection: with the tab out of sight
            # nobody reads the list, and building it walks the whole model.
            self._stale = True
            return
        self._stale = False
        self.refresh()

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        if getattr(self, "_stale", False):
            self._stale = False
            self.refresh()
