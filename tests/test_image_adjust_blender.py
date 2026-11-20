"""The picture adjustments in the render, by a REAL Blender: a wall with a picture whose left half is black
and whose right half is red, seen from the front (exposure fixed). Each adjustment is checked on the colours
of the two halves: hue turns the red to green, a flat colour replaces the picture, a green tint takes the red
away, brightness darkens, rotation by 180 degrees swaps the halves.

argv: <ingetrazo-src> <render-studio repo> <out dir> <blender.exe>"""
import copy, json, math, os, subprocess, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, OUT = [os.path.abspath(a) for a in sys.argv[1:4]]
BLENDER = sys.argv[4] if len(sys.argv) > 4 else None
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QColor, QImage, QPainter, QVector3D
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
pic = out / "halves.png"
img = QImage(32, 32, QImage.Format_RGB32); img.fill(QColor(0, 0, 0))
p = QPainter(img); p.fillRect(16, 0, 16, 32, QColor(230, 40, 40)); p.end(); img.save(str(pic))

scene = Scene()
scene.materials["Halves"] = Material("Halves", texture={"path": str(pic), "sw": 6.0, "sh": 6.0})
def quad(pts, attrs):
    f = scene.mesh.add_face([QVector3D(*q) for q in pts]); f.attrs.update(attrs)
quad([(-40, -40, 0), (40, -40, 0), (40, 40, 0), (-40, 40, 0)], {"color": (0.5, 0.5, 0.5)})
quad([(-12, 4, 0), (12, 4, 0), (12, 4, 14), (-12, 4, 14)], {"color": (0.5, 0.5, 0.5)})             # a grey hill behind
quad([(-3, 0, 0), (3, 0, 0), (3, 0, 6), (-3, 0, 6)],
     {"mat": "Halves", "texture": {"path": str(pic), "sw": 6.0, "sh": 6.0, "rot": 0.0}})
cam = OrbitCamera(); cam.target = QVector3D(0, 0, 3); cam.distance = 14
cam.yaw = math.radians(-90); cam.pitch = math.radians(0)


def render(name, image=None):
    spec = {"Halves": {"type": "generic", "roughness": 0.9}}
    if image:
        spec["Halves"]["image"] = image
    d = out / name
    job, script = P.write_studio_job(scene, cam, d, "clear", {}, engine="eevee", quality=0, width=400, height=300,
                                     materials=copy.deepcopy(spec))
    data = json.loads(job.read_text(encoding="utf-8"))
    data["studio"]["auto_exposure"] = False; data["exposure"] = -0.4
    job.write_text(json.dumps(data, indent=2), encoding="utf-8")
    subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)],
                   capture_output=True, text=True, timeout=600)
    return QImage(data["output"])


def halves(img):
    """The mean colour of the left and of the right half of the wall (the middle of the picture)."""
    def mean(x0, x1):
        r = g = b = n = 0
        for y in range(110, 190, 4):
            for x in range(x0, x1, 3):
                c = img.pixelColor(x, y); r += c.red(); g += c.green(); b += c.blue(); n += 1
        return r / n, g / n, b / n
    return mean(140, 192), mean(208, 260)


base = render("base")
L0, R0 = halves(base)
RED = 0 if L0[0] > R0[0] else 1                   # which half of the wall shows the red (the view may mirror the picture)
DARK = 1 - RED
side = lambda img, k: halves(img)[k]
ok(side(base, RED)[0] > 1.5 * side(base, RED)[1] and sum(side(base, DARK)) < 120,
   f"the picture as it is: one half red {tuple(round(c) for c in side(base, RED))}, the other dark {tuple(round(c) for c in side(base, DARK))}")

r, g, b = side(render("hue", {"hue": 120}), RED)
ok(g > 1.5 * r and g > 1.5 * b, f"hue +120 degrees: the red half turns green ({r:.0f},{g:.0f},{b:.0f})")

(lr, lg, lb), (rr, rg, rb) = halves(render("flat", {"flat": [0.1, 0.2, 0.9]}))
ok(lb > 1.5 * lr and rb > 1.5 * rr and abs(lb - rb) < 0.25 * max(lb, rb), f"a flat colour: both halves blue ({lr:.0f},{lg:.0f},{lb:.0f}) ({rr:.0f},{rg:.0f},{rb:.0f})")

r, g, b = side(render("tint", {"tint": [0.0, 1.0, 0.0], "tint_strength": 1.0}), RED)
ok(r < 0.25 * 230 and g < 60, f"a green tint at 100 % takes the red away ({r:.0f},{g:.0f},{b:.0f})")

r0 = side(base, RED)[0]
r = side(render("dark", {"brightness": -0.7}), RED)[0]
ok(r < 0.6 * r0, f"brightness -70 %: darker ({r:.0f} against {r0:.0f})")

rot = render("rot", {"rotation": 180})
ok(side(rot, DARK)[0] > 1.5 * side(rot, DARK)[1] and sum(side(rot, RED)) < 120,
   f"rotation 180 degrees: the halves are swapped (the red is now on the other side)")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
