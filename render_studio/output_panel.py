# SPDX-License-Identifier: GPL-3.0-or-later
"""The Output tab of Render Studio's panel: the size of the final picture and its file.

* **Size**: the 3D view's shape (from a width), a ready size (screens, social media,
  paper at a dpi) or a size of your own, with the proportions locked or not. The
  preview frames the same picture.
* **File**: PNG, JPEG, PNG or TIFF at 16 bits, OpenEXR in linear light; the sky can be
  left transparent (to put another one behind it). The preview window's retouching is
  saved in PNG and JPEG; the deeper files are saved as Blender wrote them.
* **Save every render** to a folder, named after the document, the look and the time.

The size and the file are kept in the document (``settings["output"]``, see
:mod:`output`); the folder is this computer's.
"""
from __future__ import annotations

from .i18n import tr, translate_on_show  # noqa: F401

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QRadioButton, QSizePolicy, QSpinBox,
                               QToolButton, QVBoxLayout, QWidget)

from . import output as O

_SETTINGS = "render_studio/"


def _bold(text: str) -> QLabel:
    lab = QLabel(text)
    f = lab.font()
    f.setBold(True)
    lab.setFont(f)
    return lab


def _shrinkable(combo: QComboBox) -> QComboBox:
    """A list box that may be narrower than its longest entry (the tray is narrow;
    the open list still shows the entries whole)."""
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(8)
    return combo


