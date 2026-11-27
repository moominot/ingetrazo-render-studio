"""The material editor's two tabs: the finer settings are hidden until Expert mode, an eye puts one in the
Material tab, and they are kept in a material only once chosen. Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import copy, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
QCoreApplication.setOrganizationName("rs-test")
QCoreApplication.setApplicationName(f"material-expert-{os.getpid()}")
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
from PySide6.QtGui import QVector3D
from core.group import Group
from core.materials import Material
from core.mesh import Mesh
from core.scene import Scene
from render_studio import material_editor as ME

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

scene = Scene()
scene.materials["Wall"] = Material("Wall", color=(0.7, 0.7, 0.7))
m = Mesh()
f = m.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
f.attrs["mat"] = "Wall"
scene.groups.append(Group(m, name="g"))

class App:
    def __init__(self): self.scene = scene; self.viewport = None; self.data = {}
    def document_data(self, d=None): return copy.deepcopy(self.data) if self.data else d
    def set_document_data(self, v): self.data = copy.deepcopy(v)

app = App()
ed = ME.MaterialEditor(app, "en")
ed.select("Wall")
seen = lambda key: ed.blocks[key].isVisibleTo(ed)
spec = lambda: (app.data.get("materials") or {}).get("Wall") or {}
fine = ("ior", "coat", "coat_roughness", "sheen", "relief_height")

ok(not ed.tabs.isTabVisible(1) and not ed.expert_view(), "expert mode off: only the Material tab")
ok(not any(seen(k) for k in fine) and seen("roughness") and seen("bump") and seen("map:bump"),
   "the Material tab: relief and roughness in view, the finer settings not")
ok(not ed.blocks["roughness"].eye.isVisibleTo(ed), "no eyes in the Material tab")
ed.set_expert(True)
ok(ed.expert_view() and all(seen(k) for k in fine) and ed.blocks["ior"].eye.isVisibleTo(ed),
   "the Expert tab shows every setting that applies, each with its eye")
ok(not seen("grass_height") and not seen("glow"), "…and none of another type's")
ed.expert_search.setText("varnish")
ok(seen("coat") and seen("coat_roughness") and not seen("roughness") and not seen("ior"), "the search finds by name")
ed.expert_search.setText("")
ed.blocks["coat"].eye.click()
ed.tabs.setCurrentIndex(0)
ok(seen("coat") and not seen("sheen"), "an opened eye puts the setting in the Material tab")
ed.sliders["roughness"].setValue(70); ed._flush()
ok(not any(k in spec() for k in fine + ("set_relief",)), f"untouched finer settings are not kept ({sorted(spec())})")
ed.sliders["coat"].setValue(40); ed._flush()
ok(abs(spec().get("coat", 0) - 0.4) < 1e-6 and "ior" not in spec(), "a chosen one is kept, alone")
ok(ed.blocks["coat"].reset.isVisibleTo(ed), "…with its way back to automatic")
ed.blocks["coat"].reset.click(); ed._flush()
ok("coat" not in spec() and ed.values["coat"].text() == "Automatic", "back to automatic: not kept")
ed.sliders["coat"].setValue(0); ed.sliders["coat"].setValue(1); ed.sliders["coat"].setValue(0); ed._flush()
ok(spec().get("coat") == 0.0, "a varnish of 0 chosen by hand is kept (it takes a finish's varnish away)")
ed._default_view()
ok(not seen("coat"), "Default view closes the eyes again; the value stays")
ok(spec().get("coat") == 0.0, "…no value changed")

ok(ed._get("bump") == 0.0, "relief starts at 0")
nrm = os.path.join(tempfile.mkdtemp(), "wall_normal.png")
from PySide6.QtGui import QColor, QImage
im = QImage(8, 8, QImage.Format_RGB32); im.fill(QColor("#8080ff")); im.save(nrm)
ed.maps["bump"].set_file(nrm, "normal"); ed._flush()
ok(abs(ed._get("bump") - 0.5) < 1e-6 and spec()["maps"]["bump"]["source"] == "normal",
   "choosing a normal map with Relief at 0 brings it to 0.5, so it shows in the render")
ed.maps["bump"].flip.setChecked(True); ed._flush()
ok(spec()["maps"]["bump"].get("flip_green") is True, "a DirectX normal map: green inverted is kept")
ed.sliders["bump"].setValue(0); ed._flush()
ok(ed._get("bump") == 0.0, "…and Relief can still be put back to 0")
ok(not seen("untile") and not seen("rough_min") and not seen("ao_strength"),
   "no picture, no map, no occlusion map: their settings are not offered")
ed.set_expert(True)
ok(seen("variation") and seen("translucency") and not seen("untile") and not seen("rough_min"),
   "Expert, a flat colour: tone variation and translucency")
rough = nrm
ed.maps["roughness"].set_file(rough, "file"); ed._flush()
ok(seen("rough_min") and seen("rough_max"), "a roughness map brings its lowest and highest")
ed.sliders["rough_max"].setValue(60); ed._flush()
ok(abs(spec().get("rough_max", 0) - 0.6) < 1e-6 and "rough_min" not in spec(), "…kept only the one chosen")
ed.set_expert(False)
ok(not seen("translucency"), "translucency starts hidden on a generic material")
ed.kind.setCurrentIndex(ed.kind.findData("foliage")); ed._flush()
ok(spec()["type"] == "foliage" and seen("translucency") and not seen("metallic") and "translucency" not in spec()
   and ed._get("translucency") == 0.5, "Foliage: translucency in view, by itself at 50 %, no metal")
ed.kind.setCurrentIndex(ed.kind.findData("generic")); ed._flush()
scene.materials["Wall"].texture = {"path": nrm, "sw": 1.0, "sh": 1.0}
ed._show(ed.list.currentItem()); ed.set_expert(True)
ok(seen("untile"), "with a picture: the repetition can be broken")
ed.untile.setChecked(True); ed._flush()
ok(spec().get("untile") is True, "…kept when ticked")
ed.untile.setChecked(False); ed._flush()
ok("untile" not in spec(), "…and not when not")
ed.search.setText("zzz")
ok(ed.list.item(0).isHidden(), "the list's search hides what does not match")
ed.search.setText("wal")
ok(not ed.list.item(0).isHidden(), "…and finds by part of the name")
ed.set_expert(False)
ok(not ed.tabs.isTabVisible(1) and ed.tabs.currentIndex() == 0, "expert mode off again")
ok(not hasattr(ed, "sel_btn") and not ed.del_btn.isVisibleTo(ed), "no «Selection» button; no «Delete» for a painted material")
scene.materials["Spare"] = Material("Spare", color=(0.2, 0.3, 0.4))
other = Mesh()
g = other.add_face([QVector3D(2, 0, 0), QVector3D(3, 0, 0), QVector3D(3, 1, 0), QVector3D(2, 1, 0)])
g.attrs["mat"] = "Spare"
scene.groups.append(Group(other, name="spare"))
from render_studio import materials as M2
M2._USED_CACHE.update(out=None)      # (the test changes the model without telling it)
ed.search.setText(""); ed.refresh(force=True); ed.select("Wall")
scene.selection.clear(); scene.selection.add(scene.groups[-1])
ed.show(); qa.processEvents()
ok(ed.current_name() == "Spare", f"the window opens on the material of what is selected ({ed.current_name()})")
ed.hide(); scene.selection.clear(); ed.show(); qa.processEvents()
ok(ed.current_name() == "Spare", "with nothing selected, the chosen one stays")
del scene.groups[-1]; M2._USED_CACHE.update(out=None); ed.refresh(force=True); ed.select("Spare")
ok(ed.current_name() == "Spare" and ed.del_btn.isVisibleTo(ed),
   "a material painted on nothing offers «Delete»")

print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
