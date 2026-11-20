"""The water controls of the material editor. argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, copy
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QVector3D
from core.scene import Scene
from core.mesh import Mesh
from core.group import Group
from core.materials import Material
from render_studio import material_editor as ME, materials as M

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

scene = Scene()
scene.materials["Superficie"] = Material("Superficie", color=(0.1, 0.3, 0.5))
m = Mesh(); f = m.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)]); f.attrs["mat"] = "Superficie"
scene.groups.append(Group(m, name="pool"))
class App:
    def __init__(self): self.scene = scene; self.viewport = None; self.data = {}
    def document_data(self, d=None): return copy.deepcopy(self.data) if self.data else d
    def set_document_data(self, v): self.data = copy.deepcopy(v)
app = App(); ed = ME.MaterialEditor(app, "en"); ed.select("Superficie")
spec = lambda: (app.data.get("materials") or {}).get("Superficie") or {}
def commit(): ed._flush()

ok(not ed.ripple.isVisibleTo(ed), "Ripple size is hidden for a generic material")
ed.kind.setCurrentIndex(ed.kind.findData("water")); commit()
ok(ed.ripple.isVisibleTo(ed), "…and shown for water")
ok(spec().get("bump") == 0.5, "choosing Water gives it waves to start with (Relief 0.5)")
ok(spec().get("type") == "water" and "ripple_size" in spec(), f"a water spec carries its ripple size ({spec()})")
ed.ripple.setValue(20); commit()
ok(abs(spec()["ripple_size"] - 0.2) < 0.011, "moving the slider changes it")
ed.kind.setCurrentIndex(ed.kind.findData("generic")); commit()
ok("ripple_size" not in spec() and not ed.ripple.isVisibleTo(ed), "a generic material does not carry it")
ed.preset.setCurrentIndex(ed.preset.findData("water")); ed._preset(0); commit()
ok(spec()["type"] == "water" and spec()["bump"] == 0.5 and abs(spec()["ripple_size"] - M.DEFAULT_RIPPLE_SIZE) < 0.011, f"the Water preset: waves 0.5 high, size {M.DEFAULT_RIPPLE_SIZE} ({spec()})")
ed.select("Superficie"); ed._show(ed.list.currentItem())
ok(abs(ed._get("ripple_size") - M.DEFAULT_RIPPLE_SIZE) < 0.011, "the saved size comes back when the material is shown again")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
