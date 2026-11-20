"""The opacity map in the render, by a REAL Blender: two walls side by side, one whose opacity map is
all black (see-through) and one all white (solid), in front of a green hill.
Checks: the transparent wall shows the hill, the other stays; with a white map on both, both show.
argv: <ingetrazo-src> <render-studio repo> <out dir> <blender.exe>"""
import json, math, os, subprocess, sys
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
def grey(name, v):
    img = QImage(16, 16, QImage.Format_RGB32); img.fill(QColor(v, v, v)); p = out / name; img.save(str(p)); return str(p)
black, white = grey("black.png", 0), grey("white.png", 255)

scene = Scene()
def quad(pts, color, mat=None):
    f = scene.mesh.add_face([QVector3D(*p) for p in pts]); f.attrs["color"] = color
    if mat: f.attrs["mat"] = mat
scene.materials["Ghost"] = Material("Ghost", color=(0.1, 0.1, 0.9))     # blue: the see-through wall
scene.materials["Solid"] = Material("Solid", color=(0.9, 0.1, 0.1))     # red: the solid one
quad([(-30, -30, 0), (30, -30, 0), (30, 30, 0), (-30, 30, 0)], (0.45, 0.45, 0.4))
quad([(-14, 3, 0), (14, 3, 0), (14, 3, 9), (-14, 3, 9)], (0.1, 0.8, 0.1))                    # the green hill
quad([(-3.2, 0, 0), (-0.6, 0, 0), (-0.6, 0, 2.4), (-3.2, 0, 2.4)], (0.1, 0.1, 0.9), "Ghost")
quad([(0.6, 0, 0), (3.2, 0, 0), (3.2, 0, 2.4), (0.6, 0, 2.4)], (0.9, 0.1, 0.1), "Solid")
cam = OrbitCamera(); cam.target = QVector3D(0, 0, 1.2); cam.distance = 11
cam.yaw = math.radians(-90); cam.pitch = math.radians(2)


def render(name, ghost_map):
    specs = {"Ghost": {"type": "generic", "maps": {"opacity": {"source": "file", "path": ghost_map, "size": 1.0}}},
             "Solid": {"type": "generic", "maps": {"opacity": {"source": "file", "path": white, "size": 1.0}}}}
    job, script = P.write_studio_job(scene, cam, out / name, "clear", {}, engine="eevee", quality=0,
                                     width=400, height=300, materials=specs)
    data = json.loads(job.read_text(encoding="utf-8"))
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)],
                       capture_output=True, text=True, timeout=900)
    return QImage(data["output"]), r.stdout + r.stderr


def count(img, y=150):
    red = blue = 0
    for x in range(img.width()):
        c = img.pixelColor(x, y); r, g, b = c.red(), c.green(), c.blue()
        if r > 1.6 * max(g, b) and r > 60: red += 1
        elif b > 1.6 * max(r, g) and b > 60: blue += 1
    return red, blue

img, log = render("ghost", black)
ok(not img.isNull(), "the render is written")
red, blue = count(img)
ok(red > 30, f"the solid wall (white map) shows ({red} red pixels)")
ok(blue < 6, f"the wall with the black map is see-through: none of it shows ({blue} blue pixels)")

img2, log2 = render("both_white", white)
red2, blue2 = count(img2)
ok(blue2 > 30 and red2 > 30, f"control: with a white map on both, both show ({red2} red, {blue2} blue)")
if fails:
    print(log[-2000:])
print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
