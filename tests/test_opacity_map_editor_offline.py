"""The opacity map of the material editor: an image file where white is opaque and black is
transparent, kept in the material's settings. argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, copy, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QImage, QVector3D, QColor
from core.scene import Scene
from core.mesh import Mesh
from core.group import Group
from core.materials import Material
from render_studio import material_editor as ME, materials as M

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

mask = os.path.join(tempfile.mkdtemp(), "leaves_opacity.png")
img = QImage(16, 16, QImage.Format_RGB32); img.fill(QColor(0, 0, 0)); img.save(mask)

scene = Scene()
scene.materials["Fence"] = Material("Fence", color=(0.4, 0.3, 0.2))
m = Mesh(); f = m.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)]); f.attrs["mat"] = "Fence"
scene.groups.append(Group(m, name="fence"))
class App:
    def __init__(self): self.scene = scene; self.viewport = None; self.data = {}
    def document_data(self, d=None): return copy.deepcopy(self.data) if self.data else d
    def set_document_data(self, v): self.data = copy.deepcopy(v)
app = App(); ed = ME.MaterialEditor(app, "en"); ed.select("Fence")
spec = lambda: (app.data.get("materials") or {}).get("Fence") or {}

ok("map:opacity" in M.shown_controls("generic") and "map:opacity" in M.shown_controls("glass"),
   "the opacity map is offered with the Transparency slider")
ok("map:opacity" not in M.shown_controls("grass"), "…and not on grass (the blades cover the face)")
ok("opacity" in ed.maps and ed.maps["opacity"].source.count() == 2, "the editor has an Opacity map row (none / file)")
ok(not ed.maps["opacity"].isHidden(), "…shown for a generic material")

ed.maps["opacity"].set_file(mask); ed._flush()
o = (spec().get("maps") or {}).get("opacity")
ok(o and o["source"] == "file" and o["path"] == mask, f"choosing a file keeps it in the settings ({o})")
ok("size" in o, "…with the size a map without a picture is tiled at")

ed.maps["opacity"].invert.setChecked(True); ed._flush()
ok((spec()["maps"]["opacity"]).get("invert") is True, "Invert swaps which part is transparent")

ed.select("Fence"); ed.refresh(force=True)
ok(ed.maps["opacity"].path == mask and ed.maps["opacity"].invert.isChecked(), "it is shown again when the material is selected")

ed.maps["opacity"].source.setCurrentIndex(0); ed.maps["opacity"]._changed(); ed._flush()
ok("opacity" not in (spec().get("maps") or {}), "No map removes it")

ed.kind.setCurrentIndex(ed.kind.findData("grass")); ed._flush()
ok(ed.maps["opacity"].isHidden() or not ed.maps["opacity"].isVisibleTo(ed), "a grass material hides the row")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
