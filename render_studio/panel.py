# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Studio's side-tray tab and its image window.

The tab: a look (preset), the engine and size, a few sliders that change
the render (clouds, sun, exposure, warmth, saturation, vignette), an
optional 360° background (HDRI) that can light the scene too, Render.
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
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from . import post, presets

_log = logging.getLogger(__name__)
_SETTINGS = "render_studio/"
HERE = Path(__file__).resolve().parent
_CHOOSE = "__choose__"
HDRI_FILTER = "360° images (*.hdr *.exr *.jpg *.jpeg *.png)"
HDRI_TIP = ("An equirectangular 360° image (.hdr, .exr, .jpg). Blender's own are 1K: "
            "good light, soft behind the model; for a sharp background use 4K or "
            "more (for example the free ones at polyhaven.com).")


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


def bundled_hdris() -> list:
    """The 360° images Blender ships (CC0, from Poly Haven; 1K), found next
    to the Blender IngeTrazo uses. Empty when there is none."""
    from core import render_blender as rb
    try:
        found = rb.find_blender(str(QSettings().value(rb.SETTINGS_KEY, "") or "") or None)
        if found is None or not found.command:
            return []
        exe = Path(found.command[0])
        return sorted(exe.parent.glob("*/datafiles/studiolights/world/*.exr"))
    except Exception:  # noqa: BLE001 - no list, no harm
        return []


def apply_hdri(block: dict, hdri: dict | None) -> dict:
    """The look's block with a 360° background: ``hdri`` = {path, rotation
    (degrees), strength (multiplier), light (it lights the scene)}. When it
    lights the scene the white balance goes neutral: the photo has its own."""
    if not hdri or not hdri.get("path"):
        return block
    light = bool(hdri.get("light", True))
    if light:
        block["white_balance"] = 6500
    block.update(hdri=str(hdri["path"]), hdri_rotation=float(hdri.get("rotation", 0.0)),
                 hdri_strength=float(hdri.get("strength", 1.0)), hdri_light=light)
    return block


