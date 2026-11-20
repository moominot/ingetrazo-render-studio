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

# ---- the format ----------------------------------------------------------------------------
ok(L.clean_light({"type": "laser"}) is None and L.clean_light("x") is None, "unknown kinds and junk are dropped")
c = L.clean_light({"type": "spot", "spot_angle": 500, "power": -3, "kelvin": 99999, "dir": [0, 0, 0], "pos": ["a"]})
ok(c["spot_angle"] == 180 and c["power"] == 0 and c["kelvin"] == L.MAX_KELVIN and c["dir"] == [0, 0, -1]
   and c["pos"] == [0, 0, 0], "numbers clamped, a null aim points down, a bad place is the origin")
two = L.clean_lights([{"type": "point", "id": "same"}, {"type": "point", "id": "same"}])
ok(len({lt["id"] for lt in two}) == 2, "a pasted duplicate gets an id of its own")
sun = L.clean_light({"type": "sun", "unit": "lm", "power": 2})
ok(sun["unit"] == "W" and L.blender_watts(sun) == 2, "a sun is always W/m²")
sq = L.clean_light({"type": "area", "shape": "square", "size": 0.5, "size_y": 3})
ok(sq["size_y"] == 0.5, "a square's length is its width")
ok(L.clean_light({"type": "point", "kelvin": None, "color": [2, 0.5, -1]})["color"] == [1, 0.5, 0],
   "a colour of its own is kept, clamped")

# ---- units -------------------------------------------------------------------------------
bulb = L.new_light("point", unit="lm", power=800)
ok(abs(L.blender_watts(bulb) - 2.1) < 0.01, f"an 800 lm bulb is ≈ 2.1 Blender W, as Blender's manual says ({L.blender_watts(bulb):.3f})")
spot = L.new_light("spot", unit="lm", power=800, spot_angle=40)
ratio = L.blender_watts(spot) / L.blender_watts(bulb)
ok(abs(ratio - 4 * math.pi / L.cone_solid_angle(40)) < 1e-9 and ratio > 8,
   f"a spot's lumens go into its cone: a 40° spot needs {ratio:.1f}× the watts of a bulb (Blender's spot is a masked point)")
w = L.convert_unit(spot, "W")
back = L.convert_unit(w, "lm")
ok(w["unit"] == "W" and abs(L.blender_watts(w) - L.blender_watts(spot)) < 1e-3 and abs(back["power"] - 800) < 0.5,
   "switching lm ↔ W keeps the brightness")
ok(L.power_label(L.new_light("point", unit="lm", power=1500)) == "1 500 lm" and L.power_label(sun) == "2 W/m²",
   "power labels")

# ---- aim and axes ----------------------------------------------------------------------
for h, t in ((0, 90), (90, 30), (225, -20), (10, 0)):
    ok(close(L.angles_from_aim(L.aim_from_angles(h, t)), (h if t != 90 else 0, t), 0.11), f"heading {h}, tilt {t} round trip")
x, y, z = L.light_basis([0, 0, -1])
ok(close(x, (1, 0, 0)) and close(y, (0, 1, 0)) and close(z, (0, 0, 1)), "a light aiming down has the world's axes (as Blender)")
x, y, z = L.light_basis([1, 0, 0], 90)
ok(close(z, (-1, 0, 0)) and abs(sum(a * b for a, b in zip(x, y))) < 1e-9, "a turned light keeps square axes")

# ---- IES ---------------------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
def ies(name, vert, horiz, cd, mult=1):
    rows = " ".join(" ".join(str(v) for v in r) for r in cd)
    p = tmp / name
    p.write_text(f"IESNA:LM-63-2002\n[TEST] x\nTILT=NONE\n1 -1 {mult} {len(vert)} {len(horiz)} 1 2 0 0 0\n1 1 0\n"
                 f"{' '.join(map(str, vert))}\n{' '.join(map(str, horiz))}\n{rows}\n", encoding="latin-1")
    return str(p)
