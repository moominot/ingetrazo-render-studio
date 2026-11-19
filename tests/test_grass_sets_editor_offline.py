"""The material editor's Grass type (height slider, presets, cube preview) and how it shows a picture's
texture set (the maps found beside it). Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import copy, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QColor, QImage, QVector3D
from core.group import Group
from core.materials import Material
from core.mesh import Mesh
from core.scene import Scene
from render_studio import cube_preview, material_editor as ME, materials as M

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

tmp = Path(tempfile.mkdtemp())
def image(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = QImage(32, 32, QImage.Format_RGB32); im.fill(QColor(color)); im.save(str(path)); return str(path)
floor = image(tmp / "ph" / "tiles_diff_1k.jpg", "#c8b89a")
image(tmp / "ph" / "tiles_nor_gl_1k.png", "#8080ff"); image(tmp / "ph" / "tiles_rough_1k.png", "#404040")
image(tmp / "ph" / "tiles_arm_1k.png", "#ff2080")          # metal from the packed map's blue
plain = image(tmp / "plain" / "photo.png", "#a0a0a0")

scene = Scene()
scene.materials["Lawn"] = Material("Lawn", color=(0.2, 0.45, 0.1))
scene.materials["Floor"] = Material("Floor", texture={"path": floor, "sw": 1.0, "sh": 1.0})
scene.materials["Plain"] = Material("Plain", texture={"path": plain, "sw": 1.0, "sh": 1.0})
m = Mesh()
for i, name in enumerate(("Lawn", "Floor", "Plain")):
    f = m.add_face([QVector3D(i, 0, 0), QVector3D(i + 1, 0, 0), QVector3D(i + 1, 1, 0), QVector3D(i, 1, 0)])
    f.attrs["mat"] = name
scene.groups.append(Group(m, name="g"))

class App:
    def __init__(self): self.scene = scene; self.viewport = None; self.data = {}
    def document_data(self, d=None): return copy.deepcopy(self.data) if self.data else d
    def set_document_data(self, v): self.data = copy.deepcopy(v)
app = App(); ed = ME.MaterialEditor(app, "en")
spec = lambda n: (app.data.get("materials") or {}).get(n) or {}

# ---- grass -----------------------------------------------------------------------------
ok("grass" in M.TYPES and M.TYPE_LABELS["grass"] == "Grass", "Grass is a material type")
ed.select("Lawn")
ok(not ed.grass.isEnabled(), "Grass height is off for a generic material")
ed.kind.setCurrentIndex(ed.kind.findData("grass")); ed._flush()
ok(ed.grass.isEnabled(), "…and on for grass")
ok(spec("Lawn").get("type") == "grass" and abs(spec("Lawn")["grass_height"] - M.DEFAULT_GRASS_HEIGHT) < 0.01,
   f"a grass spec carries its height, {M.DEFAULT_GRASS_HEIGHT * 100:.0f} cm to start ({spec('Lawn')})")
ed._set_slider("grass_height", 0.30); ed._changed(); ed._flush()
ok(abs(spec("Lawn")["grass_height"] - 0.30) < 0.01 and ed.grass_value.text() == "30 cm",
   f"the slider sets it, shown in cm ({ed.grass_value.text()})")
lo, hi = M.GRASS_HEIGHT_RANGE
ed._set_slider("grass_height", 5.0); ed._changed(); ed._flush()
ok(abs(spec("Lawn")["grass_height"] - hi) < 1e-6, f"it stops at {hi * 100:.0f} cm")
ed.preset.setCurrentIndex(ed.preset.findData("lawn")); ed._preset(0); ed._flush()
ok(spec("Lawn")["type"] == "grass" and abs(spec("Lawn")["grass_height"] - 0.06) < 0.01, "the Lawn preset: grass, 6 cm")
ed.preset.setCurrentIndex(ed.preset.findData("meadow")); ed._preset(0); ed._flush()
ok(abs(spec("Lawn")["grass_height"] - 0.30) < 0.01, "the Tall grass preset: 30 cm")
ok(abs(ed.cube_params()["grass_height"] - 0.30) < 0.01 and ed.cube_params()["kind"] == "grass", "the cube preview gets the height")
a = cube_preview.render({**ed.cube_params(), "grass_height": 0.05}, 150).toImage()
b = cube_preview.render({**ed.cube_params(), "grass_height": 0.40}, 150).toImage()
top = lambda im: sum(1 for y in range(0, 30) for x in range(150) if im.pixelColor(x, y).alpha() > 0)
ok(top(b) > top(a), f"taller grass rises higher above the cube ({top(a)} to {top(b)} px above)")
ed.kind.setCurrentIndex(ed.kind.findData("generic")); ed._flush()
ok("grass_height" not in spec("Lawn"), "a generic material carries no grass height")
mesh_faces = len(m.faces)
ok(mesh_faces == 3, "the model is not touched by the grass (render only)")

# ---- texture sets -----------------------------------------------------------------------------
ed.select("Floor")
ok(ed.set_label.isVisibleTo(ed) and "normal" in ed.set_label.text() and "roughness" in ed.set_label.text(),
   f"the editor says which maps the picture has: «{ed.set_label.text()}»")
ok(ed.maps["bump"].source.itemText(0) == "Texture set: normal map", "Relief's first choice is the set's normal map")
ok(ed.maps["roughness"].source.itemText(0) == "Texture set: roughness", "Roughness's is the set's roughness map")
ok(ed.maps["metallic"].source.itemText(0) == "Texture set: metal" and ed.maps["metallic"].set_channel == 2,
   "Metal's is the packed map's blue channel")
ok(ed.maps["glow"].source.itemText(0) == "No map", "Glow has none")
ok(not ed.maps["roughness"].preview.pixmap().isNull(), "…with a preview of the map")
px = ed.maps["metallic"].preview.pixmap().toImage().pixelColor(20, 20)
ok(abs(px.redF() - 0x80 / 255) < 0.05, f"…the packed map shows the channel it uses ({px.red()})")
ed.maps["roughness"].set_file(tmp / "plain" / "photo.png"); ed._flush()
ok((spec("Floor").get("maps") or {}).get("roughness", {}).get("source") == "file",
   "choosing another map replaces the set's (it is what the render then uses)")
ed.select("Plain")
ok(not ed.set_label.isVisibleTo(ed) and ed.maps["bump"].source.itemText(0) == "Automatic"
   and ed.maps["roughness"].source.itemText(0) == "No map", "a picture without a set: the editor as before")
tinted = image(tmp / "cache" / "tiles_tint_1.png", "#d0c0a0")
scene.materials["Floor"].texture = {"path": tinted, "base": floor, "sw": 1.0, "sh": 1.0}
ed.select("Lawn"); ed.select("Floor")
ok("normal" in ed.set_label.text(), "a tinted picture shows its original's set")

print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
