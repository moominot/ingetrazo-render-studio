"""Saving and loading a material in a file of its own, the glow slider's scale, the opacity map's picture source
and the preview window's Update button. Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import json, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtCore import QObject, QSettings
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
src = App(); brick, mask = picture("brick.png"), picture("mask.png")
src.scene.materials["Brick"] = Material("Brick", texture={"path": brick, "sw": 1.5, "sh": 0.75}, opacity=0.9, finish="satin")
src.scene.materials["Paint"] = Material("Paint", color=(0.2, 0.4, 0.6))
src.scene.plugin_data["render_studio"] = {"materials": {
    "Brick": {"type": "generic", "roughness": 0.3, "maps": {"glow": {"source": "file", "path": mask}, "roughness": {"source": "picture"}}},
    "Paint": {"type": "glow", "glow": 0.5}}}
out = tmp / "library" / "Brick"
done = MT.save_material(src, "Brick", out)
ok(done.endswith(".rsmat") and Path(done).is_file(), f"a material is saved in a .rsmat file ({Path(done).name})")
pics = Path(done).with_suffix("")
ok(sorted(p.name for p in pics.iterdir()) == ["map-1.png", "picture.png"], f"...with its pictures beside it ({sorted(p.name for p in pics.iterdir())})")
raw = json.loads(Path(done).read_text(encoding="utf-8"))
ok(raw["texture"]["path"] == "Brick/picture.png" and raw["settings"]["maps"]["glow"]["path"] == "Brick/map-1.png",
   "...and the file points to them by relative paths, so it can be moved")
ok(raw["finish"] == "satin" and raw["opacity"] == 0.9 and raw["settings"]["roughness"] == 0.3, "...with its finish, translucency and settings")
ok(MT.save_material(src, "Nobody", tmp / "x") == "", "a material the document does not have is not saved")
flat = MT.save_material(src, "Paint", tmp / "library" / "Paint.rsmat")
ok(json.loads(Path(flat).read_text())["color"] == [0.2, 0.4, 0.6] and not Path(flat).with_suffix("").exists(),
   "a flat colour has no pictures to copy")

dst = App()
name, _n = MT.load_material(dst, done)
m = dst.scene.materials[name]
sp = dst.document_data({})["materials"][name]
ok(name == "Brick" and Path(m.texture["path"]).is_file() and Path(m.texture["path"]).parent == pics and m.finish == "satin" and m.opacity == 0.9,
   "loaded in another drawing: the picture, finish and translucency")
ok(Path(sp["maps"]["glow"]["path"]).is_file() and sp["roughness"] == 0.3 and sp["maps"]["roughness"] == {"source": "picture"},
   "...and the settings, with the map file found again")
dst.viewport.history.undo()
ok(name not in dst.scene.materials and name not in (dst.document_data({}) or {}).get("materials", {}), "loading is one undo step")
n2, _n = MT.load_material(dst, done); n3, _n = MT.load_material(dst, done)
ok(n3 == "Brick (2)", f"a name in use gets a number ({n3})")
bad = tmp / "other.rsmat"; bad.write_text('{"hello": 1}')
ok(MT.load_material(dst, bad) == (None, 0) and MT.load_material(dst, tmp / "missing.rsmat") == (None, 0), "a file that is not a material loads nothing")

# ---- the editor's buttons -----------------------------------------------------------------------
ed = ME.MaterialEditor(src, "en")
ed.refresh(force=True); ed.select("Brick")
ok(ed.save_btn.isEnabled() and ed.load_btn.isEnabled(), "the editor has Save and Load")

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
win.follow_changes_box.setChecked(True)
ok(not win.update_btn.isEnabled(), "Update is off while the preview follows the changes")
win.follow_changes_box.setChecked(False)
ok(win.update_btn.isEnabled(), "...and on when it does not")
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

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
