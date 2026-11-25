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
from PySide6.QtCore import QSettings                 # settings in a throwaway file, not the user's
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tmp)
qa.setOrganizationName("RenderStudioTest"); qa.setApplicationName("live")
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
        self.data = {}
    def document_data(self, d=None): return json.loads(json.dumps(self.data)) if self.data else d
    def set_document_data(self, v): self.data = json.loads(json.dumps(v))
    def on_document_changed(self, fn): pass
app = App()
panel = P.StudioPanel(app)
panel.blender = lambda: object()                     # "found"
fake = os.path.join(REPO, "tests", "fake_blender.py")
live = LiveSession(panel, argv_factory=lambda job, script: [sys.executable, fake, str(job)], poll_ms=20, rest_ms=60)
panel._live = live
live.image.connect(panel._live_image); live.state.connect(panel.status.setText)

panel.open_preview()
ok(wait(lambda: panel.window is not None and panel.window.isVisible() and panel.window.has_image()), "Open preview opens the window and the live view gives it a first draft")
ok(live.loads == 1 and any("studio=True serve=True" in l for l in log_lines()), "Blender was loaded once, with the look (studio block) and in serve mode")
renders = lambda: [l for l in log_lines() if l.startswith("render")]
ok(wait(lambda: any("samples=8" in l for l in renders())), "the draft follows (8 samples)")
first = renders()[:2]
ok(len(first) == 2 and "samples=1 width=480" in first[0] and "samples=8 width=960" in first[1],
   f"quick first (1 sample, half width), then the draft: {first}")
ok(panel.window.mode == "preview" and "draft" in panel.window.note.text() and panel.window.note.isVisible(), "the window says it is a draft")
job = json.load(open(live._work / "job.json"))
ok(job["serve"] is True and job["studio"]["clouds"] >= 0 and job["width"] == 960, "job: serve mode, the look's studio block, draft width")
ok(job["engine"] == "eevee" and job["studio"].get("live") is True, "the live job is a lightened EEVEE draft")

n0 = len([l for l in log_lines() if l.startswith("render")])
app.viewport.camera.yaw += 0.4
ok(wait(lambda: len([l for l in log_lines() if l.startswith("render")]) > n0), "moving the camera asks for a new image")
ok(live.loads == 1, "...without reloading the scene")

glb = live._work / "model.glb"
t_glb = glb.stat().st_mtime_ns
app.scene.version += 1                                                         # the model changed
ok(wait(lambda: live.loads == 2), "changing the model reloads the scene")
ok(live.starts == 1 and any(l.startswith("reload") for l in log_lines()), "...in the same Blender (no new start)")
ok(glb.stat().st_mtime_ns != t_glb, "...with the model exported again")
n1 = len([l for l in log_lines() if l.startswith("render")])
ok(wait(lambda: len([l for l in log_lines() if l.startswith("render")]) > n1), "and a new image comes")

t_glb = glb.stat().st_mtime_ns
panel.engine.setCurrentIndex(panel.engine.findData("cycles"))
panel.preset.setCurrentIndex(panel.preset.findData("night"))                    # the look changed
ok(wait(lambda: live.loads >= 3 and live._ready), "changing the look reloads the scene")
ok(live.starts == 1 and glb.stat().st_mtime_ns == t_glb, "...in the same Blender, without exporting the model again")
ok(json.load(open(live._work / "job.json"))["engine"] == "eevee", "...still EEVEE while Render is set to Cycles")
ok(wait(lambda: any("render" in l for l in log_lines()[-1:])), "and renders it")

# ---- Follow the camera: frames while it moves -------------------------------------------
ok(wait(lambda: live._ready and not live._busy and live._done_key is not None), "settled")
n2 = len(renders())
for i in range(40):                                  # a drag: the camera changes at every poll
    app.viewport.camera.yaw += 0.02
    t_end = time.time() + 0.025
    while time.time() < t_end:
        qa.processEvents(); time.sleep(0.003)
during = renders()[n2:]
ok(len([l for l in during if "width=320" in l]) >= 3, f"while the camera moves, small frames come ({len(during)} so far)")
ok(not any("samples=8" in l for l in during), "...and no draft while it moves")
ok(wait(lambda: any("samples=8" in l for l in renders()[n2:])), "when it stops: the quick image, then the draft")

