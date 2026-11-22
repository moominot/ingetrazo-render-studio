"""Making, copying and applying materials from the material editor, the eyedropper and the paint bucket.
Each making or copying is ONE undo step. Offscreen, with IngeTrazo's own commands and history.
argv: <ingetrazo-src> <render-studio repo>"""
import json, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtGui import QAction, QColor, QImage, QVector3D
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from core.group import Group
from core.history import History
from core.materials import Material
from core.mesh import Mesh
from core.scene import Scene
from tools.paint import PaintTool
from render_studio import material_editor as ME, material_tools as MT
from render_studio.new_material import NewMaterialDialog

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

pic = os.path.join(tempfile.mkdtemp(), "bricks.png")
img = QImage(40, 20, QImage.Format_RGB32); img.fill(QColor(180, 70, 50)); img.save(pic)

class VP:
    def __init__(self, scene):
        self.scene = scene; self.history = History(scene); self.changes = 0
    def notify_scene_changed(self): self.changes += 1
    def update(self): pass
class Win:
    def __init__(self):
        self._act_eyedropper = QAction("eyedropper"); self._act_eyedropper.setCheckable(True)
        self._act_eyedropper.toggled.connect(lambda on: setattr(PaintTool, "sample_armed", bool(on)))
        self.tools = []
    def _activate_tool(self, key): self.tools.append(key)
class App:
    def __init__(self):
        self.scene = Scene(); self.viewport = VP(self.scene); self.key = "render_studio"; self.window = Win()
    def document_data(self, default=None):
        d = (self.scene.plugin_data or {}).get(self.key)
        return json.loads(json.dumps(d)) if d is not None else default
    def set_document_data(self, v): raise AssertionError("the plain call is its own, separate undo step")

app = App(); scene = app.scene
f1 = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
f2 = scene.mesh.add_face([QVector3D(2, 0, 0), QVector3D(3, 0, 0), QVector3D(3, 1, 0), QVector3D(2, 1, 0)])
grp = Group(Mesh(), name="slab"); scene.groups.append(grp)
hist = app.viewport.history

scene.selection.update([f1, grp])
ok(MT.selection_count(scene) == 2, "the selection counts a face and an object")
name, painted = MT.create_material(app, "Concrete", color=(0.5, 0.4, 0.3), opacity=None, apply=True)
ok(name == "Concrete" and painted == 2, f"a material is made and paints the selection ({name}, {painted})")
ok("Concrete" in scene.materials and f1.attrs.get("mat") == "Concrete" and tuple(f1.attrs["color"]) == (0.5, 0.4, 0.3),
   "…the face wears it, by name and colour")
ok(grp.material and grp.material.get("mat") == "Concrete", "…and the object is painted as a whole")
ok(f2.attrs.get("mat") is None, "what was not selected is left alone")
hist.undo()
ok("Concrete" not in scene.materials and f1.attrs.get("mat") is None and grp.material is None,
   "ONE undo takes the material, the face's paint and the object's paint away")
hist.redo()
ok("Concrete" in scene.materials and f1.attrs.get("mat") == "Concrete", "…and redo brings them back")

n2, _p = MT.create_material(app, "Concrete", color=(0.1, 0.1, 0.1), apply=False)
ok(n2 == "Concrete (2)" and n2 in scene.materials and f1.attrs.get("mat") == "Concrete", "a name in use gets a number, nothing is repainted")
n3, _p = MT.create_material(app, "Bricks", texture={"path": pic, "sw": 2.0, "sh": 1.0}, apply=False)
ok(scene.materials[n3].texture["path"] == pic and scene.materials[n3].color is None, "a material with a picture has the picture, no colour")

scene.selection.clear(); scene.selection.add(f2)
ok(MT.apply_to_selection(app, n3) == 1 and f2.attrs.get("mat") == n3 and f2.attrs["texture"]["path"] == pic,
   "applying a picture material paints the selected face with its picture")
hist.undo()
ok(f2.attrs.get("mat") is None and "texture" not in f2.attrs, "…one undo step")
ok(MT.apply_to_selection(app, "Nothing") is None, "an unknown material applies nothing")

# the settings of a material, copied with it
app.scene.plugin_data["render_studio"] = {"materials": {"Bricks": {"type": "generic", "roughness": 0.3,
                                                                  "image": {"hue": 40, "tint": [1, 0.5, 0.5]}}}}
