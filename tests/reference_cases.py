"""The reference cases: documents' settings (format 1) that cover every style, and the small scene they are rendered on. The render
job each one makes, through the real panel, is the reference a change to the settings must keep (test_reference_jobs.py)."""
from __future__ import annotations

import json
import math

SKY = {"look": "clear", "ground": True, "ground_shadow": True}


def _style(**k):
    return dict({"mode": "none", "width": 0.0, "color": [0.05, 0.05, 0.05], "material": "", "model_color": [0.85, 0.8, 0.7],
                 "lux_max": 0.0, "noise": 0.5, "extend": 0.4, "wetness": 0.5, "paper": 0.5, "edges": 0.4, "base": True}, **k)


CASES = {
    "realistic": dict(SKY, style=_style()),
    "realistic_outlines": dict(SKY, style=_style(width=0.8, color=[0.2, 0.05, 0.05])),
    "white": dict(SKY, style=_style(mode="white", width=0.8)),
    "model_colour": dict(SKY, style=_style(mode="model", model_color=[0.4, 0.5, 0.7])),
    "model_material": dict(SKY, style=_style(mode="model", material="Fusta", width=1.2)),
    "sketch": dict(SKY, style=_style(mode="sketch", width=1.0, noise=0.6, extend=0.3)),
    "sketch_lines_only": dict(SKY, style=_style(mode="sketch", base=False, noise=0.2, extend=0.0),
                              shadows={"draw": "lines", "color": [0.1, 0.1, 0.1], "opacity": 0.7, "spacing": 7.0, "angle": 45.0}),
    "watercolour": dict(SKY, style=_style(mode="watercolour", wetness=0.7, paper=0.6, edges=0.3)),
    "lux": dict(SKY, style=_style(mode="light", width=0.8, lux_max=50000.0)),
    "night": {"look": "night", "ground": True, "ground_shadow": True, "style": _style(), "sliders": {"stars": 1.5, "moon": 0.8}},
    "white_plan": {"look": "overcast", "ground": False, "ground_shadow": True, "style": _style(width=0.6),
                   "flat": {"color": [1.0, 1.0, 1.0]},
                   "shadows": {"draw": "colour", "color": [0.2, 0.25, 0.4], "opacity": 0.4, "spacing": 8.0, "angle": 45.0}},
    "golden_ground": {"look": "golden_hour", "ground": True, "ground_shadow": True, "style": _style(),
                      "ground_look": {"type": "grass", "color": [0.16, 0.27, 0.09], "roughness": 0.95, "haze": 2.0, "offset": -0.1},
                      "skyline": {"type": "hills", "height": 5.0, "distance": 0.0, "seed": 3, "color": None},
                      "sliders": {"exposure_bias": 0.5, "clouds": 0.6, "sun_scale": 1.3, "warmth": 0.4, "saturation": 1.2,
                                  "vignette": 0.3, "fog": 0.2, "fog_start": 20.0, "ao": 0.4, "ao_distance": 0.8, "dof": 0.2}},
}


def scene():
    """A little house: coloured walls, a pane of glass, a wooden block."""
    from PySide6.QtGui import QVector3D as V

    from core.group import Group
    from core.materials import Material
    from core.mesh import Mesh
    from core.scene import Scene

    def box(name, lo, hi, colour):
        m = Mesh()
        (x0, y0, z0), (x1, y1, z1) = lo, hi
        P = V
        for q in ([P(x0, y0, z0), P(x1, y0, z0), P(x1, y0, z1), P(x0, y0, z1)], [P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)],
                  [P(x1, y1, z0), P(x0, y1, z0), P(x0, y1, z1), P(x1, y1, z1)], [P(x0, y1, z0), P(x0, y0, z0), P(x0, y0, z1), P(x0, y1, z1)],
                  [P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)], [P(x0, y1, z0), P(x1, y1, z0), P(x1, y0, z0), P(x0, y0, z0)]):
            m.add_face(q).attrs["color"] = colour
        return Group(m, name=name)

    out = Scene()
    out.groups.append(box("walls", (0, 0, 0), (5, 4, 3), (0.72, 0.38, 0.22, 1.0)))
    out.groups.append(box("block", (6, 0.5, 0), (7.5, 2, 1.2), (0.45, 0.3, 0.16, 1.0)))
    out.groups.append(box("roof", (-0.3, -0.3, 3), (5.3, 4.3, 3.3), (0.35, 0.37, 0.41, 1.0)))
    out.materials["Fusta"] = Material("Fusta", color=(0.55, 0.36, 0.18))
    return out


def camera():
    from PySide6.QtGui import QVector3D

    from core.camera import OrbitCamera
    cam = OrbitCamera()
    cam.target = QVector3D(3.2, 2.0, 1.4)
    cam.distance = 17.0
    cam.yaw = math.radians(-55)
    cam.pitch = math.radians(24)
    cam.aspect = 16 / 9
    return cam


class _Signal:
    def connect(self, *a):
        pass


class _Viewport:
    sceneChanged = _Signal()

    def __init__(self, scene_, camera_):
        self.scene, self.camera = scene_, camera_

    def update(self):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return None


class App:
    api_version = 2

    def __init__(self):
        self.scene = scene()
        self.viewport = _Viewport(self.scene, camera())
        self.data = {}

    def document_data(self, default=None):
        return json.loads(json.dumps(self.data)) if self.data else default

    def set_document_data(self, value):
        self.data = json.loads(json.dumps(value))

    def on_document_changed(self, fn):
        pass


def panel():
    """The real panel, offscreen, on the reference scene, with its settings kept in a throwaway place."""
    import tempfile

    from PySide6.QtCore import QCoreApplication, QSettings
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
    QCoreApplication.setOrganizationName("render_studio_reference")
    QCoreApplication.setApplicationName("render_studio_reference")
    from render_studio import panel as P
    return P.StudioPanel(App())


def job_of(panel_, settings: dict, work):
    """The render job the panel makes with ``settings`` (format 1), as ``(job path, script path, comparable job)``: the paths of
    the throwaway folder are replaced, so two runs can be compared."""
    from pathlib import Path

    from render_studio import settings_store
    panel_.apply_settings({"look": "clear"})                     # nothing left over from the case before
    panel_.apply_settings(settings_store.clean(settings))
    work = Path(work)
    job, script = panel_.live_job(work, 480, 270)
    text = job.read_text(encoding="utf-8")
    for form in (str(work), str(work).replace("\\", "/"), json.dumps(str(work))[1:-1]):
        text = text.replace(form, "<WORK>")
    return job, script, json.loads(text)