# ---- Follow the camera off: the image keeps its camera ---------------------------------
ok(wait(lambda: live._ready and not live._busy and live._done_key == live._quick_key), "settled again")
panel.commands.follow_camera.setChecked(False)
kept_eye = str(live._frozen["eye"])
n3 = len(renders())
app.viewport.camera.yaw += 0.6
t_end = time.time() + 0.6
while time.time() < t_end:
    qa.processEvents(); time.sleep(0.01)
ok(all(kept_eye in l for l in renders()[n3:]), "Follow the camera off: moving the 3D view gives no image of it")
loads0 = live.loads
panel.preset.setCurrentIndex(panel.preset.findData("overcast"))
ok(wait(lambda: live.loads > loads0 and any("samples=8" in l for l in renders()[n3:])), "a change still renders...")
ok(all(kept_eye in l for l in renders()[n3:]), "...from the kept camera")
panel.commands.follow_camera.setChecked(True)
ok(wait(lambda: any(kept_eye not in l for l in renders()[n3:])), "on again: it follows the 3D view again")

# ---- Follow changes off: the live scene keeps its model and materials -------------------
ok(wait(lambda: live._ready and not live._busy), "ready")
panel.commands.follow_changes.setChecked(False)
loads1, t_glb = live.loads, glb.stat().st_mtime_ns
app.scene.version += 1
app.data = {**app.data, "materials": {"X": {"type": "grass", "grass_height": 0.2}}}
t_end = time.time() + 0.6
while time.time() < t_end:
    qa.processEvents(); time.sleep(0.01)
ok(live.loads == loads1, "Follow changes off: a model or material edit does not reload")
panel.preset.setCurrentIndex(panel.preset.findData("clear"))
ok(wait(lambda: live.loads > loads1 and live._ready), "the look still applies...")
jl = json.load(open(live._work / "job.json"))
ok(glb.stat().st_mtime_ns == t_glb and "X" not in (jl["studio"].get("materials") or {}),
   "...with the kept model (not exported) and the kept materials")
loads2 = live.loads
panel.commands.follow_changes.setChecked(True)
ok(wait(lambda: live.loads > loads2 and live._ready), "on again: the edits come in")
jl = json.load(open(live._work / "job.json"))
ok(glb.stat().st_mtime_ns != t_glb and "X" in (jl["studio"].get("materials") or {}), "...model exported, materials applied")
ok(live.starts == 1, "all in the same Blender")
ok(str(QSettings().value("render_studio/live_follow_changes")).lower() in ("true", "1"), "the switches are remembered")

# a final render stops the live view; the final picture stays on screen; Back to preview brings it back
panel._stop_live()
ok(not live.active and live._proc is None, "a final render stops the live Blender")
panel.window.set_mode("final")
ok(panel.window.bar_final.isVisibleTo(panel.window) and not panel.window.bar_preview.isVisibleTo(panel.window),
   "the final picture shows the retouch tools, not the preview's buttons")
panel.back_to_preview()
ok(wait(lambda: live.active and live._ready and live.starts == 2), "Back to preview brings the live view back (a new Blender)")
ok(panel.window.mode == "preview" and panel.window.bar_preview.isVisibleTo(panel.window), "...and the preview's buttons")
panel._stop_live(); panel._back_to_preview_if_open()
ok(wait(lambda: live.active), "a render that gave no picture to retouch resumes the live preview")

loads = live.loads
panel.window.close(); qa.processEvents()
ok(not live.active and live._proc is None, "closing the window stops the live view and closes Blender")
app.viewport.camera.yaw += 0.4; time.sleep(0.3); qa.processEvents()
ok(live.loads == loads, "nothing happens after it is off")
panel.open_preview()
ok(wait(lambda: live.active and live._ready), "Open preview brings it back")
panel.window.close(); qa.processEvents()

# no Blender: it says so, and no window opens
p2 = P.StudioPanel(app); p2.blender = lambda: None
ok(p2.open_preview() is None and p2.window is None and "Blender was not found" in p2.status.text(),
   "without Blender: a message, and no window")
ok(not p2.commands.preview.isEnabled(), "...and Open preview is off")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
