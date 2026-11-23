"""The drawing's own fog (IngeTrazo's Styles › Fog) is the render's fog: the same axial smoothstep, in its colour; the panel's own fog
sliders wait while it is on. A row of boxes going away from the camera, rendered with a real Blender.
argv: <ingetrazo-src> <render-studio repo> <out dir> <blender.exe>"""
import json, math, os, subprocess, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, OUT = [os.path.abspath(a) for a in sys.argv[1:4]]
BLENDER = sys.argv[4]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QImage, QVector3D
from core.camera import OrbitCamera
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from render_studio import drawing_fog, panel as P

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

V = QVector3D
scene = Scene()
cam = OrbitCamera(); cam.target = V(0, 30, 3); cam.distance = 40; cam.yaw = 0.0; cam.pitch = 0.0
eye, fwd = cam.eye(), cam.forward()
fwd = V(fwd.x(), fwd.y(), 0.0).normalized()
right = V.crossProduct(fwd, V(0, 0, 1)).normalized()
DEPTHS = (4.0, 14.0, 30.0, 60.0)                               # metres along the camera's axis; the drawing's fog starts at 6 and ends at 26
centres = []
for i, d in enumerate(DEPTHS):                                  # a square wall at each depth, on a diagonal so that none hides another
    c = eye + fwd * d + right * (d * (-0.45 + 0.30 * i))
    c = V(c.x(), c.y(), 3.0)
    centres.append(c)
    hw = d * 0.12
    for sign in (1, -1):
        m = Mesh()
        q = [c + right * (-hw) + V(0, 0, -hw), c + right * hw + V(0, 0, -hw), c + right * hw + V(0, 0, hw), c + right * (-hw) + V(0, 0, hw)]
        f = m.add_face(q if sign > 0 else q[::-1]); f.attrs["color"] = (0.5, 0.5, 0.5, 1.0)
        scene.groups.append(Group(m, name=f"wall{i}{'a' if sign > 0 else 'b'}"))
cam.aspect = 480 / 270

ok(drawing_fog.of(scene) is None, "no fog in the drawing: nothing to follow")
st = scene.display_style
for k, v in (("fog_enabled", True), ("fog_distance", 6.0), ("fog_thickness", 20.0), ("fog_color", (1.0, 0.0, 0.0)), ("fog_use_background", False)):
    setattr(st, k, v)
f = drawing_fog.of(scene)
ok(f and f["start"] == 6.0 and f["thickness"] == 20.0 and f["color"][0] > 0.9 and f["color"][1] < 0.01, f"the drawing's fog is read ({f})")
st.fog_use_background = True
ok(drawing_fog.of(scene)["color"] is None, "«use the background» leaves the colour to the render's sky")
st.fog_use_background = False
blk = drawing_fog.apply({"fog": 0.7, "fog_start": 30.0}, scene)
ok(blk["fog"] == 0.0 and blk["fog_drawing"]["thickness"] == 20.0, "it replaces the render's own fog in the job")

def render(name, fog_on):
    st.fog_enabled = fog_on
    job, script = P.write_studio_job(scene, cam, Path(OUT) / name, "clear", {"fog": 0.0}, engine="eevee", quality=0, width=480, height=270)
    data = json.loads(job.read_text(encoding="utf-8"))
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)], capture_output=True, text=True, timeout=900)
    return QImage(data["output"]), r.stdout + r.stderr

clear, _ = render("fog_off", False)
fogged, log = render("fog_on", True)
ok("INGETRAZO drawing's fog" in log, "Blender says it made the drawing's fog")
M = cam.projection_matrix() * cam.view_matrix()
def pixel(c, w, h):
    v = M.map(QVector3D(c)); return int((v.x() * 0.5 + 0.5) * w), int((0.5 - v.y() * 0.5) * h)
def red_excess(img, c):
    x, y = pixel(c, img.width(), img.height()); col = img.pixelColor(x, y); return col.red() - (col.green() + col.blue()) / 2
gain = [red_excess(fogged, c) - red_excess(clear, c) for c in centres]
print("red gained by each wall (4, 14, 30, 60 m):", [round(g) for g in gain])
ok(abs(gain[0]) < 20, f"the nearest wall (4 m, before the fog starts at 6 m) is not tinted ({gain[0]:+.0f})")
ok(gain[1] > gain[0] + 15 and gain[2] > gain[1] + 15, f"the farther, the redder: the fog grows with the depth ({[round(g) for g in gain]})")
ok(gain[2] > 100 and gain[3] > 100, "past its end (26 m) a wall is the fog's colour")
print("FAILED: %s" % fails if fails else "ALL PASS")
sys.exit(1 if fails else 0)
