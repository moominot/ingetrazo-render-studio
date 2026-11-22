"""(Header of the reuse test; see below.) The live view with a REAL Blender (offscreen Qt, IngeTrazo's source): a small house-like model on a
lawn typed Grass. Times the first quick image, the draft after it, a camera move, a change of look
(rebuilt in the same Blender, model not exported again) and a change of the model.
argv: <ingetrazo-src> <render-studio repo> <blender.exe>"""
import json, math, os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
BLENDER = sys.argv[3]
sys.path[:0] = [SRC, REPO]
tmp = tempfile.mkdtemp()
os.environ["XDG_CACHE_HOME"] = os.path.join(tmp, "cache")
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QVector3D
from core.camera import OrbitCamera
from core.group import Group
from core.materials import Material
from core.mesh import Mesh
from core.scene import Scene
from render_studio import panel as P
from render_studio.live import LiveSession

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)
def wait(cond, secs=120.0):
    t0 = time.time()
    while not cond() and time.time() - t0 < secs:
        qa.processEvents(); time.sleep(0.01)
    return cond()

class VP:
    def __init__(self):
        self.camera = OrbitCamera(); self.camera.target = QVector3D(0, 0, 1.2); self.camera.distance = 14
        self.camera.yaw = math.radians(-50); self.camera.pitch = math.radians(12)
    def width(self): return 1600
    def height(self): return 900
    def update(self): pass
class App:
    def __init__(self):
        self.scene = Scene(); self.viewport = VP(); self.viewport.scene = self.scene; self.data = {}
        s = self.scene
        s.materials["Tapis"] = Material("Tapis", color=(0.18, 0.40, 0.10))
        s.materials["Paret"] = Material("Paret", color=(0.85, 0.82, 0.76))
        m = Mesh(); V = QVector3D
        f = m.add_face([V(-10, -10, 0), V(10, -10, 0), V(10, 10, 0), V(-10, 10, 0)]); f.attrs["mat"] = "Tapis"
        f.attrs["color"] = (0.18, 0.40, 0.10, 1.0)
        s.groups.append(Group(m, name="lawn"))
        b = Mesh()
        x0, y0, x1, y1, z1 = -3, -2, 3, 2, 3
        for q in ([V(x0, y0, 0), V(x1, y0, 0), V(x1, y0, z1), V(x0, y0, z1)], [V(x1, y0, 0), V(x1, y1, 0), V(x1, y1, z1), V(x1, y0, z1)],
                  [V(x1, y1, 0), V(x0, y1, 0), V(x0, y1, z1), V(x1, y1, z1)], [V(x0, y1, 0), V(x0, y0, 0), V(x0, y0, z1), V(x0, y1, z1)],
                  [V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]):
            f = b.add_face(q); f.attrs["mat"] = "Paret"; f.attrs["color"] = (0.85, 0.82, 0.76, 1.0)
        s.groups.append(Group(b, name="house"))
        self.data = {"materials": {"Gespa": {"type": "grass", "roughness": 0.85, "grass_height": 0.08}}}
    def document_data(self, d=None): return json.loads(json.dumps(self.data)) if self.data else d
    def set_document_data(self, v): self.data = json.loads(json.dumps(v))
    def on_document_changed(self, fn): pass

import types
from PySide6.QtGui import QImage
app = App()
panel = P.StudioPanel(app)
found = types.SimpleNamespace(command=[BLENDER])
panel.check_blender = lambda: found
panel.blender = lambda: found
panel.quality.setCurrentIndex(0)
panel.engine.setCurrentIndex(max(0, panel.engine.findData("eevee")))
live = LiveSession(panel, argv_factory=lambda job, script: [BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)])
panel._live = live
images = []
live.image.connect(lambda p: images.append(str(p)))
results = []
panel.finished.connect(lambda p: results.append(p))

def diff(a, b):
    a, b = QImage(str(a)).convertToFormat(QImage.Format_RGB32), QImage(str(b)).convertToFormat(QImage.Format_RGB32)
    if a.size() != b.size():
        return None
    tot = n = 0
    for y in range(0, a.height(), 3):
        for x in range(0, a.width(), 3):
            ca, cb = a.pixelColor(x, y), b.pixelColor(x, y)
            tot += (abs(ca.red() - cb.red()) + abs(ca.green() - cb.green()) + abs(ca.blue() - cb.blue())) / 3.0; n += 1
    return tot / n

# a lawn that is NOT grass (grass is a sparser draft in the live view: that case goes the long way)
app.data = {}
panel.preview().show()
live.start()
ok(wait(lambda: len(images) >= 2), "the live view has its scene and a draft")
_orig_done = panel._done
stamps = []
def _timed(*a):
    stamps.append(time.time()); return _orig_done(*a)
panel._done = _timed
lines = []
live.line.connect(lambda l: lines.append((time.time(), l)))
t0 = time.time()
panel.render()
t_sent = time.time() - t0
ok(wait(lambda: len(results) >= 1, 240), "Render finishes")
print(f"   sent after {t_sent:.2f} s; callback at {stamps[0] - t0:.2f} s; Blender said:", [(round(t - t0, 2), l[:60]) for t, l in lines][:8])
t_reuse = time.time() - t0
ok(panel.proc is None and results[0] is not None, "…with a picture")
ok(getattr(panel, "last_render_reused", None) is True, "…made by the live scene, not by a Blender of its own")
fast_png = str(results[0]); keep = fast_png + ".reused.png"
import shutil; shutil.copyfile(fast_png, keep)
ok(not live.active and live.usable, "…and the live view waits (paused) with its Blender and scene")
loads, starts = live.loads, live.starts
del images[:]
panel.back_to_preview()
ok(wait(lambda: len(images) >= 1, 60) and live.active, "Back to preview: a picture at once from the waiting scene")
ok(live.loads == loads and live.starts == starts, "…with nothing loaded again and no new Blender")
results.clear()
panel.render()
ok(wait(lambda: len(results) >= 1, 120) and panel.last_render_reused is True, "a second render is made in the same scene too")
panel._stop_live()
ok(not live.usable, "closing the preview stops the paused Blender")

# the long way: no live view
results.clear()
t0 = time.time()
panel.render()
ok(wait(lambda: len(results) >= 1, 240), "the long way finishes too")
t_long = time.time() - t0
d = diff(keep, results[0])
print(f"   reused {t_reuse:.1f} s, the long way {t_long:.1f} s, mean difference {d}")
ok(d is not None and d < 1.5, f"the same picture either way (mean difference {d} of 255)")
ok(t_reuse < t_long, "…and sooner when the scene is reused")

# grass: the draft's grass is sparser, so the live scene is refused and the render is made the long way
results.clear(); images.clear()
app.scene.materials["Gespa"] = Material("Gespa", color=(0.18, 0.40, 0.10))
for g in app.scene.groups:
    for f in g.mesh.faces:
        if f.attrs.get("mat") == "Tapis": f.attrs["mat"] = "Gespa"
app.data = {"materials": {"Gespa": {"type": "grass", "roughness": 0.85, "grass_height": 0.08}}}
panel.last_render_reused = None
live.start()
ok(wait(lambda: len(images) >= 2, 240), "the live view is back, with grass")
panel.render()
ok(wait(lambda: len(results) >= 1, 400), "a grass scene still renders (the refused scene falls back to the long way)")
ok(results and results[0] is not None and QImage(str(results[0])).width() > 0, "…with a picture")
ok(panel.last_render_reused is False, "…and it says it was made the long way")
live.stop()
print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
