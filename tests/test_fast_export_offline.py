"""The quicker model export: the quick triangulation gives IngeTrazo's own triangles, the export
progress counts faces, the engine of a still big model, the preview's modal. Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import json, math, os, random, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtCore import QSettings
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
qa.setOrganizationName("RenderStudioTest"); qa.setApplicationName("fastexport")
import core.triangulate as T
from core.camera import OrbitCamera
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from render_studio import fast_export as FE, panel as P
from render_studio.i18n import tr

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

real = T.triangulate
rnd = random.Random(7)
def polygon(kind):
    if kind == "convex":
        ang = sorted(rnd.uniform(0, 6.283) for _ in range(rnd.choice([3, 4, 5, 6, 8])))
        return [(2 * math.cos(a), 2 * math.sin(a)) for a in ang]
    return [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)]                      # an L: concave
def place(poly, plane):
    return [QVector3D(*{"z": (x, y, 0.0), "x": (0.0, x, y), "y": (x, 0.0, y), "tilt": (x, y, 0.3 * x + 0.1 * y)}[plane])
            for x, y in poly]
def normal_of(pts):
    n = QVector3D(0, 0, 0)
    for i, c in enumerate(pts):
        nx = pts[(i + 1) % len(pts)]
        n += QVector3D((c.y() - nx.y()) * (c.z() + nx.z()), (c.z() - nx.z()) * (c.x() + nx.x()),
                       (c.x() - nx.x()) * (c.y() + nx.y()))
    return n.normalized()

same = total = fanned = 0
for kind in ("convex", "convex", "concave"):
    for plane in ("z", "x", "y", "tilt"):
        for _ in range(40):
            pts = place(polygon(kind), plane)
            if kind == "convex" and rnd.random() < 0.5:
                pts.reverse()
            n = normal_of(pts)
            want = real(pts, None, n)
            fan = FE.convex_fan(pts, n)
            total += 1
            if fan is None:
                same += 1 if kind == "concave" else 0     # a concave one is left to IngeTrazo's earcut
            else:
                fanned += 1
                same += 1 if [tuple(map(id, t)) for t in fan] == [tuple(map(id, t)) for t in want] else 0
ok(same == total, f"the quick fan is IngeTrazo's own triangles on {total} polygons ({fanned} convex): {same} equal")
sq = [(0, 0), (4, 0), (4, 4), (0, 4)]; hole = [(1, 1), (1, 3), (3, 3), (3, 1)]
holed = real(place(sq, "z"), [place(hole, "z")], QVector3D(0, 0, 1))
with FE.fast_triangles():
    got = T.triangulate(place(sq, "z"), [place(hole, "z")], QVector3D(0, 0, 1))
    ok(T.triangulate is not real, "the quick function is in place while the model is written")
    tri = T.triangulate(place([(0, 0), (1, 0), (0, 1)], "z"), None, QVector3D(0, 0, 1))
ok(len(got) == len(holed) and len(got) > 2, f"a face with a hole goes to IngeTrazo's function ({len(got)} triangles)")
ok(len(tri) == 1, "a triangle stays a triangle")
ok(T.triangulate is real, "IngeTrazo's own is put back after")

import gc
with FE.gc_paused():
    ok(not gc.isenabled(), "the collector sleeps while the model is written")
ok(gc.isenabled(), "...and wakes after")

import formats.meshexport as me
seen = []
realadd = me._add_face
with FE.export_progress(10, seen.append, every=2):
    for _ in range(6):
        try:
            me._add_face(object(), {}, {})
        except Exception:
            pass
ok(seen == [0.2, 0.4, 0.6], f"the progress is told every few faces ({seen})")
ok(me._add_face is realadd, "...and the writer is put back")

scene = Scene()
m = Mesh()
for i in range(5):
    m.add_face([QVector3D(i, 0, 0), QVector3D(i + 1, 0, 0), QVector3D(i + 1, 1, 0), QVector3D(i, 1, 0)])
scene.groups += [Group(m, name="a"), Group(m, name="b")]
ok(FE.unique_faces(scene) == 5 and P.expanded_faces(scene) == 10, "a shared mesh counts once for the bar, twice flat")

# ---- the preview's engine ------------------------------------------------------------------------
class VP:
    def __init__(self): self.camera = OrbitCamera(); self.scene = scene
    def update(self): pass
class App:
    def __init__(self): self.scene = scene; self.viewport = VP(); self.data = {}
    def document_data(self, d=None): return json.loads(json.dumps(self.data)) if self.data else d
    def set_document_data(self, v): self.data = json.loads(json.dumps(v))
    def on_document_changed(self, fn): pass
panel = P.StudioPanel(App())
class Live:
    follow_camera = True; follow_changes = True; active = False
live = Live(); panel._live = live
P.INSTANCED_FROM_FACES = 8                                   # this little model is "big"
panel.preset.setCurrentIndex(max(0, panel.preset.findData("clear")))
ok(panel.preview_engine.currentData() == "auto", "the preview engine is Automatic by default")
ok(panel.live_engine() == "eevee", "following the camera and the changes: EEVEE")
live.follow_camera = False
ok(panel.live_engine() == "eevee", "following only the changes: EEVEE")
live.follow_changes = False
k1 = panel.live_key()
ok(panel.live_engine() == "cycles", "following neither on a big model: Cycles")
live.follow_camera = True
ok(panel.live_key() != k1, "...and the live view's key changes with it (Blender is told again)")
live.follow_camera = False
P.INSTANCED_FROM_FACES = 10_000; panel._big_key = None
ok(panel.live_engine() == "eevee", "a model that is not big stays EEVEE")
panel.preview_engine.setCurrentIndex(panel.preview_engine.findData("cycles"))
ok(panel.live_engine() == "cycles" and QSettings().value("render_studio/preview_engine") == "cycles",
   "Cycles chosen: always Cycles, remembered")
panel.preview_engine.setCurrentIndex(panel.preview_engine.findData("eevee")); P.INSTANCED_FROM_FACES = 8; panel._big_key = None
ok(panel.live_engine() == "eevee", "EEVEE chosen: always EEVEE")

# ---- the modal ---------------------------------------------------------------------------------
from render_studio.prep_dialog import PrepDialog
d = PrepDialog(None)
d.exporting(0.5)
ok(d.maximum() == 100 and 40 <= d.value() <= 45 and tr("Exporting the model… {pct} %", pct=50) == d.labelText(), f"the modal's bar fills with the export ({d.value()})")
d.waiting("Starting Blender…")
ok(d.maximum() == 0 and d.labelText() == tr("Starting Blender…"), "...then waits while Blender starts")
d.exporting(1.0)
ok(d.maximum() == 100, "...and measures again if asked")
panel._prep = PrepDialog(None); got = []
panel._prep.canceled.connect(lambda: got.append(1))
panel._set_status("Blender: the model is in; applying the look…")
ok(panel._prep.labelText() == tr("Blender: the model is in; applying the look…"), "Blender's stages reach the modal")
panel._prep_close()
ok(panel._prep is None and not got, "closing it when the picture arrives is not Cancel")
ok(panel._export_progress() is None, "no modal, no progress callback")


# ---- opening the preview and rendering: the feedback comes first ----------------------------------
from pathlib import Path
class FakeLive:
    def __init__(self): self.active = False; self.started = 0; self.stopped = 0; self.follow_camera = True; self.follow_changes = True
    def set_follow_camera(self, on): self.follow_camera = on
    def set_follow_changes(self, on): self.follow_changes = on
    def start(self):
        self.active = True; self.started += 1
        seen.append(("start", panel._prep is not None and panel._prep.isVisible()))
    def stop(self): self.active = False; self.stopped += 1
seen = []
panel.blender = lambda: object(); panel.check_blender = lambda: object()
fl = FakeLive(); panel._live = fl
panel.open_preview()
ok(seen and seen[-1] == ("start", True), "opening the preview: the modal is up before the live view starts")
ok(panel._export_progress() is not None, "...and the export reports to it")
panel._live_image(Path("nowhere.png"))
ok(panel._prep is None, "the first picture closes the modal")
panel.open_preview()
ok(panel._prep is None, "an open live view is not covered by a new modal")
fl.active = False; panel.window.mode = "preview"; panel.proc = None
panel.open_preview()
from PySide6.QtWidgets import QPushButton
panel._prep.findChild(QPushButton).click()
ok(panel._prep is None and fl.stopped >= 1 and not panel.window.isVisible(), "Cancel in the modal: no live view, no window")

order = []
def fake_job(*a, **k):
    order.append(("job", panel.window.mode, panel.window.bar.maximum()))
    k["progress"](0.5)
    order.append(("bar", panel.window.bar.value(), panel.status.text()))
    raise RuntimeError("stop here")
real_job = P.write_studio_job; P.write_studio_job = fake_job
panel.window.set_mode("preview"); panel.window.show()
panel.render()
P.write_studio_job = real_job
ok(order and order[0] == ("job", "rendering", 0), f"rendering: the window shows it is working before the model is exported ({order[:1]})")
ok(order[1][1] == 42 and tr("Exporting the model… {pct} %", pct=50) in order[1][2], f"...with the export's progress ({order[1][1:]})")
ok(panel._preparing is False, "...and a failure leaves the panel free again")

# ---- Render straight from the panel ------------------------------------------------------------------
ok(panel.render_btn.text() == "Render" and panel.render_save_btn.text().startswith("Render and save"),
   "the panel has Render and Render and save…")
panel.window.hide(); panel.window.set_mode("preview"); fl.active = False; fl.started = 0
seen2 = []
def fake_job2(*a, **k):
    seen2.append((panel.window.isVisible(), panel.window.mode, panel._direct))
    raise RuntimeError("stop here")
P.write_studio_job = fake_job2
panel.render_btn.click()
P.write_studio_job = real_job
ok(seen2 == [(True, "rendering", True)], f"Render from the panel opens the window in Rendering, no live preview ({seen2})")
ok(not panel.window.isVisible() and fl.started == 0, "...and if it fails the window goes away and no live view starts")
panel.window.show(); panel.window.set_mode("preview")
seen3 = []
def fake_job3(*a, **k):
    seen3.append(panel._direct)
    raise RuntimeError("stop here")
P.write_studio_job = fake_job3
panel.render()
P.write_studio_job = real_job
ok(seen3 == [False] and fl.started == 1, "from an open preview it goes back to the live preview, as before")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