uni = L.read_ies(ies("u.ies", [0, 90, 180], [0], [[1000, 1000, 1000]]))
ok(uni and abs(uni["flux"] - 4 * math.pi * 1000) / (4 * math.pi * 1000) < 0.02,
   f"a uniform 1000 cd profile gives 4π·1000 lm ({uni and uni['flux']:.0f})")
fine = L.read_ies(ies("f.ies", list(range(0, 181, 5)), [0], [[1000] * 37]))
ok(abs(fine["flux"] - 4 * math.pi * 1000) < 20, "…exactly with finer angles")
half = L.read_ies(ies("h.ies", list(range(0, 181, 5)), [0, 90], [[1000 if a <= 90 else 0 for a in range(0, 181, 5)]] * 2, mult=2))
ok(abs(half["flux"] - 2 * math.pi * 2000) / (2 * math.pi * 2000) < 0.05, "only downward, with a multiplier: half a sphere at 2000 cd (plus the 90°→95° fade)")
ok(L.read_ies(str(tmp / "missing.ies")) is None and L.read_ies(ies("bad.ies", [], [], [])) is None, "a missing or broken file reads as none")

# ---- a document with an app and its undo history -------------------------------------------------
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
scene.groups.append(lamp)
hist = app.viewport.history

k1 = ops.add_free(app, L.new_light("point", pos=(0, 0, 2.5)))
ok(len(L.free_lights(scene.plugin_data)) == 1 and k1[0] == "free", "a free light is in the document's data")
ok(hist.undo() and L.free_lights(scene.plugin_data) == [], "undo takes it away (one step)")
ok(hist.redo() and len(L.free_lights(scene.plugin_data)) == 1, "redo puts it back")

k2 = ops.add_to_object(app, lamp, L.new_light("point", pos=(1.2, 1.2, 1.6), name="bulb"))
loc = L.group_lights(lamp)[0]
ok(close(loc["pos"], (0.2, 0.2, 1.6)), f"a light on an object is kept in its axes ({loc['pos']})")
e = ops.entry(scene, k2)
ok(e and close(e["world"]["pos"], (1.2, 1.2, 1.6)), "…and shown in the world where it was put")
lamp.xform.translate(2, 0, 0)
ok(close(ops.entry(scene, k2)["world"]["pos"], (3.2, 1.2, 1.6)), "moving the object moves its light")
r = QMatrix4x4(); r.rotate(90, 0, 0, 1); lamp.xform = lamp.xform * r
ok(close(ops.entry(scene, k2)["world"]["pos"], (2.8, 1.2, 1.6)), "turning it turns the light about it")
twin = copy_group(lamp, QVector3D(0, 5, 0)); scene.groups.append(twin)
kt = ("object", (twin.uid,), loc["id"])
ok(ops.entry(scene, kt) is not None and close(ops.entry(scene, kt)["world"]["pos"], (2.8, 6.2, 1.6)),
   "a copy of the component carries its own light")
ok(len(L.siblings(scene, lamp)) == 2, "the two copies are found by their shared definition")

# an edit on every copy: the power and colour go to both, each keeps its place
w = dict(ops.entry(scene, k2)["world"], power=1500, kelvin=4000)
ops.update(app, k2, w, all_copies=True)
ok(ops.entry(scene, kt)["light"]["power"] == 1500 and ops.entry(scene, kt)["light"]["kelvin"] == 4000
   and close(ops.entry(scene, kt)["world"]["pos"], (2.8, 6.2, 1.6)), "an edit for every copy: power and colour, places kept")
moved = dict(ops.entry(scene, k2)["world"], pos=[2.8, 1.2, 2.0])
ops.update(app, k2, moved, all_copies=True)
ok(close(ops.entry(scene, kt)["world"]["pos"], (2.8, 6.2, 2.0)), "moving it inside the object moves it in every copy")
ops.update(app, k2, dict(ops.entry(scene, k2)["world"], power=10), all_copies=False)
ok(ops.entry(scene, kt)["light"]["power"] == 1500, "an edit of one copy leaves the other")
hist.undo()
ok(ops.entry(scene, k2)["light"]["power"] == 1500, "undo puts the object's light back")

