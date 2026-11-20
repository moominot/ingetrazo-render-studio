"""Materials recognised by their name (or their picture's file name): water, glass, grass, tall grass
and lights, in the editor and in the render job. Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import copy, json, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QVector3D
from core.group import Group
from core.materials import Material
from core.mesh import Mesh
from core.scene import Scene
from render_studio import material_editor as ME, materials as M

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

D = M.detect_preset
cases = {
    "water": ["Aigua", "aigua piscina", "Agua de piscina", "[Water Pool Light]2", "WaterBlue", "Mar", "Llac",
              "Piscina_01", "Wasser", "Eau", "Estany", "Água"],
    "glass": ["Vidre", "Vidre finestra", "Vidrio_templado", "Translucent_Glass_Blue", "Cristal", "Verre", "Glas"],
    "lawn": ["Gespa", "gespa_01", "Césped", "Cesped", "Grass", "Vegetation_Grass_Artificial", "Lawn", "Herba",
             "Hierba", "Rasen", "Pelouse", "Relva"],
    "meadow": ["Herba alta", "Hierba_alta", "Tall grass", "GrassLong", "Prat", "Prado", "Meadow"],
    "light": ["Llum", "Luz", "LED panel", "Neon", "Làmpada", "Lámpara", "Emissive_white", "Glow"],
    None: ["Marbre", "Mármol", "Marble_07", "Formigó", "Paret", "Light grey", "Light wood", "Glasur", "Seat",
           "Ledge", "Lampshade_fabric", "Pratique", "Herbal", "Mariner", "Granit", "Brick_01", "Vidal", ""],
}
for want, names in cases.items():
    bad = [n for n in names if D(n) != want]
    ok(not bad, f"{want or 'nothing'}: {', '.join(names)}" + (f" — wrong: {[(n, D(n)) for n in bad]}" if bad else ""))
ok(D("Material12", "lawn_diff_1k.jpg") == "lawn", "the picture's file name counts too")
ok(D("Gespa", "water.jpg") == "lawn", "…the name first")
s = M.detected_spec("Aigua")
ok(s["type"] == "water" and "ripple_size" in s and "transparency" not in s and s.get("detected"),
   "a detected water: the Water preset, without touching the model's transparency")
ok(M.detected_spec("Gespa")["grass_density"] == 260 and M.detected_spec("Herba alta")["grass_height"] == 0.30,
   "grass gets the Lawn preset, tall grass the Tall grass one")

# ---- in the editor and the job ------------------------------------------------------------------
scene = Scene()
for n in ("Gespa", "Aigua", "Paret", "Vidre"):
    scene.materials[n] = Material(n, color=(0.5, 0.5, 0.5))
m = Mesh()
for i, n in enumerate(scene.materials):
    f = m.add_face([QVector3D(i, 0, 0), QVector3D(i + 1, 0, 0), QVector3D(i + 1, 1, 0), QVector3D(i, 1, 0)])
    f.attrs["mat"] = n
scene.groups.append(Group(m, name="g"))
class App:
    def __init__(self): self.scene = scene; self.viewport = None; self.data = {}
    def document_data(self, d=None): return copy.deepcopy(self.data) if self.data else d
    def set_document_data(self, v): self.data = copy.deepcopy(v)
app = App(); ed = ME.MaterialEditor(app, "ca")
texts = {ed.list.item(i).data(0x0100): ed.list.item(i).text() for i in range(ed.list.count())}
ok(texts["Gespa"].startswith("◦ ") and texts["Aigua"].startswith("◦ ") and texts["Paret"] == "Paret",
   f"the list marks the detected ones ◦ ({list(texts.values())})")
ed.select("Gespa")
ok(ed.kind.currentData() == "grass" and ed.grass.isVisibleTo(ed) and ed.preset.currentData() == "lawn",
   "«Gespa» opens as Grass, Lawn preset, with its grass controls")
ok(ed.detected_label.isVisibleTo(ed) and "Gespa" in ed.detected_label.text(),
   f"…and says it was detected: «{ed.detected_label.text()}»")
ok(not app.data.get("materials"), "nothing is written in the document just by looking")
ed.select("Aigua")
ok(ed.kind.currentData() == "water" and ed.ripple.isVisibleTo(ed), "«Aigua» opens as Water")
ed._set_slider("ripple_size", 0.3); ed._changed(); ed._flush()
ok(app.data["materials"]["Aigua"]["type"] == "water" and not ed.detected_label.isVisibleTo(ed),
   "a change makes it its own (stored as Water), and the note goes")
ed.select("Paret")
ok(ed.kind.currentData() == "generic" and not ed.detected_label.isVisibleTo(ed), "«Paret»: generic, no note")

from render_studio import panel as P
spec_job = M.job_block(M.with_detected(scene, app.data.get("materials")))
ok(spec_job.get("Gespa", {}).get("type") == "grass" and spec_job.get("Vidre", {}).get("type") == "glass",
   "the render job gets the detected ones (grass grows on «Gespa»)")
ok(abs(spec_job["Aigua"]["ripple_size"] - 0.3) < 0.02, "…and the material's own settings win")
ok("Paret" not in spec_job, "…and nothing for the others")

print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
