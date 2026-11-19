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

from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget)

from . import materials as M

_FIELDS = (  # key, label, lo, hi, tip
    ("roughness", "Roughness", 0.0, 1.0, "0 a mirror-like polish, 1 fully matte."),
    ("metallic", "Metal", 0.0, 1.0, "1 for metals: the reflection takes the material's colour."),
    ("bump", "Relief", 0.0, 1.0, "Surface relief. Automatic: from the picture's light and dark "
                                 "when it has one (joints, grain), else a fine grain."),
    ("glow", "Glow", 0.0, 50.0, "How bright it shines by itself (Glowing type): screens, light panels."),
)

#: Map sources per setting: (value, label). "" = no map (relief: automatic).
_SOURCES = {
    "roughness": (("", "No map"), ("picture", "Picture (B/W)"), ("file", "Image file…")),
    "metallic": (("", "No map"), ("picture", "Picture (B/W)"), ("file", "Image file…")),
    "bump": (("", "Automatic"), ("grain", "Fine grain"), ("picture", "Picture (B/W)"),
             ("file", "Height map file…"), ("normal", "Normal map file…")),
    "glow": (("", "No map"), ("picture", "Picture (B/W)"), ("file", "Mask file…")),
}
MAP_FILTER = "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.exr *.hdr *.tga)"
_SETTINGS = "render_studio/"


def _swatch(mat) -> QIcon:
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