scene.materials["Bricks"] = Material("Bricks", texture={"path": pic, "sw": 1.5, "sh": 0.75}, finish="satin")
new, _p = MT.duplicate_material(app, "Bricks")
sp = app.document_data({})["materials"]
ok(new == "Bricks (2)" and new in scene.materials and scene.materials[new].texture == scene.materials["Bricks"].texture
   and scene.materials[new].finish == "satin", f"a copy has the picture and the finish ({new})")
ok(sp[new] == sp["Bricks"] and sp[new] is not sp["Bricks"], "…and the editor's settings, in a copy of their own")
sp2 = app.document_data({}); sp2["materials"][new]["roughness"] = 0.9
ok(app.document_data({})["materials"]["Bricks"]["roughness"] == 0.3, "(changing one does not change the other)")
hist.undo()
ok(new not in scene.materials and new not in (app.document_data({}) or {}).get("materials", {}),
   "ONE undo removes the copy and its settings")
hist.redo()
ok(new in scene.materials and new in app.document_data({})["materials"], "…redo puts them back")
ok(MT.duplicate_material(app, "Nobody") == (None, 0), "copying a material the document does not have does nothing")

# deleting a material: only one nothing wears, one undo step
ok(MT.delete_material(app, "Bricks (2)") and "Bricks (2)" not in scene.materials, "an unused material can be deleted")
hist.undo()
ok("Bricks (2)" in scene.materials, "…and one undo brings it back")
hist.redo()
ok("Bricks (2)" not in scene.materials and MT.delete_material(app, "Nobody") is False, "…redo takes it out again; one that is not there does nothing")
from PySide6.QtGui import QVector3D as _V
from core.mesh import Mesh as _M
from core.group import Group as _G
_m = _M(); _f = _m.add_face([_V(0, 0, 0), _V(1, 0, 0), _V(1, 1, 0)]); _f.attrs["mat"] = "Bricks"
scene.groups.append(_G(_m, name="wall")); scene.version += 1
ok(MT.delete_material(app, "Bricks") is False and "Bricks" in scene.materials, "a material painted on the model is not deleted")

# the paint bucket
PaintTool.current_material = None
ok(MT.arm_paint_bucket(app, "Bricks") and PaintTool.current_material is scene.materials["Bricks"]
   and PaintTool.current_texture["path"] == pic and app.window.tools == ["paint"],
   "the paint bucket makes it the Paint tool's material and picks the tool")
ok(MT.arm_paint_bucket(app, "Concrete") and tuple(PaintTool.current_color) == (0.5, 0.4, 0.3) and PaintTool.current_texture is None,
   "a flat colour material paints its colour")
ok(not MT.arm_paint_bucket(app, "Nobody"), "an unknown material arms nothing")

# the editor: buttons, the eyedropper
ed = ME.MaterialEditor(app, "en")
f3 = scene.mesh.add_face([QVector3D(5, 0, 0), QVector3D(6, 0, 0), QVector3D(6, 1, 0), QVector3D(5, 1, 0)]); f3.attrs["mat"] = "Concrete"
ed.refresh(force=True)
ed.select("Bricks")
ed.duplicate_current()
ok(ed.current_name() == "Bricks (3)", f"the Duplicate button copies the chosen material and chooses the copy ({ed.current_name()})")
ed.paint_with_it()
ok(PaintTool.current_material is scene.materials["Bricks (3)"] and app.window.tools[-1] == "paint", "the Paint button arms the paint bucket with it")

PaintTool.sample_armed = False
ed.pick_from_view()
ok(PaintTool.sample_armed and app.window._act_eyedropper.isChecked() and ed._pick_timer.isActive(), "the eyedropper button arms IngeTrazo's sampler")
ed._poll_pick()
ok(ed.pipette_btn.isChecked() and ed._pick_timer.isActive(), "…and waits while nothing is clicked")
PaintTool.sample_armed = False; PaintTool.current_is_default = False; PaintTool.current_material = scene.materials["Concrete"]
app.window._act_eyedropper.blockSignals(True); app.window._act_eyedropper.setChecked(False); app.window._act_eyedropper.blockSignals(False)
ed._poll_pick()
ok(ed.current_name() == "Concrete" and not ed.pipette_btn.isChecked() and not ed._pick_timer.isActive(),
   "after a click, the sampled material is chosen in the editor")
