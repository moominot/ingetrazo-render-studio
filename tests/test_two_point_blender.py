"""Two-point perspective in the render, in a REAL Blender: the picture of a red block must fall where IngeTrazo's own camera puts it
(its eight corners projected with the 3D view's matrices), with its upright edges upright; the same for an ordinary view and for a
shifted frame.
argv: <ingetrazo-src> <render-studio repo> <out dir> <blender.exe>"""
import json, math, os, subprocess, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, OUT = [os.path.abspath(a) for a in sys.argv[1:4]]
BLENDER = sys.argv[4]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QImage, QVector3D, QVector4D
from core.camera import OrbitCamera
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from render_studio import panel as P, view_camera

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

W, H = 480, 270
V = QVector3D
scene = Scene()
m = Mesh()
x0, y0, z0, x1, y1, z1 = 0, 0, 0, 3, 3, 8
corners = [V(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
for q in ([V(x0,y0,z0),V(x1,y0,z0),V(x1,y0,z1),V(x0,y0,z1)], [V(x1,y0,z0),V(x1,y1,z0),V(x1,y1,z1),V(x1,y0,z1)],
          [V(x1,y1,z0),V(x0,y1,z0),V(x0,y1,z1),V(x1,y1,z1)], [V(x0,y1,z0),V(x0,y0,z0),V(x0,y0,z1),V(x0,y1,z1)],
          [V(x0,y0,z1),V(x1,y0,z1),V(x1,y1,z1),V(x0,y1,z1)], [V(x0,y1,z0),V(x1,y1,z0),V(x1,y0,z0),V(x0,y0,z0)]):
    m.add_face(q).attrs["color"] = (0.8, 0.05, 0.03, 1.0)
scene.groups.append(Group(m, name="block"))

def camera(two_point, **extra):
    cam = OrbitCamera(); cam.target = V(1.5, 1.5, 3); cam.distance = 26
    cam.yaw = math.radians(-55); cam.pitch = math.radians(30); cam.aspect = W / H
    cam.two_point = two_point
    for k, v in extra.items():
        setattr(cam, k, v)
    return cam

def expected(cam):
    """The block's bounding box in pixels, by IngeTrazo's own matrices."""
    mvp = cam.projection_matrix() * cam.view_matrix()
    xs, ys = [], []
    for c in corners:
        p = mvp.map(QVector4D(c, 1.0))
        xs.append((p.x() / p.w() + 1) / 2 * W); ys.append((1 - p.y() / p.w()) / 2 * H)
    return min(xs), min(ys), max(xs), max(ys)

def render(name, cam):
    job, script = P.write_studio_job(scene, cam, Path(OUT) / name, "clear", {}, engine="eevee", quality=0, width=W, height=H,
                                     ground=False, flat={"color": [1.0, 1.0, 1.0]}, ground_shadow=False)
    data = json.loads(job.read_text(encoding="utf-8"))
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)], capture_output=True, text=True, timeout=900)
    img = QImage(data["output"])
    if img.isNull():
        print((r.stdout + r.stderr)[-3000:])
    return img, data

def red_pixels(img):
    out = []
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.red() > c.green() + 40:
                out.append((x, y))
    return out

for name, cam in (("normal", camera(False)), ("two_point", camera(True)),
                  ("two_point_panned", camera(True, pan_shift_x=0.15, pan_shift_y=-0.08))):
    img, data = render(name, cam)
    ok(not img.isNull(), f"{name}: a picture")
    if img.isNull():
        continue
    px = red_pixels(img)
    got = (min(x for x, _ in px), min(y for _, y in px), max(x for x, _ in px) + 1, max(y for _, y in px) + 1)
    want = expected(cam)
    ok(all(abs(a - b) <= 2.5 for a, b in zip(got, want)),
       f"{name}: the block falls where the 3D view puts it (render {[round(v) for v in got]}, view {[round(v) for v in want]})")
    # the leftmost upright edge: its column at a quarter and at three quarters of its height
    left = {}
    for x, y in px:
        left[y] = min(x, left.get(y, 10**6))
    rows = sorted(left)
    xmin = min(left.values())
    edge = [y for y in rows if left[y] <= xmin + 1]
    if name.startswith("two_point"):
        ok(data["camera"].get("frame_shift") and data["camera"]["up"] == [0.0, 0.0, 1.0], f"{name}: the job says level and shifted ({data['camera'].get('frame_shift')})")
        ok(len(edge) > 0.4 * len(rows), f"{name}: the upright edge is upright ({len(edge)} of {len(rows)} rows on one column)")
    else:
        ok("frame_shift" not in data["camera"] and len(edge) < 0.4 * len(rows), f"{name}: an ordinary view stays as it was, its edge leaning ({len(edge)} of {len(rows)})")

a, b = camera(False), camera(True)
ok(view_camera.camera_key(a) != view_camera.camera_key(b), "the live view notices two-point being switched on")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
