# SPDX-License-Identifier: GPL-3.0-or-later
"""The presets of the Main page: thumbnails, a click puts one on; right-click for the rest (update, rename, duplicate,
export, delete). The built-in ones come with Render Studio and are not changed."""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QProcess, QSettings, QSize, QStandardPaths, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QGroupBox, QHBoxLayout, QInputDialog, QListWidget, QSizePolicy,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QToolButton, QVBoxLayout)

from . import icons, preset_files, user_presets, widgets
from .i18n import tr

_log = logging.getLogger(__name__)
_SETTINGS = "render_studio/"
THUMB = (320, 180)                 # kept in the file
ICON = QSize(96, 54)               # shown: two in a 240 px tray
ROWS_SHOWN = 3
HERE = Path(__file__).resolve().parent
_KIND = Qt.UserRole                # "builtin" or "own"
_REF = Qt.UserRole + 1             # the built-in's key, or the file's path


def presets_folder() -> Path:
    """Where the person's presets are kept: the extension's own folder in the program's data."""
    import os
    override = os.environ.get("RENDER_STUDIO_HOME")
    if override:
        return Path(override) / "presets"
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    return (Path(base) if base else Path.home() / ".ingetrazo") / "render_studio" / "presets"


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def thumbnail_of(image: QImage) -> bytes:
    """``image`` cut to the thumbnail's shape (from its middle) and scaled."""
    w, h = THUMB
    scaled = image.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    return png_bytes(scaled.copy((scaled.width() - w) // 2, (scaled.height() - h) // 2, w, h))


class PresetGallery(widgets.Card):
    def __init__(self, panel, folder: Path | None = None):
        super().__init__("Presets", "presets", panel, icon="grp_presets", kind="column")
        self.panel = panel
        self.folder = preset_files.Folder(folder or presets_folder())
        self._jobs: list = []
        self._migrate()
        v = self.body_layout
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setIconSize(ICON)
        self.list.setGridSize(QSize(ICON.width() + 8, ICON.height() + 22))
        self.list.setUniformItemSizes(True)
        self.list.setWordWrap(False)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setMinimumHeight(ROWS_SHOWN * (ICON.height() + 22) + 6)
        self.list.setToolTip("Click a preset to put it on. Right-click for more.")
        self.list.itemClicked.connect(self.apply_item)
        self.list.itemActivated.connect(self.apply_item)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        v.addWidget(self.list)
        row = QHBoxLayout()
        self.save_btn = QPushButton("Save as preset…")
        self.save_btn.setToolTip("Keeps the look as it is now under a name, with a thumbnail, to use it again in any drawing.")
        self.save_btn.clicked.connect(lambda: self.save_current())
        self.save_btn.setIcon(icons.icon("save"))
        self.save_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)      # its words must not widen a narrow tray
        self.menu_btn = QToolButton()
        self.menu_btn.setIcon(icons.icon("more"))
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)
        self.menu_btn.setToolTip("Import a preset, or reset every setting")
        menu = QMenu(self.menu_btn)
        menu.addAction(tr("Import a preset from a file…"), lambda: self.import_file())
        menu.addSeparator()
        self.reset_action = menu.addAction(tr("Reset all settings"), lambda: panel.reset_all())
        self.menu_btn.setMenu(menu)
        row.addWidget(self.save_btn, 1)
        row.addWidget(self.menu_btn)
        v.addLayout(row)
        self.refresh()

    def _migrate(self) -> None:
        """Once: the presets of before, kept in the program's settings, as files."""
        st = QSettings()
        mark = _SETTINGS + "presets_moved_to_files"
        raw = st.value(_SETTINGS + "user_presets", "")
        if not raw or str(st.value(mark, "")).lower() == "true":
            return
        try:
            self.folder.migrate(raw)
            st.setValue(mark, "true")
        except Exception:  # noqa: BLE001 - never in the way of the panel
            _log.exception("old presets not moved")

    # -- the list -----------------------------------------------------------------------
    @staticmethod
    def _placeholder(text: str) -> QPixmap:
        pm = QPixmap(ICON)
        pm.fill(QColor(128, 128, 128, 45))
        p = QPainter(pm)
        p.setPen(QColor(128, 128, 128))
        p.drawText(pm.rect(), Qt.AlignCenter, (text[:1] or "?").upper())
        p.end()
        return pm

    def _icon(self, thumb: bytes | None, name: str) -> QIcon:
        pm = QPixmap()
        if thumb:
            pm.loadFromData(thumb)
        if pm.isNull():
            pm = self._placeholder(name)
        return QIcon(pm.scaled(ICON, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def refresh(self, select: str = "") -> None:
        self.list.clear()
        rows = []
        for key, name, _settings in preset_files.builtins():
            shipped = HERE / "preset_thumbs" / f"{key}.png"
            rows.append(("builtin", key, tr(name), shipped.read_bytes() if shipped.is_file() else None,
                         tr("{name} — comes with Render Studio", name=tr(name))))
        for path, name, thumb in self.folder.entries():
            rows.append(("own", str(path), name, thumb, name))
        for kind, ref, name, thumb, tip in rows:
            it = QListWidgetItem(self._icon(thumb, name), name)
            it.setData(_KIND, kind)
            it.setData(_REF, ref)
            it.setToolTip(tip)
            self.list.addItem(it)
            if select and ref == select:
                self.list.setCurrentItem(it)

    def item(self, name: str):
        return next((self.list.item(i) for i in range(self.list.count()) if self.list.item(i).text() == name), None)

    def contents(self, it):
        """``(name, settings, thumbnail bytes or None)`` of a listed preset, or None."""
        if it.data(_KIND) == "builtin":
            for key, name, settings in preset_files.builtins():
                if key == it.data(_REF):
                    shipped = HERE / "preset_thumbs" / f"{key}.png"
                    return tr(name), settings, shipped.read_bytes() if shipped.is_file() else None
            return None
        return self.folder.load(Path(it.data(_REF)))

    # -- what is done with them ------------------------------------------------------------
    def apply_item(self, it) -> None:
        got = self.contents(it) if it is not None else None
        if got is None:
            self.panel._set_status(tr("That file is not a Render Studio preset."))
            return
        self.panel.apply_preset(got[1])
        self.panel._set_status(tr("Preset «{name}» applied.", name=got[0]))

    def save_current(self) -> None:
        """Ask for a name and keep the look as it is now (asks before replacing one)."""
        current = self.list.currentItem()
        default = current.text() if current is not None and current.data(_KIND) == "own" else ""
        name, ok = QInputDialog.getText(self.window(), tr("Save as preset…"), tr("Name of the preset"), text=default)
        name = user_presets.clean_name(name)
        if not ok or not name:
            return
        if self.folder.find(name) is not None and QMessageBox.question(
                self.window(), tr("Save as preset…"), tr("A preset called «{name}» exists. Replace it?", name=name)) != QMessageBox.Yes:
            return
        self.keep(name)

    def keep(self, name: str) -> Path | None:
        """The look as it is now, as the preset ``name``, with a thumbnail: the preview's picture when it shows one, else a
        small render made on the side."""
        picture = self.panel.preview_picture()
        thumb = thumbnail_of(picture) if picture is not None and not picture.isNull() else None
        try:
            existing = self.folder.find(name)
            path = existing if existing is not None else self.folder.free_path(name)
            preset_files.write(path, name, self.panel.settings_dict(), thumb)
        except (OSError, ValueError) as exc:
            self.panel._set_status(tr("Could not write the file: {error}", error=exc))
            return None
        self.refresh(str(path))
        self.panel._set_status(tr("Preset «{name}» saved.", name=name))
        if thumb is None:
            self.render_thumbnail(path)
        return path

    def render_thumbnail(self, path: Path) -> None:
        """A small draft of the picture as it is now, in a Blender of its own; the preset takes it when it is ready."""
        try:
            found = self.panel.blender_or_none()
            if found is None:
                return
            work = Path(tempfile.mkdtemp(prefix="rs_thumb_"))
            job, script = self.panel.live_job(work, *THUMB)
            data = json.loads(job.read_text(encoding="utf-8"))
            data.pop("serve", None)
            out = work / "thumb.png"
            data["output"] = str(out)
            job.write_text(json.dumps(data), encoding="utf-8")
            process = QProcess(self)
            process.setProcessChannelMode(QProcess.MergedChannels)
            process.readyReadStandardOutput.connect(lambda: process.readAllStandardOutput())

            def done(*_a):
                if process in self._jobs:
                    self._jobs.remove(process)
                image = QImage(str(out))
                if not image.isNull() and Path(path).is_file():
                    self.folder.set_thumbnail(path, thumbnail_of(image))
                    self.refresh(str(path))
                import shutil
                shutil.rmtree(work, ignore_errors=True)

            process.finished.connect(done)
            self._jobs.append(process)
            command = list(found.command) + ["-b", "--factory-startup", "--python", str(script), "--", str(job)]
            process.start(command[0], command[1:])
        except Exception:  # noqa: BLE001 - a preset without a picture is still a preset
            _log.exception("could not make the thumbnail")

    def update_item(self, it) -> None:
        if QMessageBox.question(self.window(), tr("Update with the current look"),
                                tr("Replace the preset «{name}» with the look as it is now?", name=it.text())) == QMessageBox.Yes:
            self.keep(it.text())

    def rename_item(self, it) -> None:
        name, ok = QInputDialog.getText(self.window(), tr("Rename…"), tr("Name of the preset"), text=it.text())
        name = user_presets.clean_name(name)
        if not ok or not name or name == it.text():
            return
        if self.folder.find(name) is not None and name.lower() != it.text().lower():
            self.panel._set_status(tr("A preset called «{name}» exists already.", name=name))
            return
        self.refresh(str(self.folder.rename(Path(it.data(_REF)), name)))

    def duplicate_item(self, it) -> None:
        got = self.contents(it)
        if got is not None:
            self.refresh(str(self.folder.duplicate(got[0], got[1], got[2])))

    def delete_item(self, it) -> None:
        if QMessageBox.question(self.window(), tr("Delete this preset"),
                                tr("Delete the preset «{name}»?", name=it.text())) == QMessageBox.Yes:
            self.folder.delete(Path(it.data(_REF)))
            self.refresh()

    def export_item(self, it, path: str = "") -> None:
        got = self.contents(it)
        if got is None:
            return
        if not path:
            start = str(Path(str(QSettings().value(_SETTINGS + "preset_dir", "") or "")) / (got[0] + preset_files.SUFFIX))
            path, _f = QFileDialog.getSaveFileName(self.window(), tr("Export…"), start, "Render Studio preset (*.rspreset)")
        if not path:
            return
        if not path.lower().endswith(preset_files.SUFFIX):
            path += preset_files.SUFFIX
        try:
            preset_files.write(Path(path), got[0], got[1], got[2])
        except (OSError, ValueError) as exc:
            self.panel._set_status(tr("Could not write the file: {error}", error=exc))
            return
        QSettings().setValue(_SETTINGS + "preset_dir", str(Path(path).parent))
        self.panel._set_status(tr("Preset exported to {path}", path=path))

    def import_file(self, path: str = "") -> None:
        if not path:
            start = str(QSettings().value(_SETTINGS + "preset_dir", "") or "")
            path, _f = QFileDialog.getOpenFileName(self.window(), tr("Import a preset from a file…"), start,
                                                   "Render Studio preset (*.rspreset *.json)")
        if not path:
            return
        made = self.folder.import_file(Path(path))
        if made is None:
            self.panel._set_status(tr("That file is not a Render Studio preset."))
            return
        self.refresh(str(made))
        QSettings().setValue(_SETTINGS + "preset_dir", str(Path(path).parent))
        self.panel._set_status(tr("Preset imported. Click it to use it."))

    def menu_for(self, it) -> QMenu:
        menu = QMenu(self)
        menu.addAction(tr("Apply"), lambda: self.apply_item(it))
        own = it.data(_KIND) == "own"
        if own:
            menu.addAction(tr("Update with the current look"), lambda: self.update_item(it))
            menu.addAction(tr("Rename…"), lambda: self.rename_item(it))
        menu.addAction(tr("Duplicate"), lambda: self.duplicate_item(it))
        menu.addAction(tr("Export…"), lambda: self.export_item(it))
        if own:
            menu.addSeparator()
            menu.addAction(tr("Delete this preset"), lambda: self.delete_item(it))
        return menu

    def _context_menu(self, pos) -> None:
        it = self.list.itemAt(pos)
        if it is not None:
            self.menu_for(it).exec(self.list.viewport().mapToGlobal(pos))
