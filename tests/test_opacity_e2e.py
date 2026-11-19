"""End to end: IngeTrazo opacity -> GLB -> real Blender (bpy) -> the floor shows through the water.
Needs IngeTrazo's sources AND a Python with `bpy` (pip install bpy): set BPY_PYTHON to it, else skipped.
argv: <ingetrazo-src> <render-studio repo>"""
import os, subprocess, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
BPY = os.environ.get("BPY_PYTHON")
if not BPY or not os.path.exists(BPY):
    print("SKIP set BPY_PYTHON to a Python with bpy installed"); sys.exit(0)
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QVector3D
from core.scene import Scene
from core.mesh import Mesh
from core.group import Group
from core.materials import Material
from core.history import History
from formats.gltf import save_glb
from render_studio import opacity as OP

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

work = tempfile.mkdtemp()
def build(op, name):
    sc = Scene()
    def quad(m, pts, attrs): m.add_face([QVector3D(*p) for p in pts]).attrs.update(attrs)
    floor = Mesh(); quad(floor, [(-5, -3, -1), (5, -3, -1), (5, 3, -1), (-5, 3, -1)], {"color": (0.9, 0.5, 0.1)})
    water = Mesh(); quad(water, [(-5, -3, 0), (5, -3, 0), (5, 3, 0), (-5, 3, 0)], {"mat": "agua", "color": (0.1, 0.4, 0.6)})
    sc.materials["agua"] = Material("agua", color=(0.1, 0.4, 0.6))
    sc.groups += [Group(floor, name="floor"), Group(water, name="water")]
    class VP:
        def __init__(s): s.history = History(sc)
        def update(s): pass
    class App: scene = sc
    a = App(); a.viewport = VP()
    if op is not None: OP.set_opacity(a, "agua", op)
    path = os.path.join(work, name + ".glb"); save_glb(sc, path); return path
opaque, clear = build(None, "opaque"), build(0.3, "clear")

def render(glb, tag):
    out = os.path.join(work, tag)
    r = subprocess.run([BPY, os.path.join(REPO, "tests", "glb_pool_bpy.py"), glb, out, "water"], capture_output=True, text=True)
    return out + ".png", r
(po, ro), (pc, rc) = render(opaque, "r_opaque"), render(clear, "r_clear")
ok(os.path.exists(po) and os.path.exists(pc), "both renders were made" + ("" if os.path.exists(po) and os.path.exists(pc) else f"\n{ro.stderr[-400:]}\n{rc.stderr[-400:]}"))
ok("('agua', 0.3" in rc.stdout and "('agua', 1.0" in ro.stdout, "the opacity of the IngeTrazo material reaches Blender as the alpha of the water")
if os.path.exists(po) and os.path.exists(pc):
    import numpy as np
    from PySide6.QtGui import QImage
    def px(p, x, y): c = QImage(p).pixelColor(x, y); return (c.red(), c.green(), c.blue())
    a, b = px(po, 320, 170), px(pc, 320, 170)               # over the water, where the orange floor lies below
    ok(b[0] - b[2] > a[0] - a[2] + 25, f"the orange floor shows through the transparent water (opaque {a}, 70 % transparent {b})")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