def write_studio_job(scene, camera, work: Path, preset_key: str, sliders: dict, *,
                     engine: str, quality: int, width: int, height: int, ground: bool = True,
                     hdri: dict | None = None):
    """Export the model (IngeTrazo's own job writer) and add the look (and
    the 360° background, if any). Returns (job path, studio script path)."""
    from core import render_blender as rb
    block, ambience = presets.studio(preset_key)
    block = apply_hdri(block, hdri)
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
        # The 360° background.
        self.hdri = QComboBox()
        self.hdri.setToolTip(HDRI_TIP)
        self.hdri.addItem("None", "")
        for path in bundled_hdris():
            self.hdri.addItem(f"{path.stem.capitalize()} (Blender, 1K)", str(path))
        for path in st.value(_SETTINGS + "hdri_recent", []) or []:
            if path and Path(path).is_file() and self.hdri.findData(path) < 0:
                self.hdri.addItem(Path(path).name, path)
        self.hdri.addItem("Choose a file…", _CHOOSE)
        saved = str(st.value(_SETTINGS + "hdri", "") or "")
        if saved and self.hdri.findData(saved) < 0 and Path(saved).is_file():
            self.hdri.insertItem(self.hdri.count() - 1, Path(saved).name, saved)
        self.hdri.setCurrentIndex(max(0, self.hdri.findData(saved)))
        self._hdri_prev = self.hdri.currentIndex()
        self.hdri.currentIndexChanged.connect(self._hdri_changed)
        form.addRow("360° background", self.hdri)
        self.hdri_rotation = _slider(0.0, 360.0, float(st.value(_SETTINGS + "hdri_rotation", 0.0)), 360)
        self.hdri_rotation.setToolTip("Turns the image about the vertical (degrees).")
        form.addRow("Rotation", self.hdri_rotation)
        self.hdri_strength = _slider(-3.0, 3.0, float(st.value(_SETTINGS + "hdri_strength", 0.0)), 120)
        self.hdri_strength.setToolTip("The image's brightness in stops, against the lamps and the look's light.")
        form.addRow("Brightness", self.hdri_strength)
        self.hdri_light = QCheckBox("Lights the scene")
        self.hdri_light.setToolTip("On: the image lights the model (its sun casts the shadows). "
                                   "Off: the look lights it, the image is only seen behind it.")
        self.hdri_light.setChecked(str(st.value(_SETTINGS + "hdri_light", "true")).lower() != "false")
        self.hdri_light.toggled.connect(self._hdri_enable)
        form.addRow("", self.hdri_light)
        self._hdri_enable()
        scroll.setWidget(host)
        scroll.setMinimumHeight(host.sizeHint().height() + 8)
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
        hint = block.get("engine_hint")
        if hint and self.engine.currentData() != hint:
            # EEVEE's screen-space light can't fill a room lit through a
            # window (it comes out blue and flat): a path tracer is needed.
            self.engine.setCurrentIndex(max(0, self.engine.findData(hint)))
            self.status.setText("Interiors need Cycles: light bounces through the window.")

    def _hdri_changed(self, i):
        if self.hdri.itemData(i) == _CHOOSE:
            start = str(QSettings().value(_SETTINGS + "hdri_dir", "") or "")
            path, _f = QFileDialog.getOpenFileName(self, "360° background", start, HDRI_FILTER)
            if path:
                self.set_hdri_path(path)
            else:
                self.hdri.blockSignals(True)
                self.hdri.setCurrentIndex(self._hdri_prev)
                self.hdri.blockSignals(False)
        self._hdri_prev = self.hdri.currentIndex()
        self._hdri_enable()

    def set_hdri_path(self, path: str):
        """Select ``path`` as the 360° background, adding it to the list."""
        path = str(Path(path))
        i = self.hdri.findData(path)
        if i < 0:
            i = self.hdri.count() - 1             # before "Choose a file…"
            self.hdri.insertItem(i, Path(path).name, path)
        self.hdri.blockSignals(True)
        self.hdri.setCurrentIndex(i)
        self.hdri.blockSignals(False)
        self._hdri_prev = i
        st = QSettings()
        st.setValue(_SETTINGS + "hdri_dir", str(Path(path).parent))
        if "datafiles" not in path:
            recent = [p for p in (st.value(_SETTINGS + "hdri_recent", []) or []) if p != path]
            st.setValue(_SETTINGS + "hdri_recent", ([path] + recent)[:6])
        self._hdri_enable()

    def _hdri_enable(self, *_a):
        on = bool(self.hdri.currentData())
        for w in (self.hdri_rotation, self.hdri_strength, self.hdri_light):
            w.setEnabled(on)
        lit = on and self.hdri_light.isChecked()
        # The image's own sky and sun replace the look's: these do nothing then.
        for key in ("clouds", "sun_scale"):
            if key in self.sliders:
                self.sliders[key].setEnabled(not lit)

    def hdri_settings(self) -> dict | None:
        path = self.hdri.currentData()
        if not path or path == _CHOOSE:
            return None
        return {"path": path, "rotation": _value(self.hdri_rotation),
                "strength": 2.0 ** _value(self.hdri_strength), "light": self.hdri_light.isChecked()}

    def slider_values(self) -> dict:
        return {k: _value(s) for k, s in self.sliders.items()}

    def _remember(self):
        st = QSettings()
        st.setValue(_SETTINGS + "preset", self.preset.currentData())
        st.setValue(_SETTINGS + "engine", self.engine.currentData())
        st.setValue(_SETTINGS + "quality", self.quality.currentIndex())
        st.setValue(_SETTINGS + "width", self.width.value())
        data = self.hdri.currentData()
        st.setValue(_SETTINGS + "hdri", data if data != _CHOOSE else "")
        st.setValue(_SETTINGS + "hdri_rotation", _value(self.hdri_rotation))
        st.setValue(_SETTINGS + "hdri_strength", _value(self.hdri_strength))
        st.setValue(_SETTINGS + "hdri_light", self.hdri_light.isChecked())

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
                width=width, height=height, hdri=self.hdri_settings())
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
