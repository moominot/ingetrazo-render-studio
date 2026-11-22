"""The ground's material in the LIVE view (a real Blender kept between images): choosing a material of the model
in the Ground group puts it on the generated ground, and a later change of that material's settings follows.
argv: <ingetrazo-src> <render-studio repo> <blender.exe>"""
import json, math, os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
BLENDER = sys.argv[3]
sys.path[:0] = [SRC, REPO]
tmp = tempfile.mkdtemp()
os.environ["XDG_CACHE_HOME"] = os.path.join(tmp, "cache")
from PySide6.QtCore import QCoreApplication, QSettings
QCoreApplication.setOrganizationName("rs-test"); QCoreApplication.setApplicationName("rs-test")
QSettings.setDefaultFormat(QSettings.IniFormat); QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, os.path.join(tmp, "ini"))
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QColor, QImage, QVector3D
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
def wait(cond, secs=180.0):
    t0 = time.time()
    while not cond() and time.time() - t0 < secs:
        qa.processEvents(); time.sleep(0.01)
    return cond()

chk = QImage(64, 64, QImage.Format_RGB32)
for x in range(64):
    for y in range(64):
        chk.setPixelColor(x, y, QColor(220, 30, 30) if (x // 32 + y // 32) % 2 else QColor(30, 30, 220))
chk_path = os.path.join(tmp, "Paving stone.png"); chk.save(chk_path)

class VP:
    def __init__(self):
        self.camera = OrbitCamera(); self.camera.target = QVector3D(0, 0, 0.5); self.camera.distance = 16
        self.camera.yaw = math.radians(-50); self.camera.pitch = math.radians(35)
    def width(self): return 800
    def height(self): return 600
    def update(self): pass
class App:
    def __init__(self):
        self.scene = Scene(); self.viewport = VP(); self.data = {}
        s = self.scene
        s.materials["Paret"] = Material("Paret", color=(0.85, 0.82, 0.76))
        s.materials["Paving stone"] = Material("Paving stone", texture={"path": chk_path, "sw": 0.5, "sh": 0.5})
        V = QVector3D
        b = Mesh()
        for q in ([V(-1, -1, 0), V(1, -1, 0), V(1, -1, 2), V(-1, -1, 2)], [V(1, -1, 0), V(1, 1, 0), V(1, 1, 2), V(1, -1, 2)],
                  [V(1, 1, 0), V(-1, 1, 0), V(-1, 1, 2), V(1, 1, 2)], [V(-1, 1, 0), V(-1, -1, 0), V(-1, -1, 2), V(-1, 1, 2)],
                  [V(-1, -1, 2), V(1, -1, 2), V(1, 1, 2), V(-1, 1, 2)]):
            f = b.add_face(q); f.attrs["mat"] = "Paret"; f.attrs["color"] = (0.85, 0.82, 0.76, 1.0)
        s.groups.append(Group(b, name="box"))
        p = Mesh()
        f = p.add_face([V(6, 6, 0.01), V(7, 6, 0.01), V(7, 7, 0.01), V(6, 7, 0.01)])       # somewhere a face wears the material
        f.attrs["mat"] = "Paving stone"; f.attrs["texture"] = {"path": chk_path, "sw": 0.5, "sh": 0.5}
        s.groups.append(Group(p, name="patch"))
        self.data = {"materials": {"Paving stone": {"type": "generic", "roughness": 0.9, "metallic": 0.0, "bump": 0.0, "glow": 0.0}}}
    def document_data(self, d=None): return json.loads(json.dumps(self.data)) if self.data else d
    def set_document_data(self, v): self.data = json.loads(json.dumps(v))
    def on_document_changed(self, fn): pass

app = App()
panel = P.StudioPanel(app)
panel.blender = lambda: object()
live = LiveSession(panel, argv_factory=lambda job, script: [BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)])
panel._live = live
images = []
live.image.connect(lambda p: images.append(str(p)))

def checker_pixels(path):
    im = QImage(path); reds = blues = 0
    for y in range(int(im.height() * 0.55), im.height(), 2):
        for x in range(0, im.width(), 2):
            c = im.pixelColor(x, y)
            reds += c.red() > c.blue() + 40
            blues += c.blue() > c.red() + 40
    return reds, blues

live.start()
ok(wait(lambda: len(images) >= 1 and live._ready and not live._busy), "the live view starts")
wait(lambda: live._done_key is not None and live._ready and not live._busy)
r0, b0 = checker_pixels(images[-1])
n = len(images)
i = panel.ground_material.findData("Paving stone")
ok(i >= 0, "the Ground group offers the material")
panel.ground_material.setCurrentIndex(i)
panel.ground_tile.setValue(0.5)
ok(wait(lambda: len(images) > n and live._ready and not live._busy and live._scene_key is not None
        and "Paving" in json.dumps(live._scene_key, default=str)), "choosing it rebuilds the live scene")
wait(lambda: live._done_key is not None and live._ready and not live._busy)
time.sleep(1.0)
r1, b1 = checker_pixels(images[-1])
ok(r1 + b1 > 150 and r1 + b1 > 5 * (r0 + b0 + 1), f"the live image shows the ground with the picture (checker pixels {r1}/{b1} against {r0}/{b0} before)")
job = json.load(open(live._work / "job.json"))
print("   job ground_material:", job["studio"].get("ground_material"))

# a change of the material's own settings reaches the ground too
n = len(images)
app.data["materials"]["Paving stone"]["metallic"] = 1.0
app.data["materials"]["Paving stone"]["roughness"] = 0.1
ok(wait(lambda: live._ready and live._kept_specs["Paving stone"]["metallic"] == 1.0 and len(images) > n), "a change of the material's settings is taken in")
wait(lambda: live._ready and not live._busy)
probe = os.path.join(tmp, "probe.py")
print("   (the settings are in the job:", json.load(open(live._work / "job.json"))["studio"]["materials"], ")")
print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
