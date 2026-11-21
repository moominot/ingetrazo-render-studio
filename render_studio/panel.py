# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Studio's side-tray tab.

Two tabs inside it. **Settings** sets the scene: a look (preset), a few sliders that change it
(clouds, sun, exposure, warmth, saturation, vignette), an optional 360° background (HDRI) that can
light it, and the engine and size of the final render. **Lights** (lights_panel.py) places point,
spot, area and sun lights; the lights of IngeTrazo's Render tab are rendered too. Under the tabs,
**Open preview…** opens the preview window (preview.py): a live view you can zoom and move, with
Render (then retouch and Save image…) and Render and save…. Blender is the one IngeTrazo's Render
tab found.
"""
from __future__ import annotations

from .i18n import language, tr, translate_on_show  # noqa: F401

import json
import logging
import os
import shutil
import time
from pathlib import Path

from PySide6.QtCore import QLocale, QProcess, QProcessEnvironment, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from . import lights as studio_lights, materials as mats, fast_export, output, pbr, presets, proxies, section, settings_store, studio_data, visibility, widgets
from .live import LiveSession
from .preview import ImageWindow  # noqa: F401 - re-exported: panel.ImageWindow
from .widgets import SliderRow

_log = logging.getLogger(__name__)
_SETTINGS = "render_studio/"
HERE = Path(__file__).resolve().parent
_CHOOSE = "__choose__"
HDRI_FILTER = "360° images (*.hdr *.exr *.jpg *.jpeg *.png)"
HDRI_TIP = ("An equirectangular 360° image (.hdr, .exr, .jpg). Blender's own are 1K: "
            "good light, soft behind the model; for a sharp background use 4K or "
            "more (for example the free ones at polyhaven.com).")


def _lang() -> str:
    lang = language()
    return lang if lang in ("ca", "es") else "en"


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


#: The oldest Blender the look's script works with.
MIN_BLENDER = (4, 2)


def blender_version_ok(command, timeout: float = 60.0):
    """Ask ``command`` (Blender's argv prefix) for its version: (True, "") for a
    Blender ≥ MIN_BLENDER, else (False, why, in words for the panel)."""
    import re
    import subprocess
    if not command:
        return False, tr("There is no program at that path.")
    try:
        r = subprocess.run([*command, "--version"], capture_output=True, text=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, tr("That program could not be started ({kind}).", kind=exc.__class__.__name__)
    m = re.search(r"Blender\s+(\d+)\.(\d+)", (r.stdout or "") + (r.stderr or ""))
    if not m:
        return False, tr("That program is not Blender.")
    version = (int(m.group(1)), int(m.group(2)))
    if version < MIN_BLENDER:
        return False, tr("That is Blender {have}; Render Studio needs {need} or newer.",
                         have=f"{version[0]}.{version[1]}", need=f"{MIN_BLENDER[0]}.{MIN_BLENDER[1]}")
    return True, ""


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
                     hdri: dict | None = None, materials: dict | None = None,
                     serve: bool = False, live: bool = False, reuse_model: bool = False,
                     output: dict | None = None, doc_path=None, section_opts: dict | None = None,
                     progress=None):
    """Export the model (IngeTrazo's own job writer) and add the look (and
    the 360° background, if any). ``serve``: Blender builds the scene and then
    waits for cameras on its input (the live view). ``live``: a draft scene
    (lighter EEVEE, sparser grass). ``reuse_model``: keep the model file
    already in ``work`` instead of exporting it again (only the settings
    changed). ``doc_path``: the drawing's file, where proxies keep their
    originals relative to it (proxies.py: each proxy is rendered as its full
    model, placed by Blender as an instance). ``progress``: ``callback(fraction)`` while the model is
    exported (a big model takes a while). Returns (job path, studio
    script path)."""
    from core import render_blender as rb
    block, ambience = presets.studio(preset_key)
    block = apply_hdri(block, hdri)
    block = presets.apply_sliders(block, sliders)
    try:
        materials = mats.with_detected(scene, materials)     # «Gespa» grows grass, «Aigua» ripples
    except Exception:  # noqa: BLE001 - never stops a render
        _log.exception("material names not read")
    if materials:
        block["materials"] = mats.job_block(materials)
    try:
        sets = pbr.job_block(scene)       # each picture's companion maps (normal, roughness…)
    except Exception:  # noqa: BLE001 - never stops a render: the pictures alone, as before
        _log.exception("texture sets not read")
        sets = {}
    if sets:
        block["pbr"] = sets
    if live:
        block["live"] = True
    try:
        sec = section.job_block(scene, section_opts)        # the active section cuts the render too
    except Exception:  # noqa: BLE001 - never stops a render: the whole model
        _log.exception("section not read")
        sec = None
    if sec:
        block["section"] = sec
    try:
        # Every light: Render Studio's (free and on objects) and the Render tab's.
        block["lights"] = studio_lights.job_block(scene)
        tab_lights = []
    except Exception:  # noqa: BLE001 - never stops a render: the Render tab's lights, as before
        _log.exception("lights not read")
        tab_lights = document_lights(scene)
    try:
        # Proxies: their full models go to Blender apart, as instances; the stand-ins stay
        # out of the model file. One whose original is missing renders as it is.
        placed, missing = proxies.job_block(scene, doc_path)
    except Exception:  # noqa: BLE001 - never stops a render: the stand-ins, as drawn
        _log.exception("proxies not read")
        placed, missing = [], []
    if placed:
        block["proxies"] = placed
    if missing:
        block["proxies_missing"] = sorted({g.name for g in missing})
    out_of_file = [g for g in proxies.shown_proxies(scene) if g not in missing] if placed else []
    # The ground is sized and set at the model's foot with the proxies in it.
    ground_block = rb.ground_dict(scene) if (ground and out_of_file) else None
    try:
        symbols = studio_lights.symbols_out_of_render(scene)   # an imported light's component
    except Exception:  # noqa: BLE001 - never stops a render: the symbols, as drawn
        _log.exception("light symbols not read")
        symbols = []
    shared = _shared_copies(scene)
    total = 0
    if progress is not None and not reuse_model:
        try:
            total = fast_export.unique_faces(scene) if shared.on else expanded_faces(scene)
        except Exception:  # noqa: BLE001 - no bar, nothing else
            _log.exception("faces not counted")
    with _model_kept(work if reuse_model else None), proxies.left_out(out_of_file + symbols), \
            shared, visibility.hidden_left_out(scene), fast_export.fast_triangles(), \
            fast_export.gc_paused(), \
            fast_export.export_progress(total, progress if total else None):
        job = rb.write_job(scene, camera, work, engine=engine, quality=quality, width=width,
                           height=height, ground=ground, ambience=ambience,
                           lights=tab_lights, serve=serve)
    data = json.loads(job.read_text(encoding="utf-8"))
    if out_of_file and ground:
        data["ground"] = ground_block
    if output is not None and not live:
        # The final file: the PNG Blender always writes (the preview window reads it) is it
        # for PNG and JPEG; the deeper formats get a file of their own beside it.
        from . import output as out_mod
        o = out_mod.blender_settings(output)
        if o["format"] not in ("png", "jpeg"):
            o["path"] = str(Path(data["output"]).with_suffix(o["extension"]).with_name(
                Path(data["output"]).stem + "-final" + o["extension"]))
        block["output"] = o
    data["studio"] = block
    job.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Both scripts next to the job: IngeTrazo's (the scene) and ours (the look).
    shutil.copyfile(rb.render_script(), work / "render_scene.py")
    script = work / "studio_scene.py"
    shutil.copyfile(HERE / "blender" / "studio_scene.py", script)
    return job, script


#: Above this many faces, counting every copy of every component, the model file is written with
#: its copies SHARED (one mesh per component, nodes that place it) instead of one flat list of
#: world triangles. IngeTrazo writes the flat one for Blender (it carries the camera, to turn the
#: face-me figures), and on a 588 000-face model of 8 700 placements that is 4.3 million
#: triangles of Python objects: over 21 GB and more than 7 minutes without finishing; shared, the
#: same model is 87 MB, 33 s and 4 GB. Blender turns the figures itself either way, and the
#: section cut already copies a mesh shared by several objects.
INSTANCED_FROM_FACES = int(os.environ.get("RENDER_STUDIO_INSTANCED_FROM", "150000"))


def expanded_faces(scene) -> int:
    """The model's faces counting every copy of every component (what the flat export writes);
    counted from the shared meshes, without touching a face."""
    from core.group import iter_placements
    n = len(getattr(getattr(scene, "loose_mesh", None), "faces", None) or ())
    for g in getattr(scene, "groups", None) or ():
        if getattr(g, "hidden", False):
            continue
        n += sum(len(x.mesh.faces) for x, _m in iter_placements(g))
    return n


class _shared_copies:
    """While IngeTrazo's job writer runs: a big model is exported with its copies shared (see
    :data:`INSTANCED_FROM_FACES`), by dropping the camera from the call to ``save_glb``."""

    def __init__(self, scene):
        try:
            self.on = expanded_faces(scene) > INSTANCED_FROM_FACES
        except Exception:  # noqa: BLE001 - never stops a render: the flat export, as before
            _log.exception("faces not counted")
            self.on = False
        self.saved = None

    def __enter__(self):
        if not self.on:
            return self
        import formats.gltf as gltf
        real = self.saved = gltf.save_glb
        _log.info("model exported with its copies shared")

        def save_glb(scene, path, face_me=None, only=None):
            return real(scene, path, None, only)
        gltf.save_glb = save_glb
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            import formats.gltf as gltf
            gltf.save_glb = self.saved
        return False


class _model_kept:
    """While IngeTrazo's job writer runs: its model export is skipped when
    ``work`` already holds the model file (the live view, when only a setting
    changed; exporting a big model is the slow part of a reload)."""

    def __init__(self, work):
        self.glb = Path(work) / "model.glb" if work is not None else None
        self.saved = None

    def __enter__(self):
        if self.glb is None or not self.glb.is_file():
            return self
        import formats.gltf as gltf
        self.saved = gltf.save_glb
        gltf.save_glb = lambda scene, path, *a, **k: None
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            import formats.gltf as gltf
            gltf.save_glb = self.saved
        return False


_slider, _value = widgets.slider, widgets.value


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
        self.need_box = self._need_blender_box()
        outer.addWidget(self.need_box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, 4, 0)

        # The look and its sliders: they change the SCENE (the preview and Render both draw it).
        box_look = QGroupBox("Look and light")
        form = QFormLayout(box_look)
        form.addRow(self._caption("These change the scene itself: the preview and Render both show them."))
        self.preset = QComboBox()
        for key in presets.ORDER:
            self.preset.addItem(presets.label(key, lang), key)
        self.preset.setCurrentIndex(max(0, self.preset.findData(st.value(_SETTINGS + "preset", "clear"))))
        self.preset.setToolTip("The light and the mood of the picture. Changing it puts that look's own values "
                               "in the sliders below.")
        form.addRow("Look", self.preset)
        self.sliders, self.slider_rows = {}, {}
        for key, (label, lo, hi, default, _unit) in presets.SLIDERS.items():
            block, _amb = presets.studio(self.preset.currentData())
            value = default if default is not None else block.get(key, 0.0)
            s = _slider(lo, hi, float(value))
            row = SliderRow(s, presets.SLIDER_FORMATS[key], presets.SLIDER_HINTS[key])
            self.sliders[key], self.slider_rows[key] = s, row
            form.addRow(label, row)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        col.addWidget(box_look)

        # The 360° background.
        box_bg = QGroupBox("360° background")
        form2 = QFormLayout(box_bg)
        self.hdri = QComboBox()
        self.hdri.setToolTip(HDRI_TIP)
        self.hdri.addItem(tr("None"), "")
        for path in bundled_hdris():
            self.hdri.addItem(f"{path.stem.capitalize()} (Blender, 1K)", str(path))
        for path in st.value(_SETTINGS + "hdri_recent", []) or []:
            if path and Path(path).is_file() and self.hdri.findData(path) < 0:
                self.hdri.addItem(Path(path).name, path)
        self.hdri.addItem(tr("Choose a file…"), _CHOOSE)
        saved = str(st.value(_SETTINGS + "hdri", "") or "")
        if saved and self.hdri.findData(saved) < 0 and Path(saved).is_file():
            self.hdri.insertItem(self.hdri.count() - 1, Path(saved).name, saved)
        self.hdri.setCurrentIndex(max(0, self.hdri.findData(saved)))
        self._hdri_prev = self.hdri.currentIndex()
        self.hdri.currentIndexChanged.connect(self._hdri_changed)
        form2.addRow("Image", self.hdri)
        self.hdri_rotation = _slider(0.0, 360.0, float(st.value(_SETTINGS + "hdri_rotation", 0.0)), 360)
        self.hdri_rotation_row = SliderRow(self.hdri_rotation, "{:.0f}°", "Turns the image about the vertical")
        form2.addRow("Rotation", self.hdri_rotation_row)
        self.hdri_strength = _slider(-3.0, 3.0, float(st.value(_SETTINGS + "hdri_strength", 0.0)), 120)
        self.hdri_strength_row = SliderRow(self.hdri_strength, "{:+.1f} stops",
                                           "Its brightness, against the lamps and the look's light")
        form2.addRow("Brightness", self.hdri_strength_row)
        self.hdri_light = QCheckBox("Lights the scene")
        self.hdri_light.setToolTip("On: the image lights the model (its sun casts the shadows). "
                                   "Off: the look lights it, the image is only seen behind it.")
        self.hdri_light.setChecked(str(st.value(_SETTINGS + "hdri_light", "true")).lower() != "false")
        self.hdri_light.toggled.connect(self._hdri_enable)
        form2.addRow("", self.hdri_light)
        self._hdri_enable()
        col.addWidget(box_bg)

        # What only the final render uses.
        box_final = QGroupBox("Final render")
        form3 = QFormLayout(box_final)
        form3.addRow(self._caption("Engine and Quality are for Render; the preview has its own engine."))
        self.preview_engine = QComboBox()
        self.preview_engine.addItem(tr("Automatic"), "auto")
        self.preview_engine.addItem(tr("EEVEE — fast"), "eevee")
        self.preview_engine.addItem(tr("Cycles — like the final render"), "cycles")
        self.preview_engine.setCurrentIndex(max(0, self.preview_engine.findData(st.value(_SETTINGS + "preview_engine", "auto"))))
        self.preview_engine.setToolTip(
            "Automatic: EEVEE while the preview follows the camera, and Cycles on a big model once it is "
            "still (Follow the camera and Follow changes both off: nothing is sent to Blender again, "
            "and a big model looks like the final render). EEVEE or Cycles: always that one.")
        self.preview_engine.currentIndexChanged.connect(lambda _i: QSettings().setValue(_SETTINGS + "preview_engine", self.preview_engine.currentData()))
        form3.addRow("Preview engine", self.preview_engine)
        self.engine = QComboBox()
        self.engine.addItem(tr("EEVEE — fast"), "eevee")
        self.engine.addItem(tr("Cycles — best quality"), "cycles")
        self.engine.setCurrentIndex(max(0, self.engine.findData(st.value(_SETTINGS + "engine", "eevee"))))
        self.engine.setToolTip("EEVEE: about 3 s. Cycles: the truest light, about 5 s on an RTX card "
                               "(the Interior look needs it).")
        form3.addRow("Engine", self.engine)
        self.quality = QComboBox()
        for q in ("Draft", "Medium", "High"):
            self.quality.addItem(tr(q))
        self.quality.setCurrentIndex(int(st.value(_SETTINGS + "quality", 1)))
        self.quality.setToolTip("How many samples: more is less noisy and slower.")
        form3.addRow("Quality", self.quality)
        # The picture's size and file: the Output tab (its width is the panel's ``width``).
        from .output_panel import OutputTab
        self.output_tab = OutputTab(self, width=int(st.value(_SETTINGS + "width", 1920)))
        self.width = self.output_tab.width
        col.addWidget(box_final)
        col.addStretch(1)
        scroll.setWidget(host)
        scroll.setMinimumHeight(min(host.sizeHint().height() + 8, 520))
        # Tabs: the global settings, then the lights (more to come: place and
        # sun, output). What is under them (materials, preview, status) serves all.
        from .lights_panel import LightsTab
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(scroll, "Settings")
        self.lights_tab = LightsTab(app)
        lscroll = QScrollArea()
        lscroll.setWidgetResizable(True)
        lscroll.setFrameShape(QFrame.NoFrame)
        lscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)   # it fits the tray's width
        lscroll.setWidget(self.lights_tab)
        self.tabs.addTab(lscroll, "Lights")
        from .sun_panel import SunTab
        self.sun_tab = SunTab(app, self)
        from .section_panel import SectionTab
        self.section_tab = SectionTab(app, live=self._preview_open)
        for tab_widget, title in ((self.sun_tab, "Sun"), (self.section_tab, "Section"), (self.output_tab, "Output")):
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sc.setWidget(tab_widget)
            self.tabs.addTab(sc, title)
        self.tabs.setCurrentIndex(min(self.tabs.count() - 1, max(0, int(st.value(_SETTINGS + "tab", 0) or 0))))
        self.tabs.currentChanged.connect(lambda i: QSettings().setValue(_SETTINGS + "tab", int(i)))
        outer.addWidget(self.tabs, 1)

        self.help_btn = QToolButton()
        self.help_btn.setText("?")
        self.help_btn.setToolTip("How Render Studio works, and what each control does")
        self.help_btn.clicked.connect(lambda: self.show_help("panel"))
        self.materials_btn = QPushButton("Materials…")
        self.materials_btn.setToolTip("How each material renders: polish, metal, relief, glass, glow.")
        self.materials_btn.clicked.connect(self.open_materials)
        mrow = QHBoxLayout()
        mrow.addWidget(self.materials_btn, 1)
        mrow.addWidget(self.help_btn)
        outer.addLayout(mrow)
        self.editor = None
        self._live = None
        self._prep = None
        self._preparing = False
        self._save_to = None
        self._cancelled = False
        self.preview_btn = QPushButton("Open preview…")
        self.preview_btn.setToolTip("Opens the preview window: a live view of the scene that you can zoom and move, "
                                    "with Render (then retouch and save) and Render and save…")
        self.preview_btn.setDefault(True)
        self.preview_btn.clicked.connect(self.open_preview)
        outer.addWidget(self.preview_btn)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        for combo in (self.engine, self.quality):
            combo.currentIndexChanged.connect(self._update_summary)
        self.width.valueChanged.connect(self._update_summary)
        self._init_document_settings()
        self.check_blender()

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: gray; font-size: 11px")
        return label

    # -- Blender ------------------------------------------------------------------
    def _need_blender_box(self) -> QFrame:
        """Shown while IngeTrazo has no Blender: what it is for, where it is
        (a path and Browse…), and where to download it."""
        from core import render_blender as rb
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        title = QLabel("<b>Render Studio needs Blender</b>")
        lay.addWidget(title)
        text = QLabel("Blender (free, version 4.2 or newer) makes the images. If it is installed, "
                      "choose its program; if not, download it, install it and choose it here.")
        text.setWordWrap(True)
        lay.addWidget(text)
        row = QHBoxLayout()
        self.blender_path = QLineEdit()
        self.blender_path.setPlaceholderText({"windows": "C:\\Program Files\\Blender Foundation\\…\\blender.exe",
                                              "macos": "/Applications/Blender.app"}.get(rb.package_kind(),
                                                                                       "/usr/bin/blender"))
        self.blender_path.setToolTip("The Blender program. IngeTrazo's Render tab uses the same one.")
        self.blender_path.returnPressed.connect(lambda: self.set_blender_path(self.blender_path.text()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_blender)
        row.addWidget(self.blender_path, 1)
        row.addWidget(browse)
        lay.addLayout(row)
        link = QLabel(f'<a href="{rb.DOWNLOAD_URL}">Download Blender from blender.org</a>')
        link.setOpenExternalLinks(True)
        link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lay.addWidget(link)
        steps = []
        try:
            steps = rb.install_steps()
        except Exception:  # noqa: BLE001 - an older IngeTrazo: the link is enough
            pass
        if rb.package_kind() not in ("windows", "macos"):     # Linux packages: the exact command
            for line, cmd in steps:
                note = QLabel(line + (f"<br><code>{cmd}</code>" if cmd else ""))
                note.setWordWrap(True)
                note.setTextInteractionFlags(Qt.TextSelectableByMouse)
                lay.addWidget(note)
        self.blender_msg = QLabel("")
        self.blender_msg.setWordWrap(True)
        self.blender_msg.setStyleSheet("color: #b04020")
        self.blender_msg.setVisible(False)
        lay.addWidget(self.blender_msg)
        box.setVisible(False)
        return box

    def blender(self):
        from core import render_blender as rb
        return rb.find_blender(str(QSettings().value(rb.SETTINGS_KEY, "") or "") or None)

    def check_blender(self):
        """Show the «needs Blender» box, and switch off Render and Live view, while
        there is none. Returns the Blender found, or None."""
        try:
            found = self.blender()
        except Exception:  # noqa: BLE001 - never breaks the panel
            found = None
        self.need_box.setVisible(found is None)
        self.preview_btn.setEnabled(found is not None)
        return found

    def _browse_blender(self):
        from core import render_blender as rb
        kind = rb.package_kind()
        start = self.blender_path.text() or {"windows": "C:/Program Files/Blender Foundation",
                                             "macos": "/Applications"}.get(kind, "/usr/bin")
        filt = {"windows": "Blender (blender.exe);;Programs (*.exe)",
                "macos": "Blender (*.app);;All files (*)"}.get(kind, "All files (*)")
        path, _f = QFileDialog.getOpenFileName(self, "Where is Blender?", start, filt)
        if path:
            self.set_blender_path(path)

    def set_blender_path(self, path: str) -> bool:
        """Use the Blender at ``path`` (a .app on macOS is fine): checked by
        asking its version, then saved where IngeTrazo's Render tab keeps it."""
        from core import render_blender as rb
        path = rb.app_bundle_executable(str(path).strip().strip('"'))
        self.blender_path.setText(path)
        ok, why = blender_version_ok([*rb.find_blender(path).command]
                                     if path and (rb.in_flatpak() or Path(path).is_file()) else None)
        self.blender_msg.setText(why)
        self.blender_msg.setVisible(bool(why))
        if not ok:
            return False
        QSettings().setValue(rb.SETTINGS_KEY, path)
        self._add_bundled_hdris()
        found = self.check_blender()
        self.status.setText(tr("Blender: {where}", where=found.where) if found else "")
        return found is not None

    def _add_bundled_hdris(self):
        """Blender's own 360° images, once a Blender is set (before «Choose a file…»)."""
        for path in bundled_hdris():
            if self.hdri.findData(str(path)) < 0:
                self.hdri.insertItem(self.hdri.count() - 1, f"{path.stem.capitalize()} (Blender, 1K)", str(path))

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.need_box.isVisible():            # installed or set meanwhile (the Render tab)
            self.check_blender()

    # -- live view ----------------------------------------------------------------

    def live_model_key(self):
        """What the live scene's MODEL file depends on: the document and its content."""
        scene = self.app.scene
        # Lights and the sun bump the version too, but the model file does not change.
        return (id(scene), getattr(scene, "content_version", 0) - getattr(scene, "_rs_not_model", 0))

    def live_key(self):
        """What the live scene depends on besides the camera, in three parts:
        (the model, the materials' render settings, the look with every
        setting and the proportions)."""
        try:
            from . import sun_site
            doc = (json.dumps(self.settings_dict(), sort_keys=True) + studio_lights.signature(self.app.scene)
                   + section.signature(self.app.scene, self.section_tab.settings())
                                      + json.dumps(sun_site.site(self.app.scene), sort_keys=True)
                   + self.live_engine())
            mats_ = json.dumps(self.material_specs(), sort_keys=True, default=str)
        except Exception:  # noqa: BLE001
            doc = mats_ = ""
        return (self.live_model_key(), mats_, (doc, round(self._aspect(), 3)))

    def _big_model(self) -> bool:
        """The model is big enough for the preview to prefer Cycles when it is still (counted once per
        version of the drawing: this is asked at every poll of the live view)."""
        scene = self.app.scene
        key = (id(scene), getattr(scene, "content_version", 0))
        if getattr(self, "_big_key", None) != key:
            try:
                self._big_val = expanded_faces(scene) > INSTANCED_FROM_FACES
            except Exception:  # noqa: BLE001
                self._big_val = False
            self._big_key = key
        return self._big_val

    def live_engine(self) -> str:
        """The live view's engine. The Interior look needs Cycles (EEVEE can't fill a room lit
        through a window). Otherwise the panel's Preview engine: EEVEE, Cycles, or Automatic = EEVEE
        while the view follows the camera or the changes (it must be quick), Cycles on a big model once
        it follows neither (nothing is sent to Blender again, and EEVEE looks nothing like the final
        render there). The panel's Engine is for Render."""
        block, _amb = presets.studio(self.preset.currentData())
        if block.get("engine_hint") == "cycles":
            return "cycles"
        choice = self.preview_engine.currentData()
        if choice == "cycles":
            return "cycles"
        if choice == "auto":
            live = self._live
            if (live is not None and not live.follow_camera and not live.follow_changes
                    and self._big_model()):
                return "cycles"
        return "eevee"

    def live_job(self, work: Path, width: int, height: int, reuse_model: bool = False,
                 materials: dict | None = None):
        """The job of the live Blender: the current look and settings, a draft
        in serve mode — EEVEE lightened, or Cycles for the Interior look (the
        Engine and Quality chosen are for Render). ``reuse_model``: the model
        file in ``work`` is still good (only a setting changed, or the live view
        keeps its model). ``materials``: the render settings to use (default:
        the document's)."""
        return write_studio_job(
            self.app.scene, self.app.viewport.camera, work, self.preset.currentData(),
            self.slider_values(), engine=self.live_engine(), quality=0, width=width,
            height=height, hdri=self.hdri_settings(),
            materials=self.material_specs() if materials is None else materials, serve=True,
            live=True, reuse_model=reuse_model, doc_path=self.doc_path(),
            section_opts=self.section_tab.settings(), progress=self._export_progress())

    def doc_path(self):
        """The drawing's file (None until it is saved): proxies keep their originals
        relative to it."""
        win = getattr(self.app, "window", None)
        p = getattr(win, "_current_path", None)
        return str(p) if p else None

    # -- the preview window and its live view -------------------------------------------
    def preview(self) -> ImageWindow:
        """The preview window (made once, kept for the session)."""
        if self.window is None:
            self.window = ImageWindow(self.app.window if hasattr(self.app, "window") else None, panel=self)
            translate_on_show(self.window)
            self._update_summary()
        return self.window

    def open_preview(self):
        """Open the preview window and start the live view in it. Returns the window,
        or None when there is no Blender (the panel says how to choose one)."""
        if self.check_blender() is None:
            self.status.setText("Blender was not found: choose it above.")
            return None
        win = self.preview()
        if self.proc is None and win.mode != "final":
            win.set_mode("preview")
        win.show()
        win.raise_()
        win.activateWindow()
        if self.proc is None and win.mode == "preview":
            self._start_live(prep=True)
        return win

    def back_to_preview(self):
        """From the final picture back to the live preview."""
        win = self.preview()
        if self.proc is None:
            win.set_mode("preview")
            self._start_live(prep=True)

    def _preview_open(self) -> bool:
        """The preview window is on screen and its live view runs."""
        win = self.window
        return bool(win is not None and win.isVisible()
                    and self._live is not None and self._live.active)

    def preview_closed(self):
        """The window was closed: the live Blender is not needed any more. (A render under
        way goes on, and shows its picture when it is ready.)"""
        self._stop_live()

    def _start_live(self, prep: bool = False):
        """Start the live view. ``prep``: a modal says what is happening until the first picture
        (opening the window; a big model takes a minute to export)."""
        if self._live is None:
            self._live = LiveSession(self)
            self._live.image.connect(self._live_image)
            self._live.state.connect(self._set_status)
        win = self.preview()
        self._live.set_follow_camera(win.follow_camera_box.isChecked())
        self._live.set_follow_changes(win.follow_changes_box.isChecked())
        if prep and not self._live.active and self._prep is None:
            from .prep_dialog import PrepDialog
            self._prep = PrepDialog(win)
            self._prep.canceled.connect(self._prep_cancelled)
        try:
            self._live.start()
        except Exception:  # noqa: BLE001 - say it, never crash the app
            self._prep_close()
            raise
        self.section_tab.document_changed()       # it follows the model from here on

    def _prep_close(self):
        dlg, self._prep = self._prep, None
        if dlg is not None:
            dlg.blockSignals(True)               # closing it is not Cancel
            dlg.close()
            dlg.deleteLater()

    def _prep_cancelled(self):
        """Cancel in the modal: no live view, no window."""
        self._prep = None
        self._preparing = False
        self._stop_live()
        if self.window is not None:
            self.window.hide()
        self.status.setText(tr("Preview cancelled."))

    def _export_progress(self):
        """The callback the model export reports to (the modal's bar), or None."""
        return self._prep.exporting if self._prep is not None else None

    def _stop_live(self):
        if self._live is not None and self._live.active:
            self._live.stop()

    def _follow_toggled(self, key: str, on: bool):
        QSettings().setValue(_SETTINGS + key, bool(on))
        if self._live is not None and self.window is not None:
            self._live.set_follow_camera(self.window.follow_camera_box.isChecked())
            self._live.set_follow_changes(self.window.follow_changes_box.isChecked())

    def _live_image(self, path):
        """A frame of the live view: into the window while it shows the preview."""
        self._prep_close()                        # the first picture: the modal is no longer needed
        if not Path(path).is_file() or self.window is None or self.window.mode != "preview":
            return
        self.window.show_draft(path)

    def _set_status(self, text: str):
        shown = tr(text)
        self.status.setText(shown)
        if self.window is not None:
            self.window.set_status(shown)
        if self._prep is not None:
            if text.startswith(("Starting Blender", "Blender:")):
                self._prep.waiting(text)
            elif text == "Live view: in sync":
                self._prep.waiting("Drawing the first image…")
            elif text.startswith(("Live view stopped", "Blender stopped")):
                self._prep_close()

    def _set_progress(self, fraction: float):
        if self.window is not None:
            self.window.set_progress(fraction)

    def _update_summary(self, *_a):
        if self.window is not None:
            w, h = self.output_tab.frame()
            self.window.set_summary(tr("Render: {engine} · {quality} · {w} × {h} px · {format}",
                                       engine=self.engine.currentText().split(' —')[0],
                                       quality=self.quality.currentText(), w=w, h=h,
                                       format=tr(output.FORMATS[self.output_tab.format.currentData()][0])))

    # -- the settings, in the document --------------------------------------------
    def _init_document_settings(self):
        """Keep the panel's settings in the IngeTrazo document (see
        ``settings_store`` for the format): saved a moment after each change,
        and put back when the document, or its tab, changes."""
        self._applying = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(700)
        self._save_timer.timeout.connect(self._save_document_settings)
        for combo in (self.preset, self.engine, self.quality, self.hdri):
            combo.currentIndexChanged.connect(self._schedule_save)
        self.width.valueChanged.connect(self._schedule_save)
        self.output_tab.changed.connect(self._schedule_save)
        self.section_tab.changed.connect(self._schedule_save)
        self.output_tab.changed.connect(self._update_summary)
        self.preset.currentIndexChanged.connect(lambda _i: self.sun_tab._show_sun())
        self.hdri.currentIndexChanged.connect(lambda _i: self.sun_tab._show_sun())
        self.hdri_light.toggled.connect(lambda _on: self.sun_tab._show_sun())
        for sl in (*self.sliders.values(), self.hdri_rotation, self.hdri_strength):
            sl.valueChanged.connect(self._schedule_save)
        self.hdri_light.toggled.connect(self._schedule_save)
        self._scene_id = id(self.app.scene) if hasattr(self.app, "scene") else None
        self._known = self._stored_settings()
        if self._known is not None:
            self.apply_settings(self._known)

    def _stored_settings(self):
        try:
            return settings_store.clean((self.app.document_data({}) or {}).get("settings"))
        except Exception:  # noqa: BLE001 - an old IngeTrazo: no document data
            return None

    def settings_dict(self) -> dict:
        """The panel's settings in the document format."""
        hdri = self.hdri.currentData()
        return {
            "version": settings_store.VERSION,
            "look": self.preset.currentData(),
            "engine": self.engine.currentData(),
            "quality": self.quality.currentIndex(),
            "width": self.width.value(),
            "output": self.output_tab.settings(),
            "section": self.section_tab.settings(),
            "sliders": {k: round(_value(s), 4) for k, s in self.sliders.items()},
            "hdri": ({"path": hdri, "rotation": round(_value(self.hdri_rotation), 3),
                      "brightness": round(_value(self.hdri_strength), 3),
                      "light": self.hdri_light.isChecked()}
                     if hdri and hdri != _CHOOSE else None),
        }

    def apply_settings(self, data: dict) -> None:
        """Put ``data`` (the document's settings) in the controls, without
        saving them again."""
        data = settings_store.clean(data)
        if data is None:
            return
        self._applying = True
        widgets = [self.preset, self.engine, self.quality, self.width, self.hdri,
                   self.hdri_rotation, self.hdri_strength, self.hdri_light, *self.sliders.values()]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.preset.setCurrentIndex(max(0, self.preset.findData(data["look"])))
            self.engine.setCurrentIndex(max(0, self.engine.findData(data["engine"])))
            self.quality.setCurrentIndex(data["quality"])
            self.width.setValue(data["width"])
            self.output_tab.apply(data.get("output"))
            self.section_tab.apply(data.get("section"))
            block, _amb = presets.studio(self.preset.currentData())
            for key, (_label, lo, hi, default, _unit) in presets.SLIDERS.items():
                value = data["sliders"].get(key, default if default is not None else block.get(key, 0.0))
                sl = self.sliders[key]
                sl.setValue(int(round((float(value) - lo) / (hi - lo) * sl.maximum())))
            h = data["hdri"]
            if h and Path(h["path"]).is_file():
                i = self.hdri.findData(h["path"])
                if i < 0:
                    i = self.hdri.count() - 1             # before «Choose a file…»
                    self.hdri.insertItem(i, Path(h["path"]).name, h["path"])
                self.hdri.setCurrentIndex(i)
                self.hdri_rotation.setValue(int(round(h["rotation"] / 360.0 * self.hdri_rotation.maximum())))
                self.hdri_strength.setValue(int(round((h["brightness"] + 3.0) / 6.0 * self.hdri_strength.maximum())))
                self.hdri_light.setChecked(h["light"])
            else:
                self.hdri.setCurrentIndex(0)
            self._hdri_prev = self.hdri.currentIndex()
        finally:
            for w in widgets:
                w.blockSignals(False)
            self._applying = False
        for row in (*self.slider_rows.values(), self.hdri_rotation_row, self.hdri_strength_row):
            row.update_value()                       # their signals were blocked
        self._hdri_enable()
        self._update_summary()

    def _schedule_save(self, *_a):
        if not self._applying:
            self._save_timer.start()

    def _save_document_settings(self):
        """One undo step per pause, and nothing when nothing changed."""
        if self._applying:
            return
        new = settings_store.clean(self.settings_dict())
        try:
            data = dict(self.app.document_data({}) or {})
        except Exception:  # noqa: BLE001 - an old IngeTrazo: no document data
            return
        if new == settings_store.clean(data.get("settings")):
            return
        data["settings"] = new
        self._known = new
        studio_data.write(self.app, data)

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
        for w in (self.hdri_rotation_row, self.hdri_strength_row, self.hdri_light):
            w.setEnabled(on)
        lit = on and self.hdri_light.isChecked()
        # The image's own sky and sun replace the look's: these do nothing then.
        for key in ("clouds", "sun_scale"):
            if key in self.slider_rows:
                self.slider_rows[key].setEnabled(not lit)

    def hdri_settings(self) -> dict | None:
        path = self.hdri.currentData()
        if not path or path == _CHOOSE:
            return None
        return {"path": path, "rotation": _value(self.hdri_rotation),
                "strength": 2.0 ** _value(self.hdri_strength), "light": self.hdri_light.isChecked()}

    def show_help(self, anchor: str = "panel"):
        from . import ui_help
        ui_help.show(self, anchor)

    def open_materials(self):
        from .material_editor import MaterialEditor
        if self.editor is None:
            self.editor = MaterialEditor(self.app, _lang(), self)
            translate_on_show(self.editor)
        else:
            from .material_editor import clear_swatches
            clear_swatches()                 # a picture that changed on disk shows now
            self.editor.refresh(force=True)
        self.editor.show()
        self.editor.raise_()
        self.editor.activateWindow()
        return self.editor

    def document_changed(self):
        if self.editor is not None and self.editor.isVisible():
            self.editor.refresh()
        for tab in (getattr(self, "lights_tab", None), getattr(self, "sun_tab", None),
                    getattr(self, "section_tab", None)):
            if tab is not None:
                tab.document_changed()
        if getattr(self, "_save_timer", None) is None or self._save_timer.isActive():
            return                       # a change of ours is waiting to be saved
        sid = id(self.app.scene)
        stored = self._stored_settings()
        # Another tab, or the saved settings changed under us (undo, redo, a
        # reopened file): put them in the controls.
        if sid != self._scene_id or stored != self._known:
            self._scene_id, self._known = sid, stored
            if stored is not None:
                self.apply_settings(stored)

    def material_specs(self) -> dict:
        if self.editor is not None:
            self.editor._flush()               # a change still waiting its pause
        try:
            return (self.app.document_data({}) or {}).get("materials") or {}
        except Exception:  # noqa: BLE001 - an old IngeTrazo: no document data
            return {}

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
        """The final picture's shape: the 3D view's, or the Output tab's size (the preview frames it too)."""
        try:
            return self.output_tab.aspect()
        except Exception:  # noqa: BLE001
            return 16 / 9

    def render(self, save_to: str | None = None):
        """Make the final picture. ``save_to``: save it there as soon as it is ready, as
        rendered (no retouching), and go back to the live preview; without it the window
        shows the picture with the retouch tools."""
        from core import render_blender as rb
        if self.proc is not None:
            return
        found = self.check_blender()
        if found is None:
            self.status.setText("Blender was not found: choose it above.")
            self.finished.emit(None)
            return
        if self._preparing:
            return
        self._remember()
        # Say at once that something is happening (the export of a big model and the live Blender
        # shutting down take seconds before Blender reports any progress).
        if self.window is not None:
            self.window.set_mode("rendering")
            self.window.set_busy()
        self._set_status(tr("Preparing the model…"))
        QApplication.processEvents()
        self._preparing = True
        try:
            self._stop_live()              # a final render and the live Blender should not run together
            self._render_job(found, save_to)
        finally:
            self._preparing = False

    def _export_status(self, fraction: float):
        """The model's export is ``fraction`` done: the window's status and bar say so."""
        self._set_status(tr("Exporting the model… {pct} %", pct=int(fraction * 100)))
        self._set_progress(fraction * 0.85)
        QApplication.processEvents()

    def _render_job(self, found, save_to):
        from core import render_blender as rb
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.work = rb.work_base().parent / "render-studio" / stamp
        width, height = self.output_tab.frame()
        out = self.output_tab.settings()
        try:
            job, script = write_studio_job(
                self.app.viewport.scene, self.app.viewport.camera, self.work,
                self.preset.currentData(), self.slider_values(),
                engine=self.engine.currentData(), quality=self.quality.currentIndex(),
                width=width, height=height, hdri=self.hdri_settings(),
                materials=self.material_specs(), output=out, doc_path=self.doc_path(),
                section_opts=self.section_tab.settings(), progress=self._export_status)
        except Exception as exc:  # noqa: BLE001 - say it, never crash the app
            _log.exception("render job failed")
            self._set_status(tr("Could not prepare the render: {error}", error=exc))
            self._back_to_preview_if_open()
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
        self._save_to, self._cancelled = save_to, False
        data = json.loads(job.read_text(encoding="utf-8"))
        self.output = Path(data["output"])
        missing = (data.get("studio") or {}).get("proxies_missing") or []
        extra = (data.get("studio") or {}).get("output", {}).get("path")
        self.rendered = {"format": out["format"], "file": Path(extra) if extra else self.output,
                         "jpeg_quality": out["jpeg_quality"]}
        if self.window is not None:
            self.window.set_busy()          # Blender builds the scene: nothing to measure until it renders
        self._set_status(tr("Blender is preparing the scene…") + (
            " " + tr("({n} proxy/proxies without its full model file, rendered as drawn: {names})",
                     n=len(missing), names=", ".join(missing[:3]) + ("…" if len(missing) > 3 else ""))
            if missing else ""))
        self.proc.start(argv[0], argv[1:])

    def render_and_save(self):
        """Ask where to save, then render and save it as it comes out (no retouching)."""
        if self.proc is not None:
            return
        fmt = self.output_tab.format.currentData()
        ext = output.extension(fmt)
        start = str(Path(QSettings().value(_SETTINGS + "save_dir", str(Path.home()))) /
                    f"render-{time.strftime('%Y%m%d-%H%M%S')}{ext}")
        path, _f = QFileDialog.getSaveFileName(self.window or self, tr("Render and save"), start,
                                               f"{output.FORMATS[fmt][0]} (*{ext})")
        if path and not path.lower().endswith(ext) and not (fmt == "jpeg" and path.lower().endswith(".jpeg")):
            path += ext
        if path:
            self.render(save_to=path)

    def cancel_render(self):
        if self.proc is not None:
            self._cancelled = True
            self.proc.kill()

    def _back_to_preview_if_open(self):
        """After a render that gave no picture to retouch: the live preview again, if the
        window is still open."""
        win = self.window
        if win is not None and win.isVisible():
            win.set_mode("preview")
            self._start_live()
        elif win is not None:
            win.set_mode("preview")

    def _read(self):
        from core import render_blender as rb
        text = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.splitlines():
            self._log_lines.append(line)
            p = rb.progress_of(line)
            if p is not None:
                self._set_progress(p)
            if line.startswith("INGETRAZO meter"):
                self._set_status(tr("Exposure measured; rendering…"))

    def _save_as_rendered(self, path: str) -> bool:
        """The render exactly as Blender wrote it, in the Output tab's format (a JPEG is made
        from the PNG, at its quality, over white where the sky is transparent)."""
        r = getattr(self, "rendered", None) or {"format": "png", "file": self.output, "jpeg_quality": 92}
        try:
            if r["format"] == "jpeg" or Path(path).suffix.lower() in (".jpg", ".jpeg"):
                img = QImage(str(self.output))
                if img.hasAlphaChannel():
                    flat = QImage(img.size(), QImage.Format_RGB32)
                    flat.fill(0xFFFFFFFF)
                    from PySide6.QtGui import QPainter
                    p = QPainter(flat)
                    p.drawImage(0, 0, img)
                    p.end()
                    img = flat
                return img.save(path, "JPG", int(r.get("jpeg_quality", 92)))
            shutil.copyfile(r["file"], path)
            return True
        except OSError:
            _log.exception("could not save %s", path)
            return False

    def _autosave(self) -> str | None:
        """Every final render also in the Output tab's folder, when asked: the path, or None."""
        target = self.output_tab.autosave_target()
        if target is None:
            return None
        folder, pattern = target
        r = getattr(self, "rendered", None) or {"format": "png"}
        doc = ""
        for attr in ("file_path", "path", "filename"):
            v = getattr(self.app.scene, attr, None)
            if v:
                doc = Path(str(v)).stem
                break
        name = output.file_name(pattern, doc, presets.label(self.preset.currentData(), "en"),
                                time.strftime("%Y%m%d-%H%M%S"), output.extension(r["format"]))
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        path = folder / name
        return str(path) if self._save_as_rendered(str(path)) else None

    def _done(self, code, _status):
        self.proc = None
        save_to, self._save_to = self._save_to, None
        failed = code != 0 or not self.output.exists()
        if self._cancelled or failed:
            if self._cancelled:
                self._set_status(tr("Render cancelled."))
            else:
                tail = "\n".join(l for l in self._log_lines if "Error" in l or "INGETRAZO" in l)[-600:]
                self._set_status(tr("The render failed (code {code}).\n{tail}", code=code, tail=tail))
            self._back_to_preview_if_open()
            self.finished.emit(None)
            return
        kept = self._autosave()
        if save_to:
            if self._save_as_rendered(save_to):
                QSettings().setValue(_SETTINGS + "save_dir", str(Path(save_to).parent))
                self._set_status(tr("Saved: {path}", path=save_to))
            else:
                self._set_status(tr("Rendered, but {path} could not be written (the picture is in {output}).", path=save_to, output=self.output))
            self._back_to_preview_if_open()
            self.finished.emit(self.output)
            return
        win = self.preview()
        self._set_status(tr("Done: {name}", name=self.output.name) + (" · " + tr("also saved in {path}", path=kept) if kept else ""))
        win.set_image(self.output)                        # the retouch tools and Save image…
        r = getattr(self, "rendered", None)
        win.set_rendered_file(r["file"] if r and not output.retouchable(r["format"]) else None,
                              output.FORMATS[r["format"]][0] if r else "")
        win.show()
        win.raise_()
        self.finished.emit(self.output)
