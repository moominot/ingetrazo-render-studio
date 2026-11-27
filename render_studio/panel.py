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

from PySide6.QtCore import QLocale, QProcess, QProcessEnvironment, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QImage
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from . import labels_above, wheel_guard
from . import drawing_fog, lights as studio_lights, materials as mats, fast_export, output, pbr, presets, proxies, section, settings_store, studio_data, visibility, widgets
from . import look_model, params, view_camera
from .style_groups import StyleGroups
from .toolbar import Commands
from . import preset_files
from .ambient import AmbientBox
from .preset_gallery import PresetGallery, presets_folder
from . import bindings, engine_probe, icons, layouts
from .expert import ExpertTab
from .fine_controls import FineControls
from .header_tools import HeaderTools
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


#: The height of the panel's two main buttons, Preview and Render (pixels; the others are 28).
MAIN_BUTTON = 42


#: The room above the first thing of each page, under the tabs (pixels).
PAGE_TOP = 8


def apply_backdrop(block: dict, backdrop: dict | None) -> dict:
    """The look's block with a fixed picture behind the model: ``backdrop`` = {path, fit
    («fill», «fit», «stretch»), strength (multiplier)}. The look keeps lighting the scene."""
    if not backdrop or not backdrop.get("path"):
        return block
    fit = backdrop.get("fit") if backdrop.get("fit") in ("fill", "fit", "stretch") else "fill"
    block.update(backdrop=str(backdrop["path"]), backdrop_fit=fit,
                 backdrop_strength=float(backdrop.get("strength", 1.0)))
    return block


def apply_flat(block: dict, flat: dict | None, floor: bool = True) -> dict:
    """The look's block with one plain colour behind the model: ``flat`` = {color (sRGB, as the screen shows it)}. ``floor``: the
    sun's shadows fall on the floor, over the colour. The look keeps lighting the scene."""
    st = settings_store.flat(flat)
    if st:
        block["flat"] = dict(st, floor=bool(floor))
    return block


def apply_shadows(block: dict, shadows: dict | None, style: dict | None = None) -> dict:
    """The look's block with the way the shadows are drawn (settings_store.shadows); nothing when they stay as rendered. A hatching's
    lines are as thick as the style's outlines."""
    st = settings_store.shadows(shadows) if shadows else None
    if st and st["draw"] != "render":
        st["width"] = settings_store.style(style)["width"] or 1.0
        block["shadows"] = st
    return block


def _screen_colour(linear) -> list:
    """A colour in Blender's linear terms as the screen shows it (sRGB), as the picture's pixels are."""
    return [round(12.92 * c if c <= 0.0031308 else 1.055 * c ** (1.0 / 2.4) - 0.055, 4) for c in linear[:3]]


def apply_fine(block: dict, fine: dict | None) -> dict:
    """The look's block with the finer settings not at their default (params.fine_clean); nothing when there are none. A texture
    asked for with no picture to make it of is left out."""
    values = params.fine_clean(fine)
    if values.get("finish.texture") == "image" and not os.path.isfile(values.get("finish.texture_path") or ""):
        del values["finish.texture"]
    if values:
        block["fine"] = values
    return block


#: The finer settings of the light and the picture that are values of the look's block: register key -> its name there.
_FINE_BLOCK = {"surface.albedo_cap": "albedo_cap", "image.bloom": "bloom", "image.exposure_target": "exposure_target",
               "image.exposure_white": "exposure_white", "image.exposure_max": "exposure_max",
               "sky.cloud_brightness": "cloud_brightness", "sky.cloud_seed": "cloud_seed", "shadows.softness": "sun_angle"}


def apply_fine_light(block: dict, fine: dict | None, sliders: dict | None, look: str) -> dict:
    """The finer settings of the light and the picture over the look's own. ``look``: the one rendered (a night, if the sun set)."""
    values = params.fine_clean(fine)
    block.update({name: values[key] for key, name in _FINE_BLOCK.items() if key in values})
    if "sky.cloud_scale" in values:
        block["cloud_scale"] = 1.0 / values["sky.cloud_scale"]      # (Blender's is the noise's: larger, smaller clouds)
    if "shadows.softness" in values:
        block["sun_jitter"] = True                               # (EEVEE only softens a shadow when asked to)
    if "sky.golden_elevation" in values and look == "golden_hour":
        block["sun_elevation"] = values["sky.golden_elevation"]
    if values.get("image.contrast"):
        block["looks"] = list(params.CONTRASTS[values["image.contrast"]])
    if "image.kelvin" in values:
        block["white_balance"] = values["image.kelvin"] + 1500.0 * float((sliders or {}).get("warmth") or 0.0)
    if "image.tint" in values:
        block["tint"] = 10.0 + values["image.tint"]               # (10 is Blender's own, what an untouched picture has)
    return block


