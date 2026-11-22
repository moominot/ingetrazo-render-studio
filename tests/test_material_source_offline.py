"""The «Material of» block of the material editor: colour or picture, change, size. argv: <ingetrazo-src> <repo>"""
import os, sys, copy, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QColor, QImage, QVector3D
from core.scene import Scene
from core.mesh import Mesh
from core.group import Group
from core.materials import Material
from core.history import History
from render_studio import material_editor as ME, material_tools as MT

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

tmp = Path(tempfile.mkdtemp())
pic = tmp / "p.png"
im = QImage(40, 20, QImage.Format_RGB32); im.fill(QColor("#336699")); im.save(str(pic))
scene = Scene()
scene.materials["Flat"] = Material("Flat", color=(0.7, 0.2, 0.2))
m = Mesh()
f = m.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
f.attrs["mat"] = "Flat"; f.attrs["color"] = (0.7, 0.2, 0.2)
scene.groups.append(Group(m, name="g"))

class VP:
    def __init__(self): self.history = History(scene)
    def update(self): pass
class App:
    def __init__(self): self.scene = scene; self.viewport = VP(); self.data = {}
    def document_data(self, d=None): return copy.deepcopy(self.data) if self.data else d
    def set_document_data(self, v): self.data = copy.deepcopy(v)
app = App(); ed = ME.MaterialEditor(app, "en")
seen = lambda w: w.isVisibleTo(ed)
ed.select("Flat")
ok(ed.mode_colour.isChecked() and seen(ed.colour_btn) and not seen(ed.pic_btn), "a colour material: Colour chosen, its colour button, no picture tools")
done, _msg = MT.set_material_picture(app, "Flat", str(pic), 2.0)
ed._reshow("Flat")
mat = scene.materials["Flat"]
ok(done and mat.texture and abs(mat.texture["sw"] - 2.0) < 1e-6 and abs(mat.texture["sh"] - 1.0) < 1e-6, f"a picture is added to a colour material (2 × 1 m): {mat.texture}")
ok(f.attrs.get("texture") and not f.attrs.get("color"), "the faces that wear it follow")
ok(ed.mode_picture.isChecked() and seen(ed.pic_btn) and seen(ed.edit_btn) and seen(ed.tile_w) and not seen(ed.colour_btn),
   "a picture material: Picture chosen, change, edit and size shown, no colour button")
ok(ed.pic_name.text().endswith("p.png") and abs(ed.tile_w.value() - 2.0) < 1e-6 and abs(ed.tile_h.value() - 1.0) < 1e-6, "the picture's name and size are shown")
ed.tile_w.setValue(4.0)
ok(abs(ed.tile_h.value() - 2.0) < 1e-6, "keep proportions: the height follows the width")
ed._tile_timer.stop(); ed._apply_tile()
ok(abs(scene.materials["Flat"].texture["sw"] - 4.0) < 1e-6 and abs(f.attrs["texture"]["sh"] - 2.0) < 1e-6, "the size reaches the material and its faces")
scene.version += 0
app.viewport.history.undo()
ok(abs(scene.materials["Flat"].texture["sw"] - 2.0) < 1e-6, "one undo step brings the old size back")
ok(MT.set_material_colour(app, "Flat", (0.1, 0.5, 0.1), force=True), "a picture material can become a flat colour")
mat = scene.materials["Flat"]
ok(not mat.texture and tuple(round(c, 2) for c in mat.color) == (0.1, 0.5, 0.1) and not f.attrs.get("texture"), "…on its faces too")
ok(MT.set_material_colour(app, "Flat", (1, 0, 0)) is True, "and a flat one changes colour")
print("FAILED" if fails else "ALL PASS")
sys.exit(1 if fails else 0)
