"""The centre of the ground's grass: the centroid of the drawing's objects. argv: <ingetrazo-src> <render-studio repo>"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QMatrix4x4, QVector3D
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from render_studio import ground as G
fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)
def cube():
    m = Mesh()
    for q in ([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], [(0, 0, 2), (2, 0, 2), (2, 2, 2), (0, 2, 2)]):
        m.add_face([QVector3D(*p) for p in q])
    return m
scene = Scene()
a = Group(cube(), name="a")                                   # its box centre is (1, 1)
b = Group(cube(), name="b"); b.xform = QMatrix4x4(); b.xform.translate(30, 6, 0)      # (31, 7)
big = Group(cube(), name="far"); big.xform = QMatrix4x4(); big.xform.translate(100, 0, 0); big.xform.scale(5)   # one object, however big
scene.groups += [a, b]
scene.version += 1
c = G.centroid(scene)
ok(abs(c[0] - 16.0) < 1e-3 and abs(c[1] - 4.0) < 1e-3, f"the mean of the centres of two objects: (16, 4) ({c})")
scene.groups.append(big); scene.version += 1
c = G.centroid(scene)
ok(abs(c[0] - (1 + 31 + (100 + 5)) / 3.0) < 1e-3, f"a big object counts once, like a small one ({c})")
ok(G.centroid(Scene()) == [0.0, 0.0], "no objects: the origin")
print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
