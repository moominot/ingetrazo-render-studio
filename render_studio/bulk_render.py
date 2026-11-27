# SPDX-License-Identifier: GPL-3.0-or-later
"""Render several scenes in a row: the scenes of the drawing (IngeTrazo's saved views) that are ticked,
one after another, each with the Output tab's size, format and projection, into a folder.

Each scene is recalled as a click on its tab does (camera, layers, section, style, shadows, hidden
objects), rendered, and saved as ``<document>-<scene>.<ext>``. When the batch ends, or is cancelled, the
drawing goes back to the view it had. The conversions of names are plain Python (:func:`scene_file_name`).
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from . import labels_above, wheel_guard
from . import output
from .i18n import tr

_SETTINGS = "render_studio/"
DEFAULT_PATTERN = output.DEFAULT_PATTERN


def scene_file_name(pattern: str, document: str, scene: str, ext: str, taken=(), look: str = "") -> str:
    """A file name from ``pattern`` ({document} {scene} {look} {date}), safe for any system and unlike the ones
    in ``taken`` (two scenes with the same name get -2, -3…)."""
    if not pattern or pattern == DEFAULT_PATTERN:
        pattern = output.DEFAULT_SCENES_PATTERN
    name = pattern.replace("{document}", document or "render").replace("{scene}", scene or "scene") \
        .replace("{look}", look or "").replace("{date}", time.strftime("%Y%m%d-%H%M%S"))
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" .-_") or "render"
    base, n = name, 1
    while (name + ext).lower() in {t.lower() for t in taken}:
        n += 1
        name = f"{base}-{n}"
    return name + ext


def scene_choices(scene) -> list:
    """[(view, label)] for the drawing's scenes, in the order of the Scenes tab, with their folder."""
    out = []
    for v in getattr(scene, "saved_views", None) or ():
        out.append((v, f"{v.folder} / {v.name}" if getattr(v, "folder", None) else v.name))
    return out


class BulkRun(QObject):
    """Renders ``views`` in turn through the panel's own Render (so every setting is the panel's) and puts the
    drawing back afterwards. ``progress(i, total, name)``, ``finished(done, failed, cancelled)``."""
    progress = Signal(int, int, str)
    finished = Signal(int, int, bool)

    def __init__(self, panel, views, folder, pattern, parent=None):
        super().__init__(parent)
        self.panel, self.folder, self.pattern = panel, Path(folder), pattern
        self.queue = list(views)
        self.total = len(self.queue)
        self.done = self.failed = 0
        self.cancelled = False
        self.files = []
        self._pending = False
        self._snap = None
        self._ext = output.extension(panel.output_tab.settings()["format"])
        try:
            from . import presets
            self._look = presets.label(panel.preset.currentData(), "en")
        except Exception:  # noqa: BLE001
            self._look = ""
        self._connected = False

    # -- the drawing's state ------------------------------------------------------------------
    def _recall(self, view):
        from core.saved_views import shown_state
        app = self.panel.app
        scene, camera = app.scene, app.viewport.camera
        before = shown_state(scene)
        view.apply(scene, camera)
        if shown_state(scene) != before:
            scene.version += 1
        app.viewport.update()
        return camera

    def start(self) -> bool:
        from core.saved_views import SavedView
        app = self.panel.app
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        self._snap = SavedView.capture("render-studio bulk", app.scene, app.viewport.camera)
        self.panel.finished.connect(self._one_done)
        self._connected = True
        QTimer.singleShot(0, self._next)
        return True

    def cancel(self) -> None:
        self.cancelled = True
        self.queue.clear()
        try:
            self.panel.cancel_render()
        except Exception:  # noqa: BLE001
            pass

    def _doc(self) -> str:
        for attr in ("file_path", "path", "filename"):
            v = getattr(self.panel.app.scene, attr, None)
            if v:
                return Path(str(v)).stem
        p = self.panel.doc_path()
        return Path(p).stem if p else ""

    # -- the loop -------------------------------------------------------------------------------
    def _next(self) -> None:
        if self.cancelled or not self.queue:
            self._end()
            return
        view = self.queue.pop(0)
        i = self.total - len(self.queue)
        self.progress.emit(i, self.total, view.name)
        camera = self._recall(view)
        self.panel._camera_override = camera
        self._pending = True
        name = scene_file_name(self.pattern, self._doc(), view.name, self._ext, taken=[Path(f).name for f in self.files],
                               look=self._look)
        path = str(self.folder / name)
        self._current = path
        if self.panel.render(save_to=path) is False and self._pending:
            self._one_done(None)             # render() was busy with another picture and never says «finished»

    def _one_done(self, result) -> None:
        if not self._pending:
            return
        self._pending = False
        if result is None:
            self.failed += 1
        else:
            self.done += 1
            self.files.append(self._current)
        QTimer.singleShot(0, self._next)

    def _end(self) -> None:
        if self._connected:
            try:
                self.panel.finished.disconnect(self._one_done)
            except (RuntimeError, TypeError):
                pass
            self._connected = False
        self.panel._camera_override = None
        if self._snap is not None:
            try:
                self._recall(self._snap)
            except Exception:  # noqa: BLE001 - the batch is done either way
                pass
            self._snap = None
        self.finished.emit(self.done, self.failed, self.cancelled)


class BulkDialog(QDialog):
    """The progress of a batch of scenes: which one is being rendered, a bar, Cancel. What to render, the folder and the
    names are the Output tab's."""

    def __init__(self, panel, parent=None):
        super().__init__(parent or panel)
        self.panel = panel
        self.run = None
        self.setWindowTitle("Render Studio — scenes")
        self.resize(460, 150)
        lay = QVBoxLayout(self)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        lay.addWidget(self.bar)
        brow = QHBoxLayout()
        brow.addStretch(1)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self._close_or_cancel)
        brow.addWidget(self.close_btn)
        lay.addLayout(brow)
        labels_above.apply(self)
        wheel_guard.watch(self)          # (the wheel scrolls; it changes only a picked field)

    def start(self, views, folder, pattern) -> bool:
        """Render ``views`` into ``folder`` named after ``pattern``."""
        if self.run is not None:
            return False
        self.run = BulkRun(self.panel, views, folder, pattern, self)
        self.run.progress.connect(self._progress)
        self.run.finished.connect(self._finished)
        self.bar.setRange(0, len(views))
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.close_btn.setText(tr("Cancel"))
        self.status.setText(tr("Starting…"))
        self.show()
        self.raise_()
        if not self.run.start():
            self.status.setText(tr("The folder could not be made."))
            self._finished(0, 0, True)
            return False
        return True

    def _progress(self, i: int, total: int, name: str) -> None:
        self.bar.setValue(i - 1)
        self.status.setText(tr("Rendering {i} of {total}: {name}", i=i, total=total, name=name))

    def _finished(self, done: int, failed: int, cancelled: bool) -> None:
        self.bar.setValue(self.bar.maximum() if not cancelled else self.bar.value())
        self.close_btn.setText(tr("Close"))
        folder = self.run.folder if self.run is not None else ""
        self.status.setText((tr("Cancelled. ") if cancelled else "") +
                            tr("{done} scenes rendered, {failed} failed. Saved in {folder}", done=done, failed=failed,
                               folder=folder))
        self.run = None

    def _close_or_cancel(self) -> None:
        if self.run is not None:
            self.run.cancel()
        else:
            self.close()
