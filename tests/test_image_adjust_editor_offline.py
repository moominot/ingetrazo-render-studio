"""The picture adjustments of the material editor (hue, saturation, brightness, contrast, rotation, tint, flat
colour): what is kept in the material's settings, only what differs from the picture as it is.
argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, copy, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QColor, QImage, QVector3D
from core.scene import Scene
from core.mesh import Mesh
from core.group import Group
from core.materials import Material
from render_studio import material_editor as ME, materials as M
from render_studio.image_adjust import ImageAdjust

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

pic = os.path.join(tempfile.mkdtemp(), "brick.png")
img = QImage(8, 8, QImage.Format_RGB32); img.fill(QColor(200, 60, 40)); img.save(pic)

# the widget alone
w = ImageAdjust()
ok(w.spec() is None, "nothing changed: nothing kept")
w.sliders["hue"].setValue(40); w.sliders["saturation"].setValue(150); w.sliders["rotation"].setValue(-90)
s = w.spec()
ok(s == {"hue": 40, "saturation": 1.5, "rotation": -90}, f"only what differs is kept, in the spec's units ({s})")
w.set_colour("tint", (0.9, 0.5, 0.2)); w.tint_strength.setValue(70)
ok(w.spec()["tint"] == [0.9, 0.5, 0.2] and w.spec()["tint_strength"] == 0.7, "a tint with its strength")
w.tint_strength.setValue(0)
ok("tint" not in w.spec(), "a tint of 0 % is nothing")
w.set_colour("flat", (0.1, 0.2, 0.3))
ok(w.spec()["flat"] == [0.1, 0.2, 0.3] and w.flat_check.isChecked(), "a flat colour replaces the picture")
w.reset()
ok(w.spec() is None and not w.flat_check.isChecked(), "reset goes back to the picture as it is")
w.load({"hue": -30, "brightness": 0.25, "tint": [1, 0, 0], "tint_strength": 0.4, "flat": [0.5, 0.5, 0.5]}, True)
ok(w.sliders["hue"].value() == -30 and w.sliders["brightness"].value() == 25 and w.tint == [1, 0, 0]
   and w.tint_strength.value() == 40 and w.flat_check.isChecked(), "a spec is shown in the controls")
changes = []
w.changed.connect(lambda: changes.append(1))
w.load(None, True)
ok(not changes, "loading does not announce a change")
w.sliders["contrast"].setValue(10)
ok(len(changes) == 1, "moving a slider does")

# in the editor
scene = Scene()
scene.materials["Brick"] = Material("Brick", texture={"path": pic, "sw": 1.0, "sh": 1.0})
scene.materials["Plain"] = Material("Plain", color=(0.5, 0.5, 0.5))
m = Mesh()
f = m.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
f.attrs.update({"mat": "Brick", "texture": {"path": pic, "sw": 1.0, "sh": 1.0}})
g = Mesh()
f2 = g.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)]); f2.attrs["mat"] = "Plain"
scene.groups += [Group(m, name="wall"), Group(g, name="slab")]
class App:
    def __init__(self): self.scene = scene; self.viewport = None; self.data = {}
    def document_data(self, d=None): return copy.deepcopy(self.data) if self.data else d
    def set_document_data(self, v): self.data = copy.deepcopy(v)
app = App(); ed = ME.MaterialEditor(app, "en")
spec = lambda n: (app.data.get("materials") or {}).get(n) or {}

ok("image" in M.shown_controls("generic") and "image" in M.shown_controls("glass") and "image" not in M.shown_controls("grass"),
   "the adjustments are offered on every type but grass")
ed.select("Brick")
ed.image_adj.sliders["hue"].setValue(60); ed.image_adj.set_colour("tint", (0.8, 0.8, 0.5)); ed._flush()
ok(spec("Brick").get("image", {}).get("hue") == 60 and spec("Brick")["image"]["tint"] == [0.8, 0.8, 0.5],
   f"the adjustments are kept in the material's settings ({spec('Brick').get('image')})")
ed.select("Plain"); ed.select("Brick")
ok(ed.image_adj.sliders["hue"].value() == 60 and ed.image_adj.header.isChecked(),
   "they come back when the material is selected, with the section open")
ed.select("Plain")
ok(ed.image_adj.spec() is None, "another material shows its own (none)")
ed.select("Brick"); ed.image_adj.sliders["hue"].setValue(0); ed.image_adj.reset(); ed._flush()
ok("image" not in spec("Brick"), "resetting the picture removes them from the settings")
ed.select("Brick"); ed.image_adj.sliders["brightness"].setValue(-30); ed._flush()
ed.kind.setCurrentIndex(ed.kind.findData("grass")); ed._flush()
ok("image" not in spec("Brick"), "a grass material keeps none (the blades take the picture's colour as it is)")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
