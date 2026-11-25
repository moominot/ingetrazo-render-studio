"""Saving and loading a material in a file of its own (.igmat, .skm, the older .rsmat), the glow slider's scale, the opacity map's picture source
and the preview window's Update button. Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import json, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtCore import QObject, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QVector3D
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
tmp = Path(tempfile.mkdtemp())
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp / "settings"))
qa.setOrganizationName("RenderStudioTest"); qa.setApplicationName("matsave")
from core.camera import OrbitCamera
from core.history import History
from core.materials import Material
from core.scene import Scene
from render_studio import material_editor as ME, material_tools as MT, panel as P
from render_studio.live import LiveSession

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

def picture(name):
    p = tmp / name
    img = QImage(8, 8, QImage.Format_RGB32); img.fill(QColor(120, 90, 60)); img.save(str(p)); return str(p)

class VP:
    def __init__(self, scene): self.scene = scene; self.history = History(scene); self.camera = OrbitCamera()
    def notify_scene_changed(self): pass
    def update(self): pass
class App:
    def __init__(self):
        self.scene = Scene(); self.viewport = VP(self.scene); self.key = "render_studio"; self.window = None
    def document_data(self, default=None):
        d = (self.scene.plugin_data or {}).get(self.key)
        return json.loads(json.dumps(d)) if d is not None else default
    def set_document_data(self, v): raise AssertionError("plain call")
    def on_document_changed(self, fn): pass

# ---- save and load ------------------------------------------------------------------------------
import zipfile
from formats import igmat
src = App(); brick, mask = picture("brick.png"), picture("mask.png")
src.scene.materials["Brick"] = Material("Brick", texture={"path": brick, "sw": 1.5, "sh": 0.75}, opacity=0.9, finish="satin")
src.scene.materials["Paint"] = Material("Paint", color=(0.2, 0.4, 0.6))
src.scene.plugin_data["render_studio"] = {"materials": {
    "Brick": {"type": "generic", "roughness": 0.3, "maps": {"glow": {"source": "file", "path": mask}, "roughness": {"source": "picture"}}},
    "Paint": {"type": "glow", "glow": 0.5}}}
out = tmp / "library" / "Brick"
done = MT.save_material(src, "Brick", out)
ok(done.endswith(".igmat") and Path(done).is_file(), f"a material is saved in an .igmat file ({Path(done).name})")
ok(not Path(done).with_suffix("").exists(), "...one file: no folder of pictures beside it")
with zipfile.ZipFile(done) as zf:
    members = sorted(zf.namelist())
    entry = json.loads(zf.read("material.json"))["materials"][0]
    kept_mask = zf.read("rs-maps/map-1.png")
ok("material.json" in members and any(m.startswith("textures/") for m in members) and "rs-maps/map-1.png" in members,
   f"...with its pictures inside it ({members})")
ok(kept_mask == Path(mask).read_bytes(), "...the map file as it was")
rs = entry["render_studio"]
ok(entry["finish"] == "satin" and entry["opacity"] == 0.9 and rs["roughness"] == 0.3 and rs["maps"]["glow"]["path"] == "rs-maps/map-1.png",
   "...with its finish, translucency and settings (the map by a path inside the file)")
ok(src.document_data({})["materials"]["Brick"]["maps"]["glow"]["path"] == mask, "...and the drawing's own settings are not touched")
theirs = igmat.load_materials(done)
ok(len(theirs) == 1 and theirs[0].name == "Brick" and Path(theirs[0].texture["path"]).is_file() and theirs[0].finish == "satin"
   and theirs[0].texture["sw"] == 1.5, "IngeTrazo's own import reads the file (the settings of Render Studio are left aside)")
again = MT.save_material(src, "Brick", tmp / "library" / "Brick-again.igmat")
ok(Path(done).read_bytes() == Path(again).read_bytes(), "the same material gives the same bytes")
ok(MT.save_material(src, "Nobody", tmp / "x") == "", "a material the document does not have is not saved")
flat = MT.save_material(src, "Paint", tmp / "library" / "Paint.igmat")
with zipfile.ZipFile(flat) as zf:
    flat_entry = json.loads(zf.read("material.json"))["materials"][0]
    flat_members = zf.namelist()
ok(flat_entry["color"] == [0.2, 0.4, 0.6] and flat_entry["render_studio"] == {"type": "glow", "glow": 0.5} and flat_members == ["material.json"],
   "a flat colour has no pictures to keep")
bare = tmp / "library" / "Bare.igmat"
igmat.save_materials(bare, [Material("Bare", color=(1.0, 0.0, 0.0))])
ok(MT.save_material(App(), "Bare", tmp / "q") == "" and zipfile.ZipFile(bare).namelist() == ["material.json"],
   "(a material with no settings is the file IngeTrazo writes itself)")

dst = App()
name, _n = MT.load_material(dst, done)
m = dst.scene.materials[name]
sp = dst.document_data({})["materials"][name]
ok(name == "Brick" and Path(m.texture["path"]).is_file() and m.finish == "satin" and m.opacity == 0.9 and m.texture["sw"] == 1.5,
   "loaded in another drawing: the picture, finish and translucency")
ok(Path(sp["maps"]["glow"]["path"]).is_file() and Path(sp["maps"]["glow"]["path"]).read_bytes() == Path(mask).read_bytes()
   and sp["roughness"] == 0.3 and sp["maps"]["roughness"] == {"source": "picture"},
   "...and the settings, with the map file found again")
dst.viewport.history.undo()
ok(name not in dst.scene.materials and name not in (dst.document_data({}) or {}).get("materials", {}), "loading is one undo step")
n2, _n = MT.load_material(dst, done); n3, _n = MT.load_material(dst, done)
ok(n3 == "Brick (2)", f"a name in use gets a number ({n3})")

dst2 = App()
nm, _n = MT.load_material(dst2, bare)
ok(nm == "Bare" and dst2.scene.materials["Bare"].color == (1.0, 0.0, 0.0) and not (dst2.document_data({}) or {}).get("materials"),
   "an .igmat written by IngeTrazo itself loads, with no Render Studio settings")
many = tmp / "library" / "Many.igmat"
igmat.save_materials(many, [Material("One", color=(0, 0, 1)), Material("Two", color=(0, 1, 0))])
dst3 = App()
ok(MT.load_materials(dst3, many) == ["One", "Two"] and "Two" in dst3.scene.materials, "a file with several materials brings them all")

# the older .rsmat still loads, with its picture and map found beside it
old = MT._save_rsmat(src, "Brick", tmp / "old" / "Brick")
dst4 = App()
n4, _n = MT.load_material(dst4, old)
sp4 = dst4.document_data({})["materials"][n4]
ok(old.endswith(".rsmat") and n4 == "Brick" and Path(dst4.scene.materials[n4].texture["path"]).is_file()
   and Path(sp4["maps"]["glow"]["path"]).is_file() and dst4.scene.materials[n4].finish == "satin",
   "an older .rsmat file loads as before")

# a material file of SketchUp's (.skm): its colour or picture, no settings
skm = tmp / "Teal.skm"
with zipfile.ZipFile(skm, "w") as zf:
    zf.writestr("document.xml", '<?xml version="1.0" encoding="UTF-8"?><materialDocument xmlns:mat="urn:x">'
                '<mat:material name="Teal" type="0" colorRed="0" colorGreen="128" colorBlue="128"/></materialDocument>')
dst5 = App()
n5, _n = MT.load_material(dst5, skm)
c5 = dst5.scene.materials[n5].color if n5 else None
ok(n5 == "Teal" and c5 is not None and abs(c5[1] - 128 / 255) < 0.01, f"a .skm material file loads ({n5}, {c5})")
real = Path(r"C:\ProgramData\SketchUp\SketchUp 2026\SketchUp\Materials\Asphalt & Concrete\Asphalt_01_1K.skm")
if real.is_file():
    dst6 = App()
    n6, _n = MT.load_material(dst6, real)
    ok(n6 == "Asphalt_01_1K" and Path(dst6.scene.materials[n6].texture["path"]).is_file(), f"a real .skm of the program's library loads ({n6})")

for junk in ("other.igmat", "other.skm", "other.rsmat"):
    p = tmp / junk
    p.write_text('{"hello": 1}')
    ok(MT.load_material(dst, p) == (None, 0) and MT.load_materials(dst, p) == [], f"{junk}: a file that is not a material loads nothing")
ok(MT.load_material(dst, tmp / "missing.igmat") == (None, 0) and MT.load_material(dst, tmp / "file.txt") == (None, 0),
   "a file that is missing, or of another kind, loads nothing")

# an IngeTrazo without material files writes the older .rsmat, and says so
real_igmat = MT._igmat
MT._igmat = lambda: None
try:
    fb = MT.save_material(src, "Brick", tmp / "fallback" / "Brick")
    ok(fb.endswith(".rsmat") and MT.extension() == ".rsmat" and "igmat" not in MT.save_filter() and ".igmat" not in MT.open_filter(),
       "...with no .igmat support in IngeTrazo the file is an .rsmat (and the dialogs say so)")
    ok(MT.load_material(App(), done) == (None, 0), "...and an .igmat is not guessed at")
finally:
    MT._igmat = real_igmat
ok(MT.extension() == ".igmat" and "*.igmat" in MT.open_filter() and "*.skm" in MT.open_filter(), "with it, the dialogs offer .igmat and .skm")

# ---- the editor's buttons -----------------------------------------------------------------------
ed = ME.MaterialEditor(src, "en")
ed.refresh(force=True); ed.select("Brick")
ok(ed.save_btn.isEnabled() and ed.load_btn.isEnabled(), "the editor has Save and Load")
from PySide6.QtWidgets import QFileDialog
_real_dialogs = (QFileDialog.getSaveFileName, QFileDialog.getOpenFileName)
seen = {}
target_file = str(tmp / "editor" / "Brick.igmat")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (seen.update(save=a) or target_file, ""))
ed.save_current()
ok(Path(target_file).is_file() and seen["save"][2].endswith("Brick.igmat") and "igmat" in seen["save"][3],
   f"Save material… asks for an .igmat and writes it ({Path(target_file).name})")
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (seen.update(load=a) or target_file, ""))
before = set(src.scene.materials)
ed.load_from_file()
added = sorted(set(src.scene.materials) - before)
ok(added == ["Brick (2)"] and all(x in seen["load"][3] for x in ("*.igmat", "*.skm")), f"Load material… takes it back, under a new name ({added})")
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(tmp / "other.igmat"), ""))
ed.load_from_file()
ok(ed.hint.text() == "That file is not a material file.", f"...and says so for a file that is not one ({ed.hint.text()})")
QFileDialog.getSaveFileName, QFileDialog.getOpenFileName = _real_dialogs

# ---- the glow slider ------------------------------------------------------------------------------
for want in (0.0, 0.1, 0.5, 1.0, 4.0, 12.0, 50.0):
    ed._set_slider("glow", want)
    got = ed._get("glow")
    ok(abs(got - want) <= max(0.04, 0.06 * want), f"the glow slider keeps {want} ({got})")
ed._set_slider("glow", 1.0)
ok(ed.sliders["glow"].value() < 35, f"a glow of 1 is in the lower third of the slider (at {ed.sliders['glow'].value()} %)")
ed.sliders["glow"].setValue(10)
ok(ed._get("glow") < 0.1, f"the slider's start moves in fine steps ({ed._get('glow')})")
ok(ed.values["glow"].text() == f"{ed._get('glow'):.2f}", "...and its value is shown with decimals")

# ---- the opacity map's sources ------------------------------------------------------------------------
sources = [ed.maps["opacity"].source.itemData(i) for i in range(ed.maps["opacity"].source.count())]
ok(sources == ["", "picture", "file"], f"the opacity map can use the material's picture in black and white ({sources})")
ed.maps["opacity"].source.setCurrentIndex(1)
ok(ed.maps["opacity"].spec() == {"source": "picture"}, "...and that is what the render is told")

# ---- the Update button ----------------------------------------------------------------------------
panel = P.StudioPanel(src)
win = panel.preview()
panel.commands.follow_changes.setChecked(True)
ok(not panel.commands.update.isVisible(), "Update is out of sight while the preview follows the changes")
panel.commands.follow_changes.setChecked(False)
ok(panel.commands.update.isVisible(), "...and in view when it does not")
class Stub(QObject):
    def __init__(self): super().__init__(); self.key = (2, "mats-new", "look-new")
    def live_key(self): return self.key
stub = Stub()
live = LiveSession(stub)
live._scene_key = (1, "mats-old", "look-old")
live.follow_changes = False
ok(live._wanted_key() == (1, "mats-old", "look-new"), "Follow changes off: the scene keeps its model and materials, the look applies")
live.update_now()
ok(live._wanted_key() == (1, "mats-old", "look-new"), "...Update does nothing while the live view is not running")
live._timer.start()
live.update_now()
ok(live._wanted_key() == (2, "mats-new", "look-new"), "...Update takes the model and materials as they are now")
live._force = False
ok(live._wanted_key() == (1, "mats-old", "look-new"), "...once (the next load keeps the new ones)")
live._timer.stop()

# ---- the cube: a click changes the colour (or the picture) ------------------------------------------------
from PySide6.QtWidgets import QColorDialog
f = src.scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
f.attrs.update({"mat": "Paint", "color": (0.2, 0.4, 0.6)})
g = src.scene.mesh.add_face([QVector3D(5, 0, 0), QVector3D(6, 0, 0), QVector3D(6, 1, 0), QVector3D(5, 1, 0)])
g.attrs.update({"mat": "Brick", "texture": {"path": brick, "sw": 1.5, "sh": 0.75}})
ed.refresh(force=True); ed.select("Paint")
ok(ed.cube.cursor().shape() == Qt.PointingHandCursor, "the cube shows it can be clicked")
asked = []
real_get = QColorDialog.getColor
QColorDialog.getColor = staticmethod(lambda *a, **k: (asked.append(a[0].name()) or QColor(240, 120, 0)))
ed.cube.clicked.emit()
QColorDialog.getColor = real_get
ok(asked == [QColor.fromRgbF(0.2, 0.4, 0.6).name()], f"a material with no picture opens the colour chooser at its colour ({asked})")
want = QColor(240, 120, 0)
got = src.scene.materials["Paint"].color
ok(abs(got[0] - want.redF()) < 0.01 and abs(got[1] - want.greenF()) < 0.01, f"the material has the new colour ({got})")
ok(abs(f.attrs["color"][0] - want.redF()) < 0.01, "...and so does every face that wears it")
src.viewport.history.undo()
ok(tuple(f.attrs["color"]) == (0.2, 0.4, 0.6) and tuple(src.scene.materials["Paint"].color) == (0.2, 0.4, 0.6), "...in one undo step")
ed.select("Brick")
changed = []
ed.change_picture = lambda: changed.append(1)
ed.cube.clicked.emit()
ok(changed == [1], "a material with a picture asks for another picture instead")
ok(MT.set_material_colour(src, "Brick", (1, 0, 0)) is False and MT.set_material_colour(src, "Nobody", (1, 0, 0)) is False,
   "the colour of a material with a picture, or of one that is not there, is not changed")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