# hidden objects give no light; lights switched off are not rendered
twin.hidden = True
ok(ops.entry(scene, kt) is None, "a hidden object's light is not there")
twin.hidden = False
ops.update(app, k1, dict(ops.entry(scene, k1)["world"], on=False))
block = L.job_block(scene)
ok(len(block) == 2 and all("energy" in lt and "basis" in lt for lt in block), "the job has the lights switched on, with Blender's power and axes")

# detach / attach
kd = ops.detach(app, k2)
ok(kd[0] == "free" and ops.entry(scene, kd) and close(ops.entry(scene, kd)["world"]["pos"], (2.8, 1.2, 2.0))
   and not L.group_lights(lamp), "freeing a light keeps it where it is")
hist.undo()
ok(len(L.group_lights(lamp)) == 1 and ops.entry(scene, kd) is None, "undo puts it back on the object, in one step")
ka = ops.attach(app, k1, twin)
ok(ka[0] == "object" and not L.free_lights(scene.plugin_data) and close(ops.entry(scene, ka)["world"]["pos"], (0, 0, 2.5)),
   "a free light put on an object stays where it is")

# the Render tab's lights: read, edited where that tab can follow, converted
scene.plugin_data["render_blender"] = {"ambience": "night", "lights": [
    {"kind": "spot", "pos": [0, 0, 3], "dir": [0, 0, -1], "power": 1500, "angle": 50, "kelvin": 3000, "on": True}]}
tab = [e for e in L.all_lights(scene) if e["source"] == "tab"]
ok(len(tab) == 1 and tab[0]["light"]["type"] == "spot" and tab[0]["light"]["unit"] == "W"
   and tab[0]["light"]["power"] == 1500, "the Render tab's spot is read in Blender watts")
ops.update(app, ("tab", 0), dict(tab[0]["world"], spot_angle=30, power=900))
rb = scene.plugin_data["render_blender"]
ok(rb["lights"][0]["angle"] == 30 and rb["lights"][0]["power"] == 900 and rb["ambience"] == "night",
   "editing it writes what the Render tab knows, and leaves its ambience")
kc = ops.convert_tab(app, 0)
ok(kc[0] == "free" and scene.plugin_data["render_blender"]["lights"] == [] and ops.entry(scene, kc)["light"]["power"] == 900,
   "converting moves it to Render Studio in one step")
hist.undo()
ok(len(scene.plugin_data["render_blender"]["lights"]) == 1 and ops.entry(scene, kc) is None, "…and undo brings it back")

# ---- the panel and its Lights tab ---------------------------------------------------------
panel = P.StudioPanel(app); app.on_document_changed(panel.document_changed)
ok([panel.tabs.tabText(i) for i in range(panel.tabs.count())] == ["Settings", "Lights", "Sun", "Output"],
   "the panel has its tabs: Settings, Lights, Sun, Output")
lt_tab = panel.lights_tab
heads = [lt_tab.tree.topLevelItem(i).text(0) for i in range(lt_tab.tree.topLevelItemCount())]
ok(heads == ["On objects", "From IngeTrazo's Render tab"], f"the list shows the sections that have lights ({heads})")
lt_tab.select(ka); ok(lt_tab.selected_key() == ka, "choosing a light in the list")
ok(lt_tab.spot_angle.isHidden() and not lt_tab.radius.isHidden() and lt_tab.aim_row.isHidden(),
   "a point light shows its bulb size, no beam and no aim")
lt_tab.kind.setCurrentIndex(lt_tab.kind.findData("area")); lt_tab._flush()
e = ops.entry(scene, lt_tab.selected_key())
ok(e["light"]["type"] == "area" and not lt_tab.shape.isHidden() and not lt_tab.aim_row.isHidden(),
   "its kind changed to area: shape and aim shown")
