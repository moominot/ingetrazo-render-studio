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

def quad(mesh, pts):
    return mesh.add_face([QVector3D(*p) for p in pts])

app = App(); scene = app.scene
quad(scene.mesh, [(-3, -3, 0), (3, -3, 0), (3, 3, 0), (-3, 3, 0)])
proto = Mesh(); quad(proto, [(0, 0, 0), (0.4, 0, 0), (0.4, 0.4, 0), (0, 0.4, 0)])
lamp = Group(proto, name="Floor lamp"); lamp.xform = QMatrix4x4(); lamp.xform.translate(1, 1, 0)
scene.groups.append(lamp); scene.version += 1  # direct edits: all_lights follows the version

from render_studio import blender_edit as BE, blender_session as BS
app = App(); scene = app.scene
k = ops.add_free(app, L.new_light("point", pos=(0, 0, 2.5), name="Lamp", power=800))
old = L.free_lights(scene.plugin_data)
sess = BS.BlenderSession(app, "lights", None)
sess._sent = old
def blender_view(lts, **over):
    out = []
    for lt in lts:
        x, y, z = L.light_basis(lt["dir"], lt["spin"])
        d = {"id": lt["id"], "name": lt["name"], "type": lt["type"], "on": True, "pos": lt["pos"], "x": x, "y": y, "z": z,
             "energy": L.blender_watts(lt), "color": lt["color"], "shadow": True, "radius": lt["radius"]}
        d.update(over); out.append(d)
    return out
steps = len(app.viewport.history.undo_stack) if hasattr(app.viewport.history, "undo_stack") else None
ok(sess.apply(blender_view(old)) is False, "a save with nothing changed takes nothing (no undo step)")
ok(sess.apply(blender_view(old, energy=L.blender_watts(old[0]) * 2)) is True, "a brighter lamp is taken")
now = L.free_lights(scene.plugin_data)
ok(len(now) == 1 and abs(now[0]["power"] - 1600) < 1 and now[0]["unit"] == "lm", "…in lumens, as the lamp was")
ok(app.viewport.history.undo() and abs(L.free_lights(scene.plugin_data)[0]["power"] - 800) < 1, "one undo brings the old power back")
ok(sess.apply([]) is True and L.free_lights(scene.plugin_data) == [], "deleting every light in Blender deletes them here")

# ---- a proxy light (edited in Blender): in the list, locked but for its name and place, and it can be unlocked ----------------
from render_studio import light_view
ok(L.clean_light({"type": "point", "blender": {"object": "L", "blend": "AAAA"}}).get("blender") == {"v": 1, "object": "L", "blend": "AAAA"}, "a light keeps the Blender light it carries")
ok("blender" not in L.clean_light({"type": "point", "blender": {"object": "L"}}) and "blender" not in L.clean_light({"type": "point", "blender": "x"}), "…and a junk one is dropped")
px = ops.add_free(app, L.new_light("spot", pos=(1, 1, 3), name="Spot in Blender", blender={"object": "S", "blend": "AAAA"}))
ok("Blender" in light_view._label(ops.entry(app.scene, px)["world"], 1), "the list shows it as a Blender light")
from render_studio import panel as P
panel = P.StudioPanel(app); app.on_document_changed(panel.document_changed)
tab = panel.lights_tab
tab.refresh(); tab.select(px); qa.processEvents()
ok(tab.lock_box.isVisibleTo(tab) or not tab.lock_box.isHidden(), "choosing it shows the lock notice")
locked = (tab.kind, tab.power, tab.kelvin_spin, tab.radius, tab.spot_angle, tab.shadow, tab.heading, tab.tilt)
ok(not any(w.isEnabled() for w in locked), "its settings are locked")
ok(tab.name.isEnabled() and all(w.isEnabled() for w in tab.xyz), "…but its name and its place are free")
tab.xyz[0].setValue(2.0); tab._flush()
e = ops.entry(app.scene, px)
ok(abs(e["world"]["pos"][0] - 2.0) < 1e-6 and e["world"].get("blender"), "moving it keeps the Blender light")
tab.unlock(); qa.processEvents()
e = ops.entry(app.scene, px)
ok("blender" not in e["world"] and e["world"]["type"] == "spot" and e["world"]["name"] == "Spot in Blender", "Unlock goes back to a Render Studio light with the same kind, name and place")
ok(tab.power.isEnabled() and not tab.lock_box.isVisibleTo(tab), "…and its settings are free again")
d = ops.add_free(app, L.new_light("point", pos=(0, 0, 1), blender={"object": "P", "blend": "BBBB"}))
tab.refresh(); tab.select(d); tab.duplicate(); 
ok(sum(1 for e in L.all_lights(app.scene) if e["world"].get("blender")) == 2, "a duplicate of a proxy is a proxy too")
print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
