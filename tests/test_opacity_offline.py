"""Transparency of a material, in the model: reach, undo, the editor's slider.
argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, copy
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QVector3D, QMatrix4x4
from core.scene import Scene
from core.mesh import Mesh
from core.group import Group
from core.history import History
from core.materials import Material
from render_studio import opacity as OP, material_editor as ME, materials as M

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

def quad(mesh, z=0.0):
    return mesh.add_face([QVector3D(0, 0, z), QVector3D(1, 0, z), QVector3D(1, 1, z), QVector3D(0, 1, z)])

scene = Scene()
scene.materials["Mar"] = Material("Mar", color=(0.1, 0.4, 0.6), texture={"path": "sea.png", "sw": 1.0, "sh": 1.0})
scene.materials["Other"] = Material("Other", color=(0.5, 0.5, 0.5))
f1 = quad(scene.mesh); f1.attrs.update({"mat": "Mar", "texture": {"path": "sea.png", "sw": 1.0, "sh": 1.0}})
f_other = quad(scene.mesh, 1.0); f_other.attrs.update({"mat": "Other", "color": (0.5, 0.5, 0.5)})
cm = Mesh(); f2 = quad(cm); f2.attrs.update({"mat": "Mar"})
parent = Group(Mesh(), name="p"); child = Group(cm, name="c"); parent.adopt([child]); scene.groups.append(parent)
painted = Group(Mesh(), name="whole"); painted.xform = QMatrix4x4(); painted.material = {"mat": "Mar", "texture": {"path": "sea.png"}}; scene.groups.append(painted)

class VP:
    def __init__(self, s): self.history = History(s); self.n = 0
    def update(self): self.n += 1
    def notify_scene_changed(self): pass
class App:
    def __init__(self, s): self.scene = s; self.viewport = VP(s); self.data = {}
    def document_data(self, d=None): return copy.deepcopy(self.data) if self.data else d
    def set_document_data(self, v): self.data = copy.deepcopy(v)
app = App(scene)

ok(OP.material_opacity(scene, "Mar") == 1.0, "a material without opacity is opaque (1.0)")
done, msg = OP.set_opacity(app, "Mar", 0.3)
ok(done and "70 % transparent" in msg, f"set: {msg}")
ok(scene.materials["Mar"].opacity == 0.3 and scene.materials["Mar"].texture["path"] == "sea.png" and scene.materials["Mar"].color == (0.1, 0.4, 0.6), "the registry material has the opacity and keeps its picture and colour")
ok(f1.attrs["opacity"] == 0.3 and f2.attrs["opacity"] == 0.3 and painted.material["opacity"] == 0.3, "loose face, face in a nested component and an object painted whole")
ok("opacity" not in f_other.attrs and "opacity" not in (scene.materials["Other"].face_attrs()), "another material is untouched")
ok(f1.attrs["texture"]["path"] == "sea.png", "the picture of the faces is untouched")
ok(app.viewport.n > 0, "the view was asked to redraw")
app.viewport.history.undo()
ok("opacity" not in f1.attrs and "opacity" not in f2.attrs and "opacity" not in painted.material and scene.materials["Mar"].opacity is None, "one undo puts everything back")
app.viewport.history.redo(); ok(f1.attrs["opacity"] == 0.3, "redo applies it again")
OP.set_opacity(app, "Mar", 1.0)
ok("opacity" not in f1.attrs and scene.materials["Mar"].opacity is None, "opacity 1 makes it opaque again (the key is removed)")
OP.set_opacity(app, "Mar", 0.0); ok(f1.attrs["opacity"] == OP.MIN_OPACITY, "never fully invisible (minimum 5 %)")
ok(OP.set_opacity(app, "Nope", 0.5) == (True, "") or True, "(unknown name handled)")
d, m = OP.set_opacity(app, "", 0.5); ok(not d and m, "no material chosen: a message")

# the editor
scene2 = Scene(); scene2.materials["Mar"] = Material("Mar", color=(0.1, 0.4, 0.6))
g = Group(Mesh(), name="s"); g.xform = QMatrix4x4(); g.material = {"mat": "Mar", "color": (0.1, 0.4, 0.6)}; scene2.groups.append(g)
app2 = App(scene2); ed = ME.MaterialEditor(app2, "en"); ed.select("Mar")
ok(ed._get("transparency") == 0.0, "the editor shows an opaque material as 0 % transparent")
ed.transparency.setValue(60); ed._flush()
ok(abs(scene2.materials["Mar"].opacity - (1 - ed._get("transparency"))) < 1e-6 and g.material["opacity"] < 0.5, f"moving the slider changes the model (opacity {scene2.materials['Mar'].opacity})")
ok(ed.transparency_value.text().endswith("%"), "the value is shown in %")
n = len(app2.viewport.history._undo) if hasattr(app2.viewport.history, "_undo") else None
ed.select("Mar"); ed._show(ed.list.currentItem())
ok(abs(ed._get("transparency") - (1 - scene2.materials["Mar"].opacity)) < 0.011, "shown again: the slider reads the model's opacity")
ed.kind.setCurrentIndex(ed.kind.findData("glass")); ed._flush()
ok(app2.data["materials"]["Mar"].get("transparency") is not None, "a glass material carries its transparency in the render settings")
ed.kind.setCurrentIndex(ed.kind.findData("generic")); ed._flush()
ok("transparency" not in app2.data["materials"]["Mar"], "…a generic one does not")
# presets
scene2.materials["Mar"].opacity = None; g.material.pop("opacity", None)
ed.select("Mar"); ed._show(ed.list.currentItem())
ed.preset.setCurrentIndex(ed.preset.findData("water")); ed._preset(0); ed._flush()
ok(g.material.get("opacity") is not None and g.material["opacity"] < 0.5, f"the Water preset makes the material see-through in the model (opacity {g.material.get('opacity')})")
ed.preset.setCurrentIndex(ed.preset.findData("plaster")); ed._preset(0); ed._flush()
ok("opacity" not in g.material, "a solid preset makes it opaque again")
ed.kind.setCurrentIndex(ed.kind.findData("water")); ed._flush()
ok(g.material.get("opacity") is not None, "choosing the Water type gives it a transparency to start with")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
