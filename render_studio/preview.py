# SPDX-License-Identifier: GPL-3.0-or-later
"""The preview window: where Render Studio shows its pictures.

It is the one place to look at the scene and to make the final picture, in three states:

* **preview** (the live view): a quick draft that follows the 3D view and the model, that you can
  zoom and move. Buttons: **Render** (makes the final picture, then shows the retouch tools) and
  **Render and save…** (makes it and saves it straight away, with no retouching).
* **rendering**: the progress, and Cancel.
* **final**: the finished picture with the retouch sliders (instant, no new render), **Save image…**
  and **Back to preview**.

Alone (``panel`` None, as the tests use it) it is just the final-picture viewer.
"""
from __future__ import annotations

from .i18n import tr, translate_on_show  # noqa: F401

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QToolButton, QVBoxLayout, QWidget)

from . import post
from .widgets import SliderRow, ZoomView, slider, value, set_value

_SETTINGS = "render_studio/"

NOTES = {
    "preview": "Live preview: a quick draft that follows your 3D view. Render makes the final picture; "
               "Render and save… also saves it, with no retouching.",
    "rendering": "Rendering the final picture…",
    "final": "Final picture. The sliders retouch it instantly (the scene is not rendered again); "
             "Save image… saves what you see.",
}


class ImageWindow(QWidget):
    """The picture, with zoom and pan; see the module's docstring for the three states."""

    def __init__(self, parent=None, panel=None):
        super().__init__(parent, Qt.Window)
        self.panel = panel
        self.setWindowTitle("Render Studio")
        self.resize(1100, 780)
        self.path = None
        self.original = None            # H×W×3 uint8 of the final picture
        self.shown = None               # …as retouched
        self.alpha = None               # H×W uint8 when the sky was left transparent
        self.rendered_file = None       # a 16-bit or EXR file Blender wrote, saved as it is
        self.rendered_label = ""
        self.mode = "final"
        self._saved_to = None
        lay = QVBoxLayout(self)

        # -- top: what this is, zoom, help
        top = QHBoxLayout()
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray")
        top.addWidget(self.note, 1)
        self.fit_btn = QToolButton()
        self.fit_btn.setText("Fit")
        self.fit_btn.setToolTip("The whole picture in the window (key 0, or double click)")
        self.actual_btn = QToolButton()
        self.actual_btn.setText("100 %")
        self.actual_btn.setToolTip("One picture pixel per screen pixel (key 1, or double click)")
        self.zoom_label = QLabel("")
        self.zoom_label.setMinimumWidth(44)
        self.zoom_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        help_btn = QToolButton()
        help_btn.setText("?")
        help_btn.setToolTip("How the preview, Render and the retouch sliders work")
        help_btn.clicked.connect(self._help)
        for w in (self.fit_btn, self.actual_btn, self.zoom_label, help_btn):
            top.addWidget(w)
        lay.addLayout(top)

        # -- the picture
        self.view = ZoomView()
        self.view.zoomed.connect(lambda p: self.zoom_label.setText(f"{p:.0f} %"))
        self.fit_btn.clicked.connect(self.view.fit)
        self.actual_btn.clicked.connect(lambda: self.view.actual_size())
        lay.addWidget(self.view, 1)

        # -- progress and what is happening
        prow = QHBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(lambda: self.panel and self.panel.cancel_render())
        prow.addWidget(self.status, 1)
        prow.addWidget(self.bar)
        prow.addWidget(self.cancel_btn)
        lay.addLayout(prow)

        # -- preview: the two switches of the live view, and Render
        self.bar_preview = QWidget()
        pl = QHBoxLayout(self.bar_preview)
        pl.setContentsMargins(0, 0, 0, 0)
        st = QSettings()
        self.follow_camera_box = QCheckBox("Follow the camera")
        self.follow_camera_box.setToolTip("On: frames come while you move the 3D view, then a cleaner image when "
                                          "you stop. Off: the preview keeps its camera.")
        self.follow_changes_box = QCheckBox("Follow changes")
        self.follow_changes_box.setToolTip("On: edits of the model, its textures and the materials show in the "
                                           "preview. Off: it keeps the model and materials it has (the look and "
                                           "sliders still apply).")
        for box, key in ((self.follow_camera_box, "live_follow_camera"),
                         (self.follow_changes_box, "live_follow_changes")):
            box.setChecked(str(st.value(_SETTINGS + key, "true")).lower() in ("true", "1"))
            box.toggled.connect(lambda on, k=key: self.panel and self.panel._follow_toggled(k, on))
            pl.addWidget(box)
        self.update_btn = QPushButton("Update")
        self.update_btn.setToolTip("With Follow changes off: shows the model and materials as they are now "
                                   "(the preview keeps the ones it had until then).")
        self.update_btn.setEnabled(not self.follow_changes_box.isChecked())
        self.update_btn.clicked.connect(lambda: self.panel and self.panel.update_preview())
        self.follow_changes_box.toggled.connect(lambda on: self.update_btn.setEnabled(not on))
        pl.addWidget(self.update_btn)
        pl.addStretch(1)
        self.summary = QLabel("")
        self.summary.setStyleSheet("color: gray")
        self.summary.setToolTip("The engine, quality and width set in the panel: Render uses them "
                                "(the preview is always a quick draft).")
        pl.addWidget(self.summary)
        self.expert_btn = QPushButton("Open in Blender…")
        self.expert_btn.setToolTip("Expert mode: opens this scene, as Render would make it, in a Blender with its own "
                                   "window to work in it. Nothing is rendered; the file is saved first.")
        self.expert_btn.clicked.connect(lambda: self.panel and self.panel.open_in_blender())
        pl.addWidget(self.expert_btn)
        self.render_save_btn = QPushButton("Render and save…")
        self.render_save_btn.setToolTip("Asks where to save, makes the final picture and saves it straight away, "
                                        "without retouching.")
        self.render_save_btn.clicked.connect(lambda: self.panel and self.panel.render_and_save())
        self.render_btn = QPushButton("Render")
        self.render_btn.setDefault(True)
        self.render_btn.setToolTip("Makes the final picture with the panel's engine, quality and width, then "
                                   "shows the retouch tools and Save image….")
        self.render_btn.clicked.connect(lambda: self.panel and self.panel.render())
        pl.addWidget(self.render_save_btn)
        pl.addWidget(self.render_btn)
        lay.addWidget(self.bar_preview)

        # -- final: the retouch sliders and Save
        self.bar_final = QWidget()
        fl = QVBoxLayout(self.bar_final)
        fl.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox("Retouch the finished picture: instant, nothing is rendered again")
        form = QVBoxLayout(box)
        self.adj, self.adj_rows = {}, {}
        for key, label, lo, hi, fmt, hint in post.ADJUSTMENTS:
            s = slider(lo, hi, post.NEUTRAL[key])
            s.valueChanged.connect(self._refresh)
            row = SliderRow(s, fmt, hint)
            self.adj[key], self.adj_rows[key] = s, row
            line = QHBoxLayout()
            name = QLabel(label)
            name.setMinimumWidth(96)
            name.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            line.addWidget(name)
            line.addWidget(row, 1)
            form.addLayout(line)
        fl.addWidget(box)
        frow = QHBoxLayout()
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Puts every retouch slider back to neutral (the picture as rendered)")
        self.reset_btn.clicked.connect(self._reset)
        self.back_btn = QPushButton("Back to preview")
        self.back_btn.setToolTip("Closes the final picture and returns to the live preview, to change the scene "
                                 "and render again")
        self.back_btn.clicked.connect(lambda: self.panel and self.panel.back_to_preview())
        self.save_btn = QPushButton("Save image…")
        self.save_btn.setToolTip("Saves the picture as you see it (with the retouching) as PNG or JPEG")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        frow.addWidget(self.reset_btn)
        frow.addWidget(self.back_btn)
        frow.addStretch(1)
        frow.addWidget(self.save_btn)
        fl.addLayout(frow)
        lay.addWidget(self.bar_final)
        self.set_mode("final" if panel is None else "preview")

    # -- the three states ------------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        """«preview», «rendering» or «final»: which controls show."""
        self.mode = mode
        has_panel = self.panel is not None
        self.bar_preview.setVisible(mode in ("preview", "rendering") and has_panel)
        for w in (self.render_btn, self.render_save_btn, self.follow_camera_box, self.follow_changes_box):
            w.setEnabled(mode == "preview")
        self.bar_final.setVisible(mode == "final")
        self.back_btn.setVisible(has_panel)
        self.bar.setVisible(mode == "rendering")
        self.cancel_btn.setVisible(mode == "rendering" and has_panel)
        if mode == "rendering":
            self.bar.setValue(0)
        self.note.setText(tr(NOTES[mode]) if has_panel or mode == "final" else "")
        if mode == "final":
            self.status.setText("")

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_progress(self, fraction: float) -> None:
        if self.bar.maximum() == 0:
            self.bar.setRange(0, 100)
        self.bar.setValue(int(max(0.0, min(1.0, fraction)) * 100))

    def set_busy(self) -> None:
        """A bar that waits (nothing to measure yet: Blender is starting or building the scene)."""
        self.bar.setRange(0, 0)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)

    def has_image(self) -> bool:
        return self.view.has_picture()

    def _help(self):
        from . import ui_help
        ui_help.show(self, "image")

    # -- the picture --------------------------------------------------------------------------
    def show_draft(self, path) -> None:
        """A frame of the live view (not retouched; keeps the zoom and place)."""
        pm = QPixmap(str(path))
        if not pm.isNull():
            self.path = Path(path)
            self.view.set_pixmap(pm)

    def set_image(self, path, final: bool = True) -> None:
        """The finished picture, to retouch (``final``), or a live frame."""
        if not final:
            return self.show_draft(path)
        import numpy as np
        self.path = Path(path)
        src = QImage(str(path))
        self.alpha = None
        if src.hasAlphaChannel():
            # A transparent sky: straight colours, and the alpha kept apart for saving.
            rgba = src.convertToFormat(QImage.Format_RGBA8888)
            w, h = rgba.width(), rgba.height()
            a = np.frombuffer(rgba.constBits(), dtype=np.uint8, count=rgba.bytesPerLine() * h)
            a = a.reshape(h, rgba.bytesPerLine())[:, : w * 4].reshape(h, w, 4)
            self.alpha = a[..., 3].copy()
            self.original = a[..., :3].copy()
        else:
            img = src.convertToFormat(QImage.Format_RGB888)
            w, h = img.width(), img.height()
            ptr = img.constBits()
            arr = np.frombuffer(ptr, dtype=np.uint8, count=img.bytesPerLine() * h)
            arr = arr.reshape(h, img.bytesPerLine())[:, : w * 3].reshape(h, w, 3)
            self.original = arr.copy()
        was = self.mode
        self.set_mode("final")
        self._refresh(refit=was != "final")

    def adjustments(self) -> dict:
        return {k: value(s) for k, s in self.adj.items()}

    def _reset(self):
        for key, s in self.adj.items():
            set_value(s, post.NEUTRAL[key])

    def _refresh(self, *_a, refit: bool = False):
        if self.original is None:
            return
        out = post.adjust(self.original, self.adjustments())
        self.shown = out
        h, w = out.shape[:2]
        if self.alpha is not None and self.alpha.shape == (h, w):
            # Over a checkerboard, so the transparent sky shows as such.
            import numpy as np
            yy, xx = np.mgrid[0:h, 0:w]
            board = np.where(((yy // 12 + xx // 12) % 2)[..., None] == 0, 236, 204).astype(np.float32)
            a = self.alpha[..., None].astype(np.float32) / 255.0
            disp = np.ascontiguousarray((out * a + board * (1.0 - a)).astype(np.uint8))
        else:
            disp = out
        qimg = QImage(disp.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self.view.set_pixmap(QPixmap.fromImage(qimg), refit=refit is True)

    def save_to(self, path: str) -> bool:
        if self.shown is None:
            return False
        h, w = self.shown.shape[:2]
        jpeg = Path(path).suffix.lower() in (".jpg", ".jpeg")
        if self.alpha is not None and self.alpha.shape == (h, w):
            import numpy as np
            if jpeg:                    # no transparency in a JPEG: over white
                a = self.alpha[..., None].astype(np.float32) / 255.0
                flat = np.ascontiguousarray((self.shown * a + 255.0 * (1.0 - a)).astype(np.uint8))
                return QImage(flat.data, w, h, 3 * w, QImage.Format_RGB888).copy().save(path, None, 95)
            rgba = np.ascontiguousarray(np.dstack([self.shown, self.alpha]))
            return QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy().save(path)
        return QImage(self.shown.data, w, h, 3 * w, QImage.Format_RGB888).copy().save(path)

    def set_rendered_file(self, path, label: str = "") -> None:
        """A 16-bit or EXR file Blender wrote beside the picture: Save image… offers it as it is."""
        self.rendered_file = Path(path) if path else None
        self.rendered_label = label

    def _save(self):
        start = str(Path(QSettings().value(_SETTINGS + "save_dir", str(Path.home()))) /
                    ((self.path.stem if self.path else "render") + ".png"))
        filters = "PNG (*.png);;JPEG (*.jpg)"
        extra = self.rendered_file if self.rendered_file is not None and self.rendered_file.is_file() else None
        if extra is not None:
            ext = extra.suffix
            filters = tr("{label}, as rendered, without the retouching (*{ext})", label=self.rendered_label, ext=ext) + ";;" + filters
            start = str(Path(start).with_suffix(ext))
        path, chosen = QFileDialog.getSaveFileName(self, tr("Save image"), start, filters)
        if path and extra is not None and (chosen.startswith(self.rendered_label) or (
                extra.suffix.lower() not in (".png", ".jpg", ".jpeg") and path.lower().endswith(extra.suffix.lower()))):
            import shutil
            try:
                shutil.copyfile(extra, path)
            except OSError:
                self.status.setText(tr("Could not write {path}", path=path))
                return
            QSettings().setValue(_SETTINGS + "save_dir", str(Path(path).parent))
            self.status.setText(tr("Saved as rendered: {path}", path=path))
            return
        if path and self.save_to(path):
            QSettings().setValue(_SETTINGS + "save_dir", str(Path(path).parent))
            self.status.setText(tr("Saved: {path}", path=path))

    def closeEvent(self, ev):          # noqa: N802
        if self.panel is not None:
            self.panel.preview_closed()
        super().closeEvent(ev)
