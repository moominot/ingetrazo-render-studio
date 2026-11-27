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
import logging
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSizePolicy, QSlider, QStyle, QTabBar, QToolButton, QVBoxLayout,
                               QWidget)

from . import icons, wheel_guard
from . import cube_preview
from . import opacity as opacity_mod
from . import materials as M
from . import blender_edit as BlenderEdit
from . import material_view as MV
from .material_preview import HEIGHT as SAMPLE_HEIGHT, WIDTH as SAMPLE_WIDTH, MaterialPreview
from . import pbr, studio_data, widgets
from .image_adjust import ImageAdjust

_FIELDS = (  # key, label, lo, hi, tip
    ("roughness", "Roughness", 0.0, 1.0, "0 a mirror-like polish, 1 fully matte."),
    ("metallic", "Metal", 0.0, 1.0, "1 for metals: the reflection takes the material's colour."),
    ("bump", "Relief", 0.0, 1.0, "Surface relief. Automatic: from the picture's light and dark "
                                 "when it has one (joints, grain), else a fine grain. Water: the "
                                 "height of the waves."),
    ("glow", "Glow", 0.0, 50.0, "How bright it shines by itself (Glowing type): screens, light panels. "
                                "The scale is finer at the low end: 1 is already a lot of light in a dim room."),
)

#: Map sources per setting: (value, label). "" = no map (relief: automatic).
_SOURCES = {
    "roughness": (("", "No map"), ("picture", "Picture (B/W)"), ("file", "Image file…")),
    "metallic": (("", "No map"), ("picture", "Picture (B/W)"), ("file", "Image file…")),
    "bump": (("", "Automatic"), ("grain", "Fine grain"), ("picture", "Picture (B/W)"),
             ("file", "Height map file…"), ("normal", "Normal map file…")),
    "glow": (("", "No map"), ("picture", "Picture (B/W)"), ("file", "Mask file…")),
    # white = opaque, black = transparent (a cut-out: leaves, a fence, a lace)
    "opacity": (("", "No map"), ("picture", "Picture (B/W)"), ("file", "Image file…")),
}
#: The relief's sources as buttons: (source, words, icon). "" = automatic (or the texture set's own).
_RELIEF_BUTTONS = (("", "Auto", "rel_auto"), ("grain", "Grain", "rel_grain"), ("picture", "Picture", "rel_picture"),
                   ("file", "Heights", "rel_height"), ("normal", "Normals", "rel_normal"))
_MAP_TIPS = {
    "opacity": "A picture that says where the material is see-through: white is opaque, black is transparent, "
               "greys in between (a cut-out: leaves, a fence, a lace). The render and the preview use it; the "
               "3D view shows the Transparency slider's value. It follows the material's own picture's "
               "layout when it has one.",
}
MAP_FILTER = "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.exr *.hdr *.tga)"
_SETTINGS = "render_studio/"
_log = logging.getLogger(__name__)
#: The window's own measures: the room round it, between its parts, and the height of the top row (the list's
#: search at one side, the tabs and the header's buttons at the other).
_MARGIN, _GAP, _TOP_ROW = 10, 6, 28
_LIST_WIDTH = (200, 300)


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


#: The little cube drawn by the editor is not what the render shows, so it is not in the window. When there is a
#: way of drawing the material as it renders, it goes back, centred above the name.
SHOW_PREVIEW = False