ed.pick_from_view(); PaintTool.sample_armed = False; PaintTool.current_is_default = True; PaintTool.current_material = None
app.window._act_eyedropper.blockSignals(True); app.window._act_eyedropper.setChecked(False); app.window._act_eyedropper.blockSignals(False)
ed._poll_pick()
from render_studio.i18n import tr
ok(ed.hint.text() == tr("That surface wears no named material (it is the default one)."), "a face with the default paint says so")

# the dialog's values
dlg = NewMaterialDialog(None, "Paint", 2, "")
dlg.name.setText("Warm wall"); dlg.set_colour((0.9, 0.7, 0.5))
v = dlg.values()
ok(v["name"] == "Warm wall" and v["color"] == (0.9, 0.7, 0.5) and v["apply"] is True and "texture" not in v, "the dialog gives a name and a colour")
dlg.set_picture(pic); dlg.tile.setValue(2.0)
v = dlg.values()
ok(v["texture"] == {"path": pic, "sw": 2.0, "sh": 1.0} and "color" not in v, "a picture keeps its proportions (a 2:1 image 2 m wide is 1 m high)")
empty = NewMaterialDialog(None, "x", 0, "")
ok(not empty.apply.isEnabled(), "with nothing selected there is nothing to paint")

# ---- a material taken from an element inside a component ----------------------------------------------------
from render_studio import materials as M
def mesh_with(name, mat):
    m = Mesh(); fc = m.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
    fc.attrs["mat"] = mat; return m, fc
top = Group(Mesh(), name="House")
mid_mesh, _f = mesh_with("mid", "Stone"); mid = Group(mid_mesh, name="Wall")
leaf_mesh, leaf_face = mesh_with("leaf", "Moss"); leaf = Group(leaf_mesh, name="Plant")
mid.adopt([leaf]); top.adopt([mid])
scene.groups.append(top)
scene.materials["Stone"] = Material("Stone", color=(0.5, 0.5, 0.5)); scene.materials["Moss"] = Material("Moss", color=(0.2, 0.5, 0.2))
scene.selection.clear(); scene.selection.add(top)
ok(M.selection_material(scene) == "Stone", "a selected component gives the first material inside it, nested placements included")
scene.selection.clear(); scene.selection.add(leaf)
ok(M.selection_material(scene) == "Moss", "a component two levels down gives its own")
scene.selection.clear(); scene.selection.add(leaf_face)
ok(M.selection_material(scene) == "Moss", "a face inside gives its material")
painted = Group(Mesh(), name="Painted"); painted.material = {"mat": "Wood", "color": (0.6, 0.4, 0.2)}
scene.groups.append(painted); scene.materials["Wood"] = Material("Wood", color=(0.6, 0.4, 0.2))
scene.selection.clear(); scene.selection.add(painted)
ok(M.selection_material(scene) == "Wood", "a component painted whole gives that paint")

scene.version += 1                                                                # (a drawing changed by hand: the list's cache is told)
ed.refresh(force=True)
ed.pick_from_view(); PaintTool.sample_armed = False
PaintTool.current_is_default = False; PaintTool.current_material = None           # the sampler found no name...
scene.selection.clear(); scene.selection.add(top)                                  # ...but the component is selected
app.window._act_eyedropper.blockSignals(True); app.window._act_eyedropper.setChecked(False); app.window._act_eyedropper.blockSignals(False)
ed._poll_pick()
ok(ed.current_name() == "Stone" and "Stone" in ed.hint.text(), f"the eyedropper falls back to what is selected ({ed.current_name()})")
ed.pick_from_view(); PaintTool.sample_armed = False
PaintTool.current_is_default = False; PaintTool.current_material = Material("Ghost", color=(1, 0, 0))
scene.selection.clear()
app.window._act_eyedropper.blockSignals(True); app.window._act_eyedropper.setChecked(False); app.window._act_eyedropper.blockSignals(False)
ed._poll_pick()
ok("Ghost" in ed.hint.text() and ed.hint.text() == tr("{name} is not in the list of materials (paint a face with it first).", name="Ghost"), f"a name the list does not hold is said, not ignored ({ed.hint.text()[:60]})")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
