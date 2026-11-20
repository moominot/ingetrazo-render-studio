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

ok(wait(lambda: live._ready and not live._busy and live._done_key is not None), "settled")
n = len(images); t_m = time.time()
while time.time() - t_m < 4.0:                      # a slow orbit, as a hand drags it
    app.viewport.camera.yaw += 0.01
    t_end = time.time() + 0.03
    while time.time() < t_end:
        qa.processEvents(); time.sleep(0.003)
moving = images[n:]
fps = len(moving) / 4.0
print(f"   while orbiting for 4 s: {len(moving)} frames, {fps:.1f} per second")
ok(fps >= 2.0, f"Follow the camera: frames keep coming while it moves ({fps:.1f}/s)")
ok(len(moving) and size(moving[-1][1]) == 320, "...small ones (320 px)")
ok(wait(lambda: live._done_key == live._seen_key), "when it stops, the draft")

n = len(images); t_mat = time.time()
app.data["materials"]["Gespa"]["grass_height"] = 0.25           # a material edit
ok(wait(lambda: live._ready and live._kept_specs["Gespa"]["grass_height"] == 0.25), "Follow changes: a material edit is taken in by itself")
m = len(images)
ok(wait(lambda: len(images) > m), "...and shows")
print(f"   material edit → image {images[m][0] - t_mat:.1f} s")
n = len(images); t_two = time.time()
app.data["materials"]["Gespa"]["grass_height"] = 0.12              # two edits in a row: the second
panel.preset.setCurrentIndex(panel.preset.findData("overcast"))     # arrives while the first builds
t_end = time.time() + 0.35
while time.time() < t_end:
    qa.processEvents(); time.sleep(0.005)
app.data["materials"]["Gespa"]["grass_height"] = 0.10
ok(wait(lambda: live._ready and live._kept_specs["Gespa"]["grass_height"] == 0.10 and len(images) > n),
   "edits in a row: each taken in turn")
ok(live.starts == 1, "...without starting Blender again")

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
ok(wait(lambda: live._model_key == panel.live_model_key() and live._ready), "…the new model is loaded")
ok(live.starts == 1 and glb.stat().st_mtime_ns != mt, "…same Blender, model exported again")
job = json.load(open(live._work / "job.json"))
ok(job["engine"] == "eevee" and job["studio"].get("live"), "the live job is the lightened EEVEE draft")

# The Interior look: the live view switches to Cycles (EEVEE can't fill a window-lit room).
n = len(images); t4 = time.time()
panel.preset.setCurrentIndex(panel.preset.findData("interior"))
ok(panel.live_engine() == "cycles", "the Interior look's live view is Cycles")
ok(wait(lambda: len(images) > n), "…an image comes")
print(f"   change to Interior (Cycles) → quick image {images[n][0] - t4:.1f} s" if len(images) > n else "")
job = json.load(open(live._work / "job.json"))
ok(job["engine"] == "cycles" and job["studio"].get("live"), "…the live job is Cycles")
ok(wait(lambda: live._ready and not live._busy and live._done_key is not None), "…and its draft")
ok(any("| Sample 32/32" in l for l in live.tail), "…Blender rendered it with Cycles (32 samples for the draft)")
n = len(images); t5 = time.time()
app.viewport.camera.yaw += 0.4
ok(wait(lambda: len(images) > n), "a camera move in Cycles gives a new image")
print(f"   Cycles: camera move → quick image {images[n][0] - t5:.2f} s" if len(images) > n else "")
ok(wait(lambda: live._done_key == live._seen_key and not live._busy), "…and its draft")
print(f"   Cycles: quick → draft {images[-1][0] - images[n][0]:.2f} s")
n = len(images); t_m = time.time()
while time.time() - t_m < 4.0:
    app.viewport.camera.yaw += 0.01
    t_end = time.time() + 0.03
    while time.time() < t_end:
        qa.processEvents(); time.sleep(0.003)
print(f"   Cycles while orbiting for 4 s: {len(images) - n} frames, {(len(images) - n) / 4.0:.1f} per second")
panel.preset.setCurrentIndex(panel.preset.findData("clear"))
ok(panel.live_engine() == "eevee", "another look: back to EEVEE")
ok(live.starts == 1, "…all in the same Blender")
print("   Blender starts:", live.starts)
print("   restart why:", getattr(live, "restarts_why", None), " ended:", hasattr(live, "ended_tail"))
if live.starts > 1 or fails:
    print("   Blender's last lines before it stopped:\n      "
          + "\n      ".join(getattr(live, "ended_tail", live.tail)[-30:]))
live.stop()
ok(live._proc is None, "stopping closes Blender")
print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