lt_tab.shape.setCurrentIndex(lt_tab.shape.findData("rectangle")); lt_tab.size.setValue(1.2); lt_tab.size_y.setValue(0.3)
lt_tab.tilt.setValue(45); lt_tab._flush()
e = ops.entry(scene, lt_tab.selected_key())
ok(e["light"]["shape"] == "rectangle" and e["light"]["size"] == 1.2 and e["light"]["size_y"] == 0.3
   and abs(L.angles_from_aim(e["world"]["dir"])[1] - 45) < 0.2, "shape, size and tilt edited")
n_before = len(hist._undo) if hasattr(hist, "_undo") else None
lt_tab.power.setValue(5000); lt_tab.kelvin_spin.setValue(5000); lt_tab._flush()
e = ops.entry(scene, lt_tab.selected_key())
ok(e["light"]["power"] == 5000 and e["light"]["kelvin"] == 5000, "power and colour edited together")
lt_tab.unit.setCurrentIndex(lt_tab.unit.findData("W"))
e = ops.entry(scene, lt_tab.selected_key())
ok(e["light"]["unit"] == "W" and abs(e["light"]["power"] - 5000 / L.LM_PER_W) < 0.01, "switching to watts converts the number")
# placing on a face: a downlight on a ceiling (normal down) shines down; a panel on a wall faces out
spot = lt_tab.place(L.new_light("spot"), [0, 0, 2.6], [0, 0, -1])
ok(close(spot["pos"], (0, 0, 2.57)) and close(spot["dir"], (0, 0, -1)), "a spot clicked on a ceiling hangs under it and shines down")
panel_light = lt_tab.place(L.new_light("area"), [3, 0, 1.5], [-1, 0, 0])
ok(close(panel_light["dir"], (-1, 0, 0)) and close(panel_light["pos"], (2.99, 0, 1.5)), "an area light on a wall lies on it, facing out")
bulb_air = lt_tab.place(L.new_light("point"), [1, 1, 1], None)
ok(bulb_air["pos"] == [1, 1, 1], "in the air, a light goes where clicked")
lt_tab._picking = ("new", "downlight"); lt_tab.on_object.setChecked(True)
lt_tab._picked([1.1, 1.1, 2.4], [0, 0, -1], lamp)
ok(lt_tab.selected_key() and lt_tab.selected_key()[0] == "object" and len(L.group_lights(lamp)) == 2,
   "a ready-made downlight placed on the object clicked")
lt_tab.on_object.setChecked(False)
n = len(L.all_lights(scene)); lt_tab.begin_add("sun")
ok(len(L.all_lights(scene)) == n + 1 and ops.entry(scene, lt_tab.selected_key())["light"]["type"] == "sun",
   "a sun is added at once (no place to click)")
lt_tab.delete_key(lt_tab.selected_key())
ok(len(L.all_lights(scene)) == n, "Supr on a light picked in the view deletes it")

# ---- the job -------------------------------------------------------------------------------
cam = OrbitCamera(); cam.target = QVector3D(0, 0, 1); cam.distance = 7
out = Path(tempfile.mkdtemp())
job, _script = P.write_studio_job(scene, cam, out / "job", "night", {}, engine="eevee", quality=0, width=320, height=200)
data = json.loads(job.read_text(encoding="utf-8"))
st_lights = data["studio"]["lights"]
ok(data["lights"] == [] and len(st_lights) == len(L.job_block(scene)) and any(l["source"] == "tab" for l in st_lights),
   "the job carries every light in the studio block (the Render tab's among them, not twice)")
ok(all(set(l) >= {"type", "pos", "dir", "energy", "color", "basis"} for l in st_lights), "each with what Blender needs")
key_a = panel.live_key()
ops.update(app, ka, dict(ops.entry(scene, ka)["world"], power=1, on=True))
ok(panel.live_key()[2] != key_a[2], "the live view sees a light's change")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
