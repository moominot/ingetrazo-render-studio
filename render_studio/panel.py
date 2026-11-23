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
import math
import time
from pathlib import Path

from PySide6.QtCore import QLocale, QProcess, QProcessEnvironment, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QImage
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from . import drawing_fog, user_presets, lights as studio_lights, materials as mats, fast_export, output, pbr, presets, proxies, section, settings_store, studio_data, visibility, widgets
from .live import LiveSession
from .preview import ImageWindow  # noqa: F401 - re-exported: panel.ImageWindow
from .widgets import SliderRow

_log = logging.getLogger(__name__)
_SETTINGS = "render_studio/"
HERE = Path(__file__).resolve().parent
_CHOOSE = "__choose__"
HDRI_FILTER = "360° images (*.hdr *.exr *.jpg *.jpeg *.png)"
BACKDROP_FILTER = "Pictures (*.jpg *.jpeg *.png *.webp *.tif *.tiff *.exr *.hdr)"
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


def apply_backdrop(block: dict, backdrop: dict | None) -> dict:
    """The look's block with a fixed picture behind the model: ``backdrop`` = {path, fit
    («fill», «fit», «stretch»), strength (multiplier)}. The look keeps lighting the scene."""
    if not backdrop or not backdrop.get("path"):
        return block
    fit = backdrop.get("fit") if backdrop.get("fit") in ("fill", "fit", "stretch") else "fill"
    block.update(backdrop=str(backdrop["path"]), backdrop_fit=fit,
                 backdrop_strength=float(backdrop.get("strength", 1.0)))
    return block


def apply_style_block(block: dict, scene, style: dict | None, lines: str | None = None) -> dict:
    """The look's block with the render's style (settings_store.style): only what the style uses goes to Blender. ``lines``: the line layer
    (outlines.write_layer) the script lays over the picture. A model made of one
    material of the drawing carries that material's colour and picture for when the file has no such material."""
    st = settings_store.style(style)
    if st["mode"] == "none" and st["width"] <= 0.0:
        return block
    out = {"mode": st["mode"], "width": st["width"], "color": st["color"]}
    if st["mode"] == "model":
        out["model_color"] = st["model_color"]
        if st["material"]:
            from .materials import export_name
            mat = (getattr(scene, "materials", None) or {}).get(st["material"])
            tex = (getattr(mat, "texture", None) or {}) if mat is not None else {}
            out["material"] = export_name(st["material"])
            out["texture"] = str(tex["path"]) if tex.get("path") else None
            if getattr(mat, "color", None) is not None:
                out["model_color"] = [float(c) for c in mat.color[:3]]
    elif st["mode"] == "light":
        out["lux_max"] = st["lux_max"]
    elif st["mode"] == "sketch":
        out["noise"], out["extend"] = st["noise"], st["extend"]
    elif st["mode"] == "watercolour":
        out.update(wetness=st["wetness"], paper=st["paper"], edges=st["edges"])
    if lines:
        out["lines"] = str(lines)
    block["style"] = out
    return block


def apply_ground_look(block: dict, ground_look: dict | None) -> dict:
    """The look's block with the ground's own look: ``ground_look`` = settings_store.ground_look. The
    colour replaces the look's; roughness, horizon haze (0 = none) and height offset are sent when
    they differ from the usual."""
    gl = settings_store.ground_look(ground_look)
    if gl["color"]:
        block["ground_color"] = list(gl["color"])
    if abs(gl["roughness"] - 0.9) > 1e-6:
        block["ground_roughness"] = gl["roughness"]
    if gl["haze"] <= 0.0:
        block["haze"] = False
    elif abs(gl["haze"] - 1.0) > 1e-6:
        block["haze_scale"] = gl["haze"]
    if abs(gl["offset"]) > 1e-6:
        block["ground_offset"] = gl["offset"]
    if gl["grass_radius"] > 0.0:
        block["ground_grass_radius"] = gl["grass_radius"]
    if gl["ground_radius"] > 0.0:
        block["ground_radius"] = gl["ground_radius"]
    return block


def apply_ground_material(block: dict, scene, ground_material: dict | None) -> dict:
    """The look's block with a material of the model on the generated ground: ``ground_material`` =
    {name, tile (metres, 0 = the picture's own size)}. Blender finds the material by name; the
    colour and the tile are sent for when it is not in the model's file."""
    if not ground_material or not ground_material.get("name"):
        return block
    name = str(ground_material["name"])
    mat = (getattr(scene, "materials", None) or {}).get(name)
    tex = (getattr(mat, "texture", None) or {}) if mat is not None else {}
    tile = float(ground_material.get("tile") or 0.0)
    sw, sh = (tile, tile) if tile > 0.0 else (float(tex.get("sw") or 2.0), float(tex.get("sh") or 2.0))
    from .materials import export_name
    block["ground_material"] = {"name": export_name(name), "tile": [max(0.05, sw), max(0.05, sh)],
                                "texture": str(tex["path"]) if tex.get("path") else None,
                                "color": [float(c) for c in (getattr(mat, "color", None) or (0.42, 0.42, 0.4))[:3]]}
    return block


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
                 hdri_strength=float(hdri.get("strength", 1.0)), hdri_light=light,
                 hdri_height=float(hdri.get("height", 2.5)))
    return block


