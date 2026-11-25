"""The 8 x 8 grid of prisms with graded colours, as an .igz. argv: <ingetrazo-src> <out.igz>"""
import os, sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, OUT = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path.insert(0, SRC)
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from core.camera import OrbitCamera
from core.scene import Scene
from formats import igz
from views.main_window import MainWindow

scene = Scene()
for i in range(8):
    for j in range(8):
        x, y, w, h = i * 2.0, j * 2.0, 1.2, 0.4 + ((i * 7 + j * 3) % 5) * 0.5
        p = [V(x + a * w, y + b * w, c * h) for c in (0, 1) for b in (0, 1) for a in (0, 1)]
        for f in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)):
            scene.mesh.add_face([p[k] for k in f]).attrs["color"] = (0.8, 0.5 + i * 0.05, 0.4, 1.0)
cam = OrbitCamera()
cam.target = V(7.5, 7.5, 1)
cam.distance = 28.0
home = {"target": [7.5, 7.5, 1.0]}
for k in MainWindow._CAMERA_FIELDS:
    home[k] = getattr(cam, k)
scene.camera_home = home
igz.save_scene(scene, Path(OUT))
print("saved", OUT, os.path.getsize(OUT))
