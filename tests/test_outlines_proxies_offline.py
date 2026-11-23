"""The outlines of a render are drawn from what Blender renders: a proxy's original where its stand-in stands (the stand-in is not in the
model file, so it has no lines), the stand-in of a proxy whose original is lost, nothing for what is hidden. Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo> <out dir>"""
import json, math, os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, OUT = [os.path.abspath(a) for a in sys.argv[1:4]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QImage, QMatrix4x4, QVector3D
from core.camera import OrbitCamera
from core.group import Group, copy_group
from core.mesh import Mesh
from core.scene import Scene
from formats import igz
from render_studio import outlines, panel as P, proxies

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

def block(m, lo, hi, colour):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    V = QVector3D
    for q in ([V(x0,y0,z0),V(x0,y1,z0),V(x1,y1,z0),V(x1,y0,z0)], [V(x0,y0,z1),V(x1,y0,z1),V(x1,y1,z1),V(x0,y1,z1)],
              [V(x0,y0,z0),V(x1,y0,z0),V(x1,y0,z1),V(x0,y0,z1)], [V(x0,y1,z0),V(x0,y1,z1),V(x1,y1,z1),V(x1,y1,z0)],
              [V(x0,y0,z0),V(x0,y0,z1),V(x0,y1,z1),V(x0,y1,z0)], [V(x1,y0,z0),V(x1,y1,z0),V(x1,y1,z1),V(x1,y0,z1)]):
        m.add_face(q).attrs["color"] = colour
    return m

out = Path(OUT); out.mkdir(parents=True, exist_ok=True)
proj = out / "project"; proj.mkdir(exist_ok=True)
doc = proj / "plaça.igz"
cache = out / "cache"

# The original: a red block 2 × 2 × 4 standing on its origin, with a red cap as a part.
orig = Group(block(Mesh(), (-1, -1, 0), (1, 1, 4), (0.8, 0.05, 0.05, 1.0)), name="Bloc")
orig.xform = QMatrix4x4()
cap = Group(block(Mesh(), (-0.5, -0.5, 0), (0.5, 0.5, 0.3), (0.8, 0.05, 0.05, 1.0)), name="Cap")
cap.xform = QMatrix4x4(); cap.xform.translate(0, 0, 4); orig.children = [cap]
orig.ext = {"proxy_tool": {"id": "bloc0000000000001"}}
orig_file = proj / "plaça_proxies" / "Bloc_bloc00.igz"; orig_file.parent.mkdir(exist_ok=True)
oscene = Scene(); oscene.groups.append(orig); igz.save_scene(oscene, orig_file)

def stand_in(name, x, info):
    g = Group(block(Mesh(), (-1, -1, 0), (1, 1, 4.3), (0.95, 0.55, 0.15, 1.0)), name=name)
    g.xform = QMatrix4x4(); g.xform.translate(x, 0, 0)
    g.ext = {"proxy_tool": dict(info)}
    return g

info = {"id": "bloc0000000000001", "file": str(out / "elsewhere" / "Bloc_bloc00.igz"),   # moved project:
        "rel": os.path.join("plaça_proxies", "Bloc_bloc00.igz"), "state": "proxy", "name": "Bloc"}  # rel wins
scene = Scene()
ground = scene.mesh.add_face([QVector3D(-8, -8, 0), QVector3D(8, -8, 0), QVector3D(8, 8, 0), QVector3D(-8, 8, 0)])
ground.attrs["color"] = (0.6, 0.6, 0.6, 1.0)
a = stand_in("Bloc", -3, info); scene.groups.append(a)
b = copy_group(a, QVector3D(6, 0, 0)); scene.groups.append(b)
hid = copy_group(a, QVector3D(0, 5, 0)); hid.hidden = True; scene.groups.append(hid)
lost = Group(block(Mesh(), (-0.5, -0.5, 0), (0.5, 0.5, 1.0), (0.95, 0.55, 0.15, 1.0)), name="Perdut")
lost.xform = QMatrix4x4(); lost.xform.translate(0, -5, 0)
lost.ext = {"proxy_tool": {"id": "lost", "file": str(out / "nowhere.igz"), "state": "proxy", "name": "Perdut"}}
scene.groups.append(lost)
version = scene.version

class VP:
    def __init__(self): self.scene = scene; self.camera = OrbitCamera()
    def update(self): pass
    def width(self): return 1600
    def height(self): return 900
class Win: _current_path = doc
class App:
    api_version = 2
    window = Win()
    def __init__(self): self.scene = scene; self.viewport = VP(); self.data = {}
    def document_data(self, d=None): return json.loads(json.dumps(self.data)) if self.data else d
    def set_document_data(self, v): self.data = json.loads(json.dumps(v))
    def on_document_changed(self, fn): pass
panel = P.StudioPanel(App())

placed, extra = proxies.line_geometry(scene, str(doc))
ok(len(placed) == 2 and extra is not None, "two proxies have their original (the hidden one and the lost one do not)")
g = panel.line_geometry()
ok(g is not None, "with proxies, the outlines are not drawn from the 3D view's own geometry")
tris = g[0]
def near(x, y, tol=1.5):
    c = tris.mean(axis=1)
    return tris[(abs(c[:, 0] - x) < tol) & (abs(c[:, 1] - y) < tol) & (c[:, 2] > 0.01)]
for x in (-3.0, 3.0):
    t = near(x, 0.0)
    top = t[(t[:, :, 2] > 4.2).all(axis=1)]
    ok(len(top) and np.ptp(top[:, :, 0]) <= 1.01, f"at x={x:g} the original's capped top is there (its stand-in's top is wider)")
ok(len(near(0.0, 5.0)) == 0, "the hidden placement has no lines")
lost_t = near(0.0, -5.0, 1.0)
ok(len(lost_t) and lost_t[:, :, 2].max() <= 1.001 and (g[1][:, :, 1] < -4).any(), "the proxy whose original is lost is drawn as its stand-in, with its lines")
ok(not a.hidden and hid.hidden and not lost.hidden and not b.hidden and scene.version == version, "the drawing is left as it was")
cam = OrbitCamera(); cam.target = QVector3D(0, 0, 2); cam.distance = 22; cam.yaw = math.radians(-35); cam.pitch = math.radians(22)
p1 = outlines.write_layer(VP(), cam, 640, 360, {"mode": "none", "width": 2.0, "color": [0, 0, 0]}, out / "lines_proxies.png", g)
p0 = outlines.write_layer(VP(), cam, 640, 360, {"mode": "none", "width": 2.0, "color": [0, 0, 0]}, out / "lines_standins.png")
i1, i0 = QImage(p1), QImage(p0)
d = sum(1 for y in range(0, 360, 2) for x in range(0, 640, 2) if (i1.pixelColor(x, y).alpha() > 128) != (i0.pixelColor(x, y).alpha() > 128))
ok(p1 and p0 and d > 30, f"the lines differ from the stand-ins' ({d} pixels)")
small = proxies.line_geometry(scene, str(doc), budget=10)[1]
ok(small is not None and len(small[1]) == 0 and len(small[0]) > 0, "past the budget an original only hides (no lines of its own)")
# An original that arrives without an edge list (the app's lazy meshes): the lines are read from its triangles.
_walk = outlines.scene_geometry
outlines.scene_geometry = lambda sc: (lambda g: (g[0], np.empty((0, 2, 3)), np.empty((0, 2, 3)), np.empty((0, 2, 3))))(_walk(sc))
proxies._geom_cache.clear()
try:
    nolist = proxies.line_geometry(scene, str(doc))[1]
finally:
    outlines.scene_geometry = _walk
    proxies._geom_cache.clear()
ok(nolist is not None and len(nolist[1]) > 0, f"originals without an edge list still get lines ({len(nolist[1])} hard edges from their triangles)")
print("FAILED: %s" % fails if fails else "ALL PASS")
sys.exit(1 if fails else 0)
