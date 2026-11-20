"""The Transparency of a glass material is its own setting in the render (the opacity the model gave it is
not read), so moving it is no change of the model for the live view; the one of any other material is.
Offscreen, with IngeTrazo's own commands and history. argv: <ingetrazo-src> <render-studio repo>"""
import json, os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from core.history import History
from core.materials import Material
from core.scene import Scene
from render_studio import materials as M, opacity as O

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

class VP:
    def __init__(self, scene): self.scene = scene; self.history = History(scene)
    def notify_scene_changed(self): pass
    def update(self): pass
class App:
    def __init__(self):
        self.scene = Scene(); self.viewport = VP(self.scene); self.key = "render_studio"
app = App(); scene = app.scene
for name in ("Vidre", "Window glass", "Brick", "Pool water"):
    scene.materials[name] = Material(name, color=(0.5, 0.6, 0.7))
    f = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)]); f.attrs["mat"] = name
scene.plugin_data["render_studio"] = {"materials": {"Window glass": {"type": "generic"}}}
scene.version += 1

ok(M.material_kind(scene, "Vidre") == "glass", "a material named «Vidre» is glass for the render")
ok(M.material_kind(scene, "Window glass") == "generic", "…unless its own settings say another type")
ok(M.material_kind(scene, "Brick") == "generic", "an ordinary material is generic")
ok(M.material_kind(scene, "Pool water") == "water", "water is recognised by its name too")

def moved(name, opacity):
    mv, cv = M.model_version(scene), scene.content_version
    ok_, _msg = O.set_opacity(app, name, opacity)
    return ok_, scene.content_version - cv, M.model_version(scene) - mv

okv, dv, dm = moved("Vidre", 0.3)
ok(okv and dv == 1 and dm == 0, f"the glass's Transparency is a change of the document but not of the model (+{dv}, +{dm})")
app.viewport.history.undo()
ok(M.model_version(scene) == M.model_version(scene) and scene.materials["Vidre"].opacity is None, "undo takes it back")
mv_before = M.model_version(scene)
app.viewport.history.redo()
ok(M.model_version(scene) == mv_before, "…and redo keeps it out of the model too")
okv, dv, dm = moved("Brick", 0.4)
ok(okv and dv == 1 and dm == 1, "the Transparency of an ordinary material is a change of the model (the render reads it)")
okv, dv, dm = moved("Window glass", 0.4)
ok(okv and dm == 1, "a glass-named material set to another type counts as an ordinary one")
okv, dv, dm = moved("Pool water", 0.5)
ok(okv and dm == 1, "water takes its transparency from the model: a change of the model")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
