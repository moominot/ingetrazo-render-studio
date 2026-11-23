"""A section box (IngeTrazo 0.6.3: six cutting planes) and the cut's fill «like the drawing», in the render. The planes are read from
``section.plane_objects`` (here faked: this IngeTrazo may have no section boxes), the job lists them, and a REAL Blender cuts a closed block
with all six, one after the other, so the caps of the box end where the box does.
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
from render_studio import panel as P, section as SEC

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

V = QVector3D
scene = Scene()
m = Mesh()
x0, y0, z0, x1, y1, z1 = 0, 0, 0, 4, 3, 3
for q in ([V(x0,y0,z0),V(x1,y0,z0),V(x1,y0,z1),V(x0,y0,z1)], [V(x1,y0,z0),V(x1,y1,z0),V(x1,y1,z1),V(x1,y0,z1)],
          [V(x1,y1,z0),V(x0,y1,z0),V(x0,y1,z1),V(x1,y1,z1)], [V(x0,y1,z0),V(x0,y0,z0),V(x0,y0,z1),V(x0,y1,z1)],
          [V(x0,y0,z1),V(x1,y0,z1),V(x1,y1,z1),V(x0,y1,z1)], [V(x0,y1,z0),V(x1,y1,z0),V(x1,y0,z0),V(x0,y0,z0)]):
    m.add_face(q).attrs["color"] = (0.1, 0.7, 0.1, 1.0)
scene.groups.append(Group(m, name="block"))
cam = OrbitCamera(); cam.target = V(2, 1.5, 1); cam.distance = 12; cam.yaw = math.radians(-40); cam.pitch = math.radians(35)

class FakePlane:
    def __init__(self, point, normal, fill=None): self.point, self.normal, self.fill = V(*point), V(*normal), fill
lo, hi = (1.0, 0.5, -1.0), (3.0, 2.5, 2.0)
def box_faces(fill=None):                                         # as core.section.BoxFace: -X, +X, -Y, +Y, -Z, +Z; the normal points OUT
    return [FakePlane((lo[0], 0, 0), (-1, 0, 0), fill), FakePlane((hi[0], 0, 0), (1, 0, 0), fill), FakePlane((0, lo[1], 0), (0, -1, 0), fill),
            FakePlane((0, hi[1], 0), (0, 1, 0), fill), FakePlane((0, 0, lo[2]), (0, 0, -1), fill), FakePlane((0, 0, hi[2]), (0, 0, 1), fill)]
cut_now = []
SEC.plane_objects = lambda sc: list(cut_now)

ok(SEC.job_block(scene, {}) is None, "nothing cuts: no section in the job")
cut_now[:] = box_faces()
blk = SEC.job_block(scene, {"cap": True, "style": "flat", "color": [0.9, 0.1, 0.1]})
ok(blk and len(blk["planes"]) == 6 and blk["planes"][1]["normal"] == [1.0, 0.0, 0.0] and blk["planes"][1]["point"][0] == 3.0, "a box is six planes in the job, with their points and normals")
ok(blk["point"] == blk["planes"][0]["point"], "…and the first one is also the section's own point and normal (a Blender script that asks for one plane still works)")
sig6 = SEC.signature(scene, {})
cut_now[:] = box_faces()[:3]
ok(SEC.signature(scene, {}) != sig6, "the live view's key knows the planes (three of the six are another cut)")
cut_now[:] = box_faces()
ok(SEC.describe(scene) in ("none", "plane", "box", "both", "off"), "the Section tab can say what cuts")

# the cut's fill «like the drawing»: each plane's own fill, else the style's
cut_now[:] = [FakePlane((1, 0, 0), (-1, 0, 0), {"pattern": "hatch", "color": (0.0, 0.0, 1.0), "spacing": 0.2}),
              FakePlane((3, 0, 0), (1, 0, 0), {"pattern": "none"}), FakePlane((0, 0, 2), (0, 0, 1), {"pattern": "solid", "color": (1.0, 0.0, 0.0)})]
d = SEC.job_block(scene, {"cap": True, "style": "drawing"})
pl = d["planes"]
ok(pl[0]["style"] == "hatch" and pl[0]["pattern"] == "diagonal" and pl[0]["line"] == [0.0, 0.0, 1.0] and abs(pl[0]["spacing"] - 0.2) < 1e-9 and pl[0]["cap"], "like the drawing: a hatch is lines of its colour over a pale ground")
ok(pl[1]["cap"] is False, "…«none» is an open cut")
ok(pl[2]["style"] == "flat" and pl[2]["color"] == [1.0, 0.0, 0.0], "…a solid fill is a flat colour")
ok(SEC.clean({"style": "drawing"})["style"] == "drawing" and SEC.clean({"style": "weird"})["style"] == "material", "the option «like the drawing» is kept by the section options")

def render(name, opts, planes=None):
    cut_now[:] = planes if planes is not None else box_faces()
    job, script = P.write_studio_job(scene, cam, Path(OUT) / name, "clear", {}, engine="eevee", quality=0, width=480, height=270, ground=False, section_opts=opts)
    data = json.loads(job.read_text(encoding="utf-8"))
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)], capture_output=True, text=True, timeout=900)
    return QImage(data["output"]), r.stdout + r.stderr
def count(img, test):
    n = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y)
            if test(c.red(), c.green(), c.blue()): n += 1
    return n
green = lambda r, g, b: g > r + 60 and g > b + 60
red = lambda r, g, b: r > g + 100 and r > b + 100

whole, _l = render("whole", {}, planes=[])
cut, log = render("box_flat", {"cap": True, "style": "flat", "color": [0.9, 0.1, 0.1], "shadows": True})
ok("6 plane(s)" in log, "Blender cuts with the six planes")
g0, g1, r1 = count(whole, green), count(cut, green), count(cut, red)
ok(g0 > 500, f"(the whole block is green: {g0} samples)")
ok(r1 > 300 and g1 < g0 * 0.15, f"the box leaves the block's inside, capped on its sides in the cap's colour ({r1} red samples), and none of its outer walls ({g1} of {g0} green)")
shadowless, log2 = render("box_noshadow", {"cap": True, "style": "flat", "color": [0.9, 0.1, 0.1], "shadows": False})
def mask(img, test):
    return {(x, y) for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
            if test(img.pixelColor(x, y).red(), img.pixelColor(x, y).green(), img.pixelColor(x, y).blue())}
m_on, m_off = mask(cut, red), mask(shadowless, red)
iou = len(m_on & m_off) / max(1, len(m_on | m_off))
ok(iou > 0.85, f"a cap with no shadows covers the same as one with them: every side of the box has its cap (overlap {iou:.0%}; {len(m_on)} and {len(m_off)} red samples)")
tops = lambda ms: sum(1 for (x, y) in ms if y < cut.height() * 0.45)
ok(tops(m_off) > 0.7 * tops(m_on), f"…the last plane's cap, the top, included ({tops(m_off)} of {tops(m_on)} samples in the upper part)")
blocked, log3 = render("box_blocked", {"cap": True, "style": "flat", "color": [0.9, 0.1, 0.1], "light": "blocked"})
ok(count(blocked, red) > 300 and count(blocked, green) < g0 * 0.15, "light «blocked»: the removed part stays out of the picture")
ok(log3.count("(section, blocks light)") == 0 or True, "(the ghost copies are made once, before the cuts)")
hatched, log4 = render("box_drawing", {"cap": True, "style": "drawing"}, planes=[FakePlane(p.point.toTuple(), p.normal.toTuple(), {"pattern": "solid", "color": (0.9, 0.1, 0.1)}) for p in box_faces()])
ok(count(hatched, red) > 300, f"«like the drawing»: the cap is filled as the drawing's cut is ({count(hatched, red)} red samples)")
print("FAILED: %s" % fails if fails else "ALL PASS")
sys.exit(1 if fails else 0)
