"""Render Studio's lights, without Blender: the format and its units, IES profiles, lights on
objects (moved, turned, copied with them), the one-step edits with undo/redo, the Lights tab and
the render job. argv: <ingetrazo-src> <render-studio repo>"""
import json, math, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QMatrix4x4, QVector3D
from core.camera import OrbitCamera
from core.group import Group, copy_group
from core.history import History
from core.mesh import Mesh
from core.scene import Scene
from render_studio import light_ops as ops, lights as L, panel as P

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

def close(a, b, tol=1e-4):
    return all(abs(x - y) <= tol for x, y in zip(a, b))

class VP:
    def __init__(self, scene):
        self.scene = scene; self.history = History(scene); self.changes = 0; self.listeners = []
        self.camera = OrbitCamera()
    def notify_scene_changed(self):
        self.changes += 1
        for fn in self.listeners: fn()
    def update(self): pass
    def width(self): return 1600
    def height(self): return 900
class App:
    api_version = 2
    def __init__(self):
        self.scene = Scene(); self.viewport = VP(self.scene); self.key = "render_studio"
    def document_data(self, default=None):
        d = (self.scene.plugin_data or {}).get(self.key)
        return json.loads(json.dumps(d)) if d is not None else default
    def set_document_data(self, v):
        from core.history import SetPluginDataCommand
        self.viewport.history.execute(SetPluginDataCommand(self.key, v)); self.viewport.notify_scene_changed()
    def on_document_changed(self, fn): self.viewport.listeners.append(fn)


import time, tempfile
from PySide6.QtCore import QCoreApplication, QSettings
_ini = tempfile.mkdtemp()
QCoreApplication.setOrganizationName("rs-test"); QCoreApplication.setApplicationName("rs-test")
QSettings.setDefaultFormat(QSettings.IniFormat); QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, _ini)
BLENDER = sys.argv[3]
class FakeFound:
    command = [BLENDER]
app = App(); scene = app.scene
def q(pts, color):
    f = scene.mesh.add_face([QVector3D(*p) for p in pts]); f.attrs["color"] = color
q([(-20, -20, 0), (20, -20, 0), (20, 20, 0), (-20, 20, 0)], (0.5, 0.5, 0.45))
for a, b in (((-1, -1), (1, -1)), ((1, -1), (1, 1)), ((1, 1), (-1, 1)), ((-1, 1), (-1, -1))):
    q([(a[0], a[1], 0), (b[0], b[1], 0), (b[0], b[1], 2), (a[0], a[1], 2)], (0.8, 0.8, 0.8))
scene.version += 1
app.viewport.camera = OrbitCamera(); app.viewport.camera.target = QVector3D(0, 0, 1.5); app.viewport.camera.distance = 12
panel = P.StudioPanel(app); app.on_document_changed(panel.document_changed)
panel.blender = lambda: FakeFound()
panel.check_blender = lambda: FakeFound()

from render_studio import light_ops as ops, lights as L
ops.add_free(app, L.new_light("point", pos=(3, 3, 2.5), name="Lamp", power=900))
off = ops.add_free(app, L.new_light("point", pos=(-3, 3, 2.5), name="Off lamp", power=500, on=False))
ops.add_free(app, L.new_light("spot", pos=(0, -4, 3), name="Spot", dir=[0.0, 0.5, -1.0]))
mod = os.path.join(tempfile.mkdtemp(), "person.py")
open(mod, "w").write("""
import bpy
o = next(o for o in bpy.data.objects if o.type == "LIGHT" and o.name == "Lamp")
o.data.use_custom_distance = True      # something Render Studio's lights have no place for
o.data.cutoff_distance = 9.0
o.data.energy *= 3
o.location.x += 1.0
""")
os.environ["RENDER_STUDIO_EDIT_AFTER"] = mod
tab = panel.lights_tab
msgs = []
tab._say = lambda t: msgs.append(t)
objs0 = None
tab.edit_in_blender()
t = time.time()
while time.time() - t < 240:
    qa.processEvents(); time.sleep(0.05)
    lts = L.free_lights(app.scene.plugin_data)
    if any(l.get("blender") for l in lts):
        break
lts = L.free_lights(app.scene.plugin_data)
print("LIGHTS", [(l["name"], l["type"], bool(l.get("blender")), l["on"], [round(c, 2) for c in l["pos"]]) for l in lts])
print("MSGS", msgs[-3:])
by = {l["name"]: l for l in lts}
ok(len(lts) == 3, "no light is lost or made up")
ok(by["Lamp"].get("blender") and abs(by["Lamp"]["pos"][0] - 4.0) < 0.01, "the lamp edited in Blender (a setting of Blender's own, moved) comes back as a proxy, where it was left")
ok(not by["Spot"].get("blender") and by["Spot"]["type"] == "spot", "a light nobody touched stays as it was")
ok(by["Off lamp"]["on"] is False and not by["Off lamp"].get("blender"), "a light switched off (not in the render's scene) is kept, not deleted")
print("FAILED" if fails else "ALL PASSED", len(fails)); sys.exit(1 if fails else 0)
