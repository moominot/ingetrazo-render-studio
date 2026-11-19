"""The live view, with a stand-in for Blender (same protocol). argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, json, math, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
tmp = tempfile.mkdtemp()
LOG = os.path.join(tmp, "blender.log"); os.environ["FAKE_BLENDER_LOG"] = LOG
os.environ["XDG_CACHE_HOME"] = os.path.join(tmp, "cache")
from pathlib import Path
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QVector3D
from core.scene import Scene
from core.mesh import Mesh
from core.group import Group
from core.camera import OrbitCamera
from render_studio import panel as P
from render_studio.live import LiveSession

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)
def wait(cond, secs=15.0):
    t0 = time.time()
    while not cond() and time.time() - t0 < secs:
        qa.processEvents(); time.sleep(0.01)
    return cond()
def n_first_check(): return False
def log_lines(): return open(LOG).read().splitlines() if os.path.exists(LOG) else []

class VP:
    def __init__(self): self.camera = OrbitCamera(); self.camera.target = QVector3D(0, 0, 0.5); self.camera.distance = 6
    def width(self): return 1600
    def height(self): return 900
    def update(self): pass
class App:
    def __init__(self):
        self.scene = Scene(); self.viewport = VP()
        m = Mesh(); P_ = QVector3D
        for q in ([P_(0,0,0),P_(1,0,0),P_(1,1,0),P_(0,1,0)], [P_(0,0,1),P_(1,0,1),P_(1,1,1),P_(0,1,1)]): m.add_face(q)
        self.scene.groups.append(Group(m, name="box"))
    def document_data(self, d=None): return d
    def set_document_data(self, v): pass
    def on_document_changed(self, fn): pass
app = App()
panel = P.StudioPanel(app)
panel.blender = lambda: object()                     # "found"
fake = os.path.join(REPO, "tests", "fake_blender.py")
live = LiveSession(panel, argv_factory=lambda job, script: [sys.executable, fake, str(job)], poll_ms=20, rest_ms=60)
panel._live = live
live.image.connect(panel._live_image); live.state.connect(panel.status.setText)

panel.live_box.setChecked(True)
ok(wait(lambda: panel.window is not None and panel.window.isVisible() and panel.window.original is not None), "ticking Live view opens the image window with a first draft")
ok(live.loads == 1 and any("studio=True serve=True" in l for l in log_lines()), "Blender was loaded once, with the look (studio block) and in serve mode")
ok(any(l.startswith("render") and "samples=8" in l for l in log_lines()) or n_first_check(), "draft samples (EEVEE sync: 8)")
ok("Draft" in panel.window.note.text() and panel.window.note.isVisible(), "the window says it is a draft")
job = json.load(open(live._work / "job.json"))
ok(job["serve"] is True and job["studio"]["clouds"] >= 0 and job["width"] == 960, "job: serve mode, the look's studio block, draft width")

n0 = len([l for l in log_lines() if l.startswith("render")])
app.viewport.camera.yaw += 0.4
ok(wait(lambda: len([l for l in log_lines() if l.startswith("render")]) > n0), "moving the camera asks for a new image")
ok(live.loads == 1, "...without reloading the scene")

app.scene.version += 1                                                         # the model changed
ok(wait(lambda: live.loads == 2), "changing the model reloads the scene")
n1 = len([l for l in log_lines() if l.startswith("render")])
ok(wait(lambda: len([l for l in log_lines() if l.startswith("render")]) > n1), "and a new image comes")

panel.preset.setCurrentIndex(panel.preset.findData("night"))                    # the look changed
ok(wait(lambda: live.loads == 3), "changing the look reloads the scene")
ok(wait(lambda: any("render" in l for l in log_lines()[-1:])), "and renders it")

# a final render pauses the live view; the final image stays on screen
panel._pause_live()
ok(not live.active and live._proc is None, "a final render stops the live Blender")
panel._resume_live(keep_final=True)
ok(not panel.live_box.isChecked() and not live.active, "after the final render the live view stays off (it would draw over the final image)")
panel.live_box.setChecked(True)
ok(wait(lambda: live.active and live.loads == 4 and live._ready), "ticking it again brings it back")
panel._pause_live(); panel._resume_live(keep_final=False)
ok(wait(lambda: live.active), "a render that did not start resumes the live view")

loads = live.loads
panel.live_box.setChecked(False); qa.processEvents()
ok(not live.active and live._proc is None, "unticking stops it and closes Blender")
app.viewport.camera.yaw += 0.4; time.sleep(0.3); qa.processEvents()
ok(live.loads == loads, "nothing happens after it is off")

# no Blender: it says so and unticks
p2 = P.StudioPanel(app); p2.blender = lambda: None
p2.live_box.setChecked(True)
ok(not p2.live_box.isChecked() and "Blender was not found" in p2.status.text(), "without Blender: a message, and the box unticks")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