class ClickLabel(QLabel):
    """A label that says when it is clicked (the material's cube: a colour or a picture to change)."""
    clicked = Signal()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 4)
        outer.setSpacing(4)
        self.buttons = None
        if key == "bump":
            self.buttons = MV.DataButtons([(v, tr(words), icon) for v, words, icon in _RELIEF_BUTTONS])
            self.buttons.activated.connect(self._button_chosen)
            tips = dict(_SOURCES[key])
            for v, _words, _icon in _RELIEF_BUTTONS:
                self.buttons.button(v).setToolTip(tr(tips[v]))
            outer.addWidget(self.buttons)
        self.where = QLabel("")                       # (the relief: where its map comes from)
        self.where.setStyleSheet("color: gray")
        self.where.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.flip = QCheckBox("Green inverted (DirectX)")
        self.flip.setToolTip("For a normal map drawn the other common way (often «DX» in its name): the relief "
                             "would look turned inside out in one direction.")
        lay = QHBoxLayout()
        outer.addLayout(lay)
        self.source = QComboBox()
        for value, label in _SOURCES[key]:
            self.source.addItem(tr(label), value)
        self._first_label = tr(_SOURCES[key][0][1])
        self.source.setToolTip(_MAP_TIPS.get(key) or (
            "Where the setting varies over the surface. With a map, the slider above scales it."))
        self.source.activated.connect(self._source_chosen)
        lay.addWidget(self.source, 2)
        if self.buttons is not None:
            self.source.setVisible(False)             # (the buttons show it)
            lay.addWidget(self.where, 3)
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
        outer.addWidget(self.flip)
        self.flip.toggled.connect(self._changed)
        self._loading = False
        self._update()

    def _button_chosen(self, i):
        self.source.setCurrentIndex(max(0, self.source.findData(_RELIEF_BUTTONS[i][0])))
        self._source_chosen(0)

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
        if src == "normal" and self.flip.isChecked():
            out["flip_green"] = True
        return out

    def load(self, spec, picture):
        self._loading = True
        spec = spec or {}
        self.picture = picture or ""
        self.path = spec.get("path", "")
        self.source.setCurrentIndex(max(0, self.source.findData(spec.get("source", ""))))
        self.invert.setChecked(bool(spec.get("invert")))
        self.flip.setChecked(bool(spec.get("flip_green")))
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
        self.flip.setVisible(src == "normal")
        if self.buttons is not None:
            self.buttons.blockSignals(True)
            self.buttons.setCurrentIndex(max(0, self.buttons.findData(src or "")))
            self.buttons.blockSignals(False)
            picture_button = self.buttons.button("picture")
            picture_button.setEnabled(bool(self.picture) or src == "picture")
            if src in ("file", "normal"):
                words = Path(self.path).name if self.path else ""
            elif src == "grain":
                words = tr("A fine noise")
            elif src == "picture":
                words = tr("The material's picture")
            elif self.set_path:
                words = tr("Texture set: {what}", what=Path(self.set_path).name)
            else:
                words = tr("Automatic")
            self.where.setText(words)
            self.where.setToolTip(words)
        self.preview.setVisible(True)
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
        self.preview.setVisible(pix is not None or self.buttons is None)      # (no empty square under the buttons)
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
        self.resize(820, 700)
        self._loading = False
        self._pending = None
        self._extra = {}                         # the finer settings chosen for this material
        self._locked = False
        self._session = None
        self._edits = {}                         # material name → the picture being edited outside
        self.eyes = MV.Eyes()
        self.blocks = {}                         # setting → its block
        self.cards = {}                          # card → (the card, its blocks' keys)
        self.map_toggles = {}                    # setting → the little button that opens its map options
        self.sliders, self.values, self.maps = {}, {}, {}
        self._rows = {}                          # control → what is hidden when it does nothing
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(350)
        self._commit_timer.timeout.connect(self._commit)
        self._opacity_timer = QTimer(self)
        self._opacity_timer.setSingleShot(True)
        self._opacity_timer.setInterval(350)
        self._opacity_timer.timeout.connect(self._apply_transparency)
        self._tile_timer = QTimer(self)
        self._tile_timer.setSingleShot(True)
        self._tile_timer.setInterval(350)
        self._tile_timer.timeout.connect(self._apply_tile)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        outer.setSpacing(_GAP)
        lay = QHBoxLayout()
        lay.setSpacing(_MARGIN)
        outer.addLayout(lay, 1)
        side = QWidget()                        # the list and its buttons: all of one width
        side.setMinimumWidth(_LIST_WIDTH[0])
        side.setMaximumWidth(_LIST_WIDTH[1])
        side.setLayout(self._build_list())
        lay.addWidget(side, 2)
        right = QVBoxLayout()
        right.setSpacing(_GAP)
        lay.addLayout(right, 3)
        # what is not scrolled keeps, at the right, the room of the scroll bar: its edges are the cards'
        self._scroll_room = self.style().pixelMetric(QStyle.PM_ScrollBarExtent) + _GAP
        self._build_head(right)
        page = QWidget()
        page.setStyleSheet(widgets.flat_style())
        self.page = QVBoxLayout(page)
        self.page.setContentsMargins(0, 0, _GAP, 0)          # clear of the scroll bar
        self.page.setSpacing(6)
        self._build_top()
        self._build_cards(lang)
        self.page.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)     # (its room is always there: nothing jumps)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        self.scroll = scroll
        right.addWidget(scroll, 1)
        self._build_foot(right, outer)
        self.set_expert(str(QSettings().value(_SETTINGS + "material_expert", "false")).lower() == "true")
        wheel_guard.watch(self)          # (the wheel scrolls; it changes only a picked field)
        self.refresh()

    # -- the window's parts ---------------------------------------------------------
    def _build_list(self):
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(_GAP)
        self.search = QLineEdit()
        self.search.setFixedHeight(_TOP_ROW)
        self.search.setPlaceholderText("Search a material…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._filter_list())
        left.addWidget(self.search)
        self.list = QListWidget()
        self.list.setIconSize(QSize(28, 28))
        self.list.currentItemChanged.connect(self._show)
        left.addWidget(self.list, 1)
        self.pipette_btn = MV.tool_button(
            "Pick", "mat_pick", "The eyedropper: click a face or an object in the 3D view and its material is chosen here. "
            "(It is IngeTrazo's own sampler: the Paint tool gets the same material.)", under=True, checkable=True)
        self.pipette_btn.toggled.connect(self._pipette_toggled)
        self.paint_btn = MV.tool_button("Paint", "mat_paint", "The paint bucket: pick the Paint tool with this material, "
                                        "then click a face or an object in the 3D view to paint it.", under=True)
        self.paint_btn.clicked.connect(self.paint_with_it)
        self.new_btn = MV.tool_button("New…", "plus", "Make a material (a colour or a picture) and paint the "
                                      "selection with it.", under=True)
        self.new_btn.clicked.connect(self.new_material)
        self.dup_btn = MV.tool_button("Duplicate", "mat_duplicate", "A copy of this material, settings included, under "
                                      "a new name.", under=True)
        self.dup_btn.clicked.connect(self.duplicate_current)
        self.del_btn = MV.tool_button("Delete", "trash", "Take this material out of the drawing. Only one that nothing "
                                      "is painted with.", under=True)
        self.del_btn.clicked.connect(self.delete_current)
        self.save_btn = MV.tool_button("Save…", "save", "Save this material (its colour or picture, settings and finish) "
                                       "to a file, with its pictures, to use it in another drawing.", under=True)
        self.save_btn.clicked.connect(self.save_current)
        self.load_btn = MV.tool_button("Load…", "folder", "Bring a saved material into this drawing (it is added; "
                                       "nothing is painted).", under=True)
        self.load_btn.clicked.connect(self.load_from_file)
        tools = QGridLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(3)
        for i, b in enumerate((self.pipette_btn, self.paint_btn, self.new_btn, self.dup_btn, self.save_btn,
                               self.load_btn)):
            tools.addWidget(b, i // 2, i % 2)
        tools.addWidget(self.del_btn, 3, 0, 1, 2)        # only there when the chosen material can be deleted
        self.del_btn.setVisible(False)
        left.addLayout(tools)
        self._pick_timer = QTimer(self)
        self._pick_timer.setInterval(150)
        self._pick_timer.timeout.connect(self._poll_pick)
        self._pick_ticks = 0
        return left

    def _build_head(self, right):
        top = QWidget()
        top.setFixedHeight(_TOP_ROW)
        head = QHBoxLayout(top)
        head.setContentsMargins(0, 0, self._scroll_room, 0)
        head.setSpacing(4)
        self.tabs = QTabBar()
        self.tabs.addTab(tr("Material"))         # (a tab bar's words are not translated by the tree)
        self.tabs.addTab(tr("Expert"))
        self.tabs.setDrawBase(False)
        self.tabs.currentChanged.connect(lambda _i: self._enable_glow())
        head.addWidget(self.tabs, 0, Qt.AlignBottom)
        head.addStretch(1)
        self.expert_btn = QToolButton()
        self.expert_btn.setCheckable(True)
        self.expert_btn.setText("Expert mode")
        self.expert_btn.setIcon(icons.icon("tools"))
        self.expert_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.expert_btn.setToolTip("Every setting of the material, with an eye each: open, it is also in the Material tab.")
        self.expert_btn.toggled.connect(self.set_expert)
        self.help_btn = QToolButton()
        self.help_btn.setIcon(icons.icon("comp_help"))
        self.help_btn.setToolTip("How materials render, and what each setting does")
        self.help_btn.clicked.connect(self._help)
        for b in (self.expert_btn, self.help_btn):
            b.setIconSize(QSize(16, 16))
            b.setStyleSheet(widgets.flat_style() + widgets.SMALL_BUTTON)
            head.addWidget(b, 0, Qt.AlignVCenter)
        right.addWidget(top)
        self.expert_bar = QWidget()
        bar = QHBoxLayout(self.expert_bar)
        bar.setContentsMargins(0, 0, self._scroll_room, 0)
        self.expert_search = QLineEdit()
        self.expert_search.setPlaceholderText("Search a setting…")
        self.expert_search.setClearButtonEnabled(True)
        self.expert_search.textChanged.connect(lambda _t: self._enable_glow())
        bar.addWidget(self.expert_search, 1)
        self.default_view_btn = MV.tool_button("Default view", "undo", "The Material tab shows what it showed at first. "
                                               "No value of any material changes.")
        self.default_view_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.default_view_btn.setMinimumWidth(150)
        self.default_view_btn.clicked.connect(self._default_view)
        bar.addWidget(self.default_view_btn)
        self.expert_bar.setStyleSheet(widgets.flat_style())
        self.expert_bar.setVisible(False)
        right.addWidget(self.expert_bar)

    def _build_top(self):
        """The rendered sample, the name, the notes that warn, the type and the preset."""
        # the sample: drawn by a Blender in the background (material_preview), centred above the name
        self.sample = QLabel("")
        self.sample.setAlignment(Qt.AlignCenter)
        self.sample.setStyleSheet("color: gray; background: rgba(128,128,128,30); border-radius: 6px")
        self.sample.setToolTip("The material on a one-metre sphere, rendered by Blender with the render's own steps "
                               "(EEVEE, a light of its own: the model's light and the final engine may differ).")
        self.sample.setVisible(False)
        self.page.addWidget(self.sample, 0, Qt.AlignHCenter)
        self.preview = MaterialPreview(self._sample_blender, self)
        self.preview.ready.connect(self._sample_ready)
        self.preview.said.connect(self._sample_said)
        self.cube = ClickLabel()
        self.cube.setCursor(Qt.PointingHandCursor)
        self.cube.clicked.connect(self.cube_clicked)
        self.cube.setFixedSize(150, 150)
        self.cube.setToolTip("A quick preview on a one-metre cube. It follows the sliders, the picture and the colour; "
                             "the maps and Blender's lighting only show in the render. Click it to change the "
                             "material: its colour (a material with no picture) or its picture.")
        if SHOW_PREVIEW:
            self.page.addWidget(self.cube, 0, Qt.AlignHCenter)
        words = QVBoxLayout()
        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: bold; font-size: 14px")
        words.addWidget(self.title)
        self.detected_label = QLabel("")
        self.detected_label.setWordWrap(True)
        self.detected_label.setStyleSheet("color: #2a7a3a")
        self.detected_label.setToolTip("Water, glass, grass and lights are recognised by their name (aigua, agua, "
                                       "water, piscina; vidre, vidrio, glass; gespa, césped, grass, herba; llum, "
                                       "LED, neon…) in several languages, or by their picture's file name.")
        self.detected_label.setVisible(False)
        words.addWidget(self.detected_label)
        self.page.addLayout(words)
        # a material edited in Blender: its settings here are put away until the person takes them back
        self.lock_box = QWidget()
        lb = QVBoxLayout(self.lock_box)
        lb.setContentsMargins(0, 0, 0, 0)
        self.lock_label = QLabel(tr("Edited in Blender: the render uses that material exactly as you left it. Its "
                                    "settings here are hidden."))
        self.lock_label.setWordWrap(True)
        self.lock_label.setStyleSheet("color: #8a5a00")
        self.unlock_btn = MV.tool_button("Unlock (back to the basic settings)", "mat_unlock")
        self.unlock_btn.setIconSize(QSize(22, 22))
        self.unlock_btn.setMinimumHeight(44)
        accent = icons._accent()                      # the one thing to do here: tinted with the accent
        self.unlock_btn.setStyleSheet(
            "QToolButton {{ border: 1px solid rgb({r},{g},{b}); border-radius: 5px; background: rgba({r},{g},{b},70); "
            "font-weight: bold; color: palette(button-text); }}"
            "QToolButton:hover {{ background: rgba({r},{g},{b},110); }}".format(r=accent.red(), g=accent.green(),
                                                                                 b=accent.blue()))
        self.unlock_btn.setToolTip("Drop the material made in Blender and go back to this editor's settings: the render "
                                   "makes the material from them again. The Blender version is lost (Undo brings it back).")
        self.unlock_btn.clicked.connect(self.unlock_current)
        lb.addWidget(self.lock_label)
        lb.addWidget(self.unlock_btn)
        self.lock_box.setVisible(False)
        self.page.addWidget(self.lock_box)
        self.kind = MV.DataButtons([(key, tr(M.TYPE_LABELS[key]), "type_" + key) for key in M.TYPES], per_row=3)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.page.addWidget(self._block("type", "Type", self.kind, eye=False))

    def _block(self, key, label, control=None, *, value=None, extra=None, eye=True, into=None):
        block = MV.Block(key, label, control, value, extra)
        block.eye_clicked.connect(self._set_eye)
        block.reset_clicked.connect(self._reset_one)
        block.has_eye = eye
        self.blocks[key] = block
        if into is not None:
            into[0].body_layout.addWidget(block)
            into[1].append(key)
        return block

    def _card(self, key, title, icon):
        card = widgets.Card(tr(title), "mat_" + key, icon=icon, kind="column")
        card.body_layout.setSpacing(0)
        card.add_more_button(tr("Every setting of this group (Expert)"), lambda k=key: self.open_expert(k))
        self.page.addWidget(card)
        self.cards[key] = (card, [])
        return self.cards[key]

    def _slider_block(self, key, label, lo, hi, tip, into, *, mapped=False):
        s = QSlider(Qt.Horizontal)
        s.setRange(0, 100)
        s.setProperty("lo", lo)
        s.setProperty("hi", hi)
        s.setToolTip(tip)
        value = QLabel("")
        self.sliders[key], self.values[key] = s, value
        block = self._block(key, label, s, value=value, into=into,
                            extra=self._map_toggle(key) if mapped else None)
        self._rows[key] = block
        return s, block

    def _map_row(self, key, block):
        """The map options of a setting, under its slider."""
        row = self.maps[key] = MapRow(key, self._relief_changed if key == "bump" else self._changed)
        block.add(row)
        self._rows["map:" + key] = row
        return row

    def _build_cards(self, lang):
        self.preset = QComboBox()
        self.preset.addItem("—", "")
        for key in M.PRESETS:
            self.preset.addItem(M.preset_label(key, lang), key)
        self.preset.activated.connect(self._preset)
        self.page.addWidget(self._block("preset", "Start from", self.preset))

        # what only one type has comes first
        water = self._card("water", "Waves", "type_water")
        self.water_body = MV.DataButtons([(key, M.water_body_label(key, lang), "body_" + key) for key in M.WATER_BODIES])
        for key in M.WATER_BODIES:
            self.water_body.button(key).setToolTip(
                tr("Water: how big the body of water is: a pool's wavelets, a lake's ripples, the sea's "
                   "swell, the ocean's long rollers. Choosing one sets the ripples and the waves to suit."))
        self.water_body.activated.connect(self._water_body_chosen)
        self._rows["water_body"] = self._block("water_body", "Water scale", self.water_body, into=water)
        self.waves, _b = self._slider_block(
            "waves", "Waves", 0.0, 1.0, "Water: real waves in the render's geometry (the model stays flat): the edges of "
            "a pool or a lake ripple too. 100 % is the height the chosen scale would make; 0 is flat water (only the "
            "ripples bend the light).", water)
        self.waves.valueChanged.connect(lambda _x: (self._label("waves"), self._changed()))
        self.ripple, _b = self._slider_block(
            "ripple_size", "Ripple size", 0.0, 1.0, "Water: the size of the ripples, from fine (left) to broad waves "
            "(right). Their height is in the Relief group.", water)
        self.ripple.valueChanged.connect(lambda _x: (self._label("ripple_size"), self._changed()))

        grass = self._card("grass", "Grass", "type_grass")
        self.grass, _b = self._slider_block(
            "grass_height", "Grass height", *M.GRASS_HEIGHT_RANGE, "Grass: how tall the blades grow, in the render only "
            "(the model stays flat). A few centimetres for a mown lawn, more for long grass.", grass)
        self.grass.valueChanged.connect(lambda _x: (self._label("grass_height"), self._changed()))
        self.density, _b = self._slider_block(
            "grass_density", "Grass density", *M.GRASS_DENSITY_RANGE, "Grass: how many tufts (of a few blades each) grow "
            "on a square metre. A thick lawn 250–400, long grass 60–120. The live view and the render use the same "
            "density.", grass)
        self.density.valueChanged.connect(lambda _x: (self._label("grass_density"), self._changed()))
        self.grass_value, self.density_value = self.values["grass_height"], self.values["grass_density"]

        fields = {f[0]: f for f in _FIELDS}

        def field(key, into):
            _k, label, lo, hi, tip = fields[key]
            slider, block = self._slider_block(key, label, lo, hi, tip, into, mapped=key != "bump")
            slider.valueChanged.connect(lambda _x, k=key: (self._label(k), self._changed()))
            return block

        def optional(key, into):
            label, lo, hi, _rest, tip = MV.OPTIONAL[key]
            slider, block = self._slider_block(key, label, lo, hi, tip, into)
            slider.valueChanged.connect(lambda _x, k=key: self._optional_moved(k))
            return block

        glow = self._card("glow", "Light of its own", "type_glow")
        block = field("glow", glow)
        self._map_row("glow", block)

        # what the material is made of: a flat colour or a picture, how it is changed and how big it is
        colour = self._card("colour", "Colour and picture", "grp_background")
        self._build_source(colour)
        adjust = self._card("image", "Picture adjustments", "grp_corrections")
        self.image_adj = ImageAdjust()
        self.image_adj.changed.connect(self._changed)
        self.image_adj.header.setVisible(False)           # (the card is its header)
        self.image_adj.body.setVisible(True)
        self.image_adj.header.toggled.connect(lambda _on: self.image_adj.body.setVisible(True))
        self._rows["image"] = self._block("image", "", self.image_adj, into=adjust)
        if QSettings().value("render_studio/fold_mat_image", None) is None:
            adjust[0].set_open(False)
            QSettings().remove("render_studio/fold_mat_image")

        repeat = self._card("repeat", "Variation", "rel_grain")
        self.untile = QCheckBox("Break the repetition")
        self.untile.setToolTip("So the picture's pattern is not seen repeating over a big surface: patches of it are "
                               "shifted and melted into each other, its maps with it. For irregular surfaces (grass, "
                               "concrete, stone, gravel): a pattern with joints, like bricks or tiles, would stop "
                               "lining up. In the render only.")
        self.untile.toggled.connect(self._changed)
        self._rows["untile"] = self._block("untile", "", self.untile, into=repeat)
        optional("variation", repeat)

        relief = self._card("relief", "Relief", "rel_height")
        optional("set_relief", relief)
        field("bump", relief)
        source = self._block("map:bump", "Relief from", into=relief)
        self._map_row("bump", source)
        self.set_label = QLabel("")
        self.set_label.setWordWrap(True)
        self.set_label.setStyleSheet("color: gray")
        self.set_label.setToolTip("Maps found next to the material's picture (its .pbr.json, or the "
                                  "Poly Haven and ambientCG file names). The render uses them by itself; "
                                  "choosing another map replaces that one.")
        relief[0].body_layout.addWidget(self.set_label)
        optional("relief_height", relief)
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
        self._rows["map_size"] = self._block("map_size", "Map image size", self.map_size, into=relief)

        reflect = self._card("reflection", "Reflection", "grp_finish")
        for key in ("roughness", "metallic"):
            block = field(key, reflect)
            self._map_row(key, block)
            if key == "roughness":
                optional("rough_min", reflect)
                optional("rough_max", reflect)
        for key in ("ior", "coat", "coat_roughness", "sheen"):
            optional(key, reflect)

        through = self._card("transparency", "Transparency", "type_glass")
        self.transparency, block = self._slider_block(
            "transparency", "Transparency", 0.0, 1.0 - opacity_mod.MIN_OPACITY, "How much light the material lets "
            "through, in the MODEL and in the render: 0 opaque, higher see-through (water, glass, a pool surface). It "
            "changes every face and object that wears the material, one undo step.", through)
        toggle = self._map_toggle("opacity")
        block.layout().itemAt(0).layout().insertWidget(2, toggle)
        self.transparency.valueChanged.connect(self._transparency_moved)
        self.transparency_value = self.values["transparency"]
        self._map_row("opacity", block)
        optional("translucency", through)
        optional("ao_strength", colour)

    def _build_source(self, into):
        picrow = QWidget()
        box = QVBoxLayout(picrow)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        mode = QHBoxLayout()
        mode.setSpacing(3)
        self.mode_colour = MV.tool_button("Colour", "mat_colour", "The material is one flat colour, in the MODEL (every "
                                          "face and object that wears it follows; one undo step).", checkable=True)
        self.mode_picture = MV.tool_button("Picture", "rel_picture", "The material is a picture: choose an image file. "
                                           "In the MODEL too, one undo step.", checkable=True)
        for b in (self.mode_colour, self.mode_picture):
            b.setAutoExclusive(True)
            mode.addWidget(b)
        self.mode_colour.clicked.connect(self._mode_colour)
        self.mode_picture.clicked.connect(self._mode_picture)
        source = self._block("source", "Material of", mode, into=into)
        colrow = QWidget()
        cl = QHBoxLayout(colrow)
        cl.setContentsMargins(0, 0, 0, 0)
        self.colour_btn = QPushButton("")
        self.colour_btn.setMinimumHeight(28)
        self.colour_btn.setToolTip("The material's colour: click to choose another.")
        self.colour_btn.clicked.connect(self.choose_colour)
        cl.addWidget(self.colour_btn)
        source.add(colrow)
        self.pic_name = QLabel("")
        self.pic_name.setStyleSheet("color: gray")
        self.pic_name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        box.addWidget(self.pic_name)
        self.pic_btn = MV.tool_button("Change picture…", "folder", "Replace the picture of this material in the MODEL "
                                      "(not only in the render): every face and object that wears it changes, one undo step.")
        self.pic_btn.clicked.connect(self.change_picture)
        self.edit_btn = QToolButton()
        self.edit_btn.setIcon(icons.icon("pencil"))
        self.edit_btn.setIconSize(QSize(18, 18))
        self.edit_btn.setFixedSize(38, 30)
        self.edit_btn.setStyleSheet(widgets.flat_style())
        self.edit_btn.clicked.connect(self.edit_picture)
        choose = QAction("Choose the program…", self.edit_btn)        # (its right click)
        choose.triggered.connect(lambda _c=False: self.choose_editor())
        self.edit_btn.addAction(choose)
        self.edit_btn.setContextMenuPolicy(Qt.ActionsContextMenu)
        self.choose_editor_act = choose
        self._edit_label()
        buttons = QHBoxLayout()
        buttons.setSpacing(3)
        buttons.addWidget(self.pic_btn, 1)
        buttons.addWidget(self.edit_btn)
        box.addLayout(buttons)
        size_name = QLabel("Size on the model")
        box.addWidget(size_name)
        sizes = QHBoxLayout()
        self.tile_w = QDoubleSpinBox()
        self.tile_h = QDoubleSpinBox()
        for sp, tip in ((self.tile_w, "How wide the picture is on the model, in metres."),
                        (self.tile_h, "How tall the picture is on the model, in metres.")):
            sp.setRange(0.01, 500.0)
            sp.setDecimals(2)
            sp.setSingleStep(0.1)
            sp.setSuffix(" m")
            sp.setToolTip(tip)
        self.tile_w.valueChanged.connect(lambda _v: self._tile_moved("w"))
        self.tile_h.valueChanged.connect(lambda _v: self._tile_moved("h"))
        sizes.addWidget(self.tile_w, 1)
        sizes.addWidget(QLabel("×"))
        sizes.addWidget(self.tile_h, 1)
        box.addLayout(sizes)
        self.keep_ratio = QCheckBox("Keep proportions")
        self.keep_ratio.setChecked(True)
        self.keep_ratio.setToolTip("Changing the width changes the height too, so the picture is not stretched; and a new "
                                   "picture takes its own proportions. Off: each size is its own.")
        box.addWidget(self.keep_ratio)
        source.add(picrow)
        self._rows["picture"], self._rows["colour"] = picrow, colrow

    def _build_foot(self, right, outer):
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, self._scroll_room, 0)
        foot.setSpacing(4)
        self.reset_btn = MV.tool_button("Back to automatic", "undo",
                                        "Forget these settings: IngeTrazo's own finish for this material.")
        self.reset_btn.clicked.connect(self._reset)
        self.blender_btn = MV.tool_button(
            "Edit in Blender…", "mat_blender", "For experts: open the chosen material in Blender, on a sphere with its picture and its nodes (a "
            "grass material with its grass generator too). Change anything: each time you save (Ctrl+S) it co"
            "mes back here whole and the render uses it exactly as you left it. While it is edited in Blender"
            " its settings here are hidden: «Unlock» goes back to them.")
        self.blender_btn.clicked.connect(self.edit_in_blender)
        for b in (self.reset_btn, self.blender_btn):
            b.setMinimumHeight(36)
            foot.addWidget(b)
        right.addLayout(foot)
        hint = MV.StatusLine()
        hint.setToolTip(self.HINT)
        outer.addWidget(hint)
        self.hint = hint

    # -- the rendered sample ------------------------------------------------------
    def _sample_blender(self):
        owner = self.parent()
        return owner.blender_or_none() if owner is not None and hasattr(owner, "blender_or_none") else None

    def _request_sample(self) -> None:
        """Ask for the sample of the chosen material as it is now (only with the window in sight)."""
        name = self.current_name()
        if not hasattr(self, "preview") or not self.isVisible() or name is None:
            return
        if self._sample_blender() is None:
            self.sample.setVisible(False)
            return
        try:
            payload = BlenderEdit.materials_to_blender(self.app.scene, self.specs(), [name])
        except Exception:  # noqa: BLE001 - no sample for this one
            _log.exception("no sample for %s", name)
            payload = None
        if payload:
            self.sample.setVisible(True)
            self.preview.ask(payload)

    def _sample_ready(self, picture, seconds) -> None:
        self.sample.setPixmap(picture)
        self.sample.setFixedSize(picture.size())
        self.sample_seconds = seconds

    def _sample_said(self, what) -> None:
        if what == "starting":
            self.sample.setFixedSize(SAMPLE_WIDTH, SAMPLE_HEIGHT)
            self.sample.setText(tr("Starting Blender for the sample…"))
        elif what == "failed":
            self.sample.setText(tr("The sample could not be rendered."))

    def hideEvent(self, ev):  # noqa: N802 (Qt)
        super().hideEvent(ev)
        if not ev.spontaneous() and hasattr(self, "preview"):
            self.preview.stop()                  # out of sight: its Blender goes

    # -- the Expert tab and the eyes ------------------------------------------------
    def expert_view(self) -> bool:
        return self.expert_btn.isChecked() and self.tabs.currentIndex() == 1

    def set_expert(self, on: bool) -> None:
        """Expert mode: the Expert tab is there (off: only the Material tab)."""
        on = bool(on)
        if self.expert_btn.isChecked() != on:
            self.expert_btn.setChecked(on)               # (comes back here)
            return
        QSettings().setValue(_SETTINGS + "material_expert", "true" if on else "false")
        self.tabs.setTabVisible(1, on)
        self.tabs.setCurrentIndex(1 if on else 0)
        if getattr(self, "blocks", None) and hasattr(self, "scroll"):
            self._enable_glow()

    def open_expert(self, card_key: str) -> None:
        """A card's «+»: the Expert tab, at that group."""
        self.set_expert(True)
        self.tabs.setCurrentIndex(1)
        card = self.cards[card_key][0]
        card.set_open(True)
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(card.y()))

    def _set_eye(self, key: str, on: bool) -> None:
        self.eyes.set(key, on)
        self._enable_glow()

    def _default_view(self) -> None:
        self.eyes.reset()
        self._enable_glow()

    def _filter_list(self) -> None:
        words = MV.plain(self.search.text()).split()
        for i in range(self.list.count()):
            item = self.list.item(i)
            name = MV.plain(item.data(Qt.UserRole))
            item.setHidden(not all(w in name for w in words))

    # -- the finer settings ----------------------------------------------------------
    def _optional_rest(self, key, kind) -> float:
        """Where a finer slider rests while it is automatic."""
        if key == "translucency" and kind == "foliage":
            return 0.5
        if key == "ior":
            return {"glass": 1.45, "water": 1.33}.get(kind, 1.5)
        return MV.OPTIONAL[key][3]

    def _optional_moved(self, key):
        if self._loading:
            return
        self._extra[key] = self._get(key)
        self._label(key)
        self._changed()

    def _reset_one(self, key):
        """A finer setting back to automatic."""
        if self._extra.pop(key, None) is None:
            return
        self._loading = True
        self._set_slider(key, self._optional_rest(key, self.kind.currentData()))
        self._loading = False
        self._changed()

    def _load_optional(self, spec):
        self._extra = {k: float(spec[k]) for k in MV.OPTIONAL if k in spec}
        for key in MV.OPTIONAL:
            self._set_slider(key, self._extra.get(key, self._optional_rest(key, spec.get("type", "generic"))))

    def _relief_changed(self):
        """The relief's source: a normal or height map chosen with Relief at 0 would do nothing, so Relief goes
        to the middle (a normal map as it is drawn)."""
        source = self.maps["bump"].source.currentData() or ""
        before, self._relief_source = getattr(self, "_relief_source", ""), source
        if not self._loading and source != before and source in ("file", "normal", "grain", "picture") \
                and self._get("bump") <= 0.0:
            self._loading = True
            self._set_slider("bump", 0.5)
            self._loading = False
        self._changed()

    # -- data ----------------------------------------------------------------------
        wheel_guard.watch(self)          # (the wheel scrolls; it changes only a picked field)
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
        self._filter_list()
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

    def _map_toggle(self, key):
        """The small button next to a setting that opens its map options (a picture or a file drives the slider)."""
        b = QToolButton()
        b.setCheckable(True)
        b.setArrowType(Qt.RightArrow)
        b.setAutoRaise(True)
        b.setToolTip(tr("Map: let a picture or an image file drive this setting"))
        b.toggled.connect(lambda on, k=key, t=b: (t.setArrowType(Qt.DownArrow if on else Qt.RightArrow), self._enable_glow()))
        self.map_toggles[key] = b
        return b

    def edit_in_blender(self):
        from .blender_session import BlenderSession
        owner = self.parent()
        found = owner.blender_or_none() if owner is not None and hasattr(owner, "blender_or_none") else None
        if found is None:
            self.title.setText(tr("Blender was not found: choose it in the Render Studio panel."))
            return None
        if self._session is not None:
            self._session.stop()
        name = self.current_name()
        if name is None:
            self.title.setText(tr("Choose a material first."))
            return None
        self._session = BlenderSession(self.app, "materials", found, self, only=name)
        self._session.changed.connect(self.title.setText)
        self._session.failed.connect(self.title.setText)
        if self._session.start():
            self.title.setText(tr("Opened in Blender. Change the material there and save (Ctrl+S): it comes back here."))
        return self._session

    def _help(self):
        from . import ui_help
        ui_help.show(self, "materials")

    def cube_clicked(self):
        """The cube: a material with no picture opens the colour chooser (the colour changes everywhere it is
        worn, one undo step); one with a picture asks for another picture."""
        from . import material_tools
        name = self.current_name()
        mat = (getattr(self.app.scene, "materials", None) or {}).get(name) if name else None
        if name is None:
            return
        if mat is None:
            self.hint.setText(tr("{name} is not in the document's materials yet, so its colour cannot be "
                                 "changed (paint a face with it first).", name=name))
            return
        if mat.texture:
            self.change_picture()
            return
        from PySide6.QtWidgets import QColorDialog
        start = QColor.fromRgbF(*(tuple(mat.color or (0.8, 0.8, 0.8))[:3]))
        chosen = QColorDialog.getColor(start, self, tr("Colour of the material"))
        if chosen.isValid() and material_tools.set_material_colour(
                self.app, name, (chosen.redF(), chosen.greenF(), chosen.blueF())):
            self.refresh(force=True)
            self.select(name)
            self.hint.setText(tr("Colour of {name} changed.", name=name))

    def _sync_source(self, name):
        """What the «Material of» block shows: colour or picture, the colour, the picture's name and its size."""
        mat = (getattr(self.app.scene, "materials", None) or {}).get(name) if name else None
        has = bool(mat is not None and mat.texture)
        self._tile_loading = True
        for b, on in ((self.mode_colour, not has), (self.mode_picture, has)):
            b.setAutoExclusive(False)
            b.setChecked(on)
            b.setAutoExclusive(True)
        usable = mat is not None and not getattr(self, "_locked", False)
        for w in (self.mode_colour, self.mode_picture, self.colour_btn, self.pic_btn, self.tile_w, self.tile_h,
                  self.keep_ratio):
            w.setEnabled(usable)
        rgb = tuple((getattr(mat, "color", None) or (0.8, 0.8, 0.8)))[:3] if mat is not None else (0.8, 0.8, 0.8)
        c = QColor.fromRgbF(*[max(0.0, min(1.0, float(x))) for x in rgb])
        self.colour_btn.setStyleSheet(f"background-color: {c.name()}; border: 1px solid gray")
        tex = (mat.texture or {}) if mat is not None else {}
        path = tex.get("base") or tex.get("path") or ""
        self.pic_name.setText(Path(path).name if path else "")
        self.tile_w.setValue(float(tex.get("sw", 1.0) or 1.0))
        self.tile_h.setValue(float(tex.get("sh", 1.0) or 1.0))
        self._tile_loading = False

    def _material(self):
        name = self.current_name()
        return name, ((getattr(self.app.scene, "materials", None) or {}).get(name) if name else None)

    def _reshow(self, name):
        self.refresh(force=True)
        self.select(name)

    def choose_colour(self):
        """The flat colour of the material, changed everywhere it is worn (a material with a picture becomes one
        of this colour: see «Material of»)."""
        from . import material_tools
        from PySide6.QtWidgets import QColorDialog
        name, mat = self._material()
        if mat is None:
            return
        start = QColor.fromRgbF(*(tuple(mat.color or (0.8, 0.8, 0.8))[:3]))
        chosen = QColorDialog.getColor(start, self, tr("Colour of the material"))
        if chosen.isValid() and material_tools.set_material_colour(
                self.app, name, (chosen.redF(), chosen.greenF(), chosen.blueF()), force=True):
            self._reshow(name)
            self.hint.setText(tr("Colour of {name} changed.", name=name))

    def _mode_colour(self):
        """«Colour»: a material with a picture becomes a flat colour (asked, starting from the picture's average)."""
        from . import material_tools
        from PySide6.QtWidgets import QColorDialog
        name, mat = self._material()
        if mat is None or not mat.texture:
            self._sync_source(name)
            return
        pic = self._picture(name)
        start = QColor(128, 128, 128)
        if pic:
            img = QImage(pic)
            if not img.isNull():
                start = img.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
        chosen = QColorDialog.getColor(start, self, tr("Colour of the material"))
        if chosen.isValid() and material_tools.set_material_colour(
                self.app, name, (chosen.redF(), chosen.greenF(), chosen.blueF()), force=True):
            self._reshow(name)
            self.hint.setText(tr("{name} is now a flat colour.", name=name))
        else:
            self._sync_source(name)

    def _mode_picture(self):
        """«Picture»: a colour-only material gets an image file."""
        from . import material_tools
        name, mat = self._material()
        if mat is None or mat.texture:
            self._sync_source(name)
            return
        start = str(QSettings().value(_SETTINGS + "picture_dir", "") or "")
        path, _f = QFileDialog.getOpenFileName(self, "Picture of the material", start,
                                               "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga)")
        if not path:
            self._sync_source(name)
            return
        done, message = material_tools.set_material_picture(self.app, name, path, self.tile_w.value())
        if done:
            QSettings().setValue(_SETTINGS + "picture_dir", str(Path(path).parent))
            self._reshow(name)
        else:
            self._sync_source(name)
        self.hint.setText(message)

    def _tile_moved(self, which):
        if getattr(self, "_tile_loading", False):
            return
        name, mat = self._material()
        pic = self._picture(name) if mat is not None else ""
        if self.keep_ratio.isChecked() and pic:
            img = QImage(pic)
            if not img.isNull() and img.width():
                ratio = img.height() / img.width()
                self._tile_loading = True
                if which == "w":
                    self.tile_h.setValue(self.tile_w.value() * ratio)
                else:
                    self.tile_w.setValue(self.tile_h.value() / ratio)
                self._tile_loading = False
        self._tile_timer.start()

    def _apply_tile(self):
        """The size the picture has on the model, on every face and object that wears the material."""
        from . import material_tools
        name, mat = self._material()
        if mat is not None and mat.texture and material_tools.set_texture_size(
                self.app, name, self.tile_w.value(), self.tile_h.value()):
            self._update_cube()

    def _edit_label(self):
        """The pencil's tip says what it opens: the program chosen, GIMP or Krita when found, else the system's."""
        from . import external_edit
        prog = external_edit.editor_name()
        first = tr("Edit in {program}…", program=prog) if prog else tr("Edit picture…")
        self.edit_btn.setToolTip(first + "\n\n" + tr(
            "The picture is opened as a copy and taken back into the material each time it is saved there (one undo "
            "step each); the original file is not touched. In GIMP save with File ▸ Overwrite (or Export As).")
            + "\n\n" + tr("Right click: choose another program."))

    def edit_picture(self):
        """The material's picture in another program: edited as a copy, taken back whenever it is saved."""
        from . import external_edit
        name = self.current_name()
        if name is None:
            return
        old = self._edits.pop(name, None)
        if old is not None:
            old.stop()
            old.deleteLater()
        def new_session():
            made = external_edit.PictureEdit(self.app, name, self)
            made.changed.connect(lambda msg, n=name: self._edited(n, msg))
            made.failed.connect(self.hint.setText)
            return made

        session = new_session()
        program = external_edit.find_editor()
        started = session.start(program)
        if not started and session.could_not_open:         # no program opens it: ask for one
            program = self.choose_editor()
            if program:
                session = new_session()
                started = session.start(program)
        if started:
            self._edits[name] = session
            shown = external_edit.editor_name(program) or tr("the system's program")
            self.hint.setText(tr("Opened {file} in {program}. Save it there (in GIMP: File ▸ Overwrite) and the "
                                 "material takes it.", file=session.file.name, program=shown))

    def _edited(self, name, message):
        self.refresh(force=True)
        self.select(name)
        self.hint.setText(message)

    def choose_editor(self):
        """The program that edits pictures, remembered."""
        from . import external_edit
        current = external_edit.find_editor()
        path, _f = QFileDialog.getOpenFileName(self, tr("Program to edit pictures"),
                                               str(Path(current).parent) if current else "",
                                               tr("Programs") + " (*.exe);;" + tr("All files") + " (*)")
        if path:
            external_edit.remember_editor(path)
            self._edit_label()
            self.hint.setText(tr("Pictures will be edited with {program}.", program=external_edit.editor_name(path)))
        return path

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
        name = getattr(mat, "name", None) if not PaintTool.current_is_default else None
        if not name and not PaintTool.current_is_default:
            # The sampler found a paint but no named material (one inside a component can wear it through
            # the component, or through a name the document's registry does not hold): what is selected may.
            # (A face the sampler calls default is default: nothing is looked for.)
            name = M.selection_material(self.app.scene)
        if not name:
            self.hint.setText(tr("That surface wears no named material (it is the default one)."))
            return
        if not self.select(name):
            self.refresh(force=True)
            if not self.select(name):
                self.hint.setText(tr("{name} is not in the list of materials (paint a face with it first).", name=name))
                return
        self.hint.setText(tr("Chosen: {name}.", name=name))
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

    def delete_current(self):
        """Take the chosen material out of the drawing, when nothing wears it."""
        from . import material_tools
        name = self.current_name()
        if name is None:
            return
        if material_tools.delete_material(self.app, name):
            self.title.setText(tr("{name} deleted. Undo brings it back.", name=name))
        else:
            self.title.setText(tr("{name} is painted on the model: paint those faces with another material first.", name=name))

    def save_current(self):
        """The chosen material to a file of its own (``.igmat``) with its pictures, to use in another drawing."""
        from . import material_tools
        name = self.current_name()
        if name is None:
            return
        self._flush()
        start = str(Path(str(QSettings().value(_SETTINGS + "materials_dir", "") or Path.home()))
                    / (name.replace("/", "-").replace("\\", "-") + material_tools.extension()))
        path, _f = QFileDialog.getSaveFileName(self, tr("Save the material"), start, material_tools.save_filter())
        if not path:
            return
        done = material_tools.save_material(self.app, name, path)
        if done:
            QSettings().setValue(_SETTINGS + "materials_dir", str(Path(done).parent))
            self.hint.setText(tr("Saved {name} in {path}", name=name, path=done))
        else:
            self.hint.setText(tr("{name} is not in the document's materials yet, so it cannot be saved "
                                 "(paint a face with it first).", name=name))

    def load_from_file(self):
        """A saved material into this drawing, under a name of its own (the selection is not painted)."""
        from . import material_tools
        start = str(QSettings().value(_SETTINGS + "materials_dir", "") or Path.home())
        path, _f = QFileDialog.getOpenFileName(self, tr("Load a material"), start, material_tools.open_filter())
        if not path:
            return
        names = material_tools.load_materials(self.app, path)
        if not names:
            self.hint.setText(tr("That file is not a material file."))
            return
        QSettings().setValue(_SETTINGS + "materials_dir", str(Path(path).parent))
        self._made(names[0], 0, tr("Loaded"))

    def follow_selection(self) -> bool:
        """The material of what is selected in the model becomes the chosen one (as the window opens). With
        nothing selected, or nothing with a material of its own, the chosen one stays."""
        try:
            name = M.selection_material(self.app.scene)
        except Exception:  # noqa: BLE001 - an odd selection never stops the window opening
            return False
        if not name:
            return False
        if not self.select(name):
            self.search.clear()
            self.refresh(force=True)
            return self.select(name)
        return True

    def showEvent(self, ev):  # noqa: N802 (Qt)
        super().showEvent(ev)
        if not ev.spontaneous():                  # opened by the program, not brought back by the system
            self.follow_selection()
            QTimer.singleShot(0, self._request_sample)

    def pick_selection(self):
        name = M.selection_material(self.app.scene)
        if not name or not self.select(name):
            self.title.setText("The selection has no named material. Paint it with a material "
                               "(Paint tool) so it can be edited here.")

    # -- the settings ------------------------------------------------------------------
    #: Sliders whose scale is not a straight line: the value goes as the slider's position to this power, so the
    #: low end (where a glow of 1 is already a lot of light) has room to be set finely.
    _CURVES = {"glow": 3.0, "grass_density": 2.0}

    def _set_slider(self, key, value):
        s = self.sliders[key]
        lo, hi = float(s.property("lo")), float(s.property("hi"))
        t = max(0.0, min(1.0, (float(value) - lo) / (hi - lo)))
        t = t ** (1.0 / self._CURVES.get(key, 1.0))
        s.setValue(int(round(t * 100)))
        self._label(key)

    def _get(self, key):
        s = self.sliders[key]
        lo, hi = float(s.property("lo")), float(s.property("hi"))
        t = (s.value() / 100.0) ** self._CURVES.get(key, 1.0)
        return round(lo + (hi - lo) * t, 3)

    def _label(self, key):
        v = self._get(key)
        if key in MV.OPTIONAL:
            own = key in self._extra
            self.values[key].setText(MV.shown_value(key, v) if own else tr("Automatic"))
            self.blocks[key].reset.setVisible(own)
            return
        self.values[key].setText(f"{v * 100:.0f}%" if key in ("transparency", "waves")
                                 else f"{v * 100:.0f} cm" if key == "grass_height"
                                 else f"{v:.0f}/m²" if key == "grass_density"
                                 else (f"{v:.2f}" if v < 10 else f"{v:.1f}") if key == "glow" else f"{v:.2f}")

    def _set_locked(self, on: bool) -> None:
        """A material edited in Blender: every setting of this editor is locked (and says why)."""
        self._locked = bool(on)
        self.lock_box.setVisible(self._locked)
        if self._locked:
            for w in (self.preset, self.kind, self.water_body, self.reset_btn, self.map_size, self.image_adj, self.untile,
                      *self.sliders.values(), *self.maps.values(), *self.map_toggles.values(),
                      *(self.blocks[k].reset for k in MV.OPTIONAL)):
                w.setEnabled(False)
        else:
            for w in (self.preset, self.kind, self.water_body, self.reset_btn, self.map_size, self.image_adj, self.untile,
                      *self.sliders.values(), *self.maps.values(), *self.map_toggles.values(),
                      *(self.blocks[k].reset for k in MV.OPTIONAL)):
                w.setEnabled(True)

    def unlock_current(self) -> None:
        """Back to this editor's settings: the material made in Blender is dropped."""
        name = self.current_name()
        own = dict(self.specs().get(name) or {})
        if name is None or not own.get("blender"):
            return
        own.pop("blender", None)
        self._pending = None
        self._store(name, own)
        self._show(self.list.currentItem())
        self.title.setText(tr("{name} unlocked: the render makes it from these settings again.", name=name))

    def _show(self, item, _prev=None):
        if self._loading:
            return
        self._flush()
        name = item.data(Qt.UserRole) if item is not None else None
        enabled = name is not None
        for w in (self.paint_btn, self.dup_btn, self.save_btn, self.edit_btn):
            w.setEnabled(name is not None)
        unused = name is not None and not M.used_materials(self.app.scene).get(name, 0)
        self.del_btn.setEnabled(bool(unused))
        self.del_btn.setVisible(bool(unused))
        self.del_btn.setToolTip(tr("Take this material out of the drawing.") if unused else
                                tr("Take this material out of the drawing. Only one that nothing is painted with."))
        for w in (self.preset, self.kind, self.water_body, self.reset_btn, self.map_size, self.image_adj, self.untile,
                  *self.sliders.values(), *self.maps.values()):
            w.setEnabled(enabled)
        self.title.setText(name or tr("No material is used in the model."))
        self._ts = (self.texture_set(name) or {}) if enabled else {}
        if not enabled:
            self.cube.clear()
            self.set_label.setVisible(False)
            return
        spec = dict(M.DEFAULT)
        own = self.specs().get(name)
        self._set_locked(bool((own or {}).get("blender")))
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
        self._load_optional(spec)
        self._relief_source = (maps.get("bump") or {}).get("source", "")
        for key, *_r in _FIELDS:
            self._set_slider(key, spec.get(key, M.DEFAULT.get(key, 0.0)))
            self.maps[key].load(maps.get(key), picture)
            if key in self.map_toggles:
                self.map_toggles[key].setChecked(bool(maps.get(key)))
        self.map_toggles["opacity"].setChecked(bool(maps.get("opacity")))
        self._set_slider("ripple_size", spec.get("ripple_size", M.DEFAULT_RIPPLE_SIZE))
        self._set_slider("waves", spec.get("waves", M.DEFAULT_WAVES))
        self.water_body.setCurrentIndex(max(0, self.water_body.findData(spec.get("water_body") or M.DEFAULT_WATER_BODY)))
        self._set_slider("grass_height", spec.get("grass_height", M.DEFAULT_GRASS_HEIGHT))
        self._set_slider("grass_density", spec.get("grass_density") or M.auto_grass_density(
            spec.get("grass_height", M.DEFAULT_GRASS_HEIGHT)))
        self._set_slider("transparency", 1.0 - opacity_mod.material_opacity(self.app.scene, name))
        self.image_adj.load(spec.get("image"), bool(picture))
        self.untile.setChecked(bool(spec.get("untile")))
        if spec.get("image"):
            self.cards["image"][0].set_open(True)
        size = next((m.get("size") for m in maps.values() if m and m.get("size")), 1.0)
        self.map_size.setValue(float(size))
        self._loading = False
        self._enable_glow()
        self._update_cube()
        self._sync_source(name)
        self._request_sample()

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
            self._request_sample()

    def _water_body_chosen(self, _i):
        """A scale of water chosen by hand: its ripples, their height and its waves become the ones that suit
        it (the sliders stay free to be moved after)."""
        key = self.water_body.currentData()
        if not key or self._loading:
            return
        _names, ripple, relief, _wl, _h = M.WATER_BODIES[key]
        self._loading = True
        self._set_slider("ripple_size", ripple)
        self._set_slider("bump", relief)
        self._set_slider("waves", M.DEFAULT_WAVES)
        self._loading = False
        self._changed()

    def _kind_changed(self, *_a):
        """Choosing Water gives it waves to start with (Relief 0 would be a flat mirror),
        and Water or Glass a transparency to start with (opaque would hide the point)."""
        kind = self.kind.currentData()
        prev, self._prev_kind = getattr(self, "_prev_kind", None), kind
        if (not self._loading and prev in M.DEFAULT_TRANSPARENCY and kind not in M.DEFAULT_TRANSPARENCY
                and self._get("transparency") > 0.0):
            # from glass or water to a type that is not see-through (grass, generic, glow): opaque again,
            # in the model too (the transparency is the material's opacity on every face that wears it)
            self._loading = True
            self._set_slider("transparency", 0.0)
            self._loading = False
            self._opacity_timer.start()
        if not self._loading and kind == "water" and self._get("bump") <= 0.0:
            self._loading = True
            self._set_slider("bump", 0.3)
            self._loading = False
        if not self._loading and kind in M.DEFAULT_TRANSPARENCY and self._get("transparency") <= 0.0:
            self._loading = True
            self._set_slider("transparency", M.DEFAULT_TRANSPARENCY[kind])
            self._loading = False
            self._opacity_timer.start()
        was, self._loading = self._loading, True
        for key in MV.OPTIONAL:                      # an automatic one rests where this type has it
            if key not in self._extra and key in self.sliders:
                self._set_slider(key, self._optional_rest(key, kind))
        self._loading = was
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
        if not SHOW_PREVIEW or self.current_name() is None:
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
            kind, normal_by_hand=self.maps["bump"].source.currentData() == "normal",
            rough_map=bool(self.maps["roughness"].source.currentData()
                           or ((ts.get("roughness") or ts.get("arm")) and kind not in ("glass", "water"))),
            set_ao=bool(ts.get("ao") or ts.get("arm")),
            picture=bool(self._picture(name)) if name else False,
            set_relief=bool(ts.get("normal") or (ts.get("displacement") and kind not in ("glass", "water"))),
            relief_source=self.maps["bump"].source.currentData() or "",
            file_maps=any(self.maps[k].source.currentData() in ("file", "normal")
                          for k in self.maps if f"map:{k}" in self._kind_maps(kind)))

    @staticmethod
    def _kind_maps(kind) -> set:
        """The map rows the type has at all (before the finer rules)."""
        return {r for r in M.shown_controls(kind, set_relief=False) if r.startswith("map:")}

    def _enable_glow(self):
        """Hide what does nothing for this material (another type's setting, one a texture set replaces, a
        picture's control without a picture) and, in the Material tab, what has its eye closed. The Expert tab
        shows all that applies, with the eyes."""
        if not hasattr(self, "hint"):
            return                                       # (while the window is being built)
        locked = self._locked and self.current_name() is not None      # edited in Blender: nothing to set here
        shown = self.shown_controls() if self.current_name() is not None and not locked else set()
        expert = self.expert_view()
        self.expert_bar.setVisible(expert and not locked)
        self.reset_btn.setVisible(not locked)
        kind = self.kind.currentData()
        label = self.blocks["bump"].name
        label.setText(tr("Ripple height") if kind == "water" else tr("Amount"))      # water's relief is its waves' height
        words = MV.plain(self.expert_search.text()).split() if expert else []
        applies = {"type", "preset", "source"} if self.current_name() is not None and not locked else set()
        applies |= shown
        for card_key, (card, keys) in self.cards.items():
            any_left = False
            for key in keys:
                block = self.blocks[key]
                text = MV.plain(f"{card.title()} {block.name.text()}")
                on = key in applies and (expert or self.eyes.on(key, kind)) and all(w in text for w in words)
                block.setVisible(on)
                block.show_eye(expert and block.has_eye, self.eyes.on(key, kind))
                any_left = any_left or on
            card.setVisible(any_left)
            card.force_open(bool(words))
        for key in ("type", "preset"):
            block = self.blocks[key]
            on = key in applies and (expert or self.eyes.on(key, kind)) and \
                all(w in MV.plain(block.name.text()) for w in words)
            block.setVisible(on)
            block.show_eye(expert and block.has_eye, self.eyes.on(key, kind))
        for key in ("picture", "colour"):
            self._rows[key].setVisible(key in shown)
        for key, tog in self.map_toggles.items():      # a map's options: only when it applies and is opened
            has = f"map:{key}" in shown and key != "bump"
            row_key = "transparency" if key == "opacity" else key
            tog.setVisible(has and row_key in shown)      # (a hidden setting's button must not float on its own)
            if key != "bump":
                self.maps[key].setVisible(has and (tog.isChecked() or expert))
        self.maps["bump"].setVisible("map:bump" in shown)
        for key in MV.OPTIONAL:
            self._label(key)
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
        self._set_slider("waves", spec.get("waves", M.DEFAULT_WAVES))
        self.water_body.setCurrentIndex(max(0, self.water_body.findData(spec.get("water_body") or M.DEFAULT_WATER_BODY)))
        self._set_slider("grass_height", spec.get("grass_height", M.DEFAULT_GRASS_HEIGHT))
        self._set_slider("grass_density", spec.get("grass_density") or M.auto_grass_density(
            spec.get("grass_height", M.DEFAULT_GRASS_HEIGHT)))
        self._set_slider("transparency", spec.get("transparency", 0.0))
        self._loading = False
        self._opacity_timer.start()            # the model follows the preset's transparency
        self._changed(from_preset=key)

    def _changed(self, *_a, from_preset=None):
        if self._loading or getattr(self, "_locked", False):
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
            spec["water_body"] = self.water_body.currentData()
            spec["waves"] = round(self._get("waves"), 3)
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
            self._extra = {k: float(v) for k, v in M.PRESETS[from_preset][1].items() if k in MV.OPTIONAL}
            self._loading = True
            for key in MV.OPTIONAL:
                self._set_slider(key, self._extra.get(key, self._optional_rest(key, spec["type"])))
            self._loading = False
        else:
            self.preset.setCurrentIndex(0)
        spec.update(self._extra)                # the finer ones only when chosen (a preset's coat and sheen stay)
        if self.untile.isChecked():
            spec["untile"] = True
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
        self._request_sample()

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
        for session in list(self._edits.values()):
            session.stop()
        self._edits.clear()
        super().closeEvent(ev)
