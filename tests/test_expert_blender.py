"""Expert mode: «Open in Blender…». Offline part: the button exports, writes the job with expert + blend, starts
Blender with its window (a stand-in program here) and says where the file is. Blender part: a REAL Blender
(background) builds the scene of that job, packs the pictures, saves the .blend and makes no picture; the saved
file has the model and its materials.
argv: <ingetrazo-src> <render-studio repo> <out dir> [<blender.exe>]"""
import json, math, os, subprocess, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, OUT = [os.path.abspath(a) for a in sys.argv[1:4]]
BLENDER = sys.argv[4] if len(sys.argv) > 4 else None
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage, QVector3D
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
qa.setOrganizationName("RenderStudioTest"); qa.setApplicationName("expert")
from core.camera import OrbitCamera
from core.materials import Material
from core.scene import Scene
from render_studio import panel as P
from render_studio.i18n import tr

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

out = Path(OUT); out.mkdir(parents=True, exist_ok=True)
pic = out / "brick.png"
img = QImage(16, 16, QImage.Format_RGB32); img.fill(QColor(180, 70, 50)); img.save(str(pic))
scene = Scene()
scene.materials["Brick"] = Material("Brick", texture={"path": str(pic), "sw": 2.0, "sh": 2.0})
def quad(pts, attrs):
    f = scene.mesh.add_face([QVector3D(*q) for q in pts]); f.attrs.update(attrs)
quad([(-30, -30, 0), (30, -30, 0), (30, 30, 0), (-30, 30, 0)], {"color": (0.5, 0.5, 0.5)})
quad([(-3, 0, 0), (3, 0, 0), (3, 0, 4), (-3, 0, 4)],
     {"mat": "Brick", "texture": {"path": str(pic), "sw": 2.0, "sh": 2.0, "rot": 0.0}})
cam = OrbitCamera(); cam.target = QVector3D(0, 0, 2); cam.distance = 12; cam.yaw = math.radians(-90); cam.pitch = 0.0

class VP:
    def __init__(self): self.camera = cam; self.scene = scene
    def update(self): pass
class App:
    def __init__(self): self.scene = scene; self.viewport = VP(); self.data = {}
    def document_data(self, d=None): return json.loads(json.dumps(self.data)) if self.data else d
    def set_document_data(self, v): self.data = json.loads(json.dumps(v))
    def on_document_changed(self, fn): pass

# ---- the button ---------------------------------------------------------------------------------
class Found:
    command = [os.environ.get("COMSPEC", "cmd.exe"), "/c", "exit"]      # a stand-in that starts and ends
panel = P.StudioPanel(App())
panel.blender = lambda: Found()
blend = panel.open_in_blender()
job = (blend.parent / "job.json") if blend else None
data = json.loads(job.read_text(encoding="utf-8")) if job and job.is_file() else {}
ok(blend is not None and blend.name == "scene.blend", f"the button prepared a job in its own folder ({blend})")
ok(data.get("expert") is True and data.get("blend") == str(blend), "the job says expert and where to save the .blend")
ok(tr("Opened in Blender. The scene is saved in {path}", path=str(blend)) == panel.status.text(), "the status says where the file is")
ok(panel._prep is None and panel._preparing is False, "the modal is closed and the panel is free again")
class Broken:
    command = [str(out / "no-such-blender.exe")]
panel.blender = lambda: Broken()
ok(panel.open_in_blender() is None and "Blender" in panel.status.text(), f"a Blender that does not start is said ({panel.status.text()})")
panel.blender = lambda: None
ok(panel.open_in_blender() is None, "without Blender: nothing")
ok(hasattr(panel.preview(), "expert_btn"), "the preview window has the button too")

# ---- a real Blender -----------------------------------------------------------------------------
if BLENDER:
    work = out / "expert"
    jobp, script = P.write_studio_job(scene, cam, work, "clear", {}, engine="eevee", quality=0, width=320, height=240,
                                      materials={"Brick": {"type": "generic", "roughness": 0.9}})
    d = json.loads(jobp.read_text(encoding="utf-8"))
    target = work / "scene.blend"
    d["expert"], d["blend"] = True, str(target)
    jobp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(jobp)],
                       capture_output=True, text=True, timeout=600)
    ok("INGETRAZO expert ready" in r.stdout, "Blender built the scene and says it is ready for the person")
    ok(target.is_file() and target.stat().st_size > 10000, f"the .blend was saved ({target.stat().st_size if target.is_file() else 0} bytes)")
    ok(not Path(d["output"]).exists(), "no picture was rendered")
    q = subprocess.run([BLENDER, "-b", str(target), "--python-expr",
                        "import bpy; print('OBJ', len([o for o in bpy.data.objects if o.type=='MESH'])); "
                        "print('MAT', len(bpy.data.materials)); print('CAM', bpy.context.scene.camera is not None); "
                        "print('PACKED', all(i.packed_file is not None for i in bpy.data.images if i.source=='FILE'))"],
                       capture_output=True, text=True, timeout=300)
    lines = {ln.split()[0]: ln.split()[1] for ln in q.stdout.splitlines()
             if len(ln.split()) > 1 and ln.split()[0] in ("OBJ", "MAT", "CAM", "PACKED")}
    ok(int(lines.get("OBJ", 0)) >= 1 and int(lines.get("MAT", 0)) >= 1, f"the file holds the model and its materials ({lines})")
    ok(lines.get("CAM") == "True", "...and the camera of the preview")
    ok(lines.get("PACKED") == "True", "...with its pictures packed inside")

    # ...and with its window (a window opens for a few seconds and closes by itself): the scene is built once
    # Blender's loop runs and its 3D view looks through the camera.
    probe = work / "probe.txt"
    if probe.exists():
        probe.unlink()
    d2 = dict(d); d2["blend"] = str(work / "gui.blend"); d2["expert_probe"] = str(probe)
    (work / "job_gui.json").write_text(json.dumps(d2, indent=2), encoding="utf-8")
    try:
        subprocess.run([BLENDER, "--python", str(script), "--", str(work / "job_gui.json")],
                       capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        pass
    got = probe.read_text(encoding="utf-8").strip() if probe.is_file() else "(nothing)"
    ok(got == "looking 1", f"with a window: the scene is built and the 3D view looks through the camera ({got})")
    ok((work / "gui.blend").is_file(), "...and the .blend is saved")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
