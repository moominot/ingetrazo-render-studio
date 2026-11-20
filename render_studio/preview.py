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
        pl.addStretch(1)
        self.summary = QLabel("")
        self.summary.setStyleSheet("color: gray")
        self.summary.setToolTip("The engine, quality and width set in the panel: Render uses them "
                                "(the preview is always a quick draft).")
        pl.addWidget(self.summary)
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
        self.note.setText(NOTES[mode] if has_panel or mode == "final" else "")
        if mode == "final":
            self.status.setText("")

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_progress(self, fraction: float) -> None:
        self.bar.setValue(int(max(0.0, min(1.0, fraction)) * 100))

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
        img = QImage(str(path)).convertToFormat(QImage.Format_RGB888)
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
        qimg = QImage(out.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self.view.set_pixmap(QPixmap.fromImage(qimg), refit=refit is True)

    def save_to(self, path: str) -> bool:
        if self.shown is None:
            return False
        h, w = self.shown.shape[:2]
        return QImage(self.shown.data, w, h, 3 * w, QImage.Format_RGB888).copy().save(path)

    def _save(self):
        start = str(Path(QSettings().value(_SETTINGS + "save_dir", str(Path.home()))) /
                    ((self.path.stem if self.path else "render") + ".png"))
        path, _ = QFileDialog.getSaveFileName(self, "Save image", start,
                                              "PNG (*.png);;JPEG (*.jpg)")
        if path and self.save_to(path):
            QSettings().setValue(_SETTINGS + "save_dir", str(Path(path).parent))
            self.status.setText(f"Saved: {path}")

    def closeEvent(self, ev):          # noqa: N802
        if self.panel is not None:
            self.panel.preview_closed()
        super().closeEvent(ev)
