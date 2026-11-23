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
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QScrollArea,
                               QProgressBar, QPushButton, QToolButton, QVBoxLayout, QWidget)

from . import post
from .widgets import SliderRow, ZoomView, slider, value, set_value

_SETTINGS = "render_studio/"
#: The side bar's width: the sliders and their words fit, the picture keeps the rest.
SIDE_WIDTH = 360

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
        self.lines = None               # (LineSet, style): the outlines, still vectors, over the picture without them
        self._lines_base = None
        self._lines_timer = None
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
        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.addWidget(self.view, 1)
        # The finished picture's tools (retouch, outlines) live in a bar beside it that can be hidden: more picture when it is not needed.
        self.side = QScrollArea()
        self.side.setWidgetResizable(True)
        self.side.setFrameShape(QFrame.NoFrame)
        self.side.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.side.setFixedWidth(SIDE_WIDTH)
        side_body = QWidget()
        self.side_lay = QVBoxLayout(side_body)
        self.side_lay.setContentsMargins(0, 0, 6, 0)
        self.side.setWidget(side_body)
        mid.addWidget(self.side)
        lay.addLayout(mid, 1)

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
        pv = QVBoxLayout(self.bar_preview)
        pv.setContentsMargins(0, 0, 0, 0)
        self.more_row = QWidget()                 # the live view's options: folded, the usual use needs none
        ml = QHBoxLayout(self.more_row)
        ml.setContentsMargins(0, 0, 0, 0)
        pl = ml
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
        self.update_btn = QPushButton("Update preview")
        self.update_btn.setToolTip("With Follow changes off: shows the model and materials as they are now "
                                   "(the preview keeps the ones it had until then).")
        self.update_btn.clicked.connect(lambda: self.panel and self.panel.update_preview())
        self.follow_changes_box.toggled.connect(lambda on: self.update_btn.setVisible(not on))
        pl.addStretch(1)
        self.summary = QLabel("")
        self.summary.setStyleSheet("color: gray")
        self.summary.setToolTip("The engine, quality and width set in the panel: Render uses them "
                                "(the preview is always a quick draft).")
        self.scene_btn = QPushButton("New scene from this view…")
        self.scene_btn.setToolTip("Saves the view this preview shows (the camera it keeps while Follow the camera is off, "
                                  "else the 3D view's) as a scene of the drawing, to come back to it or render it later.")
        self.scene_btn.clicked.connect(lambda: self.panel and self.panel.scene_from_preview())
        self.expert_btn = QPushButton("Open in Blender…")
        self.expert_btn.setToolTip("Expert mode: opens this scene, as Render would make it, in a Blender with its own "
                                   "window to work in it. Nothing is rendered; the file is saved first.")
        self.expert_btn.clicked.connect(lambda: self.panel and self.panel.open_in_blender())
        pl.addWidget(self.expert_btn)
        from PySide6.QtGui import QAction
        from .widgets import split_button
        self.render_save_btn = QAction("Render and save…", self)
        self.render_save_btn.setToolTip("Asks where to save, makes the final picture and saves it straight away, "
                                        "without retouching.")
        self.render_save_btn.triggered.connect(lambda: self.panel and self.panel.render_and_save())
        self.render_btn = split_button(
            "Render", lambda: self.panel and self.panel.render_main(),
            "Makes the final picture with the panel's engine, quality and width, then shows the retouch tools and "
            "Save image…. The arrow: Render and save….", [self.render_save_btn])
        main = QHBoxLayout()
        self.more_btn = QToolButton()
        self.more_btn.setText("More")
        self.more_btn.setCheckable(True)
        self.more_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.more_btn.setStyleSheet("QToolButton { border: none; }")
        self.more_btn.setToolTip("Live view options (follow the camera, follow changes) and opening the scene in Blender")
        self.more_btn.toggled.connect(self._more_toggled)
        main.addWidget(self.more_btn)
        main.addWidget(self.summary, 1)
        main.addWidget(self.scene_btn)               # always in view
        main.addWidget(self.update_btn)              # only when Follow changes is off
        main.addWidget(self.render_btn)
        self.update_btn.setVisible(not self.follow_changes_box.isChecked())
        pv.addLayout(main)
        pv.addWidget(self.more_row)
        self.more_btn.setChecked(str(st.value(_SETTINGS + "preview_more", "false")).lower() == "true")
        self._more_toggled(self.more_btn.isChecked())
        lay.addWidget(self.bar_preview)

        # -- final: the retouch sliders and Save
        self.bar_final = QWidget()
        fl = QVBoxLayout(self.bar_final)
        fl.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox(tr("Retouch: instant, nothing is rendered again"))
        form = QVBoxLayout(box)
        self.adj, self.adj_rows = {}, {}
        from .widgets import Collapsible
        self.retouch_more = Collapsible(tr("More"), "retouch_more")
        self.retouch_more.form.setContentsMargins(0, 0, 0, 0)
        for key, label, lo, hi, fmt, hint in post.ADJUSTMENTS:
            s = slider(lo, hi, post.NEUTRAL[key])
            s.valueChanged.connect(self._refresh)
            row = SliderRow(s, fmt, hint)
            self.adj[key], self.adj_rows[key] = s, row
            if key in post.SIMPLE:
                line = QHBoxLayout()
                name = QLabel(label)
                name.setMinimumWidth(96)
                name.setAlignment(Qt.AlignLeft | Qt.AlignTop)
                line.addWidget(name)
                line.addWidget(row, 1)
                form.addLayout(line)
            else:
                self.retouch_more.form.addRow(label, row)
        form.addWidget(self.retouch_more)
        self.side_lay.addWidget(box)
        self._build_lines_box(self.side_lay)
        self.side_lay.addStretch(1)
        frow = QHBoxLayout()
        self.side_btn = QToolButton()
        self.side_btn.setText(tr("Retouch"))
        self.side_btn.setCheckable(True)
        self.side_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.side_btn.setToolTip(tr("Shows or hides the bar of the retouching and the outlines"))
        self.side_btn.setChecked(str(QSettings().value(_SETTINGS + "side_open", "true")).lower() != "false")
        self.side_btn.toggled.connect(self._side_toggled)
        frow.addWidget(self.side_btn)
        self.reset_btn = QPushButton("Reset retouch")
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
        self._side_toggled(self.side_btn.isChecked())
        self.set_mode("final" if panel is None else "preview")

    # -- the outlines: vectors until the picture is saved ----------------------------------------
    def _build_lines_box(self, parent_layout) -> None:
        from PySide6.QtCore import QTimer
        from .section_panel import ColourButton
        from .widgets import NumberSlider
        self.lines_box = QGroupBox(tr("Outlines: still lines until you save"))
        form = QFormLayout(self.lines_box)
        top = QHBoxLayout()
        self.lines_on = QCheckBox(tr("Show"))
        self.lines_colour = ColourButton([0.05, 0.05, 0.05], "Outline colour", linear=True)
        self.lines_colour.setMaximumWidth(60)
        self.lines_reset = QPushButton(tr("As rendered"))
        self.lines_reset.setToolTip(tr("The outlines as the panel's style drew them"))
        top.addWidget(self.lines_on)
        top.addWidget(self.lines_colour)
        top.addStretch(1)
        top.addWidget(self.lines_reset)
        form.addRow(top)
        self.lines_width = NumberSlider(0.5, 10.0, 0.1, "{:.1f} px")
        self.lines_width.setToolTip(tr("The thickness of the lines, in pixels of this picture"))
        self.lines_hand = NumberSlider(0.0, 1.0, 0.05, "{:.0%}")
        self.lines_hand.setToolTip(tr("From a ruler (0) to a loose hand: wavering, swelling, drawn twice, broken"))
        self.lines_extend = NumberSlider(0.0, 1.0, 0.05, "{:.0%}")
        self.lines_extend.setToolTip(tr("How far the lines run past their corners"))
        self.lines_opacity = NumberSlider(0.2, 1.0, 0.05, "{:.0%}")
        self.lines_opacity.setToolTip(tr("How dark the ink is"))
        form.addRow(tr("Thickness"), self.lines_width)
        form.addRow(tr("Hand"), self.lines_hand)
        form.addRow(tr("Line extension"), self.lines_extend)
        form.addRow(tr("Ink"), self.lines_opacity)
        self._lines_timer = QTimer(self)
        self._lines_timer.setSingleShot(True)
        self._lines_timer.setInterval(120)
        self._lines_timer.timeout.connect(self._recompose)
        for sig in (self.lines_on.toggled, self.lines_colour.changed, self.lines_width.valueChanged, self.lines_hand.valueChanged,
                    self.lines_extend.valueChanged, self.lines_opacity.valueChanged):
            sig.connect(lambda *_a: self._lines_timer.start())
        self.lines_reset.clicked.connect(self._lines_to_initial)
        self.lines_box.setVisible(False)
        parent_layout.addWidget(self.lines_box)

    def set_outlines(self, lines, style: dict, base_path) -> None:
        """The picture's outlines as vectors: ``lines`` (outlines.LineSet), ``style`` (outlines.window_style: where the controls start)
        and ``base_path``, the render without them. Call it after :meth:`set_image`; the controls then restyle the lines instantly."""
        base = QImage(str(base_path))
        if lines is None or base.isNull():
            return self.clear_outlines()
        self.lines = (lines, dict(style))
        self._lines_base = base
        self._lines_set_controls(style)
        self.lines_box.setVisible(True)
        self._recompose()

    def clear_outlines(self) -> None:
        self.lines = None
        self._lines_base = None
        if getattr(self, "lines_box", None) is not None:
            self.lines_box.setVisible(False)

    def _lines_set_controls(self, style: dict) -> None:
        controls = (self.lines_on, self.lines_colour, self.lines_width, self.lines_hand, self.lines_extend, self.lines_opacity)
        for w in controls:
            w.blockSignals(True)
        self.lines_on.setChecked(True)
        self.lines_colour.set_rgb(style.get("color") or [0.05, 0.05, 0.05])
        self.lines_width.setValue(float(style.get("width", 1.5)))
        self.lines_hand.setValue(float(style.get("hand", 0.0)))
        self.lines_extend.setValue(float(style.get("extend", 0.0)))
        self.lines_opacity.setValue(float(style.get("opacity", 1.0)))
        for w in controls:
            w.blockSignals(False)

    def lines_style(self) -> dict:
        """The outlines' style as the controls say it."""
        base = dict(self.lines[1]) if self.lines else {}
        base.update(width=self.lines_width.value(), color=self.lines_colour.rgb(), hand=self.lines_hand.value(),
                    extend=self.lines_extend.value(), opacity=self.lines_opacity.value())
        return base

    def _lines_to_initial(self) -> None:
        if self.lines:
            self._lines_set_controls(self.lines[1])
            self._recompose()

    def _recompose(self) -> None:
        """The picture again: the render without lines, the lines in the controls' style over it, then the retouch."""
        if self.lines is None or self._lines_base is None:
            return
        from . import outlines
        lines = self.lines[0]
        img = outlines.composite(self._lines_base, lines if self.lines_on.isChecked() else None, self.lines_style())
        self._load_qimage(img)
        self._refresh()

    # -- the three states ------------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        """«preview», «rendering» or «final»: which controls show."""
        self.mode = mode
        has_panel = self.panel is not None
        self.bar_preview.setVisible(mode in ("preview", "rendering") and has_panel)
        for w in (self.render_btn, self.render_save_btn, self.follow_camera_box, self.follow_changes_box):
            w.setEnabled(mode == "preview")
        self.bar_final.setVisible(mode == "final")
        self.side.setVisible(mode == "final" and (not hasattr(self, "side_btn") or self.side_btn.isChecked()))
        self.back_btn.setVisible(has_panel)
        self.bar.setVisible(mode == "rendering")
        self.cancel_btn.setVisible(mode == "rendering" and has_panel)
        if mode == "rendering":
            self.bar.setValue(0)
        self.note.setText(tr(NOTES[mode]) if has_panel or mode == "final" else "")
        if mode == "final":
            self.status.setText("")

    def _side_toggled(self, on: bool) -> None:
        self.side_btn.setArrowType(Qt.RightArrow if on else Qt.LeftArrow)
        self.side.setVisible(self.mode == "final" and on)
        try:
            QSettings().setValue(_SETTINGS + "side_open", "true" if on else "false")
        except Exception:  # noqa: BLE001
            pass

    def _more_toggled(self, on: bool) -> None:
        self.more_btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.more_row.setVisible(on)
        try:
            QSettings().setValue(_SETTINGS + "preview_more", "true" if on else "false")
        except Exception:  # noqa: BLE001
            pass

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
        self.path = Path(path)
        self.clear_outlines()
        self._load_qimage(QImage(str(path)))
        was = self.mode
        self.set_mode("final")
        self._refresh(refit=was != "final")

    def _load_qimage(self, src) -> None:
        """``original`` (and ``alpha``, when the sky is clear) from a picture."""
        import numpy as np
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
