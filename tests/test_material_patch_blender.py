"""A change of some materials is made in place in the live Blender (no new scene, no model import, no
exposure meter), and the picture is the one a scene built from scratch gives. With a REAL Blender,
in serve mode, through the panel's own job writer.

Each change is sent as {"update": job}; then an image is asked from the same camera and compared with the
picture of a fresh Blender that builds the same job from scratch. A change that moves the light (a glowing
or see-through material) or the look builds the scene again, as before: the picture is still the same.

argv: <ingetrazo-src> <render-studio repo> <out dir> <blender.exe>"""
import copy, json, math, os, queue, subprocess, sys, threading, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, OUT = [os.path.abspath(a) for a in sys.argv[1:4]]
BLENDER = sys.argv[4] if len(sys.argv) > 4 else None
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QColor, QImage, QVector3D
from core.camera import OrbitCamera
from core.materials import Material
from core.scene import Scene
from render_studio import panel as P

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)
if not BLENDER:
    print("(no Blender given)"); sys.exit(0)

out = Path(OUT); out.mkdir(parents=True, exist_ok=True)
scene = Scene()
def quad(pts, color, mat=None):
    f = scene.mesh.add_face([QVector3D(*p) for p in pts]); f.attrs["color"] = color
    if mat: f.attrs["mat"] = mat
NAMES = {"Wall": (0.8, 0.8, 0.72), "Steel": (0.55, 0.57, 0.6), "Pool": (0.1, 0.35, 0.6), "Lamp": (1.0, 0.9, 0.5),
         "Door": (0.45, 0.28, 0.15)}
for n, c in NAMES.items():
    scene.materials[n] = Material(n, color=c)
quad([(-30, -30, 0), (30, -30, 0), (30, 30, 0), (-30, 30, 0)], (0.45, 0.45, 0.4))
quad([(-5, 2, 0), (-1.6, 2, 0), (-1.6, 2, 3), (-5, 2, 3)], NAMES["Wall"], "Wall")
quad([(-1.4, 2, 0), (1.4, 2, 0), (1.4, 2, 3), (-1.4, 2, 3)], NAMES["Steel"], "Steel")
quad([(1.6, 2, 0), (5, 2, 0), (5, 2, 3), (1.6, 2, 3)], NAMES["Door"], "Door")
quad([(-4, -2.5, 0.02), (4, -2.5, 0.02), (4, 0.5, 0.02), (-4, 0.5, 0.02)], NAMES["Pool"], "Pool")
quad([(-0.4, 1.99, 2.2), (0.4, 1.99, 2.2), (0.4, 1.99, 2.8), (-0.4, 1.99, 2.8)], NAMES["Lamp"], "Lamp")
cam = OrbitCamera(); cam.target = QVector3D(0, 1, 1.4); cam.distance = 13
cam.yaw = math.radians(-90); cam.pitch = math.radians(14)

work = out / "live"
def spec(**kw):
    return {"type": "generic", **kw}
BASE = {"Wall": spec(roughness=0.9), "Steel": spec(roughness=0.3, metallic=1.0)}
black = out / "black.png"
img = QImage(8, 8, QImage.Format_RGB32); img.fill(QColor(0, 0, 0)); img.save(str(black))

def write_job(materials, preset="clear", reuse=False, dest=None):
    job, script = P.write_studio_job(scene, cam, dest or work, preset, {}, engine="eevee", quality=0, width=320, height=200,
                                     materials=copy.deepcopy(materials), live=True, serve=True, reuse_model=reuse)
    data = json.loads(job.read_text(encoding="utf-8"))
    data["studio"]["auto_exposure"] = False; data["exposure"] = -0.6      # the same exposure on both sides
    job.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return job, script, data

