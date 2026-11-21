# SPDX-License-Identifier: GPL-3.0-or-later
"""The material editor window: the model's materials on the left, how the
chosen one renders on the right — a preset to start from, its type and four
settings (roughness, metal, relief, glow). Each setting can follow a map:
the material's own picture in black and white, or an image file (a normal
map, for relief), inverted and with more contrast if needed; the slider
then scales it. Saved in the document (one undo step per change), read by
the next render.
"""
from __future__ import annotations

from .i18n import tr, translate_on_show  # noqa: F401

import json
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSlider, QToolButton, QVBoxLayout, QWidget)

from . import cube_preview
from . import opacity as opacity_mod
from . import materials as M
from . import pbr, studio_data
from .image_adjust import ImageAdjust

_FIELDS = (  # key, label, lo, hi, tip
    ("roughness", "Roughness", 0.0, 1.0, "0 a mirror-like polish, 1 fully matte."),
    ("metallic", "Metal", 0.0, 1.0, "1 for metals: the reflection takes the material's colour."),
    ("bump", "Relief", 0.0, 1.0, "Surface relief. Automatic: from the picture's light and dark "
                                 "when it has one (joints, grain), else a fine grain. Water: the "
                                 "height of the waves."),
    ("glow", "Glow", 0.0, 50.0, "How bright it shines by itself (Glowing type): screens, light panels."),
)

#: Map sources per setting: (value, label). "" = no map (relief: automatic).
_SOURCES = {
    "roughness": (("", "No map"), ("picture", "Picture (B/W)"), ("file", "Image file…")),
    "metallic": (("", "No map"), ("picture", "Picture (B/W)"), ("file", "Image file…")),
    "bump": (("", "Automatic"), ("grain", "Fine grain"), ("picture", "Picture (B/W)"),
             ("file", "Height map file…"), ("normal", "Normal map file…")),
    "glow": (("", "No map"), ("picture", "Picture (B/W)"), ("file", "Mask file…")),
    # white = opaque, black = transparent (a cut-out: leaves, a fence, a lace)
    "opacity": (("", "No map"), ("file", "Image file… (black = transparent)")),
}
_MAP_TIPS = {
    "opacity": "A picture that says where the material is see-through: white is opaque, black is transparent, "
               "greys in between (a cut-out: leaves, a fence, a lace). The render and the preview use it; the "
               "3D view shows the Transparency slider's value. It follows the material's own picture's "
               "layout when it has one.",
}
MAP_FILTER = "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.exr *.hdr *.tga)"
_SETTINGS = "render_studio/"


#: The list's little pictures, kept: reading and scaling every material's picture on each refresh took
#: half a second on a model with 168 materials, and the list is rebuilt on every change of the
#: document. Emptied when the editor is shown (a picture changed on disk shows then).
_SWATCHES: dict = {}


def clear_swatches() -> None:
    _SWATCHES.clear()


def _swatch_key(mat) -> tuple:
    tex = (getattr(mat, "texture", None) or {}).get("path") if mat is not None else None
    return (str(tex or ""), tuple(float(c) for c in (getattr(mat, "color", None) or (0.8, 0.8, 0.8))[:3]))


def _swatch(mat) -> QIcon:
    key = _swatch_key(mat)
    icon = _SWATCHES.get(key)
    if icon is None:
        icon = _SWATCHES[key] = _make_swatch(mat)
    return icon


