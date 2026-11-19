# SPDX-License-Identifier: GPL-3.0-or-later
"""The material editor window: the model's materials on the left, how the
chosen one renders on the right — a preset to start from, its type and four
sliders. Saved in the document (one undo step per change), read by the next
render.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from . import materials as M

_FIELDS = (  # key, label, lo, hi, tip
    ("roughness", "Roughness", 0.0, 1.0, "0 a mirror-like polish, 1 fully matte."),
    ("metallic", "Metal", 0.0, 1.0, "1 for metals: the reflection takes the material's colour."),
    ("bump", "Relief", 0.0, 1.0, "Surface relief: from the picture's light and dark when it has "
                                 "one (joints, grain), else a fine grain (plaster, concrete)."),
    ("glow", "Glow", 0.0, 50.0, "How bright it shines by itself (Glowing type): screens, light panels."),
)


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


class MaterialEditor(QDialog):
    """``app`` is the extension's handle: its document data holds the specs."""

    def __init__(self, app, lang="en", parent=None):
        super().__init__(parent)
        self.app = app
        self.lang = lang
        self.setWindowTitle("Render Studio — materials")
        self.resize(640, 460)
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
        left.addWidget(self.list, 1)
        pick = QPushButton("From the selection")
        pick.setToolTip("Show the material of the selected face or group.")
        pick.clicked.connect(self.pick_selection)
        left.addWidget(pick)
        lay.addLayout(left, 1)

        right = QWidget()
        form = QFormLayout(right)
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
        self.sliders = {}
        self.values = {}
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
        self.reset_btn = QPushButton("Back to automatic")
        self.reset_btn.setToolTip("Forget these settings: IngeTrazo's own finish for this material.")
        self.reset_btn.clicked.connect(self._reset)
        form.addRow(self.reset_btn)
        hint = QLabel("Changes apply to the next render. They are saved with the document.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        form.addRow(hint)
        lay.addWidget(right, 1)
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
        for w in (self.preset, self.kind, self.reset_btn, *self.sliders.values()):
            w.setEnabled(enabled)
        self.title.setText(name or "No material is used in the model.")
        if not enabled:
            return
        spec = dict(M.DEFAULT)
        spec.update(self.specs().get(name) or {})
        self._loading = True
        self.preset.setCurrentIndex(max(0, self.preset.findData(spec.get("preset", ""))))
        self.kind.setCurrentIndex(max(0, self.kind.findData(spec.get("type", "generic"))))
        for key, *_r in _FIELDS:
            self._set_slider(key, spec.get(key, M.DEFAULT.get(key, 0.0)))
        self._loading = False
        self._enable_glow()

    def _enable_glow(self):
        self.sliders["glow"].setEnabled(self.kind.currentData() == "glow")

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
        if from_preset:
            spec["preset"] = from_preset
            extra = M.PRESETS[from_preset][1]
            for k in ("coat", "sheen"):
                if k in extra:
                    spec[k] = extra[k]
        else:
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