def write_studio_job(scene, camera, work: Path, preset_key: str, sliders: dict, *,
                     engine: str, quality: int, width: int, height: int, ground: bool = True,
                     ground_shadow: bool = False,
                     hdri: dict | None = None, backdrop: dict | None = None, materials: dict | None = None,
                     ground_material: dict | None = None, ground_look: dict | None = None,
                     skyline: dict | None = None, style: dict | None = None, lines: str | None = None,
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
    if output and not live and output.get("projection") in ("flat", "360"):
        engine = "cycles"                     # a panoramic camera is Cycles'; EEVEE would render it flat
    from core import render_blender as rb
    if preset_key in presets.NIGHT_WHEN_SUN_SET and not (hdri and hdri.get("path") and hdri.get("light")):
        try:
            from . import sun_site
            if not sun_site.info(sun_site.site(scene))["up"]:
                preset_key = "night"             # the sun has set at that place, date and hour: the night sky, no sun
        except Exception:  # noqa: BLE001 - not worked out: the look as chosen
            _log.exception("sun height not worked out")
    block, ambience = presets.studio(preset_key)
    block = apply_hdri(block, hdri)
    if not (hdri and hdri.get("path")):
        block = apply_backdrop(block, backdrop)
    if ground:
        block = apply_ground_material(block, scene, ground_material)
        block = apply_ground_look(block, ground_look)
        sk = settings_store.skyline(skyline)
        if sk["type"]:
            block["skyline"] = {k: v for k, v in sk.items() if v is not None}
    block = apply_style_block(block, scene, style, lines)
    block = presets.apply_sliders(block, sliders)
    block = drawing_fog.apply(block, scene)           # the drawing's own fog (IngeTrazo 0.6.3), when it has one
    try:
        materials = mats.with_detected(scene, materials)     # «Gespa» grows grass, «Aigua» ripples
    except Exception:  # noqa: BLE001 - never stops a render
        _log.exception("material names not read")
    if materials:
        block["materials"] = mats.job_block(materials)
        gm = block.get("ground_material")
        if gm and (block["materials"].get(gm["name"]) or {}).get("type") == "grass":
            try:
                from . import ground as ground_mod
                block["ground_grass_centre"] = ground_mod.centroid(scene)     # where the circle of grass is centred
            except Exception:  # noqa: BLE001 - Blender works it out from its own objects
                _log.exception("model centroid not worked out")
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
    if ground_shadow and not ground:
        # No ground is made, but the model still throws its shadow on the floor: an invisible plane
        # at the model's foot that only shows shadows (Blender's shadow catcher).
        try:
            gd = rb.ground_dict(scene)
        except Exception:  # noqa: BLE001 - never stops a render: no shadow plane
            _log.exception("shadow ground not sized")
            gd = None
        if gd:
            block["shadow_catcher"] = {"z": gd["z"], "size": gd["size"]}
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


class _ReusedProc:
    """Stands for the render's process while the live view's Blender makes the picture (cancelling stops that Blender: the live view
    starts a new one when it rests)."""

    def __init__(self, panel, live):
        self._panel, self._live = panel, live

    def kill(self):
        panel = self._panel
        panel._live_line_off()
        self._live._final = None
        self._live._shutdown()
        panel._done(-1, None)

    def state(self):
        return QProcess.Running


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
        # Settings are in pages, as a person looks for them: Main (presets, look, quality), Image (the picture's
        # own corrections), Sky (background, clouds, sun, ground). The simple controls show; the rest folds.
        def page():
            host = QWidget()
            lay = QVBoxLayout(host)
            lay.setContentsMargins(0, 0, 4, 0)
            return host, lay
        host_main, col_main = page()
        host_image, col_image = page()
        host_sky, col_sky = page()
        col = col_sky

        # Your presets: a named copy of the settings, to come back to or to share as a file.
        box_presets = QGroupBox("Presets")
        form_p = QFormLayout(box_presets)
        self.user_presets = QComboBox()
        self.user_presets.setToolTip("Your saved presets. Choosing one puts its settings (look, adjustments, "
                                     "background, ground, engine, quality, output) in the panel.")
        self.user_presets.activated.connect(self._apply_user_preset)
        self.save_preset_btn = QPushButton("Save as preset…")
        self.save_preset_btn.setToolTip("Keeps the settings as they are now under a name, to use them again in any drawing.")
        self.save_preset_btn.clicked.connect(self.save_user_preset)
        self.preset_menu_btn = QToolButton()
        self.preset_menu_btn.setText("⋯")
        self.preset_menu_btn.setPopupMode(QToolButton.InstantPopup)
        self.preset_menu_btn.setToolTip("Delete a preset, or share them as files")
        menu = QMenu(self.preset_menu_btn)
        self.act_delete_preset = menu.addAction(tr("Delete this preset"), self.delete_user_preset)
        menu.addAction(tr("Export these settings to a file…"), self.export_user_preset)
        menu.addAction(tr("Import a preset from a file…"), self.import_user_preset)
        self.preset_menu_btn.setMenu(menu)
        prow = QHBoxLayout()
        prow.addWidget(self.user_presets, 1)
        prow.addWidget(self.preset_menu_btn)
        form_p.addRow(prow)
        form_p.addRow(self.save_preset_btn)
        self.reset_btn = QPushButton("Reset all settings")
        self.reset_btn.setToolTip("Puts every setting (style, adjustments, sky, background, ground, horizon, output) back to the "
                                  "defaults. Your saved presets are not touched.")
        self.reset_btn.clicked.connect(self.reset_all)
        form_p.addRow(self.reset_btn)
        col_main.addWidget(box_presets)
        self._refresh_user_presets()

        # The look: the scene's mood. Its sliders (the adjustments) are in the Image and Environment pages.
        box_look = QGroupBox("Look")
        form = QFormLayout(box_look)
        self.preset = QComboBox()
        for key in presets.ORDER:
            self.preset.addItem(presets.label(key, lang), key)
        self.preset.setCurrentIndex(max(0, self.preset.findData(st.value(_SETTINGS + "preset", "clear"))))
        self.preset.setToolTip("The light and the mood of the picture. Changing it puts that look's own values "
                               "in the adjustments of the Image and Environment pages.")
        form.addRow("Look", self.preset)
        form.addRow(self._caption("These change the scene itself: the preview and Render both show them."))
        self.sliders, self.slider_rows = {}, {}
        self._sky_labels, self._cam_labels, self._env_labels = {}, {}, {}
        box_pic = QGroupBox("Corrections")
        form_pic = QFormLayout(box_pic)
        self.fx = QGroupBox("Effects")                  # vignette, depth of field: a group of the Image page
        self.fx.form = QFormLayout(self.fx)
        box_skyadj = QGroupBox("Sky")
        form_skyadj = QFormLayout(box_skyadj)
        for key, (label, lo, hi, default, _unit) in presets.SLIDERS.items():
            block, _amb = presets.studio(self.preset.currentData())
            value = default if default is not None else block.get(key, 0.0)
            s_ = _slider(lo, hi, float(value))
            row = SliderRow(s_, presets.SLIDER_FORMATS[key], presets.SLIDER_HINTS[key])
            self.sliders[key], self.slider_rows[key] = s_, row
            if presets.SLIDER_PAGE[key] == "sky":
                self._sky_labels[key] = label           # added under the date and the hour, in their own order
                continue
            if presets.SLIDER_PAGE[key] == "camera":
                self._cam_labels[key] = label           # added to the Camera group of the Main tab
                continue
            if presets.SLIDER_PAGE[key] == "env":
                self._env_labels[key] = label           # the Fog group of the Environment page
                continue
            target = form_pic if key in presets.SIMPLE_SLIDERS else self.fx.form
            target.addRow(label, row)
        col_image.addWidget(box_pic)
        col_image.addWidget(self.fx)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        box_look.setVisible(False)       # no longer a group of the Main tab: the look stays as the panel's base setting
        col_main.addWidget(box_look)

        # The style of the render: how it is drawn (plain, white, a model of one material, lux, a sketch, a watercolour); every
        # style can have outlines, and each has settings of its own.
        from .section_panel import ColourButton
        box_style = QGroupBox("Style")
        form_s = QFormLayout(box_style)
        form_s.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self._form_style = form_s
        self.style_mode = QComboBox()
        for key, label in presets.STYLES.items():
            self.style_mode.addItem(tr(label), key)
        self.style_mode.setToolTip("How the picture is drawn. None: as it is. White: every material white. Model: one material "
                                   "for everything. Light: the lux each surface receives, in false colour. Sketch: pencil lines "
                                   "on paper. Watercolour: washes of colour. All can have outlines.")
        form_s.addRow("Style", self.style_mode)
        self.style_width = widgets.NumberSlider(0.0, 4.0, 0.1, "{:.1f} px", special="No outlines")
        self.style_width.setToolTip("The thickness of the outlines, in pixels (0 = none).")
        form_s.addRow("Outlines", self.style_width)
        scol = QHBoxLayout()
        self.style_colour = ColourButton(presets.STYLE_DEFAULT["color"], "Outline colour", linear=True)
        self.style_colour.setToolTip("The colour of the outlines.")
        scol.addWidget(self.style_colour, 1)
        self.style_colour_box = QWidget()
        self.style_colour_box.setLayout(scol)
        scol.setContentsMargins(0, 0, 0, 0)
        form_s.addRow("Outline colour", self.style_colour_box)
        # Model: one material for everything
        self.style_material = widgets.RefreshCombo(self._fill_style_materials)
        self.style_material.setToolTip("The material every object wears: a plain colour, or a material of the drawing "
                                       "(with its picture and settings).")
        form_s.addRow("Material", self.style_material)
        self.style_model_colour = ColourButton(presets.STYLE_DEFAULT["model_color"], "Model colour", linear=True)
        self.style_model_colour.setToolTip("The colour of the model (when the material is «A colour»).")
        form_s.addRow("Model colour", self.style_model_colour)
        # Light
        self.style_lux = widgets.NumberSlider(0.0, 200000.0, 1000.0, "{:,.0f} lx", special="Automatic")
        self.style_lux.setToolTip("The top of the colour scale, in lux. Automatic: round numbers chosen from the picture. The light "
                                  "is a clear day's sun (about 100 000 lx) and the lamps in lumens; a white matte surface is assumed.")
        form_s.addRow("Scale up to", self.style_lux)
        # Sketch
        self.style_noise = widgets.NumberSlider(0.0, 1.0, 0.05, "{:.0%}")
        self.style_noise.setToolTip("How irregular the stroke is: straight, or wobbling and gone over twice like a pencil.")
        form_s.addRow("Irregular stroke", self.style_noise)
        self.style_extend = widgets.NumberSlider(0.0, 1.0, 0.05, "{:.0%}")
        self.style_extend.setToolTip("How far the lines run past their corners, as a draughtsman's do.")
        form_s.addRow("Line extension", self.style_extend)
        # Watercolour
        self.style_wet = widgets.NumberSlider(0.0, 1.0, 0.05, "{:.0%}")
        self.style_wet.setToolTip("How far the colour spreads: dry and detailed ← → wet washes.")
        form_s.addRow("Wetness", self.style_wet)
        self.style_edges = widgets.NumberSlider(0.0, 1.0, 0.05, "{:.0%}")
        self.style_edges.setToolTip("How dark the pigment pools along the edges.")
        form_s.addRow("Edges", self.style_edges)
        self.style_paper = widgets.NumberSlider(0.0, 1.0, 0.05, "{:.0%}")
        self.style_paper.setToolTip("How rough the paper is: its grain shows in the colour.")
        form_s.addRow("Paper", self.style_paper)
        self.style_note = self._caption("")
        form_s.addRow(self.style_note)
        self._style_rows = {
            "white": (), "model": (self.style_material, self.style_model_colour), "light": (self.style_lux,),
            "sketch": (self.style_noise, self.style_extend), "watercolour": (self.style_wet, self.style_edges, self.style_paper),
            "none": ()}
        col_main.addWidget(box_style)
        col_main.addWidget(self._build_camera_box())          # the camera, under the style

        # The background: the look's own sky, a 360° panorama, or one fixed picture.
        box_bg = QGroupBox("Background")
        form2 = QFormLayout(box_bg)
        self.bg_mode = QComboBox()
        self.bg_mode.addItem(tr("Sky of the look"), "sky")
        self.bg_mode.addItem(tr("360° panorama"), "pano")
        self.bg_mode.addItem(tr("Fixed picture"), "picture")
        saved_pano = str(st.value(_SETTINGS + "hdri", "") or "")
        saved_pic = str(st.value(_SETTINGS + "backdrop", "") or "")
        mode0 = str(st.value(_SETTINGS + "bg_mode", "pano" if saved_pano else ("picture" if saved_pic else "sky")))
        self.bg_mode.setCurrentIndex(max(0, self.bg_mode.findData(mode0)))
        self.bg_mode.setToolTip("What is seen behind the model. Sky of the look: the sky the look makes. "
                                "360° panorama: a photo all round you, which also lights the model. "
                                "Fixed picture: one flat picture behind it, which stays put when the view turns.")
        form2.addRow("Show", self.bg_mode)
        self.bg_note = self._caption("")
        self.bg_note.setStyleSheet("color: #b36b00; font-size: 11px")
        form2.addRow(self.bg_note)
        self.hdri = QComboBox()
        self.hdri.setToolTip(HDRI_TIP)
        self.hdri.addItem(tr("None"), "")
        for path in bundled_hdris():
            self.hdri.addItem(f"{path.stem.capitalize()} (Blender, 1K)", str(path))
        for path in st.value(_SETTINGS + "hdri_recent", []) or []:
            if path and Path(path).is_file() and self.hdri.findData(path) < 0:
                self.hdri.addItem(Path(path).name, path)
        self.hdri.addItem(tr("Choose a file…"), _CHOOSE)
        saved = saved_pano
        if saved and self.hdri.findData(saved) < 0 and Path(saved).is_file():
            self.hdri.insertItem(self.hdri.count() - 1, Path(saved).name, saved)
        self.hdri.setCurrentIndex(max(0, self.hdri.findData(saved)))
        self._hdri_prev = self.hdri.currentIndex()
        self.hdri.currentIndexChanged.connect(self._hdri_changed)
        form2.addRow("Image", self.hdri)
        self.hdri_rotation = _slider(0.0, 360.0, float(st.value(_SETTINGS + "hdri_rotation", 0.0)), 360)
        self.hdri_rotation_row = SliderRow(self.hdri_rotation, "{:.0f}°", "Turns the image about the vertical")
        self.hdri_strength = _slider(-3.0, 3.0, float(st.value(_SETTINGS + "hdri_strength", 0.0)), 120)
        self.hdri_strength_row = SliderRow(self.hdri_strength, "{:+.1f} stops",
                                           "Its brightness, against the lamps and the look's light")
        # the fixed picture's own controls
        self.backdrop = QComboBox()
        self.backdrop.setToolTip("A picture (.jpg, .png, .exr…) shown flat behind the model.")
        self.backdrop.addItem(tr("None"), "")
        for path in st.value(_SETTINGS + "backdrop_recent", []) or []:
            if path and Path(path).is_file() and self.backdrop.findData(path) < 0:
                self.backdrop.addItem(Path(path).name, path)
        self.backdrop.addItem(tr("Choose a file…"), _CHOOSE)
        if saved_pic and self.backdrop.findData(saved_pic) < 0 and Path(saved_pic).is_file():
            self.backdrop.insertItem(self.backdrop.count() - 1, Path(saved_pic).name, saved_pic)
        self.backdrop.setCurrentIndex(max(0, self.backdrop.findData(saved_pic)))
        self._backdrop_prev = self.backdrop.currentIndex()
        self.backdrop.currentIndexChanged.connect(self._backdrop_changed)
        form2.addRow("Picture", self.backdrop)
        self.backdrop_fit = QComboBox()
        self.backdrop_fit.addItem(tr("Fill the frame (crops)"), "fill")
        self.backdrop_fit.addItem(tr("Whole picture"), "fit")
        self.backdrop_fit.addItem(tr("Stretch"), "stretch")
        self.backdrop_fit.setCurrentIndex(max(0, self.backdrop_fit.findData(st.value(_SETTINGS + "backdrop_fit", "fill"))))
        self.backdrop_fit.setToolTip("How the picture sits in the frame: it covers it (and what overflows is cropped), "
                                     "it shows whole (the look's sky around it) or it is stretched to the frame.")
        form2.addRow("Fit", self.backdrop_fit)
        self.backdrop_strength = _slider(-3.0, 3.0, float(st.value(_SETTINGS + "backdrop_strength", 0.0)), 120)
        self.backdrop_strength_row = SliderRow(self.backdrop_strength, "{:+.1f} stops",
                                               "How bright the picture is in the render")
        form2.addRow("Picture brightness", self.backdrop_strength_row)
        # advanced
        self.bg_more = widgets.Collapsible(tr("Advanced"), "bg_more")
        self.hdri_height = _slider(0.5, 30.0, float(st.value(_SETTINGS + "hdri_height", 2.5)), 295)
        self.hdri_height_row = SliderRow(
            self.hdri_height, "{:.1f} m",
            "How high above the ground the image was taken from (a street panorama: about 2.5 m; a roof or "
            "a drone: more). It sets how the ground of the image is laid under the model: wrong, and the ground "
            "looks stretched or too close.")
        self.bg_more.form.addRow("Rotation", self.hdri_rotation_row)
        self.bg_more.form.addRow("Brightness", self.hdri_strength_row)
        self.bg_more.form.addRow("Viewpoint height", self.hdri_height_row)
        self.hdri_light = QCheckBox("Lights the scene")
        self.hdri_light.setToolTip("On: the image lights the model (its sun casts the shadows). "
                                   "Off: the look lights it, the image is only seen behind it.")
        self.hdri_light.setChecked(str(st.value(_SETTINGS + "hdri_light", "true")).lower() != "false")
        self.hdri_light.toggled.connect(self._hdri_enable)
        form2.addRow("", self.hdri_light)            # in view: it decides who lights the scene
        form2.addRow(self.bg_more)
        self._bg_rows = {
            "pano": [self.hdri, self.hdri_light],
            "picture": [self.backdrop, self.backdrop_fit, self.backdrop_strength_row],
        }
        self._form_bg = form2
        self.bg_mode.currentIndexChanged.connect(self._bg_enable)
        col.addWidget(box_bg)

        # The ground under the model.
        box_ground = QGroupBox("Ground")
        form_g = QFormLayout(box_ground)
        self.ground = QCheckBox("Generated ground")
        self.ground.setToolTip(
            "On: a ground is made under the model, with the look's colour, melting into the horizon. "
            "Off: no ground is added (the model's own terrain, or the 360° background's ground, shows).")
        self.ground.setChecked(str(st.value(_SETTINGS + "ground", "true")).lower() != "false")
        self.ground.toggled.connect(lambda on: QSettings().setValue(_SETTINGS + "ground", "true" if on else "false"))
        form_g.addRow("", self.ground)
        self.ground_shadow = QCheckBox("Shadow on the floor")
        self.ground_shadow.setToolTip(
            "With no generated ground: the model still throws its shadow on the floor, at its foot, and "
            "nothing else of the floor is drawn (the background, or the 360° image, shows through). "
            "Needs the sun or a light that casts shadows.")
        self.ground_shadow.setChecked(str(st.value(_SETTINGS + "ground_shadow", "true")).lower() != "false")
        self.ground_shadow.toggled.connect(lambda on: QSettings().setValue(_SETTINGS + "ground_shadow", "true" if on else "false"))
        self.ground.toggled.connect(lambda on: self.ground_shadow.setEnabled(not on))
        self.ground_shadow.setEnabled(not self.ground.isChecked())
        form_g.addRow("", self.ground_shadow)
        self.ground_type = QComboBox()
        self.ground_type.addItem(tr("Look's own"), "")
        for key, (label, _c, _r) in presets.GROUND_TYPES.items():
            self.ground_type.addItem(tr(label), key)
        self.ground_type.addItem(tr("Custom"), "custom")
        self.ground_type.setToolTip("A ready-made ground: its colour and how shiny it is. Change either under Advanced "
                                    "and it becomes Custom.")
        self.ground_type.activated.connect(self._ground_type_chosen)
        form_g.setRowWrapPolicy(QFormLayout.WrapLongRows)          # a narrow tray: the label above its field
        form_g.insertRow(0, "Type", self.ground_type)
        # advanced: its colour, shine, haze and height, and a material of the model on it
        self.ground_more = widgets.Collapsible(tr("Advanced"), "ground_more")
        from .section_panel import ColourButton
        crow = QHBoxLayout()
        self.ground_colour = ColourButton(self._ground_default_colour(), "Ground colour", linear=True)
        self.ground_colour.setToolTip("The ground's own colour instead of the look's.")
        self.ground_colour.changed.connect(self._ground_colour_edited)
        self.ground_colour_reset = QToolButton()
        self.ground_colour_reset.setText("×")
        self.ground_colour_reset.setToolTip("Back to the look's colour")
        self.ground_colour_reset.clicked.connect(self._ground_colour_reset)
        crow.addWidget(self.ground_colour, 1)
        crow.addWidget(self.ground_colour_reset)
        self._ground_color = None                  # None: the look's
        self.ground_more.form.addRow("Colour", crow)
        self.ground_rough = _slider(0.0, 1.0, 0.9, 100)
        self.ground_rough_row = SliderRow(self.ground_rough, "{:.2f}",
                                          "0 a mirror (wet pavement), 1 fully matte (grass, sand)")
        self.ground_more.form.addRow("Roughness", self.ground_rough_row)
        self.ground_haze = _slider(0.0, 4.0, 1.0, 40)
        self.ground_haze_row = SliderRow(self.ground_haze, "×{:.1f}",
                                         "How far the ground goes before it melts into the horizon: 1 the usual, "
                                         "more for a clearer far distance, 0 no haze")
        self.ground_more.form.addRow("Horizon haze", self.ground_haze_row)
        self.ground_offset = QDoubleSpinBox()
        self.ground_offset.setRange(-10.0, 10.0)
        self.ground_offset.setDecimals(2)
        self.ground_offset.setSingleStep(0.05)
        self.ground_offset.setSuffix(" m")
        self.ground_offset.setKeyboardTracking(False)
        self.ground_offset.setToolTip("Raises (+) or lowers (−) the generated ground from the model's foot.")
        self.ground_more.form.addRow("Height", self.ground_offset)
        self.ground_radius = widgets.RadiusSlider(2000.0, 10.0)
        self.ground_radius.setToolTip("The radius of the generated ground. The haze melts it into the horizon over its outer "
                                      "two thirds, so its edge is never seen. Automatic: a very large ground (the haze starts "
                                      "at 120 m).")
        self.ground_more.form.addRow("Ground radius", self.ground_radius)
        self.ground_grass = widgets.RadiusSlider(500.0, 5.0)
        self.ground_grass.setToolTip("When the ground's material is grass: the radius of the circle of grass round the model. "
                                     "Automatic: the model's farthest point plus 10 m.")
        self.ground_more.form.addRow("Grass radius", self.ground_grass)
        self._grass_rows = (self.ground_grass,)
        self.ground_grass_note = QLabel("")
        self.ground_grass_note.setWordWrap(True)
        self.ground_grass_note.setStyleSheet("color: gray; font-size: 11px")
        self.ground_more.form.addRow(self.ground_grass_note)
        self.ground_grass.valueChanged.connect(lambda _v: self._ground_grass_hint())
        self.ground_rough.valueChanged.connect(lambda _v: self._ground_custom())
        self.ground_offset.valueChanged.connect(lambda _v: None)
        self.ground_material = widgets.RefreshCombo(self._fill_ground_materials)
        self.ground_material.setToolTip(
            "A material of the model for the generated ground (grass, paving, sand, water…): it repeats at its own "
            "size over the ground. «Look's colour»: the plain colour of the look.")
        self._fill_ground_materials()
        self.ground_more.form.addRow("Material", self.ground_material)
        self.ground_tile = QDoubleSpinBox()
        self.ground_tile.setRange(0.0, 100.0)
        self.ground_tile.setDecimals(2)
        self.ground_tile.setSingleStep(0.5)
        self.ground_tile.setSuffix(" m")
        self.ground_tile.setSpecialValueText(tr("Picture's own size"))
        self.ground_tile.setKeyboardTracking(False)
        self.ground_tile.setToolTip("How big one repeat of the material's picture is on the ground. "
                                    "The first value uses the picture's own size.")
        self.ground_more.form.addRow("Tile size", self.ground_tile)
        self.ground.toggled.connect(self.ground_more.setEnabled)
        self.ground_more.setEnabled(self.ground.isChecked())
        form_g.addRow(self.ground_more)
        col.addWidget(box_ground)
        # The horizon: distant mountains, hills, forest or city that hide where the ground meets the sky.
        box_horizon = QGroupBox("Horizon")
        form_h = QFormLayout(box_horizon)
        form_h.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.skyline_type = QComboBox()
        self.skyline_type.addItem(tr("None"), "")
        for key, label in presets.SKYLINE_TYPES.items():
            self.skyline_type.addItem(tr(label), key)
        self.skyline_type.setToolTip("Distant mountains, hills, a forest or a city on the horizon: they hide the line where "
                                     "the ground meets the sky, melt into the sky with distance and cast no shadow.")
        form_h.addRow("Skyline", self.skyline_type)
        self.skyline_height = widgets.NumberSlider(0.5, 20.0, 0.5, "{:.1f}°")
        self.skyline_height.setValue(4.0)
        self.skyline_height.setToolTip("How high the tallest peaks (or towers, or trees) rise above the horizon, in degrees.")
        form_h.addRow("Height", self.skyline_height)
        self.skyline_more = widgets.Collapsible(tr("Advanced"), "skyline_more")
        self.skyline_distance = widgets.RadiusSlider(5000.0, 50.0)
        self.skyline_distance.setToolTip("How far its farthest layer is. Automatic: at the edge of the ground (its radius, or "
                                         "1 200 m when the ground is Automatic).")
        self.skyline_more.form.addRow("Distance", self.skyline_distance)
        self.skyline_seed = QSpinBox()
        self.skyline_seed.setRange(0, 9999)
        self.skyline_seed.setToolTip("Another number, another outline (the same number always gives the same one).")
        self.skyline_more.form.addRow("Shape", self.skyline_seed)
        from .section_panel import ColourButton
        scol = QHBoxLayout()
        self.skyline_colour = ColourButton(presets.SKYLINE_COLOURS["mountains"], "Skyline colour", linear=True)
        self.skyline_colour.setToolTip("The colour of the nearest layer (the farther ones are paler). By default the type's own.")
        self.skyline_colour.changed.connect(self._skyline_colour_edited)
        self.skyline_colour_reset = QToolButton()
        self.skyline_colour_reset.setText("×")
        self.skyline_colour_reset.setToolTip("Back to the type's colour")
        self.skyline_colour_reset.clicked.connect(self._skyline_colour_reset)
        scol.addWidget(self.skyline_colour, 1)
        scol.addWidget(self.skyline_colour_reset)
        self._skyline_color = None
        self.skyline_more.form.addRow("Colour", scol)
        form_h.addRow(self.skyline_more)
        self.skyline_note = self._caption("")
        form_h.addRow(self.skyline_note)
        self.skyline_type.currentIndexChanged.connect(lambda _i: self._skyline_enable())
        self.skyline_type.currentIndexChanged.connect(self._swatches_follow)
        self.preset.currentIndexChanged.connect(self._swatches_follow)
        col.addWidget(box_horizon)
        # Fog: part of the place, like the horizon it veils (it was among the picture's effects).
        box_fog = QGroupBox("Fog")
        form_fog = QFormLayout(box_fog)
        form_fog.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.fog_note = self._caption("")
        self.fog_note.setVisible(False)
        form_fog.addRow(self.fog_note)
        for key in ("fog", "fog_start"):
            form_fog.addRow(self._env_labels[key], self.slider_rows[key])
        col.addWidget(box_fog)
        self._fog_seen = "unset"
        self._fog_timer = QTimer(self)                  # the drawing's fog is set in IngeTrazo's Styles: noticed when it changes
        self._fog_timer.setInterval(1000)
        self._fog_timer.timeout.connect(self._update_fog_note)
        self._fog_timer.start()
        col_sky.insertWidget(1, box_skyadj)          # after the background, before the ground

        # What only the final render uses.
        box_final = QGroupBox("Quality")
        form3 = QFormLayout(box_final)
        form3.addRow(self._caption("Quality is for Render; the preview has its own engine."))
        self.final_more = widgets.Collapsible(tr("Advanced"), "final_more")
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
        self.final_more.form.addRow("Preview", self.preview_engine)
        self.preview_quality = QComboBox()
        for key, label in (("fast", "Fast"), ("normal", "Normal"), ("high", "High")):
            self.preview_quality.addItem(tr(label), key)
        self.preview_quality.setCurrentIndex(max(0, self.preview_quality.findData(st.value(_SETTINGS + "preview_quality", "normal"))))
        self.preview_quality.setToolTip(
            "How sharp the preview is, which is also how quickly it answers (changing a material or a light, moving the camera). "
            "Fast: smaller, rougher pictures. High: bigger, cleaner ones. Render has its own quality.")
        self.preview_quality.currentIndexChanged.connect(self._preview_quality_chosen)
        self.final_more.form.addRow("Preview quality", self.preview_quality)
        self.engine = QComboBox()
        self.engine.addItem(tr("EEVEE — fast"), "eevee")
        self.engine.addItem(tr("Cycles — best quality"), "cycles")
        self.engine.setCurrentIndex(max(0, self.engine.findData(st.value(_SETTINGS + "engine", "eevee"))))
        self.engine.setToolTip("EEVEE: about 3 s. Cycles: the truest light, about 5 s on an RTX card "
                               "(the Interior look needs it).")
        self.final_more.form.addRow("Render", self.engine)
        self.quality = widgets.ChoiceButtons([tr(q) for q in ("Draft", "Medium", "High")])
        self.quality.setCurrentIndex(int(st.value(_SETTINGS + "quality", 1)))
        self.quality.setToolTip("How many samples: more is less noisy and slower.")
        form3.addRow(self.quality)
        form3.addRow(self.final_more)
        # The picture's size and file: the Output tab (its width is the panel's ``width``).
        from .output_panel import OutputTab
        self.output_tab = OutputTab(self, width=int(st.value(_SETTINGS + "width", 1920)))
        self.width = self.output_tab.width
        col_main.addWidget(box_final)
        for lay in (col_main, col_image):
            lay.addStretch(1)
        # Tabs: the global settings, then the lights (more to come: place and
        # sun, output). What is under them (materials, preview, status) serves all.
        from .lights_panel import LightsTab
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        def scrolled(widget):
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sc.setWidget(widget)
            return sc
        self.tabs.addTab(scrolled(host_main), "Main")
        self.tabs.addTab(scrolled(host_image), "Image")
        self.tabs.addTab(scrolled(host_sky), "Environment")
        # The lights have a window of their own, like the materials (see open_lights).
        from .lights_panel import LightEditor
        self.lights_tab = LightsTab(app)
        self.lights_window = LightEditor(self.lights_tab, self)
        self.lights_tab.find_blender = self.blender_or_none
        self.lights_tab.edit_scene = lambda: self.open_in_blender(lights=True)      # the whole model in the Blender
        translate_on_show(self.lights_window)
        from .sun_panel import SunTab
        self.sun_tab = SunTab(app, self)
        from .section_panel import SectionTab
        self.section_tab = SectionTab(app, live=self._preview_open)
        # The sun's place and date belong to the sky: folded under it.
        from .sun_panel import SunQuick
        self.sun_quick = SunQuick(self.sun_tab)
        self.sun_tab.quick = self.sun_quick
        # The look is no longer chosen by name: the day or the night follows the sun, and an interior is a box to tick.
        self.interior = QCheckBox("Interior")
        self.interior.setToolTip("The picture is of a room: it is metered for the inside, and the window is allowed to burn out. "
                                 "Leave it off for a view outside.")
        self.interior.setChecked(self.preset.currentData() == "interior")
        self.interior.toggled.connect(self._interior_toggled)
        self.preset.currentIndexChanged.connect(lambda _i: self.interior.blockSignals(True) or self.interior.setChecked(
            self.preset.currentData() == "interior") or self.interior.blockSignals(False))
        form_skyadj.addRow(self.interior)
        form_skyadj.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form_skyadj.addRow("Date", self.sun_quick.date_box)           # the date and the hour, always in view; the exact ones are folded
        form_skyadj.addRow("Hour", self.sun_quick.hour_box)
        for key in ("sun_scale", "moon", "clouds", "stars"):      # the sun (or the moonlight), the clouds, the stars
            form_skyadj.addRow(self._sky_labels[key], self.slider_rows[key])
        self._form_skyadj = form_skyadj
        self.sun_tab._show_sun()                     # (and the night sliders, shown only at night)
        self.sun_more = widgets.Collapsible(tr("Place and date"), "sun_more")
        self.sun_more.form.addRow(self.sun_tab)
        form_skyadj.addRow(self.sun_more)            # the sun's group holds its place and date
        col_sky.addStretch(1)
        for tab_widget, title in ((self.section_tab, "Section"), (self.output_tab, "Output")):
            self.tabs.addTab(scrolled(tab_widget), title)
        self.tabs.setCurrentIndex(min(self.tabs.count() - 1, max(0, int(st.value(_SETTINGS + "tab", 0) or 0))))
        self.tabs.currentChanged.connect(lambda i: QSettings().setValue(_SETTINGS + "tab", int(i)))
        for combo in self.findChildren(QComboBox):       # a long name must not widen a narrow tray
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
        outer.addWidget(self.tabs, 1)

        self.help_btn = QToolButton()
        self.help_btn.setText("?")
        self.help_btn.setToolTip("How Render Studio works, and what each control does")
        self.help_btn.clicked.connect(lambda: self.show_help("panel"))
        self.tabs.setCornerWidget(self.help_btn, Qt.TopRightCorner)          # the general help, beside the tabs
        self.materials_btn = QPushButton("Materials…")
        self.materials_btn.setToolTip("How each material renders: polish, metal, relief, glass, glow.")
        self.materials_btn.clicked.connect(self.open_materials)
        self.lights_btn = QPushButton("Lights…")
        self.lights_btn.setToolTip("Point, spot, area and sun lights for the render: the list, each light's settings, "
                                   "and placing them in the model.")
        self.lights_btn.clicked.connect(self.open_lights)
        mrow = QHBoxLayout()
        mrow.addWidget(self.materials_btn, 1)
        mrow.addWidget(self.lights_btn, 1)
        outer.addLayout(mrow)
        self.editor = None
        self._live = None
        self._prep = None
        self._preparing = False
        self._direct = False
        self._save_to = None
        self._cancelled = False
        # Render, and under its arrow «Render and save…» and the scenes; Open preview, and under its arrow «Open in Blender…».
        self.render_save_btn = QAction("Render and save…", self)
        self.render_save_btn.setToolTip("Asks where to save, makes the final picture and saves it straight away, "
                                        "without the live preview and without retouching.")
        self.render_save_btn.triggered.connect(lambda: self.render_and_save())
        self.render_scenes_btn = QAction("Render the selected scenes", self)
        self.render_scenes_btn.setToolTip("Renders the scenes ticked in the Output tab, one after another, into its folder.")
        self.render_scenes_btn.triggered.connect(lambda: self.render_scenes())
        self.render_btn = widgets.split_button(
            "Render", lambda: self.render_main(),
            "Makes the final picture now, with the Engine, Quality and size above, without the live preview. It opens in "
            "a window with the retouch tools and Save image…. With «Scenes» chosen in the Output tab it renders those.",
            [self.render_save_btn, self.render_scenes_btn])
        outer.addWidget(self.render_btn)
        self.expert_btn = QAction("Open in Blender…", self)
        self.expert_btn.setToolTip("Expert mode: opens the scene, as Render would make it, in a Blender with its own window "
                                   "to work in it. The file is saved first; nothing is rendered.")
        self.expert_btn.triggered.connect(lambda: self.open_in_blender())
        self.preview_btn = widgets.split_button(
            "Open preview…", lambda: self.open_preview(),
            "Opens the preview window: a live view of the scene that you can zoom and move, with Render (then retouch and "
            "save) and Render and save…", [self.expert_btn])
        outer.addWidget(self.preview_btn)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        for combo in (self.engine, self.quality):
            combo.currentIndexChanged.connect(self._update_summary)
        self.width.valueChanged.connect(self._update_summary)
        for combo in self.findChildren(QComboBox):       # every list box, the late ones too: a long name must not widen a narrow tray
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.setSizePolicy(QSizePolicy.Ignored, combo.sizePolicy().verticalPolicy())     # may be narrower than its text
        for box in self.findChildren(QCheckBox):           # a long label must not widen a narrow tray either
            box.setSizePolicy(QSizePolicy.Ignored, box.sizePolicy().verticalPolicy())
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

    def blender_or_none(self):
        try:
            found = self.blender()
        except Exception:  # noqa: BLE001
            return None
        return found if found is not None and getattr(found, "command", None) else None

    def check_blender(self):
        """Show the «needs Blender» box, and switch off Render and Live view, while
        there is none. Returns the Blender found, or None."""
        try:
            found = self.blender()
        except Exception:  # noqa: BLE001 - never breaks the panel
            found = None
        self.need_box.setVisible(found is None)
        self.preview_btn.setEnabled(found is not None)
        self.render_btn.setEnabled(found is not None)
        self.render_save_btn.setEnabled(found is not None)
        self.expert_btn.setEnabled(found is not None)
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

    def _update_fog_note(self) -> None:
        """When the drawing has fog on, it is the render's fog: the sliders of this group wait (they are used again when it is off)."""
        try:
            fog = drawing_fog.of(self.app.scene)
        except Exception:  # noqa: BLE001
            fog = None
        key = json.dumps(fog, sort_keys=True)
        if key == self._fog_seen:
            return
        self._fog_seen = key
        for k in ("fog", "fog_start"):
            self.slider_rows[k].setEnabled(fog is None)
        if fog is None:
            self.fog_note.setVisible(False)
            return
        self.fog_note.setText(tr("The drawing's own fog is on (it starts at {start} m and is {thickness} m thick, as in the 3D view): the render "
                                 "has that one. These sliders are used when it is off.", start=f"{fog['start']:g}", thickness=f"{fog['thickness']:g}"))
        self.fog_note.setVisible(True)

    def live_key(self):
        """What the live scene depends on besides the camera, in three parts:
        (the model, the materials' render settings, the look with every
        setting and the proportions)."""
        try:
            from . import sun_site
            doc = (json.dumps(self.settings_dict(), sort_keys=True) + studio_lights.signature(self.app.scene)
                   + section.signature(self.app.scene, self.section_tab.settings())
                                      + json.dumps(sun_site.site(self.app.scene), sort_keys=True)
                   + json.dumps(drawing_fog.of(self.app.scene), sort_keys=True)
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

    def _preview_quality_chosen(self, _i) -> None:
        QSettings().setValue(_SETTINGS + "preview_quality", self.preview_quality.currentData())
        if getattr(self, "_live", None) is not None:
            self._live.quality_changed()

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
            height=height, hdri=self.hdri_settings(), backdrop=self.backdrop_settings(), ground=self.ground.isChecked(),
                ground_material=self.ground_material_settings(), ground_look=self.ground_look_settings(), skyline=self.skyline_settings(), style=self.style_settings(),
            ground_shadow=self.ground_shadow.isChecked(),
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

    def open_in_blender(self, lights: bool = False):
        """Expert mode: export the model and open the scene (as Render would make it) in a Blender with its
        window, to work in it. The file is saved first; a modal says what is happening. ``lights``: it is for editing
        the lights (the Lights window's «Edit in Blender…»): the .blend is watched and the lights come back."""
        from core import render_blender as rb
        found = self.check_blender()
        if found is None:
            self.status.setText(tr("Blender was not found: choose it above."))
            return None
        if self._preparing or self._prep is not None:
            return None
        from .prep_dialog import PrepDialog
        self._preparing = True
        self._prep = PrepDialog(self.window if self.window is not None and self.window.isVisible() else self,
                                "Preparing the model…")
        self._prep.canceled.connect(self._prep_cancelled_expert)
        self._cancel_expert = False
        try:
            self._remember()
            work = rb.work_base().parent / "render-studio" / ("expert-" + time.strftime("%Y%m%d-%H%M%S"))
            width, height = self.output_tab.frame()
            job, script = write_studio_job(
                self.app.viewport.scene, self.render_camera(), work, self.preset.currentData(),
                self.slider_values(), engine=self.engine.currentData(), quality=self.quality.currentIndex(),
                width=width, height=height, hdri=self.hdri_settings(), backdrop=self.backdrop_settings(), ground=self.ground.isChecked(),
                ground_material=self.ground_material_settings(), ground_look=self.ground_look_settings(), skyline=self.skyline_settings(), style=self.style_settings(),
                ground_shadow=self.ground_shadow.isChecked(), materials=self.material_specs(),
                output=self.output_tab.settings(), doc_path=self.doc_path(),
                section_opts=self.section_tab.settings(), progress=self._export_progress())
            data = json.loads(job.read_text(encoding="utf-8"))
            blend = work / "scene.blend"
            data["expert"], data["blend"] = True, str(blend)
            job.write_text(json.dumps(data, indent=2), encoding="utf-8")
            if self._cancel_expert:
                return None
            self._prep.waiting("Starting Blender…")
            if lights:
                from .blender_session import BlenderSession
                tab = self.lights_tab
                if tab._session is not None:
                    tab._session.stop()
                tab._session = BlenderSession(self.app, "lights", found, tab, launch=(
                    [*found.command[1:], "--python", str(script), "--", str(job)], blend, work))
                tab._session.changed.connect(tab._say)
                tab._session.failed.connect(tab._say)
                if not tab._session.start():
                    raise RuntimeError("Blender did not start")
                tab._say(tr("Opened in Blender with the whole scene. Edit the lights there and save (Ctrl+S): they come back here."))
                return blend
            proc = QProcess(self)
            env = QProcessEnvironment()
            for k, v in rb.clean_env().items():
                env.insert(k, v)
            proc.setProcessEnvironment(env)
            # Its own window and the person's own Blender settings (no --factory-startup, no -b).
            proc.setProgram(found.command[0])
            proc.setArguments([*found.command[1:], "--python", str(script), "--", str(job)])
            res = proc.startDetached()                  # (bool, pid) or bool, by the binding
            started = res[0] if isinstance(res, tuple) else bool(res)
            if not started:
                raise RuntimeError("Blender did not start")
            self._set_status(tr("Opened in Blender. The scene is saved in {path}", path=str(blend)))
            return blend
        except Exception as exc:  # noqa: BLE001 - say it, never crash the app
            _log.exception("could not open Blender")
            self._set_status(tr("Could not open Blender: {error}", error=str(exc)))
            return None
        finally:
            self._preparing = False
            self._prep_close()

    def _prep_cancelled_expert(self):
        self._cancel_expert = True
        self._prep = None

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
        if prep and not self._live.active and not self._live.usable and self._prep is None:
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
        if self._live is not None and (self._live.active or self._live.usable):
            self._live.stop()

    # ---- the camera: projection and angle of view (the 3D view's own, as IngeTrazo's Camera panel sets them) ----
    def _build_camera_box(self):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QButtonGroup
        box = QGroupBox("Camera")
        lay = QVBoxLayout(box)
        row = QHBoxLayout()
        self.proj_group = QButtonGroup(self)
        self.proj_group.setExclusive(True)
        self.proj_buttons = {}
        try:
            from views.icons import tool_icon                   # the program's own icons
        except Exception:  # noqa: BLE001 - a host without them: the names alone
            tool_icon = None
        for mode, label, tip in (("parallel", "Parallel", "Parallel projection: no vanishing points; plans, elevations, isometrics."),
                                 ("perspective", "Perspective", "Perspective: the view as the eye sees it."),
                                 ("two_point", "Two-point", "Two-point perspective: the verticals stay vertical, the usual view for architecture.")):
            b = QToolButton()
            b.setCheckable(True)
            b.setAutoRaise(False)
            icon = tool_icon("proj_" + mode) if tool_icon else QIcon()
            b.setIcon(icon)
            b.setIconSize(QSize(40, 40))
            b.setMinimumSize(52, 52)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            if icon.isNull():
                b.setText(tr(label))
            b.setToolTip(tip)
            b.setProperty("mode", mode)
            self.proj_group.addButton(b)
            self.proj_buttons[mode] = b
            row.addWidget(b)
            b.clicked.connect(lambda _c=False, m=mode: self._set_projection(m))
        lay.addLayout(row)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.fov = widgets.NumberSlider(10.0, 120.0, 1.0, "{:.0f}°")
        self.fov.setToolTip("The angle of view of the camera (the 3D view's): wide at the right, telephoto at the left. "
                            "A parallel view has none.")
        self.fov.valueChanged.connect(self._set_fov)
        form.addRow("Angle of view", self.fov)
        self.fov_note = self._caption("")
        form.addRow(self.fov_note)
        for key in ("dof", "focus"):                    # depth of field and the focal point
            form.addRow(self._cam_labels[key], self.slider_rows[key])
        lay.addLayout(form)
        self._cam_timer = QTimer(self)                   # the camera moves by many hands: follow it while the panel is shown
        self._cam_timer.setInterval(500)
        self._cam_timer.timeout.connect(self.refresh_camera)
        self._cam_timer.start()
        self.refresh_camera()
        return box

    def refresh_camera(self) -> None:
        cam = getattr(getattr(self.app, "viewport", None), "camera", None)
        if cam is None or not hasattr(cam, "projection_mode") or not self.isVisible():
            return
        mode = cam.projection_mode()
        b = self.proj_buttons.get(mode)
        if b is not None and not b.isChecked():
            b.setChecked(True)
        persp = bool(cam.perspective)
        self.fov.setEnabled(persp)
        if abs(self.fov.value() - cam.fov_deg) > 0.5 and not self.fov.slider.isSliderDown():
            self.fov.blockSignals(True)
            self.fov.setValue(max(10.0, min(120.0, float(cam.fov_deg))))
            self.fov.blockSignals(False)
        self.fov_note.setText(tr("{mm:.0f} mm lens on a full-frame camera's picture", mm=cam.focal_mm) if persp else tr("A parallel view has no angle of view."))

    def _set_projection(self, mode: str) -> None:
        vp = self.app.viewport
        if hasattr(vp, "set_projection"):
            vp.set_projection(mode)
        else:
            vp.camera.set_projection(mode)
        vp.update() if hasattr(vp, "update") else None
        self.refresh_camera()

    def _set_fov(self, degrees: float) -> None:
        cam = self.app.viewport.camera
        if not cam.perspective:
            return
        new = float(max(10.0, min(120.0, degrees)))
        old = float(cam.fov_deg)
        if abs(new - old) > 1e-6:
            # A lens is not a zoom: a wider angle means standing closer, a narrower one farther back, so that what the
            # camera aims at keeps its size and it is the perspective that changes.
            cam.distance = float(cam.distance) * math.tan(math.radians(old) / 2.0) / math.tan(math.radians(new) / 2.0)
        cam.fov_deg = new
        vp = self.app.viewport
        vp.update() if hasattr(vp, "update") else None
        self.refresh_camera()

    def render_camera(self):
        """The camera a render (or a new scene) takes: the one the preview window keeps while Follow the
        camera is off (that view is what is wanted: it is what the preview shows), else the 3D view's."""
        if getattr(self, "_camera_override", None) is not None:       # a batch of scenes: each one's own camera
            return self._camera_override
        live, win = self._live, self.window
        if (live is not None and not live.follow_camera and live.frozen_camera is not None
                and win is not None and win.isVisible()):
            return live.frozen_camera
        return self.app.viewport.camera

    def scene_from_preview(self):
        """A scene (IngeTrazo's saved view) from the preview's view: the camera it shows now (the one it keeps
        while Follow the camera is off, else the 3D view's) with the drawing's layers, section and style as they
        are. One undo step. Returns the scene made, or None."""
        from PySide6.QtWidgets import QInputDialog
        try:
            from core.history import AddSceneCommand
            from core.saved_views import SavedView
        except ImportError:
            self._set_status(tr("This IngeTrazo cannot make a scene from here."))
            return None
        scene = self.app.scene
        taken = {v.name for v in getattr(scene, "saved_views", None) or ()}
        n = 1
        while f"{tr('Scene')} {n}" in taken:
            n += 1
        parent = self.window if self.window is not None and self.window.isVisible() else self
        name, ok = QInputDialog.getText(parent, tr("New scene from this view"), tr("Name of the scene"),
                                        text=f"{tr('Scene')} {n}")
        name = (name or "").strip()
        if not ok or not name:
            return None
        if name in taken:
            n = 2
            while f"{name} {n}" in taken:
                n += 1
            name = f"{name} {n}"
        try:
            view = SavedView.capture(name, scene, self.render_camera())
            self.app.viewport.history.execute(AddSceneCommand(view))
        except Exception as exc:  # noqa: BLE001 - say it, never crash the app
            _log.exception("scene not made")
            self._set_status(tr("Could not make the scene: {error}", error=exc))
            return None
        notify = getattr(self.app.viewport, "notify_scene_changed", None)
        if callable(notify):
            notify()
        self._set_status(tr("Scene «{name}» made from the preview's view (undo removes it).", name=name))
        return view

    def update_preview(self):
        """The Update button (Follow changes off): the live view takes the model and materials as they are now."""
        if self._live is not None:
            self._live.update_now()
            self._set_status(tr("Updating the scene in Blender…"))

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
        for combo in (self.preset, self.engine, self.quality, self.hdri, self.bg_mode, self.backdrop, self.backdrop_fit):
            combo.currentIndexChanged.connect(self._schedule_save)
        self.width.valueChanged.connect(self._schedule_save)
        self.output_tab.changed.connect(self._schedule_save)
        self.section_tab.changed.connect(self._schedule_save)
        self.output_tab.changed.connect(self._update_summary)
        self.preset.currentIndexChanged.connect(lambda _i: self.sun_tab._show_sun())
        self.hdri.currentIndexChanged.connect(lambda _i: self.sun_tab._show_sun())
        self.hdri_light.toggled.connect(lambda _on: self.sun_tab._show_sun())
        self.bg_mode.currentIndexChanged.connect(lambda _i: self.sun_tab._show_sun())
        self.output_tab.changed.connect(self._bg_enable)
        for sl in (*self.sliders.values(), self.hdri_rotation, self.hdri_strength, self.hdri_height,
                   self.backdrop_strength):
            sl.valueChanged.connect(self._schedule_save)
        self.hdri_light.toggled.connect(self._schedule_save)
        self.ground.toggled.connect(self._schedule_save)
        self.ground_shadow.toggled.connect(self._schedule_save)
        self.ground_material.currentIndexChanged.connect(self._schedule_save)
        self.ground_material.currentIndexChanged.connect(lambda _i: self._ground_grass_hint())
        self._ground_grass_hint()
        self.ground_rough.valueChanged.connect(self._schedule_save)
        self.ground_haze.valueChanged.connect(self._schedule_save)
        self.ground_offset.valueChanged.connect(self._schedule_save)
        self.ground_grass.valueChanged.connect(self._schedule_save)
        self.ground_radius.valueChanged.connect(self._schedule_save)
        for sig in (self.skyline_type.currentIndexChanged, self.skyline_height.valueChanged, self.skyline_distance.valueChanged,
                    self.skyline_seed.valueChanged):
            sig.connect(self._schedule_save)
        self.ground.toggled.connect(lambda _on: self._skyline_enable())
        self._skyline_enable()
        self.style_mode.currentIndexChanged.connect(self._style_mode_chosen)
        for sig in (self.style_mode.currentIndexChanged, self.style_width.valueChanged, self.style_lux.valueChanged,
                    self.style_noise.valueChanged, self.style_extend.valueChanged, self.style_wet.valueChanged,
                    self.style_edges.valueChanged, self.style_paper.valueChanged, self.style_material.currentIndexChanged):
            sig.connect(self._schedule_save)
        for b in (self.style_colour, self.style_model_colour):
            b.changed.connect(self._schedule_save)
        self.style_material.currentIndexChanged.connect(self._style_enable)
        self.style_width.valueChanged.connect(self._style_enable)
        self._fill_style_materials()
        self._style_enable()
        self.ground_tile.valueChanged.connect(self._schedule_save)
        for sig in (self.ground_material.currentIndexChanged, self.ground_tile.valueChanged):
            sig.connect(lambda *_a: self._live is not None and self._live.update_now())   # shows at once, also when the live view keeps its model
        self._bg_enable()
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
        pic = self.backdrop.currentData()
        return {
            "version": settings_store.VERSION,
            "look": self.preset.currentData(),
            "engine": self.engine.currentData(),
            "quality": self.quality.currentIndex(),
            "width": self.width.value(),
            "output": self.output_tab.settings(),
            "section": self.section_tab.settings(),
            "sliders": {k: round(_value(s), 4) for k, s in self.sliders.items()},
            "ground": self.ground.isChecked(),
            "ground_shadow": self.ground_shadow.isChecked(),
            "ground_material": self.ground_material_settings(),
            "ground_look": self.ground_look_settings(),
            "skyline": self.skyline_settings(),
            "style": self.style_settings(),
            "hdri": ({"path": hdri, "rotation": round(_value(self.hdri_rotation), 3),
                      "brightness": round(_value(self.hdri_strength), 3),
                      "height": round(_value(self.hdri_height), 2),
                      "light": self.hdri_light.isChecked()}
                     if hdri and hdri != _CHOOSE and self.bg_mode.currentData() == "pano" else None),
            "backdrop": ({"path": pic, "fit": self.backdrop_fit.currentData(),
                          "brightness": round(_value(self.backdrop_strength), 3)}
                         if pic and pic != _CHOOSE and self.bg_mode.currentData() == "picture" else None),
        }

    def _interior_toggled(self, on: bool) -> None:
        """Interior: metered for a room. Off: the clear day (the night follows the sun by itself)."""
        want = "interior" if on else ("clear" if self.preset.currentData() == "interior" else self.preset.currentData())
        self.preset.setCurrentIndex(max(0, self.preset.findData(want)))

    def reset_all(self) -> None:
        """Every setting back to its default (the default look, no style, the look's own adjustments)."""
        self.apply_settings({"look": "clear"})
        self._preset_changed(0)
        self._schedule_save()

    def apply_settings(self, data: dict) -> None:
        """Put ``data`` (the document's settings) in the controls, without
        saving them again."""
        data = settings_store.clean(data)
        if data is None:
            return
        self._applying = True
        widgets = [self.preset, self.engine, self.quality, self.width, self.hdri, self.ground, self.ground_shadow,
                   self.ground_material, self.ground_tile, self.ground_type, self.ground_rough, self.ground_haze,
                   self.ground_offset, self.ground_grass, self.ground_radius, self.skyline_type, self.skyline_height,
                   self.skyline_distance, self.skyline_seed, self.style_mode, self.style_width, self.style_lux, self.style_noise,
                   self.style_extend, self.style_wet, self.style_edges, self.style_paper, self.style_material,
                   self.hdri_rotation, self.hdri_strength, self.hdri_height, self.hdri_light,
                   self.bg_mode, self.backdrop, self.backdrop_fit, self.backdrop_strength,
                   *self.sliders.values()]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.preset.setCurrentIndex(max(0, self.preset.findData(data["look"])))
            self.engine.setCurrentIndex(max(0, self.engine.findData(data["engine"])))
            self.quality.setCurrentIndex(data["quality"])
            self.width.setValue(data["width"])
            self.ground.setChecked(bool(data.get("ground", True)))
            self.ground_shadow.setChecked(bool(data.get("ground_shadow", True)))
            self.ground_shadow.setEnabled(not self.ground.isChecked())
            self.ground_more.setEnabled(self.ground.isChecked())
            gl = data["ground_look"]
            self.ground_type.setCurrentIndex(max(0, self.ground_type.findData(gl["type"])))
            self._ground_color = gl["color"]
            self.ground_colour.set_rgb(gl["color"] or self._ground_default_colour())
            self.ground_rough.setValue(int(round(gl["roughness"] * self.ground_rough.maximum())))
            self.ground_haze.setValue(int(round(gl["haze"] / 4.0 * self.ground_haze.maximum())))
            self.ground_offset.setValue(gl["offset"])
            self.ground_grass.setValue(gl["grass_radius"])
            self.ground_radius.setValue(gl["ground_radius"])
            sy = data["style"]
            self.style_mode.setCurrentIndex(max(0, self.style_mode.findData(sy["mode"])))
            self.style_width.setValue(sy["width"])
            self.style_colour.set_rgb(sy["color"])
            self.style_model_colour.set_rgb(sy["model_color"])
            self.style_lux.setValue(sy["lux_max"])
            self.style_noise.setValue(sy["noise"])
            self.style_extend.setValue(sy["extend"])
            self.style_wet.setValue(sy["wetness"])
            self.style_edges.setValue(sy["edges"])
            self.style_paper.setValue(sy["paper"])
            if sy["material"] and self.style_material.findData(sy["material"]) < 0:
                self.style_material.addItem(sy["material"], sy["material"])
            self.style_material.setCurrentIndex(max(0, self.style_material.findData(sy["material"])))
            sk = data["skyline"]
            self.skyline_type.setCurrentIndex(max(0, self.skyline_type.findData(sk["type"])))
            self.skyline_height.setValue(sk["height"])
            self.skyline_distance.setValue(sk["distance"])
            self.skyline_seed.setValue(sk["seed"])
            self._skyline_color = sk["color"]
            self.skyline_colour.set_rgb(sk["color"] or self._skyline_default_colour())
            gm = data.get("ground_material")
            self._choose_ground_material(gm["name"] if gm else "")
            self.ground_tile.setValue(gm["tile"] if gm else 0.0)
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
                self.hdri_height.setValue(int(round((h["height"] - 0.5) / 29.5 * self.hdri_height.maximum())))
                self.hdri_light.setChecked(h["light"])
            else:
                self.hdri.setCurrentIndex(0)
            self._hdri_prev = self.hdri.currentIndex()
            b = data.get("backdrop")
            if b and Path(b["path"]).is_file():
                i = self.backdrop.findData(b["path"])
                if i < 0:
                    i = self.backdrop.count() - 1
                    self.backdrop.insertItem(i, Path(b["path"]).name, b["path"])
                self.backdrop.setCurrentIndex(i)
                self.backdrop_fit.setCurrentIndex(max(0, self.backdrop_fit.findData(b["fit"])))
                self.backdrop_strength.setValue(int(round((b["brightness"] + 3.0) / 6.0 * self.backdrop_strength.maximum())))
            else:
                self.backdrop.setCurrentIndex(0)
            self._backdrop_prev = self.backdrop.currentIndex()
            self.bg_mode.setCurrentIndex(self.bg_mode.findData(
                "pano" if self.hdri.currentData() else ("picture" if self.backdrop.currentData() else "sky")))
        finally:
            for w in widgets:
                w.blockSignals(False)
            self._applying = False
        for row in (self.ground_rough_row, self.ground_haze_row):
            row.update_value()
        for row in (*self.slider_rows.values(), self.hdri_rotation_row, self.hdri_strength_row, self.hdri_height_row,
                    self.backdrop_strength_row):
            row.update_value()                       # their signals were blocked
        self._hdri_enable()
        self._bg_enable()
        self._skyline_enable()
        self._style_enable()
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
        self.bg_mode.setCurrentIndex(self.bg_mode.findData("pano"))     # choosing an image means to show it
        st = QSettings()
        st.setValue(_SETTINGS + "hdri_dir", str(Path(path).parent))
        if "datafiles" not in path:
            recent = [p for p in (st.value(_SETTINGS + "hdri_recent", []) or []) if p != path]
            st.setValue(_SETTINGS + "hdri_recent", ([path] + recent)[:6])
        self._hdri_enable()

    def _hdri_enable(self, *_a):
        on = bool(self.hdri.currentData()) and self.bg_mode.currentData() == "pano"
        for w in (self.hdri_rotation_row, self.hdri_strength_row, self.hdri_height_row, self.hdri_light):
            w.setEnabled(on)
        lit = on and self.hdri_light.isChecked()
        # The image's own sky and sun replace the look's: these do nothing then.
        for key in ("clouds", "sun_scale"):
            if key in self.slider_rows:
                self.slider_rows[key].setEnabled(not lit)

    # -- your presets ---------------------------------------------------------------
    def _user_presets(self) -> dict:
        return user_presets.load_all(QSettings().value(_SETTINGS + "user_presets", ""))

    def _refresh_user_presets(self, select: str = "") -> None:
        names = sorted(self._user_presets(), key=str.lower)
        self.user_presets.blockSignals(True)
        self.user_presets.clear()
        self.user_presets.addItem(tr("My presets…") if names else tr("No presets saved yet"), "")
        for n in names:
            self.user_presets.addItem(n, n)
        self.user_presets.setCurrentIndex(max(0, self.user_presets.findData(select)))
        self.user_presets.blockSignals(False)
        self.act_delete_preset.setEnabled(bool(names))

    def _store_user_preset(self, name: str, preset: dict) -> None:
        allp = self._user_presets()
        allp[name] = preset
        QSettings().setValue(_SETTINGS + "user_presets", user_presets.dump_all(allp))
        self._refresh_user_presets(name)

    def save_user_preset(self):
        """Ask for a name and keep the settings as they are now (asks before replacing one)."""
        default = self.user_presets.currentData() or ""
        name, ok = QInputDialog.getText(self, tr("Save as preset…"), tr("Name of the preset"), text=default)
        name = user_presets.clean_name(name)
        if not ok or not name:
            return
        if name in self._user_presets() and QMessageBox.question(
                self, tr("Save as preset…"), tr("A preset called «{name}» exists. Replace it?", name=name)) != QMessageBox.Yes:
            return
        preset = user_presets.make(self.settings_dict())
        if preset is not None:
            self._store_user_preset(name, preset)
            self._set_status(tr("Preset «{name}» saved.", name=name))

    def _apply_user_preset(self, _i=0):
        name = self.user_presets.currentData()
        preset = self._user_presets().get(name) if name else None
        if preset is None:
            return
        data = dict(preset)
        data["section"] = self.section_tab.settings()           # the cut belongs to the model, not to a look
        data["width"] = self.width.value()
        self.apply_settings(data)
        self._schedule_save()
        self._set_status(tr("Preset «{name}» applied.", name=name))

    def delete_user_preset(self):
        name = self.user_presets.currentData()
        if not name:
            return
        if QMessageBox.question(self, tr("Delete this preset"), tr("Delete the preset «{name}»?", name=name)) != QMessageBox.Yes:
            return
        allp = self._user_presets()
        allp.pop(name, None)
        QSettings().setValue(_SETTINGS + "user_presets", user_presets.dump_all(allp))
        self._refresh_user_presets()

    def export_user_preset(self):
        """The settings as they are now, in a file to share (named after the chosen preset, if any)."""
        name = self.user_presets.currentData() or "Render Studio"
        start = str(Path(str(QSettings().value(_SETTINGS + "preset_dir", "") or "")) / f"{name}.rspreset.json")
        path, _f = QFileDialog.getSaveFileName(self, tr("Export these settings to a file…"), start, "Render Studio preset (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(user_presets.to_file(name, self.settings_dict()), encoding="utf-8")
        except OSError as exc:
            self._set_status(tr("Could not write the file: {error}", error=exc))
            return
        QSettings().setValue(_SETTINGS + "preset_dir", str(Path(path).parent))
        self._set_status(tr("Settings exported to {path}", path=path))

    def import_user_preset(self):
        start = str(QSettings().value(_SETTINGS + "preset_dir", "") or "")
        path, _f = QFileDialog.getOpenFileName(self, tr("Import a preset from a file…"), start, "Render Studio preset (*.json)")
        if not path:
            return
        try:
            got = user_presets.from_file(Path(path).read_text(encoding="utf-8"))
        except OSError:
            got = None
        if got is None:
            self._set_status(tr("That file is not a Render Studio preset."))
            return
        name, preset = got
        self._store_user_preset(name, preset)
        self._set_status(tr("Preset «{name}» imported. Choose it in the list to use it.", name=name))

    def _bg_enable(self, *_a):
        """Show the controls of the chosen background only (and say when the output hides it)."""
        mode = self.bg_mode.currentData()
        for key, rows in self._bg_rows.items():
            for w in rows:
                self._form_bg.setRowVisible(w, mode == key)
        self._form_bg.setRowVisible(self.bg_more, mode == "pano")
        self._hdri_enable()
        hidden = mode != "sky" and bool(self.output_tab.transparent.isChecked())
        self.bg_note.setText(tr("The Output tab leaves the sky transparent, so this background will not show in the "
                                "render. Untick «Transparent sky» there.") if hidden else "")
        self._form_bg.setRowVisible(self.bg_note, hidden)

    def _backdrop_changed(self, i):
        if self.backdrop.itemData(i) == _CHOOSE:
            start = str(QSettings().value(_SETTINGS + "backdrop_dir", "") or "")
            path, _f = QFileDialog.getOpenFileName(self, tr("Fixed picture"), start, BACKDROP_FILTER)
            if path:
                self.set_backdrop_path(path)
            else:
                self.backdrop.blockSignals(True)
                self.backdrop.setCurrentIndex(self._backdrop_prev)
                self.backdrop.blockSignals(False)
        self._backdrop_prev = self.backdrop.currentIndex()

    def set_backdrop_path(self, path: str):
        """Use ``path`` as the fixed picture (and remember it among the recent ones)."""
        i = self.backdrop.findData(path)
        if i < 0:
            i = self.backdrop.count() - 1             # before "Choose a file…"
            self.backdrop.insertItem(i, Path(path).name, path)
        self.backdrop.blockSignals(True)
        self.backdrop.setCurrentIndex(i)
        self.backdrop.blockSignals(False)
        self._backdrop_prev = i
        self.bg_mode.setCurrentIndex(self.bg_mode.findData("picture"))
        st = QSettings()
        st.setValue(_SETTINGS + "backdrop_dir", str(Path(path).parent))
        recent = [p for p in (st.value(_SETTINGS + "backdrop_recent", []) or []) if p != path]
        st.setValue(_SETTINGS + "backdrop_recent", ([path] + recent)[:6])
        self._schedule_save()

    def _fill_ground_materials(self):
        """The model's materials in the ground's list (the one chosen stays)."""
        combo = self.ground_material
        keep = combo.currentData() if combo.count() else ""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("Look's colour"), "")
        try:
            counts = mats.used_materials(self.app.scene)
        except Exception:  # noqa: BLE001 - no model yet: the colour only
            counts = {}
        for n in sorted(counts, key=str.lower):
            # a material nothing is painted with is not in the file Blender gets: it is not put on the ground
            combo.addItem(n if counts[n] else tr("{name} (not painted: not used)", name=n), n)
        if keep and combo.findData(keep) < 0:
            combo.addItem(keep, keep)                     # not in the model any more: kept until changed
        combo.setCurrentIndex(max(0, combo.findData(keep)))
        combo.blockSignals(False)

    def _choose_ground_material(self, name: str):
        combo = self.ground_material
        if name and combo.findData(name) < 0:
            combo.addItem(name, name)
        combo.setCurrentIndex(max(0, combo.findData(name)))

    def _fill_style_materials(self):
        """«A colour» and the drawing's materials in the Model style's list (the one chosen stays)."""
        combo = self.style_material
        keep = combo.currentData() if combo.count() else ""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("A colour"), "")
        try:
            names = sorted(mats.used_materials(self.app.scene), key=str.lower)
        except Exception:  # noqa: BLE001
            names = []
        for n in names:
            combo.addItem(n, n)
        if keep and combo.findData(keep) < 0:
            combo.addItem(keep, keep)
        combo.setCurrentIndex(max(0, combo.findData(keep)))
        combo.blockSignals(False)

    def style_settings(self) -> dict:
        return {"mode": self.style_mode.currentData() or "none", "width": round(self.style_width.value(), 2),
                "color": self.style_colour.rgb(), "material": self.style_material.currentData() or "",
                "model_color": self.style_model_colour.rgb(), "lux_max": round(self.style_lux.value(), 0),
                "noise": round(self.style_noise.value(), 3), "extend": round(self.style_extend.value(), 3),
                "wetness": round(self.style_wet.value(), 3), "paper": round(self.style_paper.value(), 3),
                "edges": round(self.style_edges.value(), 3)}

    def _style_enable(self, *_a) -> None:
        """Only the rows the chosen style uses; the outlines' colour only when there are outlines."""
        mode = self.style_mode.currentData() or "none"
        form = self._form_style
        for m, rows in self._style_rows.items():
            for w in rows:
                form.setRowVisible(w, m == mode)
        lines = self.style_width.value() > 0.0 or mode == "sketch"
        form.setRowVisible(self.style_colour_box, lines)
        if mode == "model":
            self.style_model_colour.setEnabled(not self.style_material.currentData())
        self.style_note.setText({
            "sketch": tr("Pencil lines on paper: the sky is left out."),
            "light": tr("The picture shows lux, not colour. Approximate: white matte surfaces, a clear day's sun, the lamps' lumens."),
            "watercolour": tr("Washes of colour on paper; the outlines are painted first."),
        }.get(mode, ""))
        self.style_note.setVisible(bool(self.style_note.text()))

    def _style_mode_chosen(self, _i) -> None:
        """A style with outlines starts with a thin line; None goes back to no outlines."""
        if self._applying if hasattr(self, "_applying") else False:
            return
        mode = self.style_mode.currentData() or "none"
        if mode in ("white", "model", "light", "sketch") and self.style_width.value() <= 0.0:
            self.style_width.setValue(0.8)
        if mode == "none":
            self.style_width.setValue(0.0)
        self._style_enable()

    def skyline_settings(self) -> dict:
        return {"type": self.skyline_type.currentData() or "", "height": round(self.skyline_height.value(), 2),
                "distance": round(self.skyline_distance.value(), 1), "seed": int(self.skyline_seed.value()),
                "color": self._skyline_color}

    def _skyline_enable(self) -> None:
        """The skyline's controls only when there is one, and only with a generated ground (it stands on it)."""
        has = bool(self.skyline_type.currentData())
        on = self.ground.isChecked()
        self.skyline_type.setEnabled(on)
        for w in (self.skyline_height, self.skyline_more):
            w.setEnabled(has and on)
        self.skyline_note.setText("" if on else tr("The skyline stands on the generated ground: tick «Generated ground» to use it."))
        self.skyline_note.setVisible(not on)

    def _ground_default_colour(self) -> list:
        """The ground's colour when none is chosen: the look's own."""
        try:
            return list(presets.studio(self.preset.currentData())[0]["ground_color"])
        except Exception:  # noqa: BLE001 - before the look exists
            return [0.30, 0.29, 0.27]

    def _skyline_default_colour(self) -> list:
        return list(presets.SKYLINE_COLOURS.get(self.skyline_type.currentData() or "", presets.SKYLINE_COLOURS["mountains"]))

    def _swatches_follow(self, *_a) -> None:
        """A colour not chosen shows the one the render will use (the look's ground, the skyline type's)."""
        if getattr(self, "_ground_color", None) is None and hasattr(self, "ground_colour"):
            self.ground_colour.set_rgb(self._ground_default_colour())
        if getattr(self, "_skyline_color", None) is None and hasattr(self, "skyline_colour"):
            self.skyline_colour.set_rgb(self._skyline_default_colour())

    def _skyline_colour_edited(self) -> None:
        self._skyline_color = self.skyline_colour.rgb()
        self._schedule_save()

    def _skyline_colour_reset(self) -> None:
        self._skyline_color = None
        self.skyline_colour.set_rgb(self._skyline_default_colour())
        self._schedule_save()

    def update_night_rows(self, sun_up: bool = True) -> None:
        """The stars and moonlight sliders, only when it is night: the Night look, or a day look whose sun has set at the
        site's place, date and hour (and no 360° background lights the scene)."""
        form = getattr(self, "_form_skyadj", None)
        if form is None:
            return
        look = self.preset.currentData()
        h = self.hdri_settings()
        lit = bool(h and h.get("light"))
        night = look == "night" or (look in presets.NIGHT_WHEN_SUN_SET and not sun_up and not lit)
        for key in presets.NIGHT_SLIDERS:
            if key in self.slider_rows:
                form.setRowVisible(self.slider_rows[key], night)
        if "sun_scale" in self.slider_rows:
            form.setRowVisible(self.slider_rows["sun_scale"], not night)       # the sun by day, the moonlight by night

    def _ground_grass_hint(self):
        """Under the grass radius: how far the grass of the chosen material can reach at its density."""
        name = self.ground_material.currentData()
        spec = (self.material_specs() or {}).get(name) if name else None
        try:
            spec = spec or mats.with_detected(self.app.scene, {}).get(name)
        except Exception:  # noqa: BLE001
            pass
        grass = bool(name and spec and spec.get("type") == "grass")
        form = self.ground_more.form
        form.setRowVisible(self.ground_grass, grass)
        form.setRowVisible(self.ground_grass_note, grass)
        if not grass:
            self.ground_grass_note.setText("")
            return
        d = float(spec.get("grass_density") or mats.auto_grass_density(spec.get("grass_height", mats.DEFAULT_GRASS_HEIGHT)))
        reach = mats.grass_reach(d)
        asked = self.ground_grass.value()
        text = tr("At {d:.0f} tufts per m² the grass can reach {r:.0f} m round the model (the same density everywhere).", d=d, r=reach)
        if asked > reach:
            text += " " + tr("The radius asked for is larger: it is limited to that.")
        self.ground_grass_note.setText(text)

    def _ground_type_chosen(self, _i):
        key = self.ground_type.currentData()
        if key in presets.GROUND_TYPES:
            _l, color, rough = presets.GROUND_TYPES[key]
            self._ground_color = list(color)
            self.ground_colour.set_rgb(color)
            self.ground_rough.setValue(int(round(rough * self.ground_rough.maximum())))
        elif key == "":
            self._ground_color = None
            self.ground_colour.set_rgb(self._ground_default_colour())
            self.ground_rough.setValue(int(round(0.9 * self.ground_rough.maximum())))
        self.ground_type.setCurrentIndex(self.ground_type.findData(key))
        self._schedule_save()

    def _ground_custom(self):
        """A colour or a roughness changed by hand: the type is now Custom."""
        if getattr(self, "_applying", False) or self.ground_type.currentData() in ("custom",):
            return
        key = self.ground_type.currentData()
        if key in presets.GROUND_TYPES:
            _l, color, rough = presets.GROUND_TYPES[key]
            same = (self._ground_color == list(color) and
                    abs(_value(self.ground_rough) - rough) < 0.011)
            if same:
                return
        elif key == "" and self._ground_color is None and abs(_value(self.ground_rough) - 0.9) < 0.011:
            return
        self.ground_type.setCurrentIndex(self.ground_type.findData("custom"))

    def _ground_colour_edited(self):
        self._ground_color = self.ground_colour.rgb()
        self._ground_custom()
        self._schedule_save()

    def _ground_colour_reset(self):
        self._ground_color = None
        self.ground_colour.set_rgb(self._ground_default_colour())
        self._ground_custom()
        self._schedule_save()

    def ground_look_settings(self) -> dict:
        return {"type": self.ground_type.currentData() or "", "color": self._ground_color,
                "roughness": round(_value(self.ground_rough), 3), "haze": round(_value(self.ground_haze), 2),
                "offset": round(self.ground_offset.value(), 3), "grass_radius": round(self.ground_grass.value(), 1),
                "ground_radius": round(self.ground_radius.value(), 1)}

    def ground_material_settings(self) -> dict | None:
        name = self.ground_material.currentData()
        if not name:
            return None
        return {"name": name, "tile": round(self.ground_tile.value(), 3)}

    def backdrop_settings(self) -> dict | None:
        path = self.backdrop.currentData()
        if self.bg_mode.currentData() != "picture" or not path or path == _CHOOSE:
            return None
        return {"path": path, "fit": self.backdrop_fit.currentData(),
                "strength": 2.0 ** _value(self.backdrop_strength)}

    def hdri_settings(self) -> dict | None:
        path = self.hdri.currentData()
        if self.bg_mode.currentData() != "pano" or not path or path == _CHOOSE:
            return None
        return {"path": path, "rotation": _value(self.hdri_rotation),
                "strength": 2.0 ** _value(self.hdri_strength), "height": _value(self.hdri_height),
                "light": self.hdri_light.isChecked()}

    def show_help(self, anchor: str = "panel"):
        from . import ui_help
        ui_help.show(self, anchor)

    def render_main(self):
        """The Render button: the scenes ticked in the Output tab when «Scenes» is chosen there, else the current view."""
        if self.output_tab.scenes_mode():
            return self.render_scenes()
        return self.render()

    def render_scenes(self):
        """Render the scenes ticked in the Output tab, one after another, into its folder (named as it says)."""
        from .bulk_render import BulkDialog
        out = self.output_tab
        views = out.chosen_views()
        folder = out.folder.text().strip()
        if not views:
            self._set_status(tr("Tick at least one scene in the Output tab."))
            return None
        if not folder:
            self._set_status(tr("Choose a folder in the Output tab first."))
            return None
        if getattr(self, "bulk_window", None) is None:
            self.bulk_window = BulkDialog(self)
            translate_on_show(self.bulk_window)
        self.bulk_window.start(views, folder, out.pattern.text().strip() or output.DEFAULT_PATTERN)
        return self.bulk_window

    def open_lights(self):
        w = self.lights_window
        self.lights_tab.refresh()
        w.show()
        w.raise_()
        w.activateWindow()
        return w

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
                    getattr(self, "section_tab", None), getattr(self, "output_tab", None)):
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
        st.setValue(_SETTINGS + "hdri_height", _value(self.hdri_height))
        st.setValue(_SETTINGS + "hdri_light", self.hdri_light.isChecked())
        st.setValue(_SETTINGS + "bg_mode", self.bg_mode.currentData())
        pic = self.backdrop.currentData()
        st.setValue(_SETTINGS + "backdrop", pic if pic != _CHOOSE else "")
        st.setValue(_SETTINGS + "backdrop_fit", self.backdrop_fit.currentData())
        st.setValue(_SETTINGS + "backdrop_strength", _value(self.backdrop_strength))

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
            return False                   # busy with another picture (a batch of scenes reads this)
        found = self.check_blender()
        if found is None:
            self.status.setText("Blender was not found: choose it above.")
            self.finished.emit(None)
            return None
        if self._preparing:
            return False
        self._remember()
        camera = self.render_camera()             # the preview's view when it keeps one (Follow the camera off)
        win = self.preview()
        self._direct = not win.isVisible()        # from the panel, no preview open: its window only shows this render
        if self._direct:
            win.show()
            win.raise_()
        # Say at once that something is happening (the export of a big model and the live Blender
        # shutting down take seconds before Blender reports any progress).
        if self.window is not None:
            self.window.set_mode("rendering")
            self.window.set_busy()
        self._set_status(tr("Preparing the model…"))
        QApplication.processEvents()
        self._preparing = True
        try:
            if not self._render_in_live_scene(found, save_to, camera):
                self._stop_live()          # a final render and the live Blender should not run together
                self._render_job(found, save_to, camera)
        finally:
            self._preparing = False

    def line_geometry(self, notes: list | None = None):
        """The lines and faces the outlines are drawn from: what Blender renders. The 3D view's own geometry (fast: it is kept ready)
        when the model is rendered as it is drawn; else the scene walked with what the render leaves out of the model file left out
        (the stand-in of every proxy whose original is found, a light's symbol, objects hidden inside others) and the proxies'
        originals put where their stand-ins are (None: the 3D view's)."""
        from . import outlines
        scene = self.app.viewport.scene
        try:
            placed, extra = proxies.line_geometry(scene, self.doc_path())
        except Exception as exc:  # noqa: BLE001 - never stops a render: the 3D view's geometry
            _log.exception("proxies' lines not read")
            placed, extra = [], None
            if notes is not None:
                notes.append(f"proxies' lines NOT read: {type(exc).__name__}: {exc}")
        try:
            symbols = studio_lights.symbols_out_of_render(scene)
        except Exception:  # noqa: BLE001
            symbols = []
        try:
            nested = bool(visibility.hidden_placements(scene))
        except Exception:  # noqa: BLE001
            nested = False
        if not (placed or symbols or nested):
            if notes is not None:
                notes.append("no proxies, symbols or nested hidden: the 3D view's own geometry")
            return None
        with proxies.left_out(placed + symbols), visibility.hidden_left_out(scene):
            base = outlines.scene_geometry(scene)
        if notes is not None:
            notes.append(f"scene walked: proxies placed {len(placed)}, light symbols {len(symbols)}, nested hidden {nested}; "
                         f"base {[len(x) for x in base]}, originals {None if extra is None else [len(x) for x in extra]}")
        return outlines.merged([base, extra])

    def line_layer(self, camera, width: int, height: int, path, quiet: bool = False) -> str | None:
        """The outlines of the style as a transparent picture of ``width``×``height`` seen from ``camera`` (None: the style has none).
        They are drawn here, from the model's own geometry (outlines.py), and laid over the render by Blender's script."""
        from . import outlines
        style = settings_store.style(self.style_settings())
        if not outlines.wanted(style):
            return None
        if not quiet:
            self._set_status(tr("Drawing the outlines…"))
            QApplication.processEvents()
        notes: list = []
        # The width is in pixels of the FINAL picture: a smaller frame (the preview's) takes a thinner line, so that the preview shows
        # the lines in the proportion the render will have.
        try:
            ref = int(self.output_tab.frame()[1])
        except Exception:  # noqa: BLE001
            ref = 0
        if ref > 0 and height < ref:
            style = dict(style, width=float(style.get("width", 0.0) or 0.0) * height / ref)
            notes.append(f"width scaled to the frame: {height} of {ref} px")
        try:
            geom = self.line_geometry(notes)
        except Exception as exc:  # noqa: BLE001 - the 3D view's geometry
            _log.exception("outlines' geometry not worked out")
            notes.append(f"geometry NOT worked out: {type(exc).__name__}: {exc}")
            geom = None
        return outlines.write_layer(self.app.viewport, camera or self.app.viewport.camera, width, height, style, path, geom, notes)

    def line_set(self, camera, width: int, height: int):
        """The outlines of the style as vectors for the FINAL picture (outlines.LineSet and the controls' starting style), or None. The
        render window draws them over the picture and lets them be restyled instantly; saving puts them in it."""
        from . import outlines
        style = settings_store.style(self.style_settings())
        if not outlines.wanted(style):
            return None
        self._set_status(tr("Drawing the outlines…"))
        QApplication.processEvents()
        notes: list = []
        try:
            geom = self.line_geometry(notes)
        except Exception as exc:  # noqa: BLE001 - the 3D view's geometry
            _log.exception("outlines' geometry not worked out")
            notes.append(f"geometry NOT worked out: {type(exc).__name__}: {exc}")
            geom = None
        try:
            lines = outlines.lineset(self.app.viewport, camera or self.app.viewport.camera, int(width), int(height), geom, notes)
        except Exception:  # noqa: BLE001 - a render is never lost over its lines
            _log.exception("outlines not drawn")
            return None
        try:
            Path(self.work).mkdir(parents=True, exist_ok=True)
            (Path(self.work) / "lines.txt").write_text(chr(10).join(notes) + chr(10), encoding="utf-8")
        except OSError:
            pass
        return (lines, outlines.window_style(style)) if lines is not None else None

    def _bake_lines(self) -> None:
        """After a render whose outlines are vectors: the picture Blender wrote is kept as it is (``render-nolines.png``, what the window
        restyles) and ``self.output`` becomes the same with the lines in it, as every other way out of the render (autosave, Render and
        save…) reads it."""
        from . import outlines
        pending, self._final_lines = getattr(self, "_final_lines", None), None
        self._baked = None
        if not pending:
            return
        lines, style = pending
        try:
            base = self.output.with_name("render-nolines.png")
            shutil.copyfile(self.output, base)
            img = outlines.composite(QImage(str(base)), lines, style)
            if img.save(str(self.output), "PNG"):
                self._baked = (lines, style, base)
        except Exception:  # noqa: BLE001 - the picture without its outlines is better than none
            _log.exception("outlines not put in the picture")

    def _render_in_live_scene(self, found, save_to, camera) -> bool:
        """The final picture made by the live view's Blender, in the scene it already has, when that scene is the one this render
        would build: the same engine, up to date with the panel, an ordinary PNG or JPEG (not a panorama, not a transparent sky, not
        a deeper format). No export, no new Blender, no new scene: the picture is the same (tested) and comes much sooner. False
        when it cannot: the render is made the long way."""
        from core import render_blender as rb
        live = getattr(self, "_live", None)
        if live is None or not live.usable:
            return False
        out = self.output_tab.settings()
        engine = self.engine.currentData()
        if (out.get("projection") in ("flat", "360") or out.get("transparent") or out.get("format") not in ("png", "jpeg")
                or live.live_engine_name() != engine or engine not in rb.SAMPLES):
            return False
        width, height = self.output_tab.frame()
        self.work = rb.work_base().parent / "render-studio" / time.strftime("%Y%m%d-%H%M%S")
        try:
            self.work.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        output_file = self.work / "render.png"

        def done(path):
            self._live_line_off()
            self.output = Path(path)
            self.last_render_reused = True
            live.pause()                             # the live scene waits: «Back to preview» shows it again with nothing to load
            self._done(0, None)

        def refused():
            self.last_render_reused = False
            self._live_line_off()
            self.proc = None
            self._preparing = True
            try:
                self._stop_live()
                self._render_job(found, save_to, camera)
            finally:
                self._preparing = False

        self._log_lines = []
        self._save_to, self._cancelled = save_to, False
        self.output = output_file
        self.rendered = {"format": out["format"], "file": output_file, "jpeg_quality": out["jpeg_quality"]}
        live.line.connect(self._live_line)
        self._final_lines = self.line_set(camera, width, height)
        lines = None
        sent = live.render_final(camera or self.app.viewport.camera, output_file, width, height,
                                 rb.SAMPLES[engine][max(0, min(2, self.quality.currentIndex()))], engine, done, refused, lines=lines)
        if not sent:
            self._live_line_off()
            return False
        self.proc = _ReusedProc(self, live)
        self._set_status(tr("Rendering in the preview's scene…"))
        return True

    def _live_line(self, line: str) -> None:
        from core import render_blender as rb
        self._log_lines.append(line)
        p = rb.progress_of(line)
        if p is not None:
            self._set_progress(p)

    def _live_line_off(self) -> None:
        try:
            self._live.line.disconnect(self._live_line)
        except (RuntimeError, TypeError):
            pass

    def _export_status(self, fraction: float):
        """The model's export is ``fraction`` done: the window's status and bar say so."""
        self._set_status(tr("Exporting the model… {pct} %", pct=int(fraction * 100)))
        self._set_progress(fraction * 0.85)
        QApplication.processEvents()

    def _render_job(self, found, save_to, camera=None):
        from core import render_blender as rb
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.work = rb.work_base().parent / "render-studio" / stamp
        width, height = self.output_tab.frame()
        out = self.output_tab.settings()
        self._final_lines = None
        panorama = out.get("projection") in ("flat", "360")
        lines = None
        if not panorama and out.get("format") in ("png", "jpeg"):
            self._final_lines = self.line_set(camera, width, height)        # vectors: the window restyles them, saving flattens them
        elif not panorama:
            lines = self.line_layer(camera, width, height, self.work / "lines.png")      # a deeper format: put in by Blender
        try:
            job, script = write_studio_job(
                self.app.viewport.scene, camera or self.app.viewport.camera, self.work,
                self.preset.currentData(), self.slider_values(),
                engine=self.engine.currentData(), quality=self.quality.currentIndex(),
                width=width, height=height, hdri=self.hdri_settings(), backdrop=self.backdrop_settings(), ground=self.ground.isChecked(),
                ground_material=self.ground_material_settings(), ground_look=self.ground_look_settings(), skyline=self.skyline_settings(), style=self.style_settings(), lines=lines,
                ground_shadow=self.ground_shadow.isChecked(),
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
        if getattr(self, "_direct", False):          # the window was opened only for this render: nothing to go back to
            self._direct = False
            if win is not None:
                win.set_mode("preview")
                win.hide()
            return
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
                                time.strftime("%Y%m%d-%H%M%S"), output.extension(r["format"]), scene="view")
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
        self._bake_lines()
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
        self._direct = False                              # the picture stays in the window: it is the result
        self._set_status(tr("Done: {name}", name=self.output.name) + (" · " + tr("also saved in {path}", path=kept) if kept else ""))
        win.set_image(self.output)                        # the retouch tools and Save image…
        if getattr(self, "_baked", None):
            win.set_outlines(*self._baked)                # the outlines, still vectors
        r = getattr(self, "rendered", None)
        win.set_rendered_file(r["file"] if r and not output.retouchable(r["format"]) else None,
                              output.FORMATS[r["format"]][0] if r else "")
        win.show()
        win.raise_()
        self.finished.emit(self.output)