def _make_swatch(mat) -> QIcon:
    pix = QPixmap(28, 28)
    tex = (getattr(mat, "texture", None) or {}).get("path")
    if tex and Path(tex).is_file():
        img = QPixmap(tex)
        if not img.isNull():
            img = img.scaled(28, 28, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            return QIcon(img.copy((img.width() - 28) // 2, (img.height() - 28) // 2, 28, 28))
    r, g, b = (getattr(mat, "color", None) or (0.8, 0.8, 0.8))[:3]
    pix.fill(QColor.fromRgbF(r, g, b))
    return QIcon(pix)


def map_preview(path, invert=False, contrast=0.0, normal=False, size=44, channel=None):
    """What the render reads from a map: the image in black and white (or one
    of its channels: 0 red, 1 green, 2 blue, for a packed map), inverted, with
    contrast — as a small square picture. None if unreadable."""
    if not path or not Path(path).is_file():
        return None
    img = QImage(str(path))
    if img.isNull():
        return None
    img = img.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    img = img.copy((img.width() - size) // 2, (img.height() - size) // 2, size, size)
    if normal:
        return QPixmap.fromImage(img)
    if channel is None:
        img = img.convertToFormat(QImage.Format_Grayscale8)
    c = max(0.0, min(1.0, float(contrast)))
    lo, hi = 0.49 * c, 1.0 - 0.49 * c
    for y in range(img.height()):
        for x in range(img.width()):
            px = img.pixelColor(x, y)
            v = (px.redF(), px.greenF(), px.blueF())[channel] if channel is not None else px.redF()
            if invert:
                v = 1.0 - v
            if c > 0.0:
                v = min(1.0, max(0.0, (v - lo) / (hi - lo)))
            g = int(v * 255)
            img.setPixelColor(x, y, QColor(g, g, g))
    return QPixmap.fromImage(img)


class MapRow(QWidget):
    """Under a setting: where its map comes from, invert, contrast, a preview."""

    def __init__(self, key, on_change, parent=None):
        super().__init__(parent)
        self.key = key
        self.on_change = on_change
        self.path = ""
        self.picture = ""                       # the material's own picture, if any
        self.set_path = ""                      # the texture set's map for this setting, if any
        self.set_channel = None
        self.set_normal = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        self.source = QComboBox()
        for value, label in _SOURCES[key]:
            self.source.addItem(tr(label), value)
        self._first_label = tr(_SOURCES[key][0][1])
        self.source.setToolTip(_MAP_TIPS.get(key) or (
            "Where the setting varies over the surface. With a map, the slider above scales it."))
        self.source.activated.connect(self._source_chosen)
        lay.addWidget(self.source, 2)
        self.invert = QCheckBox("Invert")
        self.invert.setToolTip("White becomes black: for a picture whose dark parts should "
                               "be the rough, raised or glowing ones.")
        self.invert.toggled.connect(self._changed)
        lay.addWidget(self.invert)
        self.contrast = QSlider(Qt.Horizontal)
        self.contrast.setRange(0, 100)
        self.contrast.setMaximumWidth(70)
        self.contrast.setToolTip("Contrast: 0 the map as it is, 100 pure black or white.")
        self.contrast.valueChanged.connect(self._changed)
        lay.addWidget(self.contrast)
        self.preview = QLabel()
        self.preview.setFixedSize(44, 44)
        self.preview.setStyleSheet("border: 1px solid gray")
        lay.addWidget(self.preview)
        self._loading = False
        self._update()

    # what the render needs
    def spec(self):
        src = self.source.currentData()
        if not src:
            return None
        out = {"source": src}
        if src in ("file", "normal"):
            if not self.path:
                return None
            out["path"] = self.path
        if src not in ("normal", "grain"):
            if self.invert.isChecked():
                out["invert"] = True
            if self.contrast.value():
                out["contrast"] = round(self.contrast.value() / 100.0, 2)
        return out

    def load(self, spec, picture):
        self._loading = True
        spec = spec or {}
        self.picture = picture or ""
        self.path = spec.get("path", "")
        self.source.setCurrentIndex(max(0, self.source.findData(spec.get("source", ""))))
        self.invert.setChecked(bool(spec.get("invert")))
        self.contrast.setValue(int(round(float(spec.get("contrast", 0.0)) * 100)))
        self._loading = False
        self._update()

    def set_texture_set(self, path="", channel=None, normal=False, what=""):
        """The map the material's texture set gives this setting: then the first
        choice («No map» / «Automatic») reads «Texture set» and the render uses it."""
        self.set_path, self.set_channel, self.set_normal = path or "", channel, bool(normal)
        self.source.setItemText(0, tr("Texture set: {what}", what=what) if path else self._first_label)
        self._update()

    def _source_chosen(self, _i):
        src = self.source.currentData()
        if src in ("file", "normal"):
            st = QSettings()
            start = self.path or str(st.value(_SETTINGS + "map_dir", "") or "")
            path, _f = QFileDialog.getOpenFileName(self, tr("Map image"), start, MAP_FILTER)
            if path:
                self.path = path
                st.setValue(_SETTINGS + "map_dir", str(Path(path).parent))
            elif not self.path:
                self.source.setCurrentIndex(0)
        self._changed()

    def set_file(self, path, source="file"):
        """Choose an image file without the dialog (tests, scripts)."""
        self.path = str(path)
        self.source.setCurrentIndex(max(0, self.source.findData(source)))
        self._changed()

    def _changed(self, *_a):
        self._update()
        if not self._loading:
            self.on_change()

    def _update(self):
        src = self.source.currentData()
        grey = src not in ("", "normal", "grain", None)
        # Invert and contrast only act on a black-and-white map: hidden otherwise.
        self.invert.setVisible(grey)
        self.contrast.setVisible(grey)
        # «Picture (B/W)» does nothing on a material without a picture: not offered.
        i = self.source.findData("picture")
        item = self.source.model().item(i) if i >= 0 else None
        if item is not None:
            item.setEnabled(bool(self.picture) or src == "picture")
        if not src and self.set_path:            # the texture set's own map
            pix = map_preview(self.set_path, normal=self.set_normal, channel=self.set_channel)
            self.preview.setPixmap(pix if pix is not None else QPixmap())
            self.preview.setToolTip(tr("From the texture set: {name}", name=Path(self.set_path).name))
            return
        path = self.picture if src == "picture" else self.path if src in ("file", "normal") else ""
        pix = map_preview(path, self.invert.isChecked(), self.contrast.value() / 100.0,
                          normal=src == "normal") if path else None
        self.preview.setPixmap(pix if pix is not None else QPixmap())
        if src == "picture" and not self.picture:
            self.preview.setToolTip(tr("This material has no picture: the map does nothing."))
        else:
            self.preview.setToolTip(Path(path).name if path else "")


class MaterialEditor(QDialog):
    """``app`` is the extension's handle: its document data holds the specs."""

    HINT = ("Changes apply to the next render. They are saved with the document. "
            "With a map, a setting's slider scales it. «Change picture…» and «Transparency» "
            "are the exceptions: they change the material in the model itself.")

    def __init__(self, app, lang="en", parent=None):
        super().__init__(parent)
        self.app = app
        self.lang = lang
        self.setWindowTitle("Render Studio — materials")
        self.resize(880, 600)
        self._loading = False
        self._pending = None
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(350)
        self._commit_timer.timeout.connect(self._commit)

        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.setIconSize(QSize(28, 28))
        self.list.currentItemChanged.connect(self._show)
        self.list.setMinimumWidth(180)
        self.list.setMaximumWidth(280)
        left.addWidget(self.list, 1)
        tools = QGridLayout()
        self.pipette_btn = QPushButton("Pick from the view")
        self.pipette_btn.setCheckable(True)
        self.pipette_btn.setToolTip("The eyedropper: click a face or an object in the 3D view and its material is "
                                    "chosen here. (It is IngeTrazo's own sampler: the Paint tool gets the same "
                                    "material.)")
        self.pipette_btn.toggled.connect(self._pipette_toggled)
        self.paint_btn = QPushButton("Paint with it")
        self.paint_btn.setToolTip("The paint bucket: pick the Paint tool with this material, then click a face or an "
                                  "object in the 3D view to paint it.")
        self.paint_btn.clicked.connect(self.paint_with_it)
        self.new_btn = QPushButton("New…")
        self.new_btn.setToolTip("Make a material (a colour or a picture) and paint the selection with it.")
        self.new_btn.clicked.connect(self.new_material)
        self.dup_btn = QPushButton("Duplicate")
        self.dup_btn.setToolTip("A copy of this material, settings included, under a new name.")
        self.dup_btn.clicked.connect(self.duplicate_current)
        tools.addWidget(self.pipette_btn, 0, 0)
        tools.addWidget(self.paint_btn, 0, 1)
        tools.addWidget(self.new_btn, 1, 0)
        tools.addWidget(self.dup_btn, 1, 1)
        left.addLayout(tools)
        self._pick_timer = QTimer(self)
        self._pick_timer.setInterval(150)
        self._pick_timer.timeout.connect(self._poll_pick)
        self._pick_ticks = 0
        pick = QPushButton("From the selection")
        pick.setToolTip("Show the material of the selected face or group.")
        pick.clicked.connect(self.pick_selection)
        left.addWidget(pick)
        help_btn = QToolButton()
        help_btn.setText("?")
        help_btn.setToolTip("How materials render, and what each setting does")
        help_btn.clicked.connect(self._help)
        left.addWidget(help_btn)
        lay.addLayout(left, 2)

        right = QWidget()
        form = QFormLayout(right)
        form.setContentsMargins(8, 6, 22, 6)          # clear of the scroll bar
        self.title = QLabel("")
        self.title.setStyleSheet("font-weight: bold")
        form.addRow(self.title)
        self.detected_label = QLabel("")
        self.detected_label.setWordWrap(True)
        self.detected_label.setStyleSheet("color: #2a7a3a")
        self.detected_label.setToolTip("Water, glass, grass and lights are recognised by their name (aigua, agua, "
                                       "water, piscina; vidre, vidrio, glass; gespa, césped, grass, herba; llum, "
                                       "LED, neon…) in several languages, or by their picture's file name.")
        self.detected_label.setVisible(False)
        form.addRow(self.detected_label)
        prev = QHBoxLayout()
        self.cube = QLabel()
        self.cube.setFixedSize(150, 150)
        self.cube.setToolTip("A quick preview on a one-metre cube")
        note = QLabel("Quick preview on a 1 m cube. It follows the sliders, the picture and the colour; "
                      "the maps and Blender's lighting only show in the render.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray")
        prev.addWidget(self.cube)
        prev.addWidget(note, 1)
        form.addRow(prev)
        picrow = QHBoxLayout()
        self.pic_btn = QPushButton("Change picture…")
        self.pic_btn.setToolTip("Replace the picture of this material in the MODEL (not only in the "
                                "render): every face and object that wears it changes, one undo step.")
        self.pic_btn.clicked.connect(self.change_picture)
        self.keep_ratio = QCheckBox("Keep proportions")
        self.keep_ratio.setChecked(True)
        self.keep_ratio.setToolTip("The tile height follows the new image's proportions. Off: the "
                                   "tile size stays and a different shape is stretched.")
        picrow.addWidget(self.pic_btn)
        picrow.addWidget(self.keep_ratio)
        picrow.addStretch(1)
        form.addRow(picrow)
        self.form = form
        self._rows = {"picture": picrow}        # control → its form row (hidden when it does nothing)
        self.image_adj = ImageAdjust()
        self.image_adj.changed.connect(self._changed)
        form.addRow(self.image_adj)
        self._rows["image"] = self.image_adj
        self.set_label = QLabel("")
        self.set_label.setWordWrap(True)
        self.set_label.setStyleSheet("color: gray")
        self.set_label.setToolTip("Maps found next to the material's picture (its .pbr.json, or the "
                                  "Poly Haven and ambientCG file names). The render uses them by itself; "
                                  "choosing another map below replaces that one.")
        form.addRow(self.set_label)
        self.preset = QComboBox()
        self.preset.addItem("—", "")
        for key in M.PRESETS:
            self.preset.addItem(M.preset_label(key, lang), key)
        self.preset.activated.connect(self._preset)
        form.addRow("Start from", self.preset)
        self.kind = QComboBox()
        for key in M.TYPES:
            self.kind.addItem(tr(M.TYPE_LABELS[key]), key)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        form.addRow("Type", self.kind)
        self.sliders, self.values, self.maps = {}, {}, {}
        self.transparency = QSlider(Qt.Horizontal)
        self.transparency.setRange(0, 100)
        self.transparency.setProperty("lo", 0.0)
        self.transparency.setProperty("hi", 1.0 - opacity_mod.MIN_OPACITY)
        self.transparency.setToolTip("How much light the material lets through, in the MODEL and in the render: "
                                     "0 opaque, higher see-through (water, glass, a pool surface). It changes "
                                     "every face and object that wears the material, one undo step.")
        self.transparency_value = QLabel("")
        self.transparency_value.setMinimumWidth(34)
        self._opacity_timer = QTimer(self)
        self._opacity_timer.setSingleShot(True)
        self._opacity_timer.setInterval(350)
        self._opacity_timer.timeout.connect(self._apply_transparency)
        self.transparency.valueChanged.connect(self._transparency_moved)
        trow = QHBoxLayout()
        trow.addWidget(self.transparency, 1)
        trow.addWidget(self.transparency_value)
        form.addRow("Transparency", trow)
        self._rows["transparency"] = trow
        self.sliders["transparency"] = self.transparency
        self.values["transparency"] = self.transparency_value
        self.maps["opacity"] = MapRow("opacity", self._changed)
        form.addRow("", self.maps["opacity"])
        self._rows["map:opacity"] = self.maps["opacity"]
        for key, label, lo, hi, tip in _FIELDS:
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 100)
            s.setProperty("lo", lo)
            s.setProperty("hi", hi)
            s.setToolTip(tip)
            v = QLabel("")
            v.setMinimumWidth(34)
            s.valueChanged.connect(lambda _x, k=key: (self._label(k), self._changed()))
            row = QHBoxLayout()
            row.addWidget(s, 1)
            row.addWidget(v)
            form.addRow(label, row)
            self.sliders[key] = s
            self.values[key] = v
            self.maps[key] = MapRow(key, self._changed)
            form.addRow("", self.maps[key])
            self._rows[key] = row
            self._rows["map:" + key] = self.maps[key]
        self.ripple = QSlider(Qt.Horizontal)
        self.ripple.setRange(0, 100)
        self.ripple.setProperty("lo", 0.0)
        self.ripple.setProperty("hi", 1.0)
        self.ripple.setToolTip("Water: the size of the ripples, from fine (left) to broad waves (right). "
                               "Their height is the Relief slider.")
        self.ripple_value = QLabel("")
        self.ripple_value.setMinimumWidth(34)
        self.ripple.valueChanged.connect(lambda _x: (self._label("ripple_size"), self._changed()))
        rrow = QHBoxLayout()
        rrow.addWidget(self.ripple, 1)
        rrow.addWidget(self.ripple_value)
        form.addRow("Ripple size", rrow)
        self._rows["ripple_size"] = rrow
        self.sliders["ripple_size"] = self.ripple
        self.values["ripple_size"] = self.ripple_value
        lo, hi = M.GRASS_HEIGHT_RANGE
        self.grass = QSlider(Qt.Horizontal)
        self.grass.setRange(0, 100)
        self.grass.setProperty("lo", lo)
        self.grass.setProperty("hi", hi)
        self.grass.setToolTip("Grass: how tall the blades grow, in the render only (the model stays flat). "
                              "A few centimetres for a mown lawn, more for long grass.")
        self.grass_value = QLabel("")
        self.grass_value.setMinimumWidth(34)
        self.grass.valueChanged.connect(lambda _x: (self._label("grass_height"), self._changed()))
        grow = QHBoxLayout()
        grow.addWidget(self.grass, 1)
        grow.addWidget(self.grass_value)
        form.addRow("Grass height", grow)
        self._rows["grass_height"] = grow
        self.sliders["grass_height"] = self.grass
        self.values["grass_height"] = self.grass_value
        lo, hi = M.GRASS_DENSITY_RANGE
        self.density = QSlider(Qt.Horizontal)
        self.density.setRange(0, 100)
        self.density.setProperty("lo", lo)
        self.density.setProperty("hi", hi)
        self.density.setToolTip("Grass: how many tufts (of a few blades each) grow on a square metre. "
                                "A thick lawn 250–400, long grass 60–120. The live view and the render "
                                "use the same density.")
        self.density_value = QLabel("")
        self.density_value.setMinimumWidth(34)
        self.density.valueChanged.connect(lambda _x: (self._label("grass_density"), self._changed()))
        drow = QHBoxLayout()
        drow.addWidget(self.density, 1)
        drow.addWidget(self.density_value)
        form.addRow("Grass density", drow)
        self._rows["grass_density"] = drow
        self.sliders["grass_density"] = self.density
        self.values["grass_density"] = self.density_value
        self.map_size = QDoubleSpinBox()
        self.map_size.setRange(0.02, 50.0)
        self.map_size.setDecimals(2)
        self.map_size.setSingleStep(0.1)
        self.map_size.setValue(1.0)
        self.map_size.setSuffix(" m")
        self.map_size.setToolTip("How big one image of a map file is on the model — used when "
                                 "the material has no picture of its own (with one, the maps "
                                 "follow the picture's size).")
        self.map_size.valueChanged.connect(self._changed)
        form.addRow("Map image size", self.map_size)
        self._rows["map_size"] = self.map_size
        self.reset_btn = QPushButton("Back to automatic")
        self.reset_btn.setToolTip("Forget these settings: IngeTrazo's own finish for this material.")
        self.reset_btn.clicked.connect(self._reset)
        form.addRow(self.reset_btn)
        hint = QLabel(self.HINT)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        form.addRow(hint)
        self.hint = hint
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(right)
        lay.addWidget(scroll, 3)
        self.refresh()

    # -- data ----------------------------------------------------------------------
    def specs(self) -> dict:
        data = self.app.document_data({}) or {}
        return dict(data.get("materials") or {})

    def _store(self, name, spec):
        data = self.app.document_data({}) or {}
        mats = dict(data.get("materials") or {})
        if spec is None:
            mats.pop(name, None)
        else:
            mats[name] = spec
        data["materials"] = mats
        studio_data.write(self.app, data)

    def texture_set(self, name):
        """The companion maps of the material's picture (pbr.find_maps), or None;
        a tinted picture's are its original's."""
        mat = self.app.scene.materials.get(name) if name else None
        tex = (getattr(mat, "texture", None) or {}) if mat is not None else {}
        src = tex.get("base") or tex.get("path")
        try:
            return pbr.find_maps(src) if src else None
        except Exception:  # noqa: BLE001 - an odd folder never breaks the editor
            return None

    def _show_texture_set(self, name, kind="generic"):
        """The line listing the set's maps, and «Texture set: …» as the first map
        choice of the settings it gives — only what the render uses for this type
        (glass and water take only the normal map; the grass's blades none)."""
        ts = dict(getattr(self, "_ts", None) or {}) if name else {}
        if kind in ("glass", "water"):
            ts = {"normal": ts["normal"], "normal_flip_green": ts.get("normal_flip_green")} \
                if ts.get("normal") else {}
        names = (("normal", tr("normal")), ("roughness", tr("roughness")), ("ao", tr("ambient occlusion")),
                 ("displacement", tr("displacement")), ("metalness", tr("metal")), ("opacity", tr("opacity")),
                 ("arm", tr("AO/roughness/metal packed")))
        found = [label for key, label in names if ts.get(key)]
        self.set_label.setText(tr("Texture set: {maps}. The render uses these maps.", maps=", ".join(found))
                               if found else "")
        self.set_label.setVisible(bool(found))
        arm = ts.get("arm", "")
        self.maps["roughness"].set_texture_set(ts.get("roughness") or arm, None if ts.get("roughness") else 1,
                                               what="roughness")
        self.maps["metallic"].set_texture_set(ts.get("metalness") or arm, None if ts.get("metalness") else 2,
                                              what="metal")
        if ts.get("normal"):
            self.maps["bump"].set_texture_set(ts["normal"], normal=True, what="normal map")
        else:
            self.maps["bump"].set_texture_set(ts.get("displacement", ""), what="displacement")
        self.maps["opacity"].set_texture_set(ts.get("opacity") or "", what="opacity map")
        self.maps["glow"].set_texture_set("")

    def detected(self, name):
        """The settings the material's name (or its picture's file name) gives it when it has
        none of its own — what the render uses too (materials.detected_spec) — or None."""
        mat = self.app.scene.materials.get(name) if name else None
        tex = (getattr(mat, "texture", None) or {}) if mat is not None else {}
        pic = tex.get("base") or tex.get("path") or ""
        return M.detected_spec(name, Path(pic).name if pic else None)

    def _picture(self, name):
        mat = self.app.scene.materials.get(name) if name else None
        tex = (getattr(mat, "texture", None) or {}).get("path") if mat is not None else None
        return tex if tex and Path(tex).is_file() else ""

    # -- the list -----------------------------------------------------------------
    def refresh(self, force=False):
        """Rebuild the list from the document (keeps the current material). Nothing is rebuilt
        when no row would change (it runs on every change of the document, selections included);
        ``force`` rebuilds anyway."""
        current = self.current_name()
        scene = self.app.scene
        used = M.used_materials(scene)
        specs = self.specs()
        shown = [(name, "● " if name in specs else "◦ " if self.detected(name) else "", used[name],
                  _swatch_key(scene.materials.get(name))) for name in sorted(used, key=str.lower)]
        spec_sig = json.dumps(specs, sort_keys=True, default=str)
        if not force and shown == getattr(self, "_shown_rows", None) and self.list.count() == len(shown):
            if spec_sig != getattr(self, "_shown_specs", None):
                self._shown_specs = spec_sig       # a setting changed (an undo, say): the pane only
                self._show(self.list.currentItem())
            return
        self._shown_rows, self._shown_specs = shown, spec_sig
        self._loading = True
        self.list.clear()
        for name in sorted(used, key=str.lower):
            mat = scene.materials.get(name)
            mark = "● " if name in specs else "◦ " if self.detected(name) else ""
            item = QListWidgetItem(_swatch(mat) if mat is not None else QIcon(), mark + name)
            item.setData(Qt.UserRole, name)
            item.setToolTip(tr("{n} painted with it", n=used[name]) if used[name]
                            else tr("In the model's materials, not worn by anything yet"))
            self.list.addItem(item)
        self._loading = False
        if current:
            self.select(current)
        elif self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._show(None)

    def current_name(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def select(self, name) -> bool:
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == name:
                self.list.setCurrentRow(i)
                return True
        return False

    def _help(self):
        from . import ui_help
        ui_help.show(self, "materials")

    def change_picture(self):
        """Replace the material's picture in the model (see texture_swap)."""
        from . import texture_swap
        name = self.current_name()
        start = str(QSettings().value(_SETTINGS + "picture_dir", "") or "")
        path, _f = QFileDialog.getOpenFileName(self, "New picture for the material", start,
                                               "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga)")
        if not path:
            return
        done, message = texture_swap.swap_picture(self.app, name, path, self.keep_ratio.isChecked())
        if done:
            QSettings().setValue(_SETTINGS + "picture_dir", str(Path(path).parent))
            self.refresh()
            self.select(name)
        self.title.setToolTip(message)
        self.hint.setText(message)

    # -- the eyedropper, the paint bucket, new and copied materials -----------------------------
    def _document_window(self):
        return getattr(self.app, "window", None)

    def _pipette_toggled(self, on):
        """The eyedropper is IngeTrazo's own: its toolbar button arms the Paint tool's sampler and the next
        click on a face or an object samples its material, which is then chosen here."""
        win = self._document_window()
        act = getattr(win, "_act_eyedropper", None)
        if not on:
            if act is not None and act.isChecked():
                act.setChecked(False)               # cancelled from here
            self._pick_timer.stop()
            return
        if act is None:
            self.pipette_btn.blockSignals(True)
            self.pipette_btn.setChecked(False)
            self.pipette_btn.blockSignals(False)
            self.hint.setText("This IngeTrazo has no eyedropper to borrow.")
            return
        self._pick_ticks = 0
        act.setChecked(True)                        # arms the sampler and picks the Paint tool
        self._pick_timer.start()
        self.hint.setText("Click a face or an object in the 3D view to choose its material here.")

    def pick_from_view(self):
        """Arm the eyedropper (see :meth:`_pipette_toggled`)."""
        self.pipette_btn.setChecked(True)

    def _poll_pick(self):
        try:
            from tools.paint import PaintTool
        except Exception:  # noqa: BLE001 - an IngeTrazo without the Paint tool
            self._pick_timer.stop()
            return
        self._pick_ticks += 1
        if PaintTool.sample_armed:
            if self._pick_ticks > 400:               # a minute with no click: let go
                self.pipette_btn.setChecked(False)
            return
        self._pick_timer.stop()
        self.pipette_btn.blockSignals(True)
        self.pipette_btn.setChecked(False)
        self.pipette_btn.blockSignals(False)
        mat = PaintTool.current_material
        if PaintTool.current_is_default or mat is None or not getattr(mat, "name", None):
            self.hint.setText("That surface wears no named material (it is the default one).")
            return
        if not self.select(mat.name):
            self.refresh(force=True)
            self.select(mat.name)
        self.hint.setText(tr("Chosen: {name}.", name=mat.name))
        self.raise_()
        self.activateWindow()

    def paint_with_it(self):
        """The paint bucket: this material becomes the Paint tool's, and the tool is picked."""
        from . import material_tools
        name = self.current_name()
        if name is None:
            return
        if material_tools.arm_paint_bucket(self.app, name):
            self.hint.setText(tr("Click a face or an object in the 3D view to paint it with {name}.", name=name))
        else:
            self.hint.setText("This material is not in the document's materials yet (paint a face with it first) "
                              "or the Paint tool is not available.")

    def _selected_count(self):
        from . import material_tools
        return material_tools.selection_count(self.app.scene)

    def _made(self, name, painted, what):
        self.refresh(force=True)
        self.select(name)
        extra = " " + tr("and painted {n} on the selection", n=painted) if painted else ""
        self.hint.setText(f"{what} {name}{extra}.")

    def new_material(self):
        """A material from scratch (a colour or a picture), painted on the selection if asked."""
        from . import material_tools
        from .new_material import NewMaterialDialog
        scene = self.app.scene
        start = str(QSettings().value(_SETTINGS + "picture_dir", "") or "")
        dlg = NewMaterialDialog(self, material_tools.unique_name(scene, "Material", self.specs()),
                                self._selected_count(), start)
        translate_on_show(dlg)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        if dlg.picture:
            QSettings().setValue(_SETTINGS + "picture_dir", str(Path(dlg.picture).parent))
        name, painted = material_tools.create_material(
            self.app, v["name"], color=v.get("color"), texture=v.get("texture"), apply=v["apply"])
        self._made(name, painted, tr("Made"))

    def duplicate_current(self):
        """A copy of the chosen material, settings included, under a name of its own."""
        from . import material_tools
        name = self.current_name()
        if name is None:
            return
        new, _n = material_tools.duplicate_material(self.app, name, apply=False)
        if new is None:
            self.hint.setText(f"{name} is not in the document's materials yet, so it cannot be copied "
                              "(paint a face with it first).")
            return
        self._made(new, 0, tr("Copied {name} as", name=name))

    def pick_selection(self):
        name = M.selection_material(self.app.scene)
        if not name or not self.select(name):
            self.title.setText("The selection has no named material. Paint it with a material "
                               "(Paint tool) so it can be edited here.")

    # -- the settings ------------------------------------------------------------------
    def _set_slider(self, key, value):
        s = self.sliders[key]
        lo, hi = float(s.property("lo")), float(s.property("hi"))
        s.setValue(int(round((float(value) - lo) / (hi - lo) * 100)))
        self._label(key)

    def _get(self, key):
        s = self.sliders[key]
        lo, hi = float(s.property("lo")), float(s.property("hi"))
        return round(lo + (hi - lo) * s.value() / 100.0, 3)

    def _label(self, key):
        v = self._get(key)
        self.values[key].setText(f"{v * 100:.0f}%" if key == "transparency"
                                 else f"{v * 100:.0f} cm" if key == "grass_height"
                                 else f"{v:.0f}/m²" if key == "grass_density"
                                 else f"{v:.0f}" if key == "glow" else f"{v:.2f}")

    def _show(self, item, _prev=None):
        if self._loading:
            return
        self._flush()
        name = item.data(Qt.UserRole) if item is not None else None
        enabled = name is not None
        for w in (self.paint_btn, self.dup_btn):
            w.setEnabled(name is not None)
        for w in (self.preset, self.kind, self.reset_btn, self.map_size, self.image_adj,
                  *self.sliders.values(), *self.maps.values()):
            w.setEnabled(enabled)
        self.title.setText(name or "No material is used in the model.")
        self._ts = (self.texture_set(name) or {}) if enabled else {}
        if not enabled:
            self.cube.clear()
            self.set_label.setVisible(False)
            return
        spec = dict(M.DEFAULT)
        own = self.specs().get(name)
        detected = None if own else self.detected(name)
        spec.update(own or detected or {})
        self.detected_label.setText(
            tr("Detected from the name: {label}. The render uses it; change any setting to make it your own.",
               label=M.preset_label(detected['preset'], self.lang)) if detected else "")
        self.detected_label.setVisible(bool(detected))
        maps = spec.get("maps") or {}
        picture = self._picture(name)
        self._loading = True
        self.preset.setCurrentIndex(max(0, self.preset.findData(spec.get("preset", ""))))
        self.kind.setCurrentIndex(max(0, self.kind.findData(spec.get("type", "generic"))))
        for key, *_r in _FIELDS:
            self._set_slider(key, spec.get(key, M.DEFAULT.get(key, 0.0)))
            self.maps[key].load(maps.get(key), picture)
        self._set_slider("ripple_size", spec.get("ripple_size", M.DEFAULT_RIPPLE_SIZE))
        self._set_slider("grass_height", spec.get("grass_height", M.DEFAULT_GRASS_HEIGHT))
        self._set_slider("grass_density", spec.get("grass_density") or M.auto_grass_density(
            spec.get("grass_height", M.DEFAULT_GRASS_HEIGHT)))
        self._set_slider("transparency", 1.0 - opacity_mod.material_opacity(self.app.scene, name))
        self.image_adj.load(spec.get("image"), bool(picture))
        size = next((m.get("size") for m in maps.values() if m and m.get("size")), 1.0)
        self.map_size.setValue(float(size))
        self._loading = False
        self._enable_glow()
        self._update_cube()

    def _transparency_moved(self, *_a):
        self._label("transparency")
        if self._loading:
            return
        self._changed()                       # glass also uses it in the render settings
        self._opacity_timer.start()

    def _apply_transparency(self):
        """The model: the opacity of the material on every face that wears it."""
        name = self.current_name()
        if name is None:
            return
        done, message = opacity_mod.set_opacity(self.app, name, 1.0 - self._get("transparency"))
        if message:
            self.hint.setText(message)
        if done:
            self._update_cube()

    def _kind_changed(self, *_a):
        """Choosing Water gives it waves to start with (Relief 0 would be a flat mirror),
        and Water or Glass a transparency to start with (opaque would hide the point)."""
        kind = self.kind.currentData()
        if not self._loading and kind == "water" and self._get("bump") <= 0.0:
            self._loading = True
            self._set_slider("bump", 0.5)
            self._loading = False
        if not self._loading and kind in M.DEFAULT_TRANSPARENCY and self._get("transparency") <= 0.0:
            self._loading = True
            self._set_slider("transparency", M.DEFAULT_TRANSPARENCY[kind])
            self._loading = False
            self._opacity_timer.start()
        self._changed()

    def cube_params(self, name=None) -> dict:
        """What the cube preview draws: the material's colour and picture from
        the model, and the type and sliders as they are now in the editor."""
        name = name or self.current_name()
        mat = self.app.scene.materials.get(name) if name else None
        tex = (getattr(mat, "texture", None) or {}) if mat is not None else {}
        return {
            "color": getattr(mat, "color", None) if mat is not None else None,
            "texture": self._picture(name) if name else "",
            "tile": (float(tex.get("sw", 1.0) or 1.0), float(tex.get("sh", 1.0) or 1.0)),
            "kind": self.kind.currentData(),
            "roughness": self._get("roughness"), "metallic": self._get("metallic"),
            "bump": self._get("bump"), "glow": self._get("glow"),
            "opacity": 1.0 - self._get("transparency"),
            "grass_height": self._get("grass_height"),
            "grass_density": self._get("grass_density"),
        }

    def _update_cube(self):
        if self.current_name() is None:
            self.cube.clear()
            return
        try:
            self.cube.setPixmap(cube_preview.render(self.cube_params(), 150))
        except Exception:  # noqa: BLE001 - a preview must never break the editor
            self.cube.clear()

    def shown_controls(self) -> set:
        """The controls that change the render of the current material as it is set
        now (materials.shown_controls)."""
        name = self.current_name()
        ts = getattr(self, "_ts", None) or {}
        kind = self.kind.currentData()
        return M.shown_controls(
            kind, picture=bool(self._picture(name)) if name else False,
            set_relief=bool(ts.get("normal") or (ts.get("displacement") and kind not in ("glass", "water"))),
            relief_source=self.maps["bump"].source.currentData() or "",
            file_maps=any(self.maps[k].source.currentData() in ("file", "normal")
                          for k in self.maps if f"map:{k}" in self._kind_maps(kind)))

    @staticmethod
    def _kind_maps(kind) -> set:
        """The map rows the type has at all (before the finer rules)."""
        return {r for r in M.shown_controls(kind, set_relief=False) if r.startswith("map:")}

    def _enable_glow(self):
        """Hide what does nothing for this material (another type's setting, one a
        texture set replaces, a picture's control without a picture)."""
        shown = self.shown_controls() if self.current_name() is not None else set(self._rows)
        for key, row in self._rows.items():
            self.form.setRowVisible(row, key in shown)
        kind = self.kind.currentData()
        label = self.form.labelForField(self._rows["bump"])
        if label is not None:                    # water's relief is its waves' height
            label.setText(tr("Wave height") if kind == "water" else tr("Relief"))
        self._show_texture_set(self.current_name(), kind)

    def _preset(self, _i):
        key = self.preset.currentData()
        if not key:
            return
        spec = M.PRESETS[key][1]
        self._loading = True
        self.kind.setCurrentIndex(max(0, self.kind.findData(spec.get("type", "generic"))))
        for k, *_r in _FIELDS:
            self._set_slider(k, spec.get(k, M.DEFAULT.get(k, 0.0)))
        self._set_slider("ripple_size", spec.get("ripple_size", M.DEFAULT_RIPPLE_SIZE))
        self._set_slider("grass_height", spec.get("grass_height", M.DEFAULT_GRASS_HEIGHT))
        self._set_slider("grass_density", spec.get("grass_density") or M.auto_grass_density(
            spec.get("grass_height", M.DEFAULT_GRASS_HEIGHT)))
        self._set_slider("transparency", spec.get("transparency", 0.0))
        self._loading = False
        self._opacity_timer.start()            # the model follows the preset's transparency
        self._changed(from_preset=key)

    def _changed(self, *_a, from_preset=None):
        if self._loading:
            return
        self._enable_glow()
        self._update_cube()
        name = self.current_name()
        if name is None:
            return
        spec = {"type": self.kind.currentData()}
        kind_maps = self._kind_maps(spec["type"])
        for key, *_r in _FIELDS:
            spec[key] = self._get(key)
        if spec["type"] == "water":
            spec["ripple_size"] = self._get("ripple_size")
        if spec["type"] == "grass":
            spec["grass_height"] = self._get("grass_height")
            spec["grass_density"] = round(self._get("grass_density"), 1)
        if spec["type"] == "glass":
            spec["transparency"] = self._get("transparency")
        maps = {}
        for key, row in self.maps.items():
            if f"map:{key}" not in kind_maps:      # another type's map: the render ignores it
                continue
            m = row.spec()
            if m:
                if m["source"] in ("file", "normal"):
                    m["size"] = round(self.map_size.value(), 3)
                maps[key] = m
        if maps:
            spec["maps"] = maps
        img = self.image_adj.spec() if spec["type"] != "grass" else None
        if img:
            spec["image"] = img
        if from_preset:
            spec["preset"] = from_preset
            extra = M.PRESETS[from_preset][1]
            for k in ("coat", "sheen"):
                if k in extra:
                    spec[k] = extra[k]
        else:
            # A slider or a map moved: the preset's coat and sheen stay (from
            # the change still waiting its pause, if any).
            old = (self._pending[1] if self._pending and self._pending[0] == name
                   else self.specs().get(name) or {})
            for k in ("coat", "sheen"):
                if k in old:
                    spec[k] = old[k]
            self.preset.setCurrentIndex(0)
        self._pending = (name, spec)
        self._commit_timer.start()             # one undo step per pause, not per pixel

    def _flush(self):
        if self._opacity_timer.isActive():
            self._opacity_timer.stop()
            self._apply_transparency()
        if self._pending is not None:
            self._commit_timer.stop()
            self._commit()

    def _commit(self):
        if self._pending is None:
            return
        name, spec = self._pending
        self._pending = None
        self._store(name, spec)
        self._mark(name, True)

    def _mark(self, name, on):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.UserRole) == name:
                item.setText(("● " if on else "◦ " if self.detected(name) else "") + name)
        if on and name == self.current_name():
            self.detected_label.setVisible(False)      # its own settings now

    def _reset(self):
        name = self.current_name()
        if name is None:
            return
        self._pending = None
        self._commit_timer.stop()
        self._store(name, None)
        self._mark(name, False)
        self._show(self.list.currentItem())

    def closeEvent(self, ev):
        self._flush()
        super().closeEvent(ev)
