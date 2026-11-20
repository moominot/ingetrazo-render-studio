"""Glass in the live preview (the draft EEVEE has no ray tracing) against the final render: a pane of
glass in front of a red wall must let the wall show in both.
argv: <ingetrazo-src> <render-studio repo> <out dir> <blender.exe>"""
import copy, json, math, os, subprocess, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, OUT = [os.path.abspath(a) for a in sys.argv[1:4]]
BLENDER = sys.argv[4] if len(sys.argv) > 4 else None
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QImage, QVector3D
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
scene.materials["Vidre"] = Material("Vidre", color=(0.8, 0.9, 0.95), opacity=0.25)
def quad(pts, attrs):
    f = scene.mesh.add_face([QVector3D(*q) for q in pts]); f.attrs.update(attrs)
quad([(-40, -40, 0), (40, -40, 0), (40, 40, 0), (-40, 40, 0)], {"color": (0.5, 0.5, 0.5)})
quad([(-12, 4, 0), (12, 4, 0), (12, 4, 14), (-12, 4, 14)], {"color": (0.85, 0.08, 0.08)})            # the red wall
quad([(-3, 0, 0), (3, 0, 0), (3, 0, 5), (-3, 0, 5)], {"mat": "Vidre", "color": (0.8, 0.9, 0.95), "opacity": 0.25})
cam = OrbitCamera(); cam.target = QVector3D(0, 0, 2.5); cam.distance = 14
cam.yaw = math.radians(-90); cam.pitch = math.radians(0)

def render(name, live, specs=None, overrides=None):
    d = out / name
    job, script = P.write_studio_job(scene, cam, d, "clear", {}, engine="eevee", quality=0, width=400, height=300,
                                     materials=copy.deepcopy(specs or {}), live=live)
    data = json.loads(job.read_text(encoding="utf-8"))
    data["studio"]["auto_exposure"] = False; data["exposure"] = -0.4
    if overrides:
        data["studio"]["eevee_overrides"] = overrides
    job.write_text(json.dumps(data, indent=2), encoding="utf-8")
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)],
                       capture_output=True, text=True, timeout=600)
    return QImage(data["output"]), r.stdout + r.stderr

def through(img):
    """How red the middle of the pane is: red / (green + blue + 1)."""
    r = g = b = n = 0
    for y in range(120, 180, 4):
        for x in range(170, 230, 4):
            c = img.pixelColor(x, y); r += c.red(); g += c.green(); b += c.blue(); n += 1
    return r / n, g / n, b / n

final, _ = render("final", False)
live, _ = render("live", True)
clear, _ = render("clear", False, {"Vidre": {"type": "glass", "roughness": 0.0, "transparency": 0.95}})
milky, _ = render("milky", False, {"Vidre": {"type": "glass", "roughness": 0.0, "transparency": 0.4}})
redness = lambda img: through(img)[0] / (sum(through(img)) + 1)
for name, img in (("the final render", final), ("the live preview", live), ("the glass at 95 % transparency", clear)):
    r, g, b = through(img)
    print(f"      {name}: mean colour through the pane ({r:.0f},{g:.0f},{b:.0f})")
    ok(r > 1.25 * g and r > 1.25 * b, f"{name}: the red wall shows through the glass")
ok(redness(clear) > redness(milky) + 0.05, f"the editor's Transparency decides how much: 95 % shows more of the wall than 40 % ({redness(clear):.2f} against {redness(milky):.2f})")
ok(abs(redness(final) - redness(live)) < 0.05, "the live preview and the final render show the glass alike")
print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
