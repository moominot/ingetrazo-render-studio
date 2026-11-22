"""The opacity map of the material editor: an image file where white is opaque and black is
transparent, kept in the material's settings. argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, copy, json, tempfile
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

scene = Scene()
scene.materials["Fence"] = Material("Fence", color=(0.4, 0.3, 0.2))
m = Mesh(); f = m.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)]); f.attrs["mat"] = "Fence"
scene.groups.append(Group(m, name="fence"))
class App:
    def __init__(self): self.scene = scene; self.viewport = None; self.data = {}
    def document_data(self, d=None): return copy.deepcopy(self.data) if self.data else d
    def set_document_data(self, v): self.data = copy.deepcopy(v)

app = App(); ed = ME.MaterialEditor(app, "en"); ed.show(); ed.select("Fence"); qa.processEvents()
ok(not ed.lock_box.isVisible() and ed.sliders["roughness"].isEnabled() and ed.preset.isEnabled(), "an ordinary material: nothing is locked")
app.data = {"materials": {"Fence": {"type": "generic", "roughness": 0.3, "metallic": 0.0, "bump": 0.0, "glow": 0.0,
                                     "blender": {"v": 1, "material": "Fence", "group": None, "tuft": None, "blend": "AAAA"}}}}
ed.refresh(force=True); ed.select("Fence"); ed._show(ed.list.currentItem()); qa.processEvents()
ok(ed.lock_box.isVisible(), "a material edited in Blender says so")
locked = [ed.preset, ed.kind, ed.reset_btn, ed.map_size, ed.image_adj, *ed.sliders.values(), *ed.maps.values(), *ed.map_toggles.values()]
ok(not any(w.isEnabled() for w in locked), f"…and every setting of the editor is locked ({sum(w.isEnabled() for w in locked)} still enabled)")
before = json.dumps(app.data, sort_keys=True)
ed._changed(); ed.sliders["roughness"].setValue(80); ed._flush()
ok(json.dumps(app.data, sort_keys=True) == before, "…and nothing can change the settings while it is locked")
ed.unlock_current(); qa.processEvents()
ok("blender" not in app.data["materials"]["Fence"] and app.data["materials"]["Fence"]["roughness"] == 0.3, "Unlock drops the Blender material and keeps the basic settings")
ok(not ed.lock_box.isVisible() and all(w.isEnabled() for w in [ed.preset, ed.kind, *ed.sliders.values()]), "…the editor is free again")
# a map button of a hidden setting does not float on its own (a material with a texture set hides Relief, say)
ed.select("Fence"); ed._enable_glow(); qa.processEvents()
shown = ed.shown_controls()
stray = [k for k, t in ed.map_toggles.items() if t.isVisibleTo(ed) and ("transparency" if k == "opacity" else k) not in shown]
ok(not stray, f"no map button floats without its setting ({stray})")
print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
