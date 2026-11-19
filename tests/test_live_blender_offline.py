"""The live view with a REAL Blender (offscreen Qt, IngeTrazo's source): a small house-like model on a
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
        self.scene = Scene(); self.viewport = VP(); self.data = {}
        s = self.scene
        s.materials["Gespa"] = Material("Gespa", color=(0.18, 0.40, 0.10))
        s.materials["Paret"] = Material("Paret", color=(0.85, 0.82, 0.76))
        m = Mesh(); V = QVector3D
        f = m.add_face([V(-10, -10, 0), V(10, -10, 0), V(10, 10, 0), V(-10, 10, 0)]); f.attrs["mat"] = "Gespa"
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

app = App()
panel = P.StudioPanel(app)
panel.blender = lambda: object()
live = LiveSession(panel, argv_factory=lambda job, script: [BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)])
panel._live = live
images = []
live.image.connect(lambda p: images.append((time.time(), str(p))))
live.state.connect(lambda t: print("   state:", t, flush=True))

def size(path):
    from PySide6.QtGui import QImage
    im = QImage(path); return im.width()

t0 = time.time()
live.start()
ok(wait(lambda: len(images) >= 1), "a first image comes")
t_quick = images[0][0] - t0 if images else -1
ok(wait(lambda: len(images) >= 2), "then the draft")
t_draft = images[1][0] - images[0][0] if len(images) > 1 else -1
print(f"   start → quick image {t_quick:.1f} s (Blender start + scene build), quick → draft {t_draft:.1f} s")
ok(len(images) >= 2 and size(images[0][1]) == 480 and size(images[1][1]) == 960, "quick image 480 px, draft 960 px")

n = len(images); t1 = time.time()
app.viewport.camera.yaw += 0.5
ok(wait(lambda: len(images) > n), "a camera move gives a new image")
t_move = images[n][0] - t1 if len(images) > n else -1
ok(wait(lambda: len(images) > n + 1), "…and its draft")
print(f"   camera move → quick image {t_move:.2f} s (includes the {live._rest()} ms rest)")

glb = live._work / "model.glb"; mt = glb.stat().st_mtime_ns
n = len(images); t2 = time.time()
panel.preset.setCurrentIndex(panel.preset.findData("golden_hour"))
ok(wait(lambda: len(images) > n), "a change of look gives a new image")
t_look = images[n][0] - t2 if len(images) > n else -1
print(f"   change of look → quick image {t_look:.1f} s (rebuilt in the same Blender)")
ok(live.starts == 1 and glb.stat().st_mtime_ns == mt, "…same Blender, model not exported again")
ok(t_look < t_quick, f"…quicker than starting ({t_look:.1f} s < {t_quick:.1f} s)")

n = len(images); t3 = time.time()
app.scene.version += 1
ok(wait(lambda: len(images) > n), "a change of the model gives a new image")
print(f"   change of model → quick image {time.time() - t3:.1f} s")
ok(live.starts == 1 and glb.stat().st_mtime_ns != mt, "…same Blender, model exported again")
job = json.load(open(live._work / "job.json"))
ok(job["engine"] == "eevee" and job["studio"].get("live"), "the live job is the lightened EEVEE draft")
live.stop()
ok(live._proc is None, "stopping closes Blender")
print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
