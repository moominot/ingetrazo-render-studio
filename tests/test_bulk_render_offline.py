"""Render Studio's lights, without Blender: the format and its units, IES profiles, lights on
objects (moved, turned, copied with them), the one-step edits with undo/redo, the Lights tab and
the render job. argv: <ingetrazo-src> <render-studio repo>"""
import json, math, os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QMatrix4x4, QVector3D
from core.camera import OrbitCamera
from core.group import Group, copy_group
from core.history import History
from core.mesh import Mesh
from core.scene import Scene
from render_studio import light_ops as ops, lights as L, panel as P

import time
fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

def close(a, b, tol=1e-4):
    return all(abs(x - y) <= tol for x, y in zip(a, b))

class VP:
    def __init__(self, scene):
        self.scene = scene; self.history = History(scene); self.changes = 0; self.listeners = []
        self.camera = OrbitCamera()
    def notify_scene_changed(self):
        self.changes += 1
        for fn in self.listeners: fn()
    def update(self): pass
    def width(self): return 1600
    def height(self): return 900
class App:
    api_version = 2
    def __init__(self):
        self.scene = Scene(); self.viewport = VP(self.scene); self.key = "render_studio"
    def document_data(self, default=None):
        d = (self.scene.plugin_data or {}).get(self.key)
        return json.loads(json.dumps(d)) if d is not None else default
    def set_document_data(self, v):
        from core.history import SetPluginDataCommand
        self.viewport.history.execute(SetPluginDataCommand(self.key, v)); self.viewport.notify_scene_changed()
    def on_document_changed(self, fn): self.viewport.listeners.append(fn)


from PySide6.QtCore import QTimer, Qt
from core.saved_views import SavedView
from render_studio import bulk_render as BR
ok(BR.scene_file_name("{document}-{scene}", "Casa", "Planta/1", ".png") == "Casa-Planta_1.png", "a scene's file name is safe")
ok(BR.scene_file_name("{scene}", "x", "A", ".png", taken=["a.png"]) == "A-2.png", "two scenes with one name get a number")
_n = BR.scene_file_name("", "", "", ".jpg")
ok(_n.startswith("render-scene-") and _n.endswith(".jpg"), f"empty pieces still make a name ({_n})")

app = App(); scene = app.scene
app.viewport.camera = OrbitCamera()
app.viewport.camera.distance = 7.0
class Win: _current_path = None
app.window = Win()
for n, d in enumerate((11.0, 22.0, 33.0)):
    cam = OrbitCamera(); cam.distance = d
    v = SavedView.capture(f"Scene {n + 1}", scene, cam)
    scene.saved_views.append(v)
scene.saved_views[1].folder = "Alçats"
choices = BR.scene_choices(scene)
ok([c[1] for c in choices] == ["Scene 1", "Alçats / Scene 2", "Scene 3"], f"the scenes are listed with their folder ({[c[1] for c in choices]})")

panel = P.StudioPanel(app)
tab = panel.output_tab
panel.show()
ok(hasattr(panel.render_btn, "menu") and panel.render_btn.menu() is not None, "the Render button has an arrow with a menu")
names = [a.text() for a in panel.render_btn.menu().actions()]
ok(names == ["Render and save…", "Render the selected scenes", "Open in Blender…"], f"…holding Render and save…, the scenes and Open in Blender… ({names})")
ok(not tab.scenes_box.isVisibleTo(tab), "the Output tab starts in «Current view»: no scenes list")
tab.mode_scenes.setChecked(True); qa.processEvents()
ok(tab.scenes_box.isVisibleTo(tab) and tab.scene_list.count() == 3 and all(tab.scene_list.item(i).checkState() for i in range(3)),
   "choosing «Scenes» lists every scene, ticked")
ok(not tab.autosave.isEnabled(), "…and the scenes are always saved: the «Save each render» tick is off")
tab.scene_list.item(1).setCheckState(Qt.Unchecked)
ok(len(tab.chosen_views()) == 2, "unticking one leaves two")
seen = []
def fake_render(save_to=None):
    seen.append((save_to, app.viewport.camera.distance, panel.render_camera().distance))
    QTimer.singleShot(5, lambda: panel.finished.emit(Path(save_to)))
panel.render = fake_render
out = tempfile.mkdtemp()
tab.folder.setText(out); tab.pattern.setText("{scene}")
bad = panel.render_scenes() if False else None
tab.folder.setText("")
panel.render_scenes()
ok(not seen and "folder" in panel.status.text().lower(), f"with no folder it says so and renders nothing ({panel.status.text()[:60]})")
tab.folder.setText(out)
done = []
win = panel.render_scenes()
win.run.finished.connect(lambda d, f, c: done.append((d, f, c)))
t = time.time()
while not done and time.time() - t < 10:
    qa.processEvents()
ok(done == [(2, 0, False)], f"two scenes rendered, none failed ({done})")
ok([Path(s[0]).name for s in seen] == ["Scene 1.png", "Scene 3.png"], f"in order, named after the scenes with the Output tab's name ({[Path(s[0]).name for s in seen]})")
ok([s[1] for s in seen] == [11.0, 33.0] and [s[2] for s in seen] == [11.0, 33.0], "each render took its scene's camera")
ok(app.viewport.camera.distance == 7.0 and panel._camera_override is None, "afterwards the view is as it was")
ok("2 scenes rendered" in win.status.text(), f"the progress window says so ({win.status.text()})")
# the Render button follows the mode
seen.clear(); done.clear()
calls = []
panel.render_scenes = lambda: calls.append("scenes")
real_render = panel.render
panel.render = lambda *a, **k: calls.append("view")
panel.render_main()
tab.mode_view.setChecked(True)
panel.render_main()
ok(calls == ["scenes", "view"], f"Render does the scenes in «Scenes» mode and the current view otherwise ({calls})")
# the name and folder are the same for one render and for many
ok(tab.autosave_target() is None, "the folder and name serve the current view too (when «Save each render» is on)")
tab.autosave.setChecked(True)
ok(tab.autosave_target() == (Path(out), "{scene}"), "…the same folder and name as the scenes")

# the Output tab: projection first, then size, file, what to render, where to save; no help button of its own
from PySide6.QtWidgets import QToolButton
from render_studio.widgets import Card
heads = [tab.layout().itemAt(i).widget().title() for i in range(tab.layout().count())
         if isinstance(tab.layout().itemAt(i).widget(), Card)]                      # as they are laid out, top to bottom
ok(heads == ["Projection", "Size", "File", "What to render", "Save"], f"the Output tab's order ({heads})")
ok(not any(b.text() == "?" for b in tab.findChildren(QToolButton)), "the Output tab has no help button (the panel's is beside the tabs)")
# the ground: the radius sliders
from render_studio import ground as G
from PySide6.QtGui import QMatrix4x4
panel.ground_material.addItem("Lawn", "Lawn")
ok(not panel.ground_more.form.isRowVisible(panel.ground_grass) if hasattr(panel.ground_more.form, "isRowVisible") else True, "the grass radius is not shown for a material that is not grass")
panel.ground_radius.setValue(150)
ok(panel.ground_look_settings()["ground_radius"] == 150.0 and P.apply_ground_look({}, panel.ground_look_settings())["ground_radius"] == 150.0, "the ground radius is in the settings and the job")
cen = G.centroid(app.scene)
ok(len(cen) == 2, f"the centroid of the drawing's objects is worked out ({cen})")
print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
