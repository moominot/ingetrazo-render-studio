# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Studio's side-tray tab and its image window.

The tab: a look (preset), the engine and size, a few sliders that change
the render (clouds, sun, exposure, warmth, saturation, vignette), Render.
The window: the image, with live adjustments that need no new render, and
Save. Blender is the one IngeTrazo's Render tab found; the lights placed
there are used (they matter for Night and Interior).
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

from PySide6.QtCore import QLocale, QProcess, QProcessEnvironment, QSettings, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from . import post, presets

_log = logging.getLogger(__name__)
_SETTINGS = "render_studio/"
HERE = Path(__file__).resolve().parent


def _lang() -> str:
    name = QLocale().name().lower()
    return "ca" if name.startswith("ca") else "es" if name.startswith("es") else "en"


def document_lights(scene) -> list:
    """The lights placed in IngeTrazo's Render tab (its document data)."""
    from core import render_blender as rb
    raw = (getattr(scene, "plugin_data", {}) or {}).get("render_blender") or {}
    try:
        return rb.clean_lights(list(raw.get("lights") or []))
    except Exception:  # noqa: BLE001 - an old or odd document: no lights
        return []


def write_studio_job(scene, camera, work: Path, preset_key: str, sliders: dict, *,
                     engine: str, quality: int, width: int, height: int, ground: bool = True):
    """Export the model (IngeTrazo's own job writer) and add the look. Returns
    (job path, studio script path)."""
    from core import render_blender as rb
    block, ambience = presets.studio(preset_key)
    block = presets.apply_sliders(block, sliders)
    job = rb.write_job(scene, camera, work, engine=engine, quality=quality, width=width,
                       height=height, ground=ground, ambience=ambience,
                       lights=document_lights(scene))
    data = json.loads(job.read_text(encoding="utf-8"))
    data["studio"] = block
    job.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Both scripts next to the job: IngeTrazo's (the scene) and ours (the look).
    shutil.copyfile(rb.render_script(), work / "render_scene.py")
    script = work / "studio_scene.py"
    shutil.copyfile(HERE / "blender" / "studio_scene.py", script)
    return job, script


def _slider(lo, hi, value, steps=200):
    s = QSlider(Qt.Horizontal)
    s.setRange(0, steps)
    s.setProperty("lo", lo)
    s.setProperty("hi", hi)
    s.setValue(int(round((value - lo) / (hi - lo) * steps)))
    return s


def _value(s: QSlider) -> float:
    lo, hi = float(s.property("lo")), float(s.property("hi"))
    return lo + (hi - lo) * s.value() / s.maximum()