class Live:
    def __init__(self, job, script):
        self.p = subprocess.Popen([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  encoding="utf-8", errors="replace", bufsize=1)
        self.q = queue.Queue(); self.lines = []
        threading.Thread(target=self._read, daemon=True).start()
        self.first = self.wait("INGETRAZO ready", 300)
    def _read(self):
        for ln in self.p.stdout:
            self.lines.append(ln.rstrip()); self.q.put(ln.rstrip())
    def wait(self, token, timeout=300):
        t0 = time.time(); got = []
        while time.time() - t0 < timeout:
            try: ln = self.q.get(timeout=0.5)
            except queue.Empty: continue
            got.append(ln)
            if token in ln: return got
        raise TimeoutError(token + "\n" + "\n".join(self.lines[-15:]))
    def send(self, obj): self.p.stdin.write(json.dumps(obj) + "\n"); self.p.stdin.flush()
    def update(self, job, key="update"):
        t = time.time(); self.send({key: str(job)}); got = self.wait("INGETRAZO ready"); return got, time.time() - t
    def image(self, data, name):
        o = out / name
        self.send({"camera": data["camera"], "output": str(o), "width": 320, "height": 200, "samples": 16})
        self.wait("INGETRAZO done"); return QImage(str(o))
    def close(self):
        try: self.send({"quit": True})
        except Exception: pass
        try: self.p.wait(timeout=20)
        except Exception: self.p.kill()

def fresh(materials, name, preset="clear"):
    d = out / ("fresh_" + name)
    job, script, data = write_job(materials, preset, dest=d)
    data["serve"] = False; data["output"] = str(d / "render.png")
    job.write_text(json.dumps(data, indent=2), encoding="utf-8")
    subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)],
                   capture_output=True, text=True, timeout=600)
    return QImage(data["output"])

def diff(a, b):
    if a.isNull() or b.isNull() or a.size() != b.size(): return 999.0
    tot = n = 0
    for y in range(0, a.height(), 2):
        for x in range(0, a.width(), 2):
            ca, cb = a.pixelColor(x, y), b.pixelColor(x, y)
            tot += abs(ca.red() - cb.red()) + abs(ca.green() - cb.green()) + abs(ca.blue() - cb.blue()); n += 3
    return tot / n

job, script, data = write_job(BASE)
live = Live(job, script)
ok(any("imported" in l for l in live.first), "the scene is built once")
OPAQ = {"type": "generic", "roughness": 0.5, "maps": {"opacity": {"source": "file", "path": str(black), "size": 1.0}}}
STEEL = spec(roughness=0.7, metallic=1.0)
WALL2 = spec(roughness=0.15, metallic=0.9)              # a wall that shows its finish (a matt one barely changes)
try:
    CASES = [
        ("a slider: the wall becomes a polished metal", dict(BASE, Wall=WALL2), True),
        ("a slider on a metal: roughness again", dict(BASE, Wall=WALL2, Steel=STEEL), True),
        ("a coat and a metal value on the door",
         dict(BASE, Wall=WALL2, Steel=STEEL, Door=spec(roughness=0.2, coat=0.6, metallic=0.4)), True),
        ("an opacity map on the door (black = transparent)", dict(BASE, Wall=WALL2, Steel=STEEL, Door=OPAQ), True),
        ("the wall's settings removed (back to what the importer and the finishes made)", dict(Steel=STEEL, Door=OPAQ), True),
        ("a lamp that glows (moves the light: the scene is built again)",
         dict(Steel=STEEL, Lamp={"type": "glow", "glow": 8.0, "roughness": 0.5}), False),
    ]
    img_before = live.image(data, "live_before.png")
    for k, (label, mats, patchable) in enumerate(CASES):
        job, script, data = write_job(mats, reuse=True)
        got, secs = live.update(job)
        text = "\n".join(got)
        was_patch = "INGETRAZO patch" in text
        rebuilt = "INGETRAZO imported" in text
        ok(was_patch == patchable and rebuilt != patchable,
           f"{label}: {'changed in place' if was_patch else 'scene built again'} ({secs:.2f} s)")
        print("      ", next((l for l in got if "INGETRAZO patch" in l), "(no patch line)")[:110], flush=True)
        img_live = live.image(data, f"live_{k}.png")
        img_new = fresh(mats, f"c{k}")
        d = diff(img_live, img_new)
        ok(d < 1.5, f"...and the picture is the one of a scene built from scratch (mean difference {d:.2f}/255)")
        moved = diff(img_before, img_new)
        ok(moved > 0.2, f"...and the change is visible: the picture before was {moved:.2f}/255 away from it")
        img_before = img_live
    got, secs = live.update(job)
    ok("INGETRAZO patch 0 materials" in "\n".join(got), f"a job with nothing changed changes no material ({secs:.1f} s)")
finally:
    live.close()
print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