class OutputTab(QWidget):
    changed = Signal()                  # the size or the file changed (save, preview)

    def __init__(self, panel, width: int = 1920, parent=None):
        super().__init__(parent)
        self.panel = panel
        self._filling = False
        self._ratio = None              # width / height while «Keep proportions» is on
        self._kept_height = O.DEFAULT["height"]   # the height of its own (the view's shape shows another)
        st = QSettings()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_bold("Projection"))
        formp = QFormLayout()
        formp.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self._proj_form = formp
        self.projection = QComboBox()
        self.projection.addItem(tr("Normal view"), "normal")
        self.projection.addItem(tr("Flat panorama"), "flat")
        self.projection.addItem(tr("360° panorama"), "360")
        self.projection.setToolTip("Normal: the 3D view's camera. Flat panorama: a wide picture where vertical lines stay "
                                   "vertical (a stitched photo). 360°: all round, for a VR or panorama viewer. Panoramas "
                                   "are rendered from the camera's place, with Cycles.")
        self.projection.currentIndexChanged.connect(self._projection_chosen)
        _shrinkable(self.projection)
        formp.addRow("Projection", self.projection)
        self.angle = QSpinBox()
        self.angle.setRange(30, 360)
        self.angle.setSingleStep(10)
        self.angle.setSuffix("°")
        self.angle.setValue(O.DEFAULT["angle"])
        self.angle.setToolTip("How much of the horizon the flat panorama covers; its height follows the picture's shape.")
        self.angle.valueChanged.connect(self._emit)
        formp.addRow("Angle", self.angle)
        self.proj_note = QLabel("")
        self.proj_note.setWordWrap(True)
        self.proj_note.setStyleSheet("color: gray; font-size: 11px")
        formp.addRow(self.proj_note)
        lay.addLayout(formp)

        lay.addWidget(_bold("Size"))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.size = QComboBox()
        for key, label, _w, _h in O.SIZES:
            self.size.addItem(tr(label), key)
        self.size.setToolTip("The picture's size. «Same shape as the 3D view»: the width below, the height "
                             "follows the view.")
        self.size.currentIndexChanged.connect(self._size_chosen)
        _shrinkable(self.size)
        form.addRow("Size", self.size)
        self.width = QSpinBox()
        self.width.setRange(320, O.MAX_PX)
        self.width.setSingleStep(160)
        self.width.setSuffix(" px")
        self.width.setValue(int(width))
        self.width.setToolTip("The picture's width in pixels")
        self.height = QSpinBox()
        self.height.setRange(O.MIN_PX, O.MAX_PX)
        self.height.setSingleStep(90)
        self.height.setSuffix(" px")
        self.height.setValue(O.DEFAULT["height"])
        self.height.setToolTip("The picture's height in pixels")
        for w in (self.width, self.height):
            w.setMinimumWidth(78)
            w.setSizePolicy(QSizePolicy.Ignored, w.sizePolicy().verticalPolicy())
        self.width.valueChanged.connect(self._width_edited)
        self.height.valueChanged.connect(self._height_edited)
        wrow = QHBoxLayout()
        wrow.setContentsMargins(0, 0, 0, 0)
        wrow.addWidget(self.width)
        wrow.addWidget(QLabel("×"))
        wrow.addWidget(self.height)
        self.swap = QToolButton()
        self.swap.setText("⇄")
        self.swap.setToolTip("Turn it: landscape ↔ portrait")
        self.swap.clicked.connect(self._swap)
        wrow.addWidget(self.swap)
        wbox = QWidget()
        wbox.setLayout(wrow)
        form.addRow("Width × height", wbox)
        self.keep = QCheckBox("Keep proportions")
        self.keep.setToolTip("Changing the width changes the height with it, and the other way round")
        self.keep.toggled.connect(self._keep_toggled)
        form.addRow("", self.keep)
        self.dpi = QSpinBox()
        self.dpi.setRange(30, 1200)
        self.dpi.setSingleStep(50)
        self.dpi.setValue(O.DEFAULT["dpi"])
        self.dpi.setSuffix(" dpi")
        self.dpi.setToolTip("Dots per inch: the paper sizes are worked out at it, and it says how big a print is")
        self.dpi.valueChanged.connect(self._dpi_edited)
        form.addRow("Print resolution", self.dpi)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color: gray; font-size: 11px")
        form.addRow(self.summary)
        lay.addLayout(form)


        lay.addWidget(_bold("File"))
        form2 = QFormLayout()
        form2.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self._file_form = form2
        self.format = QComboBox()
        for key in O.FORMAT_ORDER:
            self.format.addItem(tr(O.FORMATS[key][0]), key)
        self.format.setToolTip("PNG and JPEG keep the preview window's retouching. 16-bit PNG and TIFF and "
                               "OpenEXR keep more of the light for editing elsewhere; they are saved as "
                               "Blender wrote them.")
        self.format.currentIndexChanged.connect(self._format_chosen)
        _shrinkable(self.format)
        form2.addRow("Format", self.format)
        self.jpeg_quality = QSpinBox()
        self.jpeg_quality.setRange(10, 100)
        self.jpeg_quality.setValue(O.DEFAULT["jpeg_quality"])
        self.jpeg_quality.setSuffix(" %")
        self.jpeg_quality.valueChanged.connect(self._emit)
        form2.addRow("JPEG quality", self.jpeg_quality)
        self.transparent = QCheckBox("Transparent sky")
        self.transparent.setToolTip("The sky is left transparent (the ground and the model stay): to put another "
                                    "sky behind it. The exposure is measured with the sky, as usual.")
        self.transparent.toggled.connect(self._emit)
        form2.addRow("", self.transparent)
        self.file_note = QLabel("")
        self.file_note.setWordWrap(True)
        self.file_note.setStyleSheet("color: gray; font-size: 11px")
        form2.addRow(self.file_note)
        lay.addLayout(form2)

        lay.addWidget(_bold("What to render"))
        mrow = QVBoxLayout()
        mrow.setSpacing(2)
        self.mode_view = QRadioButton("Current view")
        self.mode_scenes = QRadioButton("Scenes")
        self.mode_view.setToolTip("Render the view of the 3D window (or the one the preview keeps).")
        self.mode_scenes.setToolTip("Render the scenes you tick below, one after another.")
        mode = str(st.value(_SETTINGS + "output_mode", "view"))
        (self.mode_scenes if mode == "scenes" else self.mode_view).setChecked(True)
        self.mode_scenes.toggled.connect(self._mode_changed)
        for r in (self.mode_view, self.mode_scenes):
            r.setSizePolicy(QSizePolicy.Ignored, r.sizePolicy().verticalPolicy())      # (the tray is narrow)
        mrow.addWidget(self.mode_view)
        mrow.addWidget(self.mode_scenes)
        lay.addLayout(mrow)
        self.scenes_box = QWidget()
        sb = QVBoxLayout(self.scenes_box)
        sb.setContentsMargins(0, 0, 0, 0)
        self.scene_list = QListWidget()
        self.scene_list.setMaximumHeight(140)
        self.scene_list.setToolTip("The scenes of the drawing (IngeTrazo's saved views): tick the ones to render.")
        sb.addWidget(self.scene_list)
        srow = QHBoxLayout()
        self.scenes_all = QPushButton("All")
        self.scenes_none = QPushButton("None")
        self.scenes_all.clicked.connect(lambda: self._tick_scenes(True))
        self.scenes_none.clicked.connect(lambda: self._tick_scenes(False))
        srow.addWidget(self.scenes_all)
        srow.addWidget(self.scenes_none)
        srow.addStretch(1)
        sb.addLayout(srow)
        lay.addWidget(self.scenes_box)
        self._ticked = set()
        self._scenes_stale = True

        lay.addWidget(_bold("Save"))
        form3 = QFormLayout()
        form3.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.autosave = QCheckBox("Save each render")
        self.autosave.setToolTip("The view you render is also saved in the folder, named as below. The scenes are always "
                                 "saved there.")
        self.autosave.setChecked(str(st.value(_SETTINGS + "autosave", "false")).lower() in ("true", "1"))
        self.autosave.toggled.connect(self._remember_autosave)
        frow = QHBoxLayout()
        frow.setContentsMargins(0, 0, 0, 0)
        self.folder = QLineEdit(str(st.value(_SETTINGS + "autosave_dir", "") or ""))
        self.folder.setPlaceholderText("choose a folder")
        self.folder.editingFinished.connect(self._remember_autosave)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        frow.addWidget(self.folder, 1)
        frow.addWidget(browse)
        fbox = QWidget()
        fbox.setLayout(frow)
        form3.addRow("Folder", fbox)
        stored = str(st.value(_SETTINGS + "autosave_name", O.DEFAULT_PATTERN) or "")
        if stored == "{document}-{look}-{date}":               # the name this tab started with: the new one
            stored = O.DEFAULT_PATTERN
        self.pattern = QLineEdit(stored or O.DEFAULT_PATTERN)
        self.pattern.setToolTip("{document}: the document's name, {scene}: the scene's name («view» for the current "
                                "view), {look}: the look, {date}: the date and time")
        self.pattern.editingFinished.connect(self._remember_autosave)
        form3.addRow("Name", self.pattern)
        form3.addRow(self.autosave)
        lay.addLayout(form3)
        self._mode_changed()
        lay.addStretch(1)
        self._layout()

    # ---- the values ---------------------------------------------------------------------
    def settings(self) -> dict:
        """The document's ``output`` block."""
        h = self._kept_height if self.size.currentData() == "view" else self.height.value()
        return O.clean({"size": self.size.currentData(), "height": h, "dpi": self.dpi.value(),
                        "format": self.format.currentData(), "jpeg_quality": self.jpeg_quality.value(),
                        "transparent": self.transparent.isChecked(),
                        "projection": self.projection.currentData(), "angle": self.angle.value()})

    def apply(self, out: dict, width: int | None = None) -> None:
        """Put ``out`` (and the width) in the controls without saving them again."""
        out = O.clean(out)
        self._filling = True
        widgets = (self.size, self.width, self.height, self.dpi, self.format, self.jpeg_quality, self.transparent,
                   self.projection, self.angle)
        for w in widgets:
            w.blockSignals(True)
        try:
            self.size.setCurrentIndex(max(0, self.size.findData(out["size"])))
            if width is not None:
                self.width.setValue(int(width))
            self.height.setValue(out["height"])
            self._kept_height = out["height"]
            self.dpi.setValue(out["dpi"])
            self.format.setCurrentIndex(max(0, self.format.findData(out["format"])))
            self.jpeg_quality.setValue(out["jpeg_quality"])
            self.transparent.setChecked(out["transparent"])
            self.projection.setCurrentIndex(max(0, self.projection.findData(out["projection"])))
            self.angle.setValue(out["angle"])
            self._fill_preset()
        finally:
            for w in widgets:
                w.blockSignals(False)
            self._filling = False
        self._layout()

    def view_aspect(self) -> float:
        vp = getattr(getattr(self.panel, "app", None), "viewport", None)
        try:
            return max(0.2, vp.width() / max(1, vp.height()))
        except Exception:  # noqa: BLE001
            return 16 / 9

    def frame(self) -> tuple:
        """(width, height) of the final picture."""
        return O.frame(self.width.value(), self.settings(), self.view_aspect())

    def aspect(self) -> float:
        w, h = self.frame()
        return w / max(1, h)

    def autosave_target(self):
        """(folder, name pattern) when every render is to be saved, else None."""
        folder = self.folder.text().strip()
        if not self.autosave.isChecked() or not folder:
            return None
        return Path(folder), self.pattern.text().strip() or O.DEFAULT_PATTERN

    # ---- editing ---------------------------------------------------------------------------
    def _fill_preset(self) -> None:
        """A ready size puts its pixels in the boxes."""
        key = self.size.currentData()
        wh = O.preset_size(key, self.dpi.value())
        if wh is not None:
            for w in (self.width, self.height):
                w.blockSignals(True)
            self.width.setValue(wh[0])
            self.height.setValue(wh[1])
            self._kept_height = wh[1]
            for w in (self.width, self.height):
                w.blockSignals(False)

    def _size_chosen(self, _i) -> None:
        if self._filling:
            return
        self._fill_preset()
        if self.size.currentData() == "custom":
            self.height.blockSignals(True)
            self.height.setValue(self._kept_height)
            self.height.blockSignals(False)
        self._ratio = None
        self._layout()
        self._emit()

    def _to_custom(self) -> None:
        """Typing a size of your own leaves a ready size."""
        if self.size.currentData() not in ("view", "custom"):
            self.size.blockSignals(True)
            self.size.setCurrentIndex(self.size.findData("custom"))
            self.size.blockSignals(False)

    def _width_edited(self, v) -> None:
        if self._filling:
            return
        if self.size.currentData() != "view":
            self._to_custom()
            if self.keep.isChecked() and self._ratio:
                self.height.blockSignals(True)
                self.height.setValue(max(O.MIN_PX, round(v / self._ratio)))
                self.height.blockSignals(False)
            self._kept_height = self.height.value()
        self._layout()
        self._emit()

    def _height_edited(self, v) -> None:
        if self._filling:
            return
        self._kept_height = v
        self._to_custom()
        if self.keep.isChecked() and self._ratio:
            self.width.blockSignals(True)
            self.width.setValue(max(self.width.minimum(), round(v * self._ratio)))
            self.width.blockSignals(False)
        self._layout()
        self._emit()

    def _keep_toggled(self, on) -> None:
        self._ratio = (self.width.value() / max(1, self.height.value())) if on else None

    def _swap(self) -> None:
        w, h = self.frame()
        self._filling = True
        self.size.setCurrentIndex(self.size.findData("custom"))
        self.width.setValue(h)
        self.height.setValue(w)
        self._kept_height = w
        self._filling = False
        if self.keep.isChecked():
            self._ratio = h / max(1, w)
        self._layout()
        self._emit()

    def _dpi_edited(self, _v) -> None:
        if self._filling:
            return
        if O.is_paper(self.size.currentData()):
            self._fill_preset()
        self._layout()
        self._emit()

    def _projection_chosen(self, _i) -> None:
        """A flat panorama starts from the 3:1 size; a 360° one needs the 2:1 its picture has."""
        if self._filling:
            return
        if self.projection.currentData() == "flat" and self.size.currentData() in ("view", "custom") and \
                self.width.value() < 3000:
            self.size.setCurrentIndex(self.size.findData("pano"))
            self._fill_preset()
        self._layout()
        self._emit()

    def _format_chosen(self, _i) -> None:
        self._layout()
        self._emit()

    def _emit(self, *_a) -> None:
        if not self._filling:
            self._layout()
            self.changed.emit()

    def _layout(self) -> None:
        key = self.size.currentData()
        view = key == "view"
        proj = self.projection.currentData()
        self._proj_form.setRowVisible(self.angle, proj == "flat")
        self.proj_note.setText({"normal": "", "flat": tr("A cylindrical panorama from the camera's place; rendered with Cycles."),
                                "360": tr("All round, 2:1, from the camera's place; rendered with Cycles. The height is half the width.")}[proj])
        self._proj_form.setRowVisible(self.proj_note, bool(proj != "normal"))
        self.height.setEnabled(not view and proj != "360")
        self.swap.setEnabled(True)
        self.keep.setVisible(key == "custom")
        w, h = self.frame()
        if (view or self.projection.currentData() == "360") and self.height.value() != h:
            # The height the 3D view gives, shown in its (disabled) box.
            self.height.blockSignals(True)
            self.height.setValue(h)
            self.height.blockSignals(False)
        self.summary.setText(O.describe(w, h, self.dpi.value()) +
                             ("\n" + tr("The height follows the 3D view's shape.") if view else
                              "\n" + tr("The preview shows this frame; the view's height is kept, its sides change.")))
        fmt = self.format.currentData()
        self.jpeg_quality.setVisible(fmt == "jpeg")
        lab = self._file_form.labelForField(self.jpeg_quality)
        if lab is not None:
            lab.setVisible(fmt == "jpeg")
        alpha = O.FORMATS[fmt][3]
        self.transparent.setEnabled(alpha)
        if not alpha:
            self.transparent.setChecked(False)
        self.file_note.setText(
            tr("The preview window's retouching is saved with it.") if O.retouchable(fmt) else
            tr("Saved as Blender wrote it (the retouching sliders only change the picture on screen). ")
            + (tr("Linear light, for compositing: it looks dark and flat until it is toned.") if fmt == "exr" else
               tr("16 bits per channel: more room to edit it elsewhere.")))

    # ---- the scenes -------------------------------------------------------------------------------
    def scenes_mode(self) -> bool:
        return self.mode_scenes.isChecked()

    def refresh_scenes(self) -> None:
        """The drawing's scenes in the list (the ticks stay)."""
        if self.scene_list.count():
            self._ticked = {self.scene_list.item(i).text() for i in range(self.scene_list.count())
                            if self.scene_list.item(i).checkState() == Qt.Checked}
        first = not getattr(self, "_scenes_seen", False)
        self.scene_list.clear()
        self._views = []
        try:
            from .bulk_render import scene_choices
            choices = scene_choices(self.panel.app.scene)
        except Exception:  # noqa: BLE001 - no scenes in this IngeTrazo
            choices = []
        for view, label in choices:
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if (first or label in self._ticked) else Qt.Unchecked)
            self.scene_list.addItem(item)
            self._views.append(view)
        self._scenes_seen = True
        self._scenes_stale = False

    def chosen_views(self) -> list:
        """The scenes ticked, in the order of the list."""
        if self._scenes_stale:
            self.refresh_scenes()
        return [self._views[i] for i in range(self.scene_list.count()) if self.scene_list.item(i).checkState() == Qt.Checked]

    def _tick_scenes(self, on: bool) -> None:
        for i in range(self.scene_list.count()):
            self.scene_list.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def _mode_changed(self, *_a) -> None:
        scenes = self.mode_scenes.isChecked()
        self.scenes_box.setVisible(scenes)
        self.autosave.setEnabled(not scenes)
        QSettings().setValue(_SETTINGS + "output_mode", "scenes" if scenes else "view")
        if scenes:
            self.refresh_scenes()

    def document_changed(self) -> None:
        """The scenes may have changed: the list is made again when it is next in sight."""
        self._scenes_stale = True
        if self.isVisible() and self.mode_scenes.isChecked():
            self.refresh_scenes()

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if self._scenes_stale and self.mode_scenes.isChecked():
            self.refresh_scenes()

    def _remember_autosave(self, *_a) -> None:
        st = QSettings()
        st.setValue(_SETTINGS + "autosave", self.autosave.isChecked())
        st.setValue(_SETTINGS + "autosave_dir", self.folder.text().strip())
        st.setValue(_SETTINGS + "autosave_name", self.pattern.text().strip())

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("Save every render in"), self.folder.text() or str(Path.home()))
        if path:
            self.folder.setText(path)
            self.autosave.setChecked(True)
            self._remember_autosave()

    def _help(self) -> None:
        from . import ui_help
        ui_help.show(self, "output")