class ImageWindow(QDialog):
    """The render, fitted to the window, with live adjustments and Save."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Render Studio")
        self.resize(1100, 760)
        self.path = None
        self.original = None            # H×W×3 uint8
        self.shown = None
        lay = QVBoxLayout(self)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.view.setMinimumSize(320, 200)
        lay.addWidget(self.view, 1)
        form = QFormLayout()
        self.adj = {}
        for key, label, lo, hi, val in (("exposure", "Exposure (EV)", -2.0, 2.0, 0.0),
                                        ("contrast", "Contrast", 0.6, 1.6, 1.0),
                                        ("saturation", "Saturation", 0.0, 1.8, 1.0),
                                        ("warmth", "Warmth", -1.0, 1.0, 0.0),
                                        ("vignette", "Vignette", 0.0, 0.8, 0.0)):
            s = _slider(lo, hi, val)
            s.valueChanged.connect(self._refresh)
            self.adj[key] = s
            form.addRow(label, s)
        lay.addLayout(form)
        row = QHBoxLayout()
        reset = QPushButton("Reset")
        reset.clicked.connect(self._reset)
        save = QPushButton("Save image…")
        save.clicked.connect(self._save)
        row.addWidget(reset)
        row.addStretch(1)
        row.addWidget(save)
        lay.addLayout(row)

    def set_image(self, path: Path):
        import numpy as np
        self.path = Path(path)
        img = QImage(str(path)).convertToFormat(QImage.Format_RGB888)
        w, h = img.width(), img.height()
        ptr = img.constBits()
        arr = np.frombuffer(ptr, dtype=np.uint8, count=img.bytesPerLine() * h)
        arr = arr.reshape(h, img.bytesPerLine())[:, : w * 3].reshape(h, w, 3)
        self.original = arr.copy()
        self._refresh()

    def adjustments(self) -> dict:
        return {k: _value(s) for k, s in self.adj.items()}

    def _reset(self):
        for key, s in self.adj.items():
            neutral = post.NEUTRAL[key]
            lo, hi = float(s.property("lo")), float(s.property("hi"))
            s.setValue(int(round((neutral - lo) / (hi - lo) * s.maximum())))

    def _refresh(self, *_a):
        if self.original is None:
            return
        out = post.adjust(self.original, self.adjustments())
        self.shown = out
        h, w = out.shape[:2]
        qimg = QImage(out.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self._pixmap = QPixmap.fromImage(qimg)
        self._fit()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit()

    def _fit(self):
        pm = getattr(self, "_pixmap", None)
        if pm is not None:
            self.view.setPixmap(pm.scaled(self.view.size(), Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))

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


class StudioPanel(QWidget):
    finished = Signal(object)            # Path of the image, or None

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.proc = None
        self.work = None
        self.window = None
        self._log_lines = []
        st = QSettings()
        lang = _lang()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        form = QFormLayout(host)
        self.preset = QComboBox()
        for key in presets.ORDER:
            self.preset.addItem(presets.label(key, lang), key)
        self.preset.setCurrentIndex(max(0, self.preset.findData(st.value(_SETTINGS + "preset", "clear"))))
        form.addRow("Look", self.preset)
        self.engine = QComboBox()
        self.engine.addItem("EEVEE — fast", "eevee")
        self.engine.addItem("Cycles — best quality", "cycles")
        self.engine.setCurrentIndex(max(0, self.engine.findData(st.value(_SETTINGS + "engine", "eevee"))))
        form.addRow("Engine", self.engine)
        self.quality = QComboBox()
        for q in ("Draft", "Medium", "High"):
            self.quality.addItem(q)
        self.quality.setCurrentIndex(int(st.value(_SETTINGS + "quality", 1)))
        form.addRow("Quality", self.quality)
        self.width = QSpinBox()
        self.width.setRange(320, 7680)
        self.width.setSingleStep(160)
        self.width.setSuffix(" px")
        self.width.setValue(int(st.value(_SETTINGS + "width", 1920)))
        form.addRow("Width", self.width)
        self.sliders = {}
        for key, (label, lo, hi, default, _unit) in presets.SLIDERS.items():
            block, _amb = presets.studio(self.preset.currentData())
            value = default if default is not None else block.get(key, 0.0)
            s = _slider(lo, hi, float(value))
            s.setToolTip(label)
            self.sliders[key] = s
            form.addRow(label, s)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)
        self.render_btn = QPushButton("Render")
        self.render_btn.clicked.connect(self.render)
        outer.addWidget(self.render_btn)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        outer.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

    # -- settings ---------------------------------------------------------------
    def _preset_changed(self, _i):
        """A new look puts its own values in the sliders that it sets."""
        block, _amb = presets.studio(self.preset.currentData())
        for key, (label, lo, hi, default, _u) in presets.SLIDERS.items():
            value = default if default is not None else block.get(key, 0.0)
            s = self.sliders[key]
            s.setValue(int(round((float(value) - lo) / (hi - lo) * s.maximum())))

    def slider_values(self) -> dict:
        return {k: _value(s) for k, s in self.sliders.items()}

    def _remember(self):
        st = QSettings()
        st.setValue(_SETTINGS + "preset", self.preset.currentData())
        st.setValue(_SETTINGS + "engine", self.engine.currentData())
        st.setValue(_SETTINGS + "quality", self.quality.currentIndex())
        st.setValue(_SETTINGS + "width", self.width.value())

    # -- rendering ----------------------------------------------------------------
    def _aspect(self) -> float:
        vp = self.app.viewport
        try:
            return max(0.2, vp.width() / max(1, vp.height()))
        except Exception:  # noqa: BLE001
            return 16 / 9

    def render(self):
        from core import render_blender as rb
        if self.proc is not None:
            return
        found = rb.find_blender(str(QSettings().value(rb.SETTINGS_KEY, "") or "") or None)
        if found is None:
            self.status.setText("Blender was not found. Set it up in IngeTrazo's Render tab first.")
            self.finished.emit(None)
            return
        self._remember()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.work = rb.work_base().parent / "render-studio" / stamp
        width = self.width.value()
        height = max(2, round(width / self._aspect()))
        try:
            job, script = write_studio_job(
                self.app.viewport.scene, self.app.viewport.camera, self.work,
                self.preset.currentData(), self.slider_values(),
                engine=self.engine.currentData(), quality=self.quality.currentIndex(),
                width=width, height=height)
        except Exception as exc:  # noqa: BLE001 - say it, never crash the app
            _log.exception("render job failed")
            self.status.setText(f"Could not prepare the render: {exc}")
            self.finished.emit(None)
            return
        argv = [*found.command, "-b", "--factory-startup", "--python", str(script), "--", str(job)]
        self.proc = QProcess(self)
        env = QProcessEnvironment()
        for k, v in rb.clean_env().items():
            env.insert(k, v)
        self.proc.setProcessEnvironment(env)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._done)
        self._log_lines = []
        self.output = Path(json.loads(job.read_text(encoding="utf-8"))["output"])
        self.render_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.status.setText("Blender is preparing the scene…")
        self.proc.start(argv[0], argv[1:])

    def _read(self):
        from core import render_blender as rb
        text = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.splitlines():
            self._log_lines.append(line)
            p = rb.progress_of(line)
            if p is not None:
                self.bar.setValue(int(p * 100))
            if line.startswith("INGETRAZO meter"):
                self.status.setText("Exposure measured; rendering…")

    def _done(self, code, _status):
        self.proc = None
        self.render_btn.setEnabled(True)
        self.bar.setVisible(False)
        if code != 0 or not self.output.exists():
            tail = "\n".join(l for l in self._log_lines if "Error" in l or "INGETRAZO" in l)[-600:]
            self.status.setText(f"The render failed (code {code}).\n{tail}")
            self.finished.emit(None)
            return
        self.status.setText(f"Done: {self.output.name}")
        if self.window is None:
            self.window = ImageWindow(self.app.window if hasattr(self.app, "window") else None)
        self.window.set_image(self.output)
        self.window.show()
        self.window.raise_()
        self.finished.emit(self.output)