def apply_style_block(block: dict, scene, style: dict | None, lines: str | None = None) -> dict:
    """The look's block with the render's style (settings_store.style): only what the style uses goes to Blender. ``lines``: the line layer
    (outlines.write_layer) the script lays over the picture. A model made of one
    material of the drawing carries that material's colour and picture for when the file has no such material."""
    st = settings_store.style(style)
    parts = st.get("parts")
    if st["mode"] == "none" and st["width"] <= 0.0 and not parts:
        return block
    out = {"mode": st["mode"], "width": st["width"], "color": st["color"]}
    if parts:
        out["parts"] = parts
        if parts["outline"] and st["width"] <= 0.0:
            from .outlines import AUTO_WIDTH
            out["width"] = AUTO_WIDTH
        for key in ("noise", "extend", "lux_max", "wetness", "paper", "edges", "base"):
            out[key] = st[key]
    if st["mode"] == "model" or (parts and parts["surface"] == "mono"):
        out["model_color"] = st["model_color"]
        if st["material"]:
            from .materials import export_name
            mat = (getattr(scene, "materials", None) or {}).get(st["material"])
            tex = (getattr(mat, "texture", None) or {}) if mat is not None else {}
            out["material"] = export_name(st["material"])
            out["texture"] = str(tex["path"]) if tex.get("path") else None
            if getattr(mat, "color", None) is not None:
                out["model_color"] = [float(c) for c in mat.color[:3]]
    if parts:
        pass
    elif st["mode"] == "light":
        out["lux_max"] = st["lux_max"]
    elif st["mode"] == "sketch":
        out["noise"], out["extend"] = st["noise"], st["extend"]
        out["base"] = st["base"]
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
                     progress=None, viewport=None, flat: dict | None = None, shadows: dict | None = None,
                     fine: dict | None = None):
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
    if params.fine_clean(fine).get("shadows.outline"):
        block["shadow_ink"] = _screen_colour(settings_store.style(style)["color"])     # the shadows' line: the outlines' ink
    block = apply_flat(block, flat, ground_shadow)
    block = apply_shadows(block, shadows, style)
    block = apply_fine(block, fine)
    block = presets.apply_sliders(block, sliders)
    block = apply_fine_light(block, fine, sliders, preset_key)       # (after the sliders: the warmth adds to a balance set here)
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
        sec = section.job_block(scene, section_opts, viewport)      # the active section cuts the render too
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
        placed, missing = proxies.job_block(scene, doc_path, progress=progress)
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
    data["camera"] = view_camera.camera_dict(camera)       # with the two-point view's level sight line and frame shift
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
        self.setObjectName("render_studio_panel")
        self.commands = Commands(self)                # the toolbar's, which also hold the live view's two switches
        st = QSettings()
        lang = _lang()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.need_box = self._need_blender_box()
        outer.addWidget(self.need_box)
        # Settings are in pages, as a person looks for them: Main (presets, camera, quality), Style (surface, outline,
        # finish and the picture's own corrections), Environment (sun and sky, shadows, background, ground).
        def page():
            host = QWidget()
            lay = QVBoxLayout(host)
            lay.setContentsMargins(0, PAGE_TOP, 4, 0)
            return host, lay
        host_main, col_main = page()
        host_image, col_image = page()
        host_sky, col_sky = page()
        col = col_sky

        # The presets (a whole look, with its picture) and the ambients (only the light). Both are filled in further down,
        # once the controls they put values in exist.
        presets_slot = QVBoxLayout()
        col_main.addLayout(presets_slot)

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
        box_pic = widgets.Card("Corrections", "corrections", icon="grp_corrections")
        form_pic = box_pic.form
        self.fx = widgets.Card("Effects", "effects", icon="grp_effects")     # vignette, depth of field: a group of the Image page
        box_skyadj = widgets.Card("Sun and sky", "sky", icon="grp_sky")
        form_skyadj = box_skyadj.form
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

        # The style: the surface, the outline and the finish, each on its own (style_groups.py), above the picture's corrections.
        self.style_groups = StyleGroups(self.app, self)
        for i, group_box in enumerate(self.style_groups.boxes):
            col_image.insertWidget(i, group_box)
        col_image.addStretch(1)
        self.shadows_box = self._build_shadows_box()          # (it goes under the sun, in the Environment page)
        col_main.addWidget(self._build_camera_box())

        # The background: the look's own sky, a 360° panorama, or one fixed picture.
        box_bg = widgets.Card("Background", "background", icon="grp_background")
        form2 = box_bg.form
        self.bg_mode = QComboBox()
        self.bg_mode.addItem(tr("Sky of the look"), "sky")
        self.bg_mode.addItem(tr("360° panorama"), "pano")
        self.bg_mode.addItem(tr("Fixed picture"), "picture")
        self.bg_mode.addItem(tr("Plain colour"), "flat")
        self.bg_mode.addItem(tr("Transparent"), "transparent")
        self.bg_mode.addItem(tr("Paper"), "paper")
        self._paper_under = False          # a document's paper behind a plain colour or a picture (an old sketch's)
        self.bg_mode.activated.connect(self._background_chosen)
        saved_pano = str(st.value(_SETTINGS + "hdri", "") or "")
        saved_pic = str(st.value(_SETTINGS + "backdrop", "") or "")
        mode0 = str(st.value(_SETTINGS + "bg_mode", "pano" if saved_pano else ("picture" if saved_pic else "sky")))
        self.bg_mode.setCurrentIndex(max(0, self.bg_mode.findData(mode0)))
        self.bg_mode.setToolTip("What is seen behind the model. Sky of the look: the sky the look makes. "
                                "360° panorama: a photo all round you, which also lights the model. "
                                "Fixed picture: one flat picture behind it, which stays put when the view turns. "
                                "Plain colour: exactly that colour behind the model (white, for instance). "
                                "Transparent: nothing behind, to put the picture over another one (the model, its lines and its "
                                "shadow on the floor; save it as PNG). "
                                "Paper: the sky is left out and drawing paper is behind.")
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
        # the plain colour's own controls
        from .section_panel import ColourButton
        try:
            colour0 = [float(c) for c in str(st.value(_SETTINGS + "flat_color", "1,1,1")).split(",")][:3]
        except ValueError:
            colour0 = [1.0, 1.0, 1.0]
        self.flat_colour = ColourButton(colour0 if len(colour0) == 3 else [1.0, 1.0, 1.0], "Background colour")
        self.flat_colour.setToolTip("The colour behind the model, exactly as it is: the exposure and the look do not tone it.")
        form2.addRow("Colour", self.flat_colour)
        # advanced
        self.bg_more = widgets.Section()            # (in view when it is a panorama: what is touched first, not an «advanced» part)
        self.hdri_height = _slider(0.5, 30.0, float(st.value(_SETTINGS + "hdri_height", 2.5)), 295)
        self.hdri_height_row = SliderRow(
            self.hdri_height, "{:.1f} m",
            "How high above the ground the image was taken from (a street panorama: about 2.5 m; a roof or "
            "a drone: more). It sets how the ground of the image is laid under the model: wrong, and the ground "
            "looks stretched or too close.")
        self.bg_more.form.addRow("Rotation", self.hdri_rotation_row)
        self.bg_more.form.addRow("Panorama brightness", self.hdri_strength_row)
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
            "flat": [self.flat_colour],
        }
        self._form_bg = form2
        self.bg_mode.currentIndexChanged.connect(self._bg_enable)
        self.bg_mode.currentIndexChanged.connect(self._floor_enable)
        col.addWidget(box_bg)

        # The ground under the model.
        box_ground = widgets.Card("Ground", "ground", icon="grp_ground")
        form_g = box_ground.form
        self.ground = QCheckBox("Generated ground")
        self.ground.setToolTip(
            "On: a ground is made under the model, with the look's colour, melting into the horizon. "
            "Off: no ground is added (the model's own terrain, or the 360° background's ground, shows).")
        self.ground.setChecked(str(st.value(_SETTINGS + "ground", "true")).lower() != "false")
        self.ground.toggled.connect(lambda on: QSettings().setValue(_SETTINGS + "ground", "true" if on else "false"))
        form_g.addRow("", self.ground)
        self.ground_shadow = QCheckBox("Shadow on the floor")
        self.ground_shadow.setToolTip(
            "The model throws its shadow on the floor, at its foot. With no generated ground, or over a plain colour, "
            "nothing else of the floor is drawn (what is behind shows through). A generated ground seen as it is "
            "always takes the shadows. Needs the sun or a light that casts shadows.")
        self.ground_shadow.setChecked(str(st.value(_SETTINGS + "ground_shadow", "true")).lower() != "false")
        self.ground_shadow.toggled.connect(lambda on: QSettings().setValue(_SETTINGS + "ground_shadow", "true" if on else "false"))
        self.ground.toggled.connect(self._floor_enable)
        self._form_shadows.addRow(self.ground_shadow)
        self._floor_enable()
        self.ground_type = QComboBox()
        self.ground_type.addItem(tr("Look's own"), "")
        for key, (label, _c, _r) in presets.GROUND_TYPES.items():
            self.ground_type.addItem(tr(label), key)
        self.ground_type.addItem(tr("Custom"), "custom")
        self.ground_type.setToolTip("A ready-made ground: its colour and how shiny it is. Change either one and it becomes Custom.")
        self.ground_type.activated.connect(self._ground_type_chosen)
        form_g.setRowWrapPolicy(QFormLayout.WrapLongRows)          # a narrow tray: the label above its field
        form_g.insertRow(0, "Type", self.ground_type)
        # advanced: its colour, shine, haze and height, and a material of the model on it
        self.ground_more = widgets.Section()
        _rows = {}                                  # added in the order of use once they all exist: what it is made of, then where
        from .section_panel import ColourButton
        crow = QHBoxLayout()
        self.ground_colour = ColourButton(self._ground_default_colour(), "Ground colour", linear=True)
        self.ground_colour.setToolTip("The ground's own colour instead of the look's.")
        self.ground_colour.changed.connect(self._ground_colour_edited)
        self.ground_colour_reset = QToolButton()
        self.ground_colour_reset.setIcon(icons.icon("undo"))
        self.ground_colour_reset.setToolTip("Back to the look's colour")
        self.ground_colour_reset.clicked.connect(self._ground_colour_reset)
        crow.addWidget(self.ground_colour, 1)
        crow.addWidget(self.ground_colour_reset)
        self._ground_color = None                  # None: the look's
        _rows["colour"] = ("Colour", crow)
        self.ground_rough = _slider(0.0, 1.0, 0.9, 100)
        self.ground_rough_row = SliderRow(self.ground_rough, "{:.2f}",
                                          "0 a mirror (wet pavement), 1 fully matte (grass, sand)")
        _rows["rough"] = ("Roughness", self.ground_rough_row)
        self.ground_haze = _slider(0.0, 4.0, 1.0, 40)
        self.ground_haze_row = SliderRow(self.ground_haze, "×{:.1f}",
                                         "How far the ground goes before it melts into the horizon: 1 the usual, "
                                         "more for a clearer far distance, 0 no haze")
        self.ground_offset = QDoubleSpinBox()
        self.ground_offset.setRange(-10.0, 10.0)
        self.ground_offset.setDecimals(2)
        self.ground_offset.setSingleStep(0.05)
        self.ground_offset.setSuffix(" m")
        self.ground_offset.setKeyboardTracking(False)
        self.ground_offset.setToolTip("Raises (+) or lowers (−) the generated ground from the model's foot.")
        _rows["level"] = ("Level", self.ground_offset)
        self.ground_radius = widgets.RadiusSlider(2000.0, 10.0)
        self.ground_radius.setToolTip("The radius of the generated ground. The haze melts it into the horizon over its outer "
                                      "two thirds, so its edge is never seen. Automatic: a very large ground (the haze starts "
                                      "at 120 m).")
        _rows["radius"] = ("Ground radius", self.ground_radius)
        self.ground_grass = widgets.RadiusSlider(500.0, 5.0)
        self.ground_grass.setToolTip("When the ground's material is grass: the radius of the circle of grass round the model. "
                                     "Automatic: the model's farthest point plus 10 m.")
        _rows["grass"] = ("Grass radius", self.ground_grass)
        self._grass_rows = (self.ground_grass,)
        self.ground_grass_note = QLabel("")
        self.ground_grass_note.setWordWrap(True)
        self.ground_grass_note.setStyleSheet("color: gray; font-size: 11px")
        _rows["note"] = (self.ground_grass_note,)
        self.ground_grass.valueChanged.connect(lambda _v: self._ground_grass_hint())
        self.ground_rough.valueChanged.connect(lambda _v: self._ground_custom())
        self.ground_offset.valueChanged.connect(lambda _v: None)
        self.ground_material = widgets.RefreshCombo(self._fill_ground_materials)
        self.ground_material.setToolTip(
            "A material of the model for the generated ground (grass, paving, sand, water…): it repeats at its own "
            "size over the ground. «Look's colour»: the plain colour of the look.")
        self._fill_ground_materials()
        _rows["material"] = ("Material", self.ground_material)
        self.ground_tile = QDoubleSpinBox()
        self.ground_tile.setRange(0.0, 100.0)
        self.ground_tile.setDecimals(2)
        self.ground_tile.setSingleStep(0.5)
        self.ground_tile.setSuffix(" m")
        self.ground_tile.setSpecialValueText(tr("Picture's own size"))
        self.ground_tile.setKeyboardTracking(False)
        self.ground_tile.setToolTip("How big one repeat of the material's picture is on the ground. "
                                    "The first value uses the picture's own size.")
        _rows["tile"] = ("Tile size", self.ground_tile)
        for key in ("material", "tile", "colour", "rough", "level", "radius", "grass", "note"):
            self.ground_more.form.addRow(*_rows[key])
        self.ground.toggled.connect(self.ground_more.setEnabled)
        self.ground_more.setEnabled(self.ground.isChecked())
        form_g.addRow(self.ground_more)
        col.addWidget(box_ground)
        # The horizon: distant mountains, hills, forest or city that hide where the ground meets the sky.
        box_horizon = widgets.Card("Horizon", "horizon", icon="grp_horizon")
        form_h = box_horizon.form
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
        form_h.addRow("Peak height", self.skyline_height)
        self.skyline_more = widgets.Section()
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
        self.skyline_colour_reset.setIcon(icons.icon("undo"))
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
        box_fog = widgets.Card("Fog", "fog", icon="grp_fog")
        form_fog = box_fog.form
        self.fog_note = self._caption("")
        self.fog_note.setVisible(False)
        form_fog.addRow(self.fog_note)
        for key in ("fog", "fog_start"):
            form_fog.addRow(self._env_labels[key], self.slider_rows[key])
        form_fog.addRow("Ground haze", self.ground_haze_row)          # how far the generated ground goes before it melts into the horizon
        self.ground.toggled.connect(self.ground_haze_row.setEnabled)
        self.ground_haze_row.setEnabled(self.ground.isChecked())
        col.addWidget(box_fog)
        self._fog_seen = "unset"
        self._fog_timer = QTimer(self)                  # the drawing's fog is set in IngeTrazo's Styles: noticed when it changes
        self._fog_timer.setInterval(1000)
        self._fog_timer.timeout.connect(self._update_fog_note)
        self._fog_timer.start()
        col_sky.insertWidget(0, box_skyadj)          # first: the light decides the rest
        col_sky.insertWidget(1, self.shadows_box)    # and the shadows it casts

        # What only the final render uses.
        box_final = widgets.Card("Quality", "quality", icon="grp_quality")
        form3 = box_final.form
        form3.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form3.addRow(self._caption("Quality is for Render; the preview has its own engine."))
        self.preview_engine = QComboBox()
        self.preview_engine.addItem(tr("Automatic"), "auto")
        self.preview_engine.addItem(tr("EEVEE — fast"), "eevee")
        self.preview_engine.addItem(tr("Cycles — like the final render"), "cycles")
        self.preview_engine.setCurrentIndex(max(0, self.preview_engine.findData(st.value(_SETTINGS + "preview_engine", "auto"))))
        self.preview_engine.setToolTip(
            "Automatic: Cycles when Blender finds a graphics card for it (the quicker and truer live view there), else "
            "EEVEE. EEVEE or Cycles: always that one.")
        self.preview_engine.currentIndexChanged.connect(lambda _i: QSettings().setValue(_SETTINGS + "preview_engine", self.preview_engine.currentData()))
        self.preview_quality = QComboBox()
        for key, label in (("fast", "Fast"), ("normal", "Normal"), ("high", "High")):
            self.preview_quality.addItem(tr(label), key)
        self.preview_quality.setCurrentIndex(max(0, self.preview_quality.findData(st.value(_SETTINGS + "preview_quality", "normal"))))
        self.preview_quality.setToolTip(
            "How sharp the preview is, which is also how quickly it answers (changing a material or a light, moving the camera). "
            "High: as sharp as the preview window shows it, so a picture saved from the preview is bigger too.")
        self.preview_quality.currentIndexChanged.connect(self._preview_quality_chosen)
        self.engine = QComboBox()
        self.engine.addItem(tr("Automatic"), "auto")
        self.engine.addItem(tr("EEVEE — fast"), "eevee")
        self.engine.addItem(tr("Cycles — best quality"), "cycles")
        kept = st.value(_SETTINGS + "engine", "auto")
        if not st.value(_SETTINGS + "engine_auto", ""):
            # «Automatic» is new: the EEVEE kept until now was the old default, not a choice
            kept = "auto" if kept == "eevee" else kept
            st.setValue(_SETTINGS + "engine", kept)
            st.setValue(_SETTINGS + "engine_auto", "1")
        self.engine.setCurrentIndex(max(0, self.engine.findData(kept)))
        self.engine.setToolTip(
            "Automatic: Cycles when Blender finds a graphics card for it (the truest light, and what the pre"
            "view shows), else EEVEE. EEVEE: quicker without a card. Cycles: always (the Interior look needs it).")
        self.quality = widgets.ChoiceButtons([tr(q) for q in ("Draft", "Medium", "High")],
                                             icons=("q_draft", "q_medium", "q_high"))
        self.quality.setCurrentIndex(int(st.value(_SETTINGS + "quality", 1)))
        self.quality.setToolTip("How many samples: more is less noisy and slower.")
        form3.addRow(self.quality)
        form3.addRow("Engine", self.engine)                  # which of these show is the layout's choice (Expert mode)
        form3.addRow("Preview engine", self.preview_engine)
        form3.addRow("Preview quality", self.preview_quality)
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
        self.tabs.addTab(scrolled(host_image), "Style")
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
        form_skyadj.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form_skyadj.addRow("Date", self.sun_quick.date_box)           # the date and the hour, always in view; the exact ones are folded
        form_skyadj.addRow("Hour", self.sun_quick.hour_box)
        self.sun_more = widgets.Section()
        form_skyadj.addRow(self.sun_more)                             # the place, right under the date and the hour
        for key in ("sun_scale", "moon", "clouds", "stars"):      # the sun (or the moonlight), the clouds, the stars
            form_skyadj.addRow(self._sky_labels[key], self.slider_rows[key])
        self._form_skyadj = form_skyadj
        self.sun_tab._show_sun()                     # (and the night sliders, shown only at night)
        self.sky_note = self._caption("")            # says why the clouds wait when the background is not the look's sky
        self.sky_note.setVisible(False)
        form_skyadj.addRow(self.sky_note)
        self.sun_tab.embed()                          # (the date and the hour are the two sliders above: said once)
        self.sun_more.form.addRow(self.sun_tab)
        col_sky.addStretch(1)
        self.ambient = AmbientBox(self)
        self.ambient.chosen.connect(self.set_ambient)
        self.gallery = PresetGallery(self)
        presets_slot.addWidget(self.gallery)
        presets_slot.addWidget(self.ambient)
        for signal in (self.preset.currentIndexChanged, self.hdri.currentIndexChanged, self.hdri_light.toggled,
                       self.bg_mode.currentIndexChanged):
            signal.connect(self._ambient_state)
        self._ambient_state()
        col_main.addStretch(1)
        for tab_widget, title in ((self.section_tab, "Section"), (self.output_tab, "Output")):
            self.tabs.addTab(scrolled(tab_widget), title)
        self.tabs.setCurrentIndex(min(self.tabs.count() - 1, max(0, int(st.value(_SETTINGS + "tab", 0) or 0))))
        self._expert_peek = False                      # the Expert page opened by a group's «+», to go when it is left
        self.tabs.currentChanged.connect(self._tab_chosen)
        for combo in self.findChildren(QComboBox):       # a long name must not widen a narrow tray
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
        flat = widgets.flat_style()
        for i in range(self.tabs.count()):
            self.tabs.widget(i).setStyleSheet(flat)
        outer.addWidget(self.tabs, 1)

        self.expert_mode = QToolButton()
        self.expert_mode.setCheckable(True)
        self.expert_mode.setText(tr("Expert mode"))
        self.expert_mode.setIcon(icons.icon("tools"))
        self.expert_mode.setIconSize(QSize(16, 16))
        self.expert_mode.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.expert_mode.setToolTip("Adds the Expert page: every setting, with an eye to choose what each page shows.")
        self.help_btn = QToolButton()
        self.help_btn.setIcon(icons.icon("comp_help"))
        self.help_btn.setToolTip("How Render Studio works, and what each control does")
        self.help_btn.clicked.connect(lambda: self.show_help("panel"))
        self.help_btn.setIconSize(QSize(16, 16))
        # Expert mode and the general help: in the tray's header, beside its name (header_tools.py).
        self.header_tools = HeaderTools(self, (self.expert_mode, self.help_btn))
        outer.insertWidget(0, self.header_tools.own_row)
        self.editor = None
        self._live = None
        self._prep = None
        self._preparing = False
        self._direct = False
        self._save_to = None
        self._cancelled = False
        mrow = QHBoxLayout()
        self.materials_btn, self.lights_btn = self._command_button(self.commands.materials), \
            self._command_button(self.commands.lights)
        mrow.addWidget(self.materials_btn, 1)
        mrow.addWidget(self.lights_btn, 1)
        outer.addLayout(mrow)
        # Render, and under its arrow «Render and save…», the scenes and «Open in Blender…».
        self.render_save_btn = QAction("Render and save…", self)
        self.render_save_btn.setToolTip("Asks where to save, makes the final picture and saves it straight away, "
                                        "without the live preview and without retouching.")
        self.render_save_btn.triggered.connect(lambda: self.render_and_save())
        self.render_scenes_btn = QAction("Render the selected scenes", self)
        self.render_scenes_btn.setToolTip("Renders the scenes ticked in the Output tab, one after another, into its folder.")
        self.render_scenes_btn.triggered.connect(lambda: self.render_scenes())
        self.expert_btn = QAction("Open in Blender…", self)
        self.expert_btn.setToolTip("Expert mode: opens the scene, as Render would make it, in a Blender with its own window "
                                   "to work in it. The file is saved first; nothing is rendered.")
        self.expert_btn.triggered.connect(lambda: self.open_in_blender())
        self.commands.preview.setIconText(tr("Preview"))      # the panel's shorter name: a button takes the icon's text
        self.preview_btn = self._command_button(self.commands.preview)
        self.render_btn = widgets.split_button(
            "Render", lambda: self.render_main(),
            "Makes the final picture now, with the Engine, Quality and size above, without the live preview. It opens in "
            "a window with the retouch tools and Save image…. With «Scenes» chosen in the Output tab it renders those.",
            [self.render_save_btn, self.render_scenes_btn, self.expert_btn])
        self.render_btn.setIcon(icons.icon("capture"))
        self.render_btn.setIconSize(QSize(18, 18))
        self.render_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)      # half the row each, whatever their words
        self.preview_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        for button in (self.preview_btn, self.render_btn):                         # the two that matter most: taller
            button.setMinimumHeight(MAIN_BUTTON)
            button.setIconSize(QSize(22, 22))
        self.render_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        row = QHBoxLayout()                                   # look, then take it: the two side by side
        row.addWidget(self.preview_btn, 1)
        row.addWidget(self.render_btn, 1)
        outer.addLayout(row)
        # The foot's last line: what is going on, and how long a render has taken.
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)      # a long message must not widen the tray
        self.foot_row = QHBoxLayout()
        self.foot_row.addWidget(self.status, 1)
        outer.addLayout(self.foot_row)
        # The finer settings' controls, each at the end of its group (found by a control of that group).
        anchors = {"surface": self.style_groups.surface, "finish": self.style_groups.finish,
                   "image": self.sliders["exposure_bias"], "sky": self.sliders["clouds"], "shadows": self.shadow_draw}
        self.fine = FineControls(self, {group: bindings.row_of(anchor)[0] for group, anchor in anchors.items()})
        self.fine.changed.connect(self._fine_changed)
        # Every setting's control is in place: the layout takes out of the pages what it does not show (expert.py).
        self.section_tab.after_paint = self._filter_layout
        self.expert = ExpertTab(self, layouts.Folder(presets_folder().parent / "layouts"))
        self.expert_scroll = scrolled(self.expert)
        self.expert_page = QWidget()                 # the search at the top, fixed; the groups scroll under it
        page = QVBoxLayout(self.expert_page)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(6)
        top = QVBoxLayout()
        top.setContentsMargins(0, 8, 4, 0)
        top.addWidget(self.expert.search)
        page.addLayout(top)
        page.addWidget(self.expert_scroll, 1)
        self.expert_mode.setChecked(str(QSettings().value(_SETTINGS + "expert_mode", "false")).lower() == "true")
        self.expert_page.setStyleSheet(flat)
        for button in (self.materials_btn, self.lights_btn, self.preview_btn, self.expert_mode, self.help_btn):
            button.setStyleSheet(flat if button not in (self.expert_mode, self.help_btn) else flat + widgets.SMALL_BUTTON)
        self.set_expert_mode(self.expert_mode.isChecked())
        self._add_more_buttons()
        self.expert_mode.toggled.connect(self.set_expert_mode)
        self.clock = widgets.ClockLabel()
        self.foot_row.addWidget(self.clock)
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
        for card in self._page_cards():
            card.unfolded.connect(lambda c=card: self._accordion(c))
        self._drawings = set()                       # the drawings already seen: one just opened starts folded
        self._note_drawing()
        self.check_blender()
        labels_above.apply(self)
        wheel_guard.watch(self)          # (the wheel scrolls; it changes only a picked field)

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

    def _command_button(self, action) -> QToolButton:
        """A button of the panel for one of the toolbar's commands: its icon before its name, greyed when the command is."""
        button = widgets.CentredButton()
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(18, 18))
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setMinimumHeight(28)
        return button

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
        self.commands.need_blender(found is not None)
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

    def _detect_gpu(self) -> None:
        """What «Automatic» goes by: whether Cycles has a graphics card here (asked of Blender once)."""
        if getattr(self, "_gpu", None) is not None:
            return
        found = self.blender()
        if found is None:
            return
        self._set_status(tr("Looking for a graphics card…"))
        QApplication.processEvents()
        self._gpu = engine_probe.gpu_backend(found)
        self._set_status("")
        self._update_summary()

    def final_engine(self) -> str | None:
        """The engine Render uses: the one chosen, or with «Automatic» Cycles when there is a graphics card, else EEVEE.
        None while that has not been looked for yet (:meth:`_detect_gpu`; this never starts Blender)."""
        choice = self.engine.currentData()
        if choice != "auto":
            return choice
        gpu = getattr(self, "_gpu", None)
        if gpu is None:
            try:
                gpu = engine_probe.known(self.blender())
            except Exception:  # noqa: BLE001 - not known yet
                gpu = None
            if gpu is None:
                return None
            self._gpu = gpu
        return "cycles" if gpu else "eevee"

    def _render_engine(self) -> str:
        """:meth:`final_engine`, looking for a graphics card first when that is what it takes."""
        if self.engine.currentData() == "auto":
            self._detect_gpu()
        return self.final_engine() or "eevee"

    def live_engine(self) -> str:
        """The live view's engine. The Interior look needs Cycles (EEVEE can't fill a room lit
        through a window). Otherwise the panel's Preview engine: EEVEE, Cycles, or Automatic = Cycles
        when it has a graphics card here (it keeps the scene between frames, so it is the quicker live
        view, and the truer one). Without a card, EEVEE; and Cycles on a big model once the view
        follows neither the camera nor the changes (nothing is sent to Blender again, and EEVEE looks
        nothing like the final render there). The panel's Engine is for Render."""
        block, _amb = presets.studio(self.preset.currentData())
        if block.get("engine_hint") == "cycles":
            return "cycles"
        choice = self.preview_engine.currentData()
        if choice == "cycles":
            return "cycles"
        if choice == "auto":
            if getattr(self, "_gpu", ""):
                return "cycles"
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
            height=height, hdri=self.hdri_settings(), backdrop=self.backdrop_settings(), flat=self.flat_settings(), shadows=self.shadow_settings(), fine=self.fine_settings(), ground=self.ground.isChecked(),
                ground_material=self.ground_material_settings(), ground_look=self.ground_look_settings(), skyline=self.skyline_settings(), style=self.style_settings(),
            ground_shadow=self.ground_shadow.isChecked(),
            materials=self.material_specs() if materials is None else materials, serve=True,
            live=True, reuse_model=reuse_model, doc_path=self.doc_path(),
            section_opts=self.section_tab.settings(), progress=self._export_progress(),
                viewport=getattr(self.app, "viewport", None))

    def window_of_the_program(self):
        """IngeTrazo's main window, or None."""
        return getattr(self.app, "window", None)

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
                self.slider_values(), engine=self._render_engine(), quality=self.quality.currentIndex(),
                width=width, height=height, hdri=self.hdri_settings(), backdrop=self.backdrop_settings(), flat=self.flat_settings(), shadows=self.shadow_settings(), fine=self.fine_settings(), ground=self.ground.isChecked(),
                ground_material=self.ground_material_settings(), ground_look=self.ground_look_settings(), skyline=self.skyline_settings(), style=self.style_settings(),
                ground_shadow=self.ground_shadow.isChecked(), materials=self.material_specs(),
                output=self.output_tab.settings(), doc_path=self.doc_path(),
                section_opts=self.section_tab.settings(), progress=self._export_progress(),
                viewport=getattr(self.app, "viewport", None))
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
        if "auto" in (self.preview_engine.currentData(), self.engine.currentData()):
            self._detect_gpu()
        self._live.set_follow_camera(self.commands.follow_camera.isChecked())
        self._live.set_follow_changes(self.commands.follow_changes.isChecked())
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
        box = widgets.Card("Camera", "camera", icon="grp_camera", kind="column")
        lay = box.body_layout
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
        if self._live is not None:
            self._live.set_follow_camera(self.commands.follow_camera.isChecked())
            self._live.set_follow_changes(self.commands.follow_changes.isChecked())

    def _live_image(self, path):
        """A frame of the live view: into the window while it shows the preview."""
        self._prep_close()                        # the first picture: the modal is no longer needed
        if not Path(path).is_file() or self.window is None or self.window.mode != "preview":
            return
        self.window.show_draft(path)
        self.window.set_preview_info(self._preview_info())

    def _preview_info(self) -> str:
        """What the picture in the preview window is: its engine and its size."""
        engine = "Cycles" if self.live_engine() == "cycles" else "EEVEE"
        w, h = self.window.view.picture_size()
        return tr("Preview: {engine} · {w} × {h} px", engine=engine, w=w, h=h)

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
            engine = {"cycles": "Cycles", "eevee": "EEVEE", None: tr("Automatic")}[self.final_engine()]
            self.window.set_summary(tr("Render: {engine} · {quality} · {w} × {h} px · {format}",
                                       engine=engine,
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
        self.flat_colour.changed.connect(self._schedule_save)
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
        self.style_groups.changed.connect(self._schedule_save)
        for sig in (self.shadow_draw.currentIndexChanged, self.shadow_opacity.valueChanged, self.shadow_spacing.valueChanged,
                    self.shadow_angle.valueChanged, self.shadow_colour.changed):
            sig.connect(self._schedule_save)
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
            "shadows": self.shadow_settings(),
            "hdri": ({"path": hdri, "rotation": round(_value(self.hdri_rotation), 3),
                      "brightness": round(_value(self.hdri_strength), 3),
                      "height": round(_value(self.hdri_height), 2),
                      "light": self.hdri_light.isChecked()}
                     if hdri and hdri != _CHOOSE and self.bg_mode.currentData() == "pano" else None),
            "backdrop": ({"path": pic, "fit": self.backdrop_fit.currentData(),
                          "brightness": round(_value(self.backdrop_strength), 3)}
                         if pic and pic != _CHOOSE and self.bg_mode.currentData() == "picture" else None),
            "flat": self.flat_settings(),
            **({"fine": fine} if (fine := self.fine_settings()) else {}),
        }

    def fine_settings(self) -> dict:
        """The finer settings not at their default ({} while the panel is being built)."""
        return self.fine.settings() if getattr(self, "fine", None) is not None else {}

    def _fine_enable(self) -> None:
        """The rows of the finer settings that mean something with the other choices."""
        if getattr(self, "fine", None) is None:
            return
        model = dict(self.style_groups.values())
        model.update({"background.kind": self.bg_mode.currentData(), "shadows.draw": self.shadow_draw.currentData(),
                      "ground.on": self.ground.isChecked(), "ambient.look": self.preset.currentData()})
        self.fine.enable(model)

    def _fine_changed(self) -> None:
        self._fine_enable()
        self._filter_layout()
        self._schedule_save()

    # -- the ambients and the presets ---------------------------------------------------------
    def set_ambient(self, look: str) -> None:
        """An ambient's button: only the light changes (the look, with its own values in the sliders it sets)."""
        index = self.preset.findData(look)
        if index >= 0:
            if index == self.preset.currentIndex():
                self._preset_changed(index)                  # pressed again: the look's own values come back
            else:
                self.preset.setCurrentIndex(index)
        self._ambient_state()
        self._schedule_save()

    def _sun_has_set(self) -> bool:
        """Whether a look of the day will be rendered as a night: the sun is down at the site's place, date and hour."""
        if self.preset.currentData() not in presets.NIGHT_WHEN_SUN_SET or (self.hdri_settings() or {}).get("light"):
            return False
        try:
            from . import sun_site
            return not sun_site.info(sun_site.site(self.app.scene))["up"]
        except Exception:  # noqa: BLE001 - not worked out: the look as chosen
            return False

    def _ambient_state(self, *_a) -> None:
        if getattr(self, "ambient", None) is not None:
            self.ambient.show_state(self.preset.currentData(), self._sun_has_set())

    def apply_preset(self, preset: dict) -> None:
        """Wear a preset's look; the camera, the quality, the section and the output stay."""
        self.apply_settings(preset_files.apply_to(self.settings_dict(), preset))
        self._schedule_save()

    def preview_picture(self):
        """The picture the preview window shows now, or None (closed, or nothing in it yet)."""
        window = self.window
        if window is None or not window.isVisible() or not window.has_image() or window.path is None:
            return None
        image = QImage(str(window.path))
        return None if image.isNull() else image

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
                   self.skyline_distance, self.skyline_seed,
                   self.shadow_draw, self.shadow_colour, self.shadow_opacity, self.shadow_spacing, self.shadow_angle,
                   self.hdri_rotation, self.hdri_strength, self.hdri_height, self.hdri_light,
                   self.bg_mode, self.backdrop, self.backdrop_fit, self.backdrop_strength, self.flat_colour,
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
            model = look_model.from_v1(data)
            self.style_groups.set_values(model)
            sh = settings_store.shadows(data.get("shadows"))
            self.shadow_draw.setCurrentIndex(max(0, self.shadow_draw.findData(sh["draw"])))
            self.shadow_colour.set_rgb(sh["color"])
            self.shadow_opacity.setValue(sh["opacity"] * 100.0)
            self.shadow_spacing.setValue(sh["spacing"])
            self.shadow_angle.setValue(sh["angle"])

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
            if getattr(self, "fine", None) is not None:
                self.fine.set_values(model)
            plain = data.get("flat")
            if plain:
                self.flat_colour.set_rgb(plain["color"])
            self.bg_mode.setCurrentIndex(self.bg_mode.findData(
                ("transparent" if plain.get("transparent") else "flat") if plain else "pano" if self.hdri.currentData() else ("picture" if self.backdrop.currentData() else "sky")))
            paper = model["background.paper_sky"]
            if paper and self.bg_mode.currentData() == "sky" and model["surface.kind"] != "paper":
                self.bg_mode.setCurrentIndex(self.bg_mode.findData("paper"))
            self._paper_under = paper and self.bg_mode.currentData() in ("flat", "pano", "picture")
        finally:
            for w in widgets:
                w.blockSignals(False)
            self._applying = False
        self._shadows_enable()
        self._floor_enable()
        for row in (self.ground_rough_row, self.ground_haze_row):
            row.update_value()
        for row in (*self.slider_rows.values(), self.hdri_rotation_row, self.hdri_strength_row, self.hdri_height_row,
                    self.backdrop_strength_row):
            row.update_value()                       # their signals were blocked
        self._hdri_enable()
        self._bg_enable()
        self._skyline_enable()
        self._update_summary()
        self._fine_enable()
        self._filter_layout()
        if getattr(self, "expert", None) is not None and self.expert.isVisible():
            self.expert.refresh()

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
        if hint and self.engine.currentData() != hint and self.final_engine() != hint:
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
        self.hdri.blockSignals(True)              # (before the insert: it moves «Choose a file…», which is the current line,
        if i < 0:                                 # and that change would open the dialog again)
            i = self.hdri.count() - 1             # before "Choose a file…"
            self.hdri.insertItem(i, Path(path).name, path)
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
    # -- the expert page and the layout ---------------------------------------------------------
    def set_expert_mode(self, on: bool) -> None:
        """The Expert page there or not; what the pages show is the layout's, either way."""
        index = self.tabs.indexOf(self.expert_page)
        if on and index < 0:
            self.tabs.addTab(self.expert_page, tr("Expert"))
        elif not on and index >= 0:
            self.tabs.removeTab(index)
        self.expert_page.setVisible(on and self.tabs.currentWidget() is self.expert_page)
        self._expert_peek = False                  # what the button says is what stays
        QSettings().setValue(_SETTINGS + "expert_mode", "true" if on else "false")

    # -- the groups: folded when a drawing opens, one at a time as an accordion ----------------------
    def _pages(self) -> list:
        """The panel's pages, the Expert one too (also while its tab is not there)."""
        pages = [self.tabs.widget(i) for i in range(self.tabs.count())]
        return [p for p in pages if p is not self.expert_page] + [self.expert_scroll]

    def _page_cards(self) -> list:
        return [card for page in self._pages() for card in page.findChildren(widgets.Card)]

    def _accordion(self, card) -> None:
        """With the accordion on, a group that opens folds the others of its page (not one that holds it, nor one
        inside it)."""
        if not self.expert.accordion.isChecked():
            return
        for page in self._pages():
            if not page.isAncestorOf(card):
                continue
            for other in page.findChildren(widgets.Card):
                if other is not card and not other.isAncestorOf(card) and not card.isAncestorOf(other):
                    other.set_open(False)

    def fold_groups(self) -> None:
        """Every group folded but the presets."""
        for card in self._page_cards():
            if card is not self.gallery:
                card.set_open(False)
        self.gallery.set_open(True)

    def _note_drawing(self) -> None:
        """A drawing just opened (or a new one) starts at the Main page with the groups folded. Coming back to its
        tab changes nothing, nor does saving it under a name: it has things to undo, so it was not just opened."""
        scene = getattr(self.app, "scene", None)
        key = (id(scene), self.doc_path())
        if key in self._drawings:
            return
        self._drawings.add(key)
        history = getattr(getattr(self.app, "viewport", None), "history", None)
        if not getattr(history, "undo_stack", None):
            self.tabs.setCurrentIndex(0)                 # the Main page, whatever was in view
            self.fold_groups()

    # -- a group's «+»: all its settings, in the Expert page ----------------------------------------
    def _add_more_buttons(self) -> None:
        """Each group of the pages that has settings in the Expert page gets a «+» in its header that opens them there."""
        groups: dict = {}
        for key, control in self.expert.controls.items():
            node = control
            while node is not None and not isinstance(node, widgets.Card):
                node = node.parentWidget()
            if node is not None:
                groups.setdefault(node, (params.BY_KEY[key].tab, params.BY_KEY[key].group))
        groups.setdefault(self.fx, ("style", "image"))            # «Effects»: settings of the picture, as «Corrections»
        tip = tr("All the settings of this group (Expert page)")
        for card, (tab, group) in groups.items():
            card.add_more_button(tip, lambda t=tab, g=group: self.open_expert_group(t, g))

    def open_expert_group(self, tab: str, group: str) -> None:
        """The Expert page at ``group``, unfolded. With «Expert mode» off the page is there only while one looks at it."""
        keys = {p.key for p in params.PARAMS if p.tab == tab and p.group == group}
        card = next((header for header, shown in self.expert.headers if keys & set(shown)), None)
        if card is None:
            return
        if self.tabs.indexOf(self.expert_page) < 0:
            self.tabs.addTab(self.expert_page, tr("Expert"))
            self._expert_peek = True
        self.tabs.setCurrentWidget(self.expert_page)
        self.expert.search.clear()                            # (a search left behind could be hiding it)
        card.set_open(True)
        self.expert.refresh()
        QTimer.singleShot(0, lambda: self._scroll_to(card))   # once the page is laid out

    def _scroll_to(self, card) -> None:
        try:
            self.expert.layout().activate()
            self.expert_scroll.verticalScrollBar().setValue(max(0, card.mapTo(self.expert, card.rect().topLeft()).y() - 4))
        except RuntimeError:                                  # the panel gone meanwhile
            _log.debug("no group to scroll to", exc_info=True)

    def _tab_chosen(self, index: int) -> None:
        if self._expert_peek and self.tabs.widget(index) is not self.expert_page:
            self._expert_peek = False
            QTimer.singleShot(0, self._drop_peek)             # (not while the tabs are telling of the change)
        if not self._expert_peek:
            QSettings().setValue(_SETTINGS + "tab", int(index))

    def _drop_peek(self) -> None:
        index = self.tabs.indexOf(self.expert_page)
        if index >= 0 and not self.expert_mode.isChecked() and self.tabs.currentWidget() is not self.expert_page:
            self.tabs.removeTab(index)

    def reapply_conditions(self) -> None:
        """Every row that depends on a choice, shown or hidden again as that choice says."""
        self.style_groups.enable()
        self.section_tab._paint()
        self._bg_enable()
        self._floor_enable()
        self._shadows_enable()
        self._skyline_enable()
        self._ground_grass_hint()
        self._fine_enable()
        try:
            self.sun_tab._show_sun()                    # the night's sliders or the sun's
        except Exception:  # noqa: BLE001 - while the panel is being built
            _log.exception("sun not shown")

    def _filter_layout(self) -> None:
        if getattr(self, "expert", None) is not None:
            self.expert.filter.apply()

    def _floor_enable(self, *_a):
        """«Shadow on the floor» can be chosen unless a generated ground is seen as it is."""
        self.ground_shadow.setEnabled(not self.ground.isChecked() or self.bg_mode.currentData() in ("flat", "transparent"))

    def _bg_enable(self, *_a):
        """Show the controls of the chosen background only (and say when the output hides it)."""
        mode = self.bg_mode.currentData()
        for key, rows in self._bg_rows.items():
            for w in rows:
                self._form_bg.setRowVisible(w, mode == key)
        self._form_bg.setRowVisible(self.bg_more, mode == "pano")
        self._hdri_enable()
        sky_only = mode in ("sky", "paper")
        if "clouds" in self.slider_rows and getattr(self, "sky_note", None) is not None:
            self.slider_rows["clouds"].setEnabled(sky_only)
            self.sky_note.setText("" if sky_only else tr("Clouds are the look's sky: the panorama or the picture has its own."))
            self.sky_note.setVisible(not sky_only)
        hidden = mode not in ("sky", "transparent") and bool(self.output_tab.transparent.isChecked())
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
        self.backdrop.blockSignals(True)              # (before the insert, as in set_hdri_path)
        if i < 0:
            i = self.backdrop.count() - 1             # before "Choose a file…"
            self.backdrop.insertItem(i, Path(path).name, path)
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

    def _build_shadows_box(self):
        """«Shadows»: how the sun's shadows are drawn, whatever the style. One choice; its settings only when it needs them."""
        from .section_panel import ColourButton
        box = widgets.Card("Shadows", "shadows", icon="grp_shadows")
        form = box.form
        self._form_shadows = form
        self.shadow_draw = QComboBox()
        for key, label in presets.SHADOW_DRAWS.items():
            self.shadow_draw.addItem(tr(label), key)
        self.shadow_draw.setToolTip("How the sun's shadows (and the faces turned away from it) are drawn: as Blender renders them, "
                                    "or painted over in a colour or a hatching.")
        form.addRow("Draw", self.shadow_draw)
        self.shadow_colour = ColourButton(presets.SHADOW_DEFAULT["color"], "Shadow colour")
        self.shadow_colour.setToolTip("The colour of the shadows, or of their hatching.")
        form.addRow("Colour", self.shadow_colour)
        self.shadow_opacity = widgets.NumberSlider(5.0, 100.0, 5.0, "{:.0f}%")
        self.shadow_opacity.setToolTip("How much the colour covers what is under it.")
        form.addRow("Intensity", self.shadow_opacity)
        self.shadow_spacing = widgets.NumberSlider(3.0, 40.0, 1.0, "{:.0f} px")
        self.shadow_spacing.setToolTip("The distance between lines or dots, in pixels of the picture. They are as thick as the outlines.")
        form.addRow("Hatch spacing", self.shadow_spacing)
        self.shadow_angle = widgets.NumberSlider(0.0, 175.0, 5.0, "{:.0f}°")
        self.shadow_angle.setToolTip("The direction of the hatching.")
        form.addRow("Hatch angle", self.shadow_angle)
        d = presets.SHADOW_DEFAULT
        self.shadow_opacity.setValue(d["opacity"] * 100.0)
        self.shadow_spacing.setValue(d["spacing"])
        self.shadow_angle.setValue(d["angle"])
        self.shadow_draw.currentIndexChanged.connect(self._shadows_enable)
        self._shadows_enable()
        return box

    def _shadows_enable(self, *_a) -> None:
        draw = self.shadow_draw.currentData() or "render"
        for w in (self.shadow_colour, self.shadow_opacity):
            self._form_shadows.setRowVisible(w, draw != "render")
        for w in (self.shadow_spacing, self.shadow_angle):
            self._form_shadows.setRowVisible(w, draw in ("lines", "cross", "dots"))

    def shadow_settings(self) -> dict:
        return {"draw": self.shadow_draw.currentData() or "render", "color": [round(float(c), 4) for c in self.shadow_colour.rgb()],
                "opacity": round(self.shadow_opacity.value() / 100.0, 3), "spacing": round(self.shadow_spacing.value(), 1),
                "angle": round(self.shadow_angle.value(), 1)}

    def _paper_behind(self, surface: str) -> bool:
        """Whether paper takes the sky's place: chosen as the background, asked for by a paper surface, or brought by the document."""
        return self.bg_mode.currentData() == "paper" or surface == "paper" or self._paper_under

    def _background_chosen(self, _i) -> None:
        self._paper_under = False                # what a person chooses is what there is
        if self.bg_mode.currentData() == "transparent" and self.output_tab.format.currentData() == "jpeg":
            self.output_tab.format.setCurrentIndex(self.output_tab.format.findData("png"))     # a JPEG has no transparency
            self._set_status(tr("The output is now PNG: a JPEG cannot be transparent."))

    def style_settings(self) -> dict:
        """The surface, outline, finish and paper as the document and the render job keep them (format 1's style)."""
        values = self.style_groups.values()
        values["background.paper_sky"] = self._paper_behind(values["surface.kind"])
        return look_model.style_of(values)

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
        self._ambient_state()                       # the sun may have set (or risen): the buttons say what will be rendered
        self._filter_layout()

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

    def flat_settings(self) -> dict | None:
        mode = self.bg_mode.currentData()
        if mode not in ("flat", "transparent"):
            return None
        out = {"color": [round(float(c), 4) for c in self.flat_colour.rgb()]}
        if mode == "transparent":
            out["transparent"] = True                # (kept as a plain colour that is not painted)
        return out

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
        self.editor.follow_selection()           # (also when the window was already open)
        self.editor.show()
        self.editor.raise_()
        self.editor.activateWindow()
        return self.editor

    def document_changed(self):
        if self.editor is not None and self.editor.isVisible():
            self.editor.refresh()
        if getattr(self, "_drawings", None) is not None:
            self._note_drawing()
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
        st.setValue(_SETTINGS + "flat_color", ",".join(f"{c:.4f}" for c in self.flat_colour.rgb()))
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
        self._start_clock()
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
        style = self.style_with_cut(settings_store.style(self.style_settings()))
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
            if outlines.cut_of(style):
                style["cut"] = dict(style["cut"], width=float(style["cut"].get("width", 2.4)) * height / ref)
            notes.append(f"width scaled to the frame: {height} of {ref} px")
        try:
            geom = self.line_geometry(notes)
        except Exception as exc:  # noqa: BLE001 - the 3D view's geometry
            _log.exception("outlines' geometry not worked out")
            notes.append(f"geometry NOT worked out: {type(exc).__name__}: {exc}")
            geom = None
        return outlines.write_layer(self.app.viewport, camera or self.app.viewport.camera, width, height, style, path, geom, notes)

    def style_with_cut(self, style: dict) -> dict:
        """The outline style with the cut's: while a section cuts the model (a plane, or IngeTrazo's section box), ``style["cut"]`` says how
        the rim of the cap is drawn (the Section tab) and whether the cap hides what is behind it."""
        from . import outlines
        try:
            if not outlines.cut_planes(self.app.scene):
                return style
        except Exception:  # noqa: BLE001
            return style
        opts = self.section_tab.settings()
        return dict(style, cut={"on": bool(opts.get("outline", True)), "color": list(opts.get("outline_color") or (0.05, 0.05, 0.05)),
                                "width": float(opts.get("outline_width", 2.4)), "cap": bool(opts.get("cap", True)), "srgb": True, "hand": float(opts.get("outline_hand", 0.0)), "opacity": float(opts.get("outline_opacity", 1.0))})

    def line_set(self, camera, width: int, height: int):
        """The outlines of the style as vectors for the FINAL picture (outlines.LineSet and the controls' starting style), or None. The
        render window draws them over the picture and lets them be restyled instantly; saving puts them in it."""
        from . import outlines
        style = self.style_with_cut(settings_store.style(self.style_settings()))
        if not outlines.wanted(style):
            return None
        self._set_status(tr("Drawing the outlines…"))
        QApplication.processEvents()
        notes: list = []
        cut = outlines.cut_of(style)
        try:
            geom = self.line_geometry(notes)
        except Exception as exc:  # noqa: BLE001 - the 3D view's geometry
            _log.exception("outlines' geometry not worked out")
            notes.append(f"geometry NOT worked out: {type(exc).__name__}: {exc}")
            geom = None
        try:
            lines = outlines.lineset(self.app.viewport, camera or self.app.viewport.camera, int(width), int(height), geom, notes,
                                     cut_outline=bool(cut and cut.get("on")), cap=bool(cut.get("cap", True)) if cut else True)
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
        engine = self._render_engine()
        if (out.get("projection") in ("flat", "360") or out.get("transparent") or self.bg_mode.currentData() == "transparent" or out.get("format") not in ("png", "jpeg")
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

    # -- render stopwatch + log ---------------------------------------------------
    @staticmethod
    def _fmt_elapsed(sec: float) -> str:
        sec = max(0.0, sec)
        h, rem = divmod(int(sec), 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _show_clock(self, text) -> None:
        self.clock.set_text(text)
        if self.window is not None:
            self.window.set_clock(text)

    def _start_clock(self) -> None:
        self._t0 = time.perf_counter()
        self._last_logged_pct = -1
        _log.info("Render started")
        if getattr(self, "_clock", None) is None:
            self._clock = QTimer(self)
            self._clock.setInterval(1000)
            self._clock.timeout.connect(self._tick_clock)
        self._clock.start()
        self._show_clock("0:00")

    def _tick_clock(self) -> None:
        t0 = getattr(self, "_t0", None)
        if t0 is None:
            return
        if self.proc is None and not self._preparing:      # the render ended some other way (failed to prepare, refused)
            took = self._stop_clock()
            _log.info("Render stopped after %.1f s", took or 0.0)
            return
        self._show_clock(self._fmt_elapsed(time.perf_counter() - t0))

    def _stop_clock(self) -> float | None:
        """Stop the stopwatch: the seconds the render took, or None when none was running."""
        t0, self._t0 = getattr(self, "_t0", None), None
        if getattr(self, "_clock", None) is not None:
            self._clock.stop()
        self._show_clock(None)
        return None if t0 is None else time.perf_counter() - t0

    def _log_progress(self, line: str, p) -> None:
        t0 = getattr(self, "_t0", None)
        at = self._fmt_elapsed(time.perf_counter() - t0) if t0 is not None else "-"
        if line.startswith("INGETRAZO"):
            _log.info("[%s] %s", at, line.strip())
        elif p is not None:
            pct = int(p * 100) // 10 * 10
            if pct != getattr(self, "_last_logged_pct", -1):
                self._last_logged_pct = pct
                _log.info("[%s] Render progress %d %%", at, int(p * 100))

    def _live_line(self, line: str) -> None:
        from core import render_blender as rb
        self._log_lines.append(line)
        p = rb.progress_of(line)
        self._log_progress(line, p)
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
                engine=self._render_engine(), quality=self.quality.currentIndex(),
                width=width, height=height, hdri=self.hdri_settings(), backdrop=self.backdrop_settings(), flat=self.flat_settings(), shadows=self.shadow_settings(), fine=self.fine_settings(), ground=self.ground.isChecked(),
                ground_material=self.ground_material_settings(), ground_look=self.ground_look_settings(), skyline=self.skyline_settings(), style=self.style_settings(), lines=lines,
                ground_shadow=self.ground_shadow.isChecked(),
                materials=self.material_specs(), output=out, doc_path=self.doc_path(),
                section_opts=self.section_tab.settings(), progress=self._export_status,
                viewport=getattr(self.app, "viewport", None))
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
                    f"{output.save_name()}{ext}")
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
            self._log_progress(line, p)
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
        took = self._stop_clock()
        stamp = (tr("Render time: {t}", t=self._fmt_elapsed(took)) if took is not None else "")
        if took is not None:
            _log.info("Render %s in %.1f s (%s)", "finished" if not (self._cancelled or failed) else "stopped",
                      took, self._fmt_elapsed(took))
        if self._cancelled or failed:
            if self._cancelled:
                self._set_status(tr("Render cancelled."))
            else:
                tail = "\n".join(l for l in self._log_lines if "Error" in l or "INGETRAZO" in l)[-600:]
                self._set_status(tr("The render failed (code {code}).\n{tail}", code=code, tail=tail) + ((chr(10) + stamp) if stamp else ""))
            self._back_to_preview_if_open()
            self.finished.emit(None)
            return
        self._bake_lines()
        kept = self._autosave()
        if save_to:
            if self._save_as_rendered(save_to):
                QSettings().setValue(_SETTINGS + "save_dir", str(Path(save_to).parent))
                self._set_status(tr("Saved: {path}", path=save_to) + (f" · {stamp}" if stamp else ""))
            else:
                self._set_status(tr("Rendered, but {path} could not be written (the picture is in {output}).", path=save_to, output=self.output))
            self._back_to_preview_if_open()
            self.finished.emit(self.output)
            return
        win = self.preview()
        self._direct = False                              # the picture stays in the window: it is the result
        self._set_status(tr("Done: {name}", name=self.output.name) + (" · " + tr("also saved in {path}", path=kept) if kept else "")
                         + (f" · {stamp}" if stamp else ""))
        win.set_image(self.output)                        # the retouch tools and Save image…
        if getattr(self, "_baked", None):
            win.set_outlines(*self._baked)                # the outlines, still vectors
        r = getattr(self, "rendered", None)
        win.set_rendered_file(r["file"] if r and not output.retouchable(r["format"]) else None,
                              output.FORMATS[r["format"]][0] if r else "")
        win.show()
        win.raise_()
        self.finished.emit(self.output)
