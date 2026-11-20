"""Render Studio's own writes into the document (a material's settings) are not a change of the
model: the live view keeps its model, the list of used materials is not read again, and the
material editor rebuilds nothing when no row changes. Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import json, os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QVector3D
from core.history import History
from core.materials import Material
from core.scene import Scene
from render_studio import material_editor as ME, materials as M, studio_data

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

class VP:
    def __init__(self, scene):
        self.scene = scene; self.history = History(scene); self.changes = 0
    def notify_scene_changed(self): self.changes += 1
    def update(self): pass
class App:
    def __init__(self):
        self.scene = Scene(); self.viewport = VP(self.scene); self.key = "render_studio"
    def document_data(self, default=None):
        d = (self.scene.plugin_data or {}).get(self.key)
        return json.loads(json.dumps(d)) if d is not None else default
    def set_document_data(self, v):
        raise AssertionError("the plain call bumps the version as a model change")

app = App(); scene = app.scene
scene.materials["Brick"] = Material("Brick", color=(0.7, 0.3, 0.2))
scene.materials["Grass"] = Material("Grass", color=(0.2, 0.6, 0.2))
f = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
f.attrs["mat"] = "Brick"
scene.version += 1

mv0, cv0 = M.model_version(scene), scene.content_version
studio_data.write(app, {"materials": {"Brick": {"type": "matte"}}})
ok(scene.content_version == cv0 + 1 and M.model_version(scene) == mv0,
   "a write of ours bumps the document's version but not the model's")
ok(app.document_data({})["materials"]["Brick"]["type"] == "matte" and app.viewport.changes == 1,
   "…it is stored and announced")
app.viewport.history.undo()
ok(M.model_version(scene) == mv0 and app.document_data({}) is None or "Brick" not in (app.document_data({}) or {}).get("materials", {}),
   "undo takes it back, still not a model change")
app.viewport.history.redo()
ok(M.model_version(scene) == mv0 and "Brick" in app.document_data({})["materials"], "redo puts it back, still not a model change")
scene.version += 1                                   # a real edit
ok(M.model_version(scene) != mv0, "a real edit of the model does change it")

# the list of used materials is read again only when the model changed
calls = []
real = M._used_materials
M._used_materials = lambda s: (calls.append(1), real(s))[1]
try:
    M.used_materials(scene); n = len(calls)
    M.used_materials(scene)
    ok(len(calls) == n, "the second ask is answered from memory")
    studio_data.write(app, {"materials": {"Brick": {"type": "glass"}}})
    M.used_materials(scene)
    ok(len(calls) == n, "…and a material's settings changing does not make it read the faces again")
    scene.version += 1
    M.used_materials(scene)
    ok(len(calls) == n + 1, "…but an edit of the model does")
finally:
    M._used_materials = real

# the editor: rows unchanged -> nothing rebuilt; a setting changed -> only the pane; a row changed -> rebuilt
made = []
real_make = ME._make_swatch
ME._make_swatch = lambda mat: (made.append(1), real_make(mat))[1]
try:
    ME.clear_swatches()
    ed = ME.MaterialEditor(app, "en")
    rows0 = [ed.list.item(i).text() for i in range(ed.list.count())]
    ok(len(rows0) == 2 and any("Brick" in r for r in rows0), f"the editor lists the used materials ({rows0})")
    built = len(made)
    ed.refresh(); ed.refresh()
    ok(len(made) == built, "refreshing again reads no picture and builds no row")
    shows = []
    real_show = ed._show
    ed._show = lambda item, _prev=None: (shows.append(1), real_show(item, _prev))[1]
    studio_data.write(app, {"materials": {"Brick": {"type": "matte", "bump": 0.4}}})
    ed.refresh()
    ok(len(shows) == 1 and len(made) == built, "a setting changed (undo, say): the pane is shown again, the list is not rebuilt")
    studio_data.write(app, {"materials": {"Brick": {"type": "matte"}, "Grass": {"type": "grass"}}})
    ed.refresh()
    rows1 = [ed.list.item(i).text() for i in range(ed.list.count())]
    ok(any(r.startswith("● ") and "Grass" in r for r in rows1), f"a row's mark changed: the list is rebuilt ({rows1})")
    ed.refresh(force=True)
    ok(ed.list.count() == 2, "force rebuilds anyway")
finally:
    ME._make_swatch = real_make

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