def map_preview(path, invert=False, contrast=0.0, normal=False, size=44):
    """What the render reads from a map: the image in black and white,
    inverted, with contrast — as a small square picture. None if unreadable."""
    if not path or not Path(path).is_file():
        return None
    img = QImage(str(path))
    if img.isNull():
        return None
    img = img.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    img = img.copy((img.width() - size) // 2, (img.height() - size) // 2, size, size)
    if normal:
        return QPixmap.fromImage(img)
    img = img.convertToFormat(QImage.Format_Grayscale8)
    c = max(0.0, min(1.0, float(contrast)))
    lo, hi = 0.49 * c, 1.0 - 0.49 * c
    for y in range(img.height()):
        for x in range(img.width()):
            v = img.pixelColor(x, y).redF()
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
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        self.source = QComboBox()
        for value, label in _SOURCES[key]:
            self.source.addItem(label, value)
        self.source.setToolTip("Where the setting varies over the surface. With a map, "
                               "the slider above scales it.")
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

    def _source_chosen(self, _i):
        src = self.source.currentData()
        if src in ("file", "normal"):
            st = QSettings()
            start = self.path or str(st.value(_SETTINGS + "map_dir", "") or "")
            path, _f = QFileDialog.getOpenFileName(self, "Map image", start, MAP_FILTER)
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
        self.invert.setEnabled(grey)
        self.contrast.setEnabled(grey)
        path = self.picture if src == "picture" else self.path if src in ("file", "normal") else ""
        pix = map_preview(path, self.invert.isChecked(), self.contrast.value() / 100.0,
                          normal=src == "normal") if path else None
        self.preview.setPixmap(pix if pix is not None else QPixmap())
        if src == "picture" and not self.picture:
            self.preview.setToolTip("This material has no picture: the map does nothing.")
        else:
            self.preview.setToolTip(Path(path).name if path else "")


class MaterialEditor(QDialog):
    """``app`` is the extension's handle: its document data holds the specs."""

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
        pick = QPushButton("From the selection")
        pick.setToolTip("Show the material of the selected face or group.")
        pick.clicked.connect(self.pick_selection)
        left.addWidget(pick)
        lay.addLayout(left, 2)

        right = QWidget()
        form = QFormLayout(right)
        form.setContentsMargins(8, 6, 22, 6)          # clear of the scroll bar
        self.title = QLabel("")
        self.title.setStyleSheet("font-weight: bold")
        form.addRow(self.title)
        self.preset = QComboBox()
        self.preset.addItem("—", "")
        for key in M.PRESETS:
            self.preset.addItem(M.preset_label(key, lang), key)
        self.preset.activated.connect(self._preset)
        form.addRow("Start from", self.preset)
        self.kind = QComboBox()
        for key in M.TYPES:
            self.kind.addItem(M.TYPE_LABELS[key], key)
        self.kind.currentIndexChanged.connect(self._changed)
        form.addRow("Type", self.kind)
        self.sliders, self.values, self.maps = {}, {}, {}
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
        self.reset_btn = QPushButton("Back to automatic")
        self.reset_btn.setToolTip("Forget these settings: IngeTrazo's own finish for this material.")
        self.reset_btn.clicked.connect(self._reset)
        form.addRow(self.reset_btn)
        hint = QLabel("Changes apply to the next render. They are saved with the document. "
                      "With a map, a setting's slider scales it.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        form.addRow(hint)
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
        self.app.set_document_data(data)

    def _picture(self, name):
        mat = self.app.scene.materials.get(name) if name else None
        tex = (getattr(mat, "texture", None) or {}).get("path") if mat is not None else None
        return tex if tex and Path(tex).is_file() else ""

    # -- the list -----------------------------------------------------------------
    def refresh(self):
        """Rebuild the list from the document (keeps the current material)."""
        current = self.current_name()
        scene = self.app.scene
        used = M.used_materials(scene)
        specs = self.specs()
        self._loading = True
        self.list.clear()
        for name in sorted(used, key=str.lower):
            mat = scene.materials.get(name)
            item = QListWidgetItem(_swatch(mat) if mat is not None else QIcon(),
                                   ("● " if name in specs else "") + name)
            item.setData(Qt.UserRole, name)
            item.setToolTip(f"{used[name]} faces")
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

    def pick_selection(self):
        name = M.selection_material(self.app.scene)
        if not name or not self.select(name):
            self.title.setText("The selection has no named material.")

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
        self.values[key].setText(f"{v:.0f}" if key == "glow" else f"{v:.2f}")

    def _show(self, item, _prev=None):
        if self._loading:
            return
        self._flush()
        name = item.data(Qt.UserRole) if item is not None else None
        enabled = name is not None
        for w in (self.preset, self.kind, self.reset_btn, self.map_size,
                  *self.sliders.values(), *self.maps.values()):
            w.setEnabled(enabled)
        self.title.setText(name or "No material is used in the model.")
        if not enabled:
            return
        spec = dict(M.DEFAULT)
        spec.update(self.specs().get(name) or {})
        maps = spec.get("maps") or {}
        picture = self._picture(name)
        self._loading = True
        self.preset.setCurrentIndex(max(0, self.preset.findData(spec.get("preset", ""))))
        self.kind.setCurrentIndex(max(0, self.kind.findData(spec.get("type", "generic"))))
        for key, *_r in _FIELDS:
            self._set_slider(key, spec.get(key, M.DEFAULT.get(key, 0.0)))
            self.maps[key].load(maps.get(key), picture)
        size = next((m.get("size") for m in maps.values() if m and m.get("size")), 1.0)
        self.map_size.setValue(float(size))
        self._loading = False
        self._enable_glow()

    def _enable_glow(self):
        on = self.kind.currentData() == "glow"
        self.sliders["glow"].setEnabled(on)
        self.maps["glow"].setEnabled(on)

    def _preset(self, _i):
        key = self.preset.currentData()
        if not key:
            return
        spec = M.PRESETS[key][1]
        self._loading = True
        self.kind.setCurrentIndex(max(0, self.kind.findData(spec.get("type", "generic"))))
        for k, *_r in _FIELDS:
            self._set_slider(k, spec.get(k, M.DEFAULT.get(k, 0.0)))
        self._loading = False
        self._changed(from_preset=key)

    def _changed(self, *_a, from_preset=None):
        if self._loading:
            return
        self._enable_glow()
        name = self.current_name()
        if name is None:
            return
        spec = {"type": self.kind.currentData()}
        for key, *_r in _FIELDS:
            spec[key] = self._get(key)
        maps = {}
        for key, row in self.maps.items():
            m = row.spec()
            if m:
                if m["source"] in ("file", "normal"):
                    m["size"] = round(self.map_size.value(), 3)
                maps[key] = m
        if maps:
            spec["maps"] = maps
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
                item.setText(("● " if on else "") + name)

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
