"""The material editor shows only the controls that change the render of the material as it is
set (its type, its picture, its texture set), and the panel's checks of a Blender chosen by hand.
Offscreen, no Blender. argv: <ingetrazo-src> <render-studio repo>"""
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
from render_studio import material_editor as ME, materials as M, presets
from render_studio import panel as P

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

# ---- the rules, without Qt ------------------------------------------------------------------
S = M.shown_controls
ok({"metallic", "map:metallic"} <= S("generic") and not ({"metallic", "map:metallic"} & S("glass")),
   "Metal only for generic materials (the render ignores it on the others)")
ok("glow" in S("glow") and "map:glow" in S("glow") and "glow" not in S("generic"), "Glow only for glowing")
ok({"bump", "ripple_size"} <= S("water") and "map:bump" not in S("water"),
   "Water: Relief is the waves' height, with Ripple size; no relief map (its own ripples)")
ok({"grass_height", "grass_density"} <= S("grass") and "transparency" not in S("grass")
   and not ({"grass_height", "grass_density"} & S("generic")), "Grass height and density only for grass")
ok("ripple_size" not in S("generic") and "ripple_size" not in S("glass"), "Ripple size only for water")
ok("bump" not in S("generic", set_relief=True) and "map:bump" in S("generic", set_relief=True),
   "a texture set's relief with no map chosen: the Relief slider does nothing, so it hides")
ok("bump" in S("generic", set_relief=True, relief_source="picture"), "…a relief map chosen: it shows again")
ok("map_size" in S("generic", file_maps=True) and "map_size" not in S("generic", picture=True, file_maps=True)
   and "map_size" not in S("generic"), "Map image size: a map file on a material without a picture only")
ok("picture" in S("generic", picture=True) and "picture" not in S("generic"), "Change picture: only with a picture")

# ---- the editor -------------------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
def image(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = QImage(32, 32, QImage.Format_RGB32); im.fill(QColor(color)); im.save(str(path)); return str(path)
floor = image(tmp / "ph" / "tiles_diff_1k.jpg", "#c8b89a")
image(tmp / "ph" / "tiles_nor_gl_1k.png", "#8080ff"); image(tmp / "ph" / "tiles_rough_1k.png", "#404040")
scene = Scene()
scene.materials["Plain"] = Material("Plain", color=(0.7, 0.7, 0.7))
scene.materials["Floor"] = Material("Floor", texture={"path": floor, "sw": 1.0, "sh": 1.0})
m = Mesh()
for i, name in enumerate(("Plain", "Floor")):
    f = m.add_face([QVector3D(i, 0, 0), QVector3D(i + 1, 0, 0), QVector3D(i + 1, 1, 0), QVector3D(i, 1, 0)])
    f.attrs["mat"] = name
scene.groups.append(Group(m, name="g"))

class App:
    def __init__(self): self.scene = scene; self.viewport = None; self.data = {}
    def document_data(self, d=None): return copy.deepcopy(self.data) if self.data else d
    def set_document_data(self, v): self.data = copy.deepcopy(v)
app = App(); ed = ME.MaterialEditor(app, "en")
seen = lambda w: w.isVisibleTo(ed)
spec = lambda n: (app.data.get("materials") or {}).get(n) or {}
kind = lambda k: (ed.kind.setCurrentIndex(ed.kind.findData(k)), ed._flush())

ed.select("Plain")
ok(not seen(ed.pic_btn), "no picture: «Change picture…» is hidden")
ok(seen(ed.sliders["metallic"]) and not seen(ed.sliders["glow"]) and not seen(ed.ripple) and not seen(ed.grass),
   "generic: metal shown; glow, ripples and grass hidden")
ok(not seen(ed.map_size), "no map file: Map image size hidden")
row = ed.maps["roughness"]
i = row.source.findData("picture")
ok(not row.source.model().item(i).isEnabled(), "no picture: «Picture (B/W)» cannot be chosen")
ok(not seen(row.invert) and not seen(row.contrast), "no map: Invert and contrast hidden")
row.set_file(tmp / "ph" / "tiles_rough_1k.png"); ed._flush()
ok(seen(row.invert) and seen(row.contrast), "a black-and-white map: Invert and contrast shown")
ok(seen(ed.map_size), "a map file on a material without a picture: Map image size shown")
kind("water")
ok(seen(ed.ripple) and seen(ed.sliders["bump"]) and not seen(ed.maps["bump"]) and not seen(ed.sliders["metallic"]),
   "water: ripple size and wave height, no relief map, no metal")
ok(ed.form.labelForField(ed._rows["bump"]).text() == "Wave height", "water: Relief reads «Wave height»")
kind("glow")
ok(seen(ed.sliders["glow"]) and seen(ed.maps["glow"]) and not seen(ed.ripple), "glowing: glow and its map")
ok(ed.form.labelForField(ed._rows["bump"]).text() == "Relief", "…and Relief is Relief again")
kind("glass")
ok(not seen(ed.sliders["metallic"]) and seen(ed.transparency), "glass: no metal, transparency shown")
ed.maps["metallic"].set_file(tmp / "ph" / "tiles_rough_1k.png"); ed._flush()
ok("metallic" not in (spec("Plain").get("maps") or {}), "a hidden setting's map is not saved (the render ignores it)")
kind("generic")

ed.select("Floor")
ok(seen(ed.pic_btn), "with a picture: «Change picture…» shown")
ok(not seen(ed.sliders["bump"]) and seen(ed.maps["bump"]),
   "the texture set gives the relief: the Relief slider is hidden, its map row stays")
ed.maps["bump"].source.setCurrentIndex(ed.maps["bump"].source.findData("picture")); ed._changed(); ed._flush()
ok(seen(ed.sliders["bump"]), "…choosing a relief map brings the slider back (it scales that map)")
kind("glass")
ok("roughness" not in ed.set_label.text() and "normal" in ed.set_label.text()
   and ed.maps["roughness"].source.itemText(0) == "No map",
   f"glass: only the set's normal map is offered (the render uses no other): «{ed.set_label.text()}»")

# ---- the panel: the live view's engine and a Blender chosen by hand ---------------------------
block, _amb = presets.studio("interior")
ok(block.get("engine_hint") == "cycles", "the Interior look asks for Cycles (so its live view uses Cycles)")
ok(not presets.studio("clear")[0].get("engine_hint"), "…the others keep the light EEVEE live view")
ok(P.blender_version_ok(None)[0] is False, "no program: not a Blender")
if Path(sys.executable).name.lower().startswith("python"):
    fake = tmp / "fake_blender.py"
    for text, want in (("Blender 4.1.0", False), ("Blender 5.3.0 (hash x)", True), ("GIMP 3", False)):
        fake.write_text(f"print({text!r})", encoding="utf-8")
        got, why = P.blender_version_ok([sys.executable, str(fake)])
        ok(got is want, f"«{text}»: {'accepted' if want else 'refused'} ({why or 'ok'})")

print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
