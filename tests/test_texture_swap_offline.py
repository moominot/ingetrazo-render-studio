"""Changing the picture of an IngeTrazo material in the model: reach, placement kept,
proportions, tint, undo. Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QImage, QColor, QVector3D, QMatrix4x4
from core.group import Group
from core.history import History
from core.materials import Material
from core.mesh import Mesh
from core.scene import Scene
from render_studio import texture_swap as TS

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

tmp = Path(tempfile.mkdtemp())
os.environ.setdefault("XDG_DATA_HOME", str(tmp / "data"))
def image(name, w, h, color):
    p = tmp / name; im = QImage(w, h, QImage.Format_RGB32); im.fill(QColor(color)); im.save(str(p)); return str(p)
A, B, C = image("a.png", 100, 50, "#a05020"), image("b.png", 100, 100, "#2050a0"), image("c.png", 100, 25, "#20a050")
bad = tmp / "notimage.png"; bad.write_bytes(b"this is not a picture")

def quad(mesh, z=0.0):
    return mesh.add_face([QVector3D(0, 0, z), QVector3D(4, 0, z), QVector3D(4, 4, z), QVector3D(0, 4, z)])

scene = Scene()
tex_a = {"path": A, "sw": 1.0, "sh": 1.0, "rot": 15.0}
scene.materials["Wood"] = Material("Wood", texture=dict(tex_a))
scene.materials["Plain"] = Material("Plain", color=(0.5, 0.5, 0.5))
scene.materials["Other"] = Material("Other", texture={"path": A, "sw": 1.0, "sh": 1.0})

f1 = quad(scene.mesh); f1.attrs.update({"mat": "Wood", "texture": {**tex_a, "uvw": [[0, 0, 1], [1, 0, 1], [1, 1, 1]]}})
f_other = quad(scene.mesh, 1.0); f_other.attrs.update({"mat": "Other", "texture": {"path": A, "sw": 1.0, "sh": 1.0}})
child_mesh = Mesh(); f2 = quad(child_mesh); f2.attrs.update({"mat": "Wood", "texture": {"path": A, "sw": 2.0, "sh": 1.0, "rot": 0.0}})
parent = Group(Mesh(), name="parent"); child = Group(child_mesh, name="child"); parent.adopt([child]); scene.groups.append(parent)
painted = Group(Mesh(), name="painted"); painted.xform = QMatrix4x4()
painted.material = {"mat": "Wood", "texture": dict(tex_a)}; scene.groups.append(painted)

class VP:
    def __init__(self, s): self.history = History(s); self.updates = 0
    def update(self): self.updates += 1
    def notify_scene_changed(self): pass
class App:
    def __init__(self, s): self.scene = s; self.viewport = VP(s)
app = App(scene)
snap = lambda: (dict(scene.materials["Wood"].texture), dict(f1.attrs["texture"]), dict(f2.attrs["texture"]),
                dict(painted.material["texture"]), dict(f_other.attrs["texture"]))
before = snap()

done, msg = TS.swap_picture(app, "Wood", B, keep_proportions=True)
ok(done, "swap succeeds: " + msg)
new_path = scene.materials["Wood"].texture["path"]
ok(new_path != A and Path(new_path).is_file() and "imported" in new_path, "the registry material points at the new image, in the texture cache")
ok(f1.attrs["texture"]["path"] == new_path and f2.attrs["texture"]["path"] == new_path and painted.material["texture"]["path"] == new_path,
   "loose face, face inside a nested component and an object painted whole all changed")
ok(f1.attrs["texture"]["uvw"] == [[0, 0, 1], [1, 0, 1], [1, 1, 1]] and f1.attrs["texture"]["rot"] == 15.0, "a texture placed by hand keeps its placement and turn")
ok(abs(f1.attrs["texture"]["sh"] - 2.0) < 1e-9 and abs(f2.attrs["texture"]["sh"] - 2.0) < 1e-9 and f1.attrs["texture"]["sw"] == 1.0 and f2.attrs["texture"]["sw"] == 2.0,
   "proportions kept: 100x50 -> 100x100 doubles the tile height, widths untouched")
ok(f_other.attrs["texture"] == before[4], "a face of ANOTHER material is untouched")
ok(app.viewport.updates > 0, "the viewport was asked to redraw")

app.viewport.history.undo()
ok(snap() == before, "one undo puts every texture back exactly")
app.viewport.history.redo()
ok(f1.attrs["texture"]["path"] == new_path and scene.materials["Wood"].texture["path"] == new_path, "redo applies it again")
app.viewport.history.undo()

done, _ = TS.swap_picture(app, "Wood", C, keep_proportions=False)
ok(done and f1.attrs["texture"]["sh"] == 1.0 and f2.attrs["texture"]["sh"] == 1.0 and f1.attrs["texture"]["path"] != A,
   "keep proportions OFF: new image, tile sizes untouched")
app.viewport.history.undo()

# tint: the picture changes, the colour stays, re-applied to the new image
from core.texture import tinted_texture
tinted = tinted_texture({"path": A, "sw": 1.0, "sh": 1.0}, (1.0, 0.0, 0.0))
ok(tinted.get("base") == A and tinted["path"] != A, "(setup) tint produced a base and a tinted image")
scene.materials["Wood"].texture = dict(tinted); f1.attrs["texture"] = dict(tinted)
done, _ = TS.swap_picture(app, "Wood", B)
t = f1.attrs["texture"]
ok(done and t.get("tint") == tinted["tint"] and t["base"] == scene.materials["Wood"].texture["base"] and t["base"] != A and t["path"] != t["base"],
   "a tinted material keeps its tint, over the NEW image")
app.viewport.history.undo()
ok(f1.attrs["texture"] == tinted, "undo restores the tinted texture")

# refusals
n = len(app.viewport.history._undo) if hasattr(app.viewport.history, "_undo") else None
for what, args in (("a file that is not an image", ("Wood", str(bad))), ("a colour-only material", ("Plain", B)),
                   ("a material that does not exist", ("Nope", B)), ("no material chosen", ("", B))):
    done, msg = TS.swap_picture(app, *args)
    ok(not done and msg, f"refused: {what} ({msg})")
ok(f1.attrs["texture"] == tinted, "the refusals changed nothing")
# saved and reopened: the NEW picture travels with the document (embedded), the old one does not
from formats import igz
plain = {"path": A, "sw": 1.0, "sh": 1.0}          # without the red tint of the test above
scene.materials["Wood"].texture = dict(plain)
for face in (f1, f2): face.attrs["texture"] = dict(plain)
painted.material = {"mat": "Wood", "texture": dict(plain)}
done, _ = TS.swap_picture(app, "Wood", B)
out = tmp / "doc.igz"; igz.save_scene(scene, out)
s2 = Scene(); igz.load_into(s2, out)
tex2 = s2.materials["Wood"].texture
ok(tex2 and Path(tex2["path"]).is_file() and QImage(tex2["path"]).width() == 100 and QImage(tex2["path"]).height() == 100,
   "saved and reopened: the material still has the new 100x100 picture")
ok(QImage(tex2["path"]).pixelColor(5, 5).blue() > 120 and QImage(tex2["path"]).pixelColor(5, 5).red() < 80, "...and it is the blue one (b.png), not the old brown")
# the editor's button
from PySide6.QtWidgets import QFileDialog
from render_studio import material_editor as ME
class App2(App):
    def document_data(self, default=None): return default
    def set_document_data(self, v): pass
    def on_document_changed(self, fn): pass
app2 = App2(scene)
ed = ME.MaterialEditor(app2, "en")
ok(ed.pic_btn.text() == "Change picture…" and ed.keep_ratio.isChecked(), "the editor has the button and a Keep proportions box (on)")
ed.select("Wood")
real = QFileDialog.getOpenFileName
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (C, ""))
try:
    ed.pic_btn.click(); qa.processEvents()
finally:
    QFileDialog.getOpenFileName = real
ok(Path(scene.materials["Wood"].texture["path"]).name.endswith("c.png"), "the button replaces the picture in the model")
ok("now uses c.png" in ed.hint.text(), "and says so")
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
before_p = scene.materials["Wood"].texture["path"]
try:
    ed.pic_btn.click()
finally:
    QFileDialog.getOpenFileName = real
ok(scene.materials["Wood"].texture["path"] == before_p, "cancelling the file dialog changes nothing")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
