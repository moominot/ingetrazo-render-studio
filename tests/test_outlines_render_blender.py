"""The outlines of a final render are vectors in the render window: Blender renders without lines, the picture the window shows has them
and they are restyled instantly; Render and save… and the autosave get them put in. A REAL Blender (offscreen Qt, IngeTrazo's source).
argv: <ingetrazo-src> <render-studio repo> <blender.exe>"""
import json, math, os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
BLENDER = sys.argv[3]
sys.path[:0] = [SRC, REPO]
tmp = tempfile.mkdtemp()
os.environ["XDG_CACHE_HOME"] = os.path.join(tmp, "cache")
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtCore import QCoreApplication, QSettings        # settings in a throwaway file, not the user's
_prev = (QCoreApplication.organizationName(), QCoreApplication.applicationName(), QSettings.defaultFormat())
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
qa.setOrganizationName("RenderStudioTest"); qa.setApplicationName("workflow")
def _restore_settings():
    QSettings.setDefaultFormat(_prev[2]); qa.setOrganizationName(_prev[0]); qa.setApplicationName(_prev[1])
from PySide6.QtGui import QImage, QVector3D
from core import render_blender as rb
from core.camera import OrbitCamera
from core.group import Group
from core.materials import Material
from core.mesh import Mesh
from core.scene import Scene
from render_studio import panel as P

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)
def wait(cond, secs=120.0):
    t0 = time.time()
    while not cond() and time.time() - t0 < secs:
        qa.processEvents(); time.sleep(0.01)
    return cond()

class VP:
    def __init__(self):
        self.camera = OrbitCamera(); self.camera.target = QVector3D(0, 0, 1.2); self.camera.distance = 14
        self.camera.yaw = math.radians(-50); self.camera.pitch = math.radians(12)
    def width(self): return 1600
    def height(self): return 900
    def update(self): pass
class App:
    api_version = 2
    def __init__(self):
        self.scene = Scene(); self.viewport = VP(); self.viewport.scene = self.scene; self.data = {}
        s = self.scene
        s.materials["Terreny"] = Material("Terreny", color=(0.5, 0.45, 0.3))
        s.materials["Paret"] = Material("Paret", color=(0.85, 0.82, 0.76))
        m = Mesh(); V = QVector3D
        f = m.add_face([V(-10, -10, 0), V(10, -10, 0), V(10, 10, 0), V(-10, 10, 0)]); f.attrs["mat"] = "Terreny"
        f.attrs["color"] = (0.5, 0.45, 0.3, 1.0)
        s.groups.append(Group(m, name="ground"))
        b = Mesh()
        x0, y0, x1, y1, z1 = -3, -2, 3, 2, 3
        for q in ([V(x0, y0, 0), V(x1, y0, 0), V(x1, y0, z1), V(x0, y0, z1)], [V(x1, y0, 0), V(x1, y1, 0), V(x1, y1, z1), V(x1, y0, z1)],
                  [V(x1, y1, 0), V(x0, y1, 0), V(x0, y1, z1), V(x1, y1, z1)], [V(x0, y1, 0), V(x0, y0, 0), V(x0, y0, z1), V(x0, y1, z1)],
                  [V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]):
            f = b.add_face(q); f.attrs["mat"] = "Paret"; f.attrs["color"] = (0.85, 0.82, 0.76, 1.0)
        s.groups.append(Group(b, name="house"))
    def document_data(self, d=None): return json.loads(json.dumps(self.data)) if self.data else d
    def set_document_data(self, v): self.data = json.loads(json.dumps(v))
    def on_document_changed(self, fn): pass

app = App()
panel = P.StudioPanel(app)
found = rb.BlenderFound([BLENDER], BLENDER)
panel.blender = lambda: found
panel.width.setValue(480); panel.quality.setCurrentIndex(0)
panel.style_groups.outline.setChecked(True); panel.style_groups.width.setValue(3.0)
finished = []
panel.finished.connect(lambda p: finished.append(p))
win = panel.open_preview()
wait(lambda: win.has_image())
dark = lambda a: int((a.astype(int).sum(axis=2) < 200).sum())
win.render_btn.click(); qa.processEvents()
ok(wait(lambda: len(finished) == 1) and finished[0] is not None, "the render finishes")
import numpy as np
base = QImage(str(Path(finished[0]).with_name("render-nolines.png")))
ok(not base.isNull(), "the picture Blender rendered is kept apart, without lines")
ok(win.lines is not None and win.lines_box.isVisibleTo(win), "the window has the outlines as vectors, with their controls")
ok(abs(win.lines_width.value() - 3.0) < 0.06, "…starting as the panel's style says")
def arr(img):
    img = img.convertToFormat(QImage.Format_RGB888)
    return np.frombuffer(img.constBits(), dtype=np.uint8, count=img.bytesPerLine() * img.height()).reshape(img.height(), img.bytesPerLine())[:, : img.width() * 3].reshape(img.height(), img.width(), 3)
d_base, d_baked, d_shown = dark(arr(base)), dark(arr(QImage(str(finished[0])))), dark(win.shown)
ok(d_baked > d_base + 100 and abs(d_shown - d_baked) < 0.05 * d_baked + 30, f"the file and the window have the lines ({d_base} dark pixels without, {d_baked} in the file, {d_shown} shown)")
win.lines_width.setValue(7.0); win._recompose()
ok(dark(win.shown) > d_shown * 1.4, "restyled in the window without rendering again")
out = Path(tmp) / "flat.png"
ok(win.save_to(str(out)) and dark(arr(QImage(str(out)))) > d_shown * 1.4, "Save image… flattens the restyled lines")
win.back_btn.click(); qa.processEvents()
ok(win.lines is None or win.mode == "preview", "back to the preview")
# A section cutting the house: Blender cuts and caps it, the rim of the cap is a vector line of its own colour in the window
from core import section as ISEC
cam_eye = app.viewport.camera.eye()
side = 1.0 if cam_eye.x() > 0 else -1.0                         # the removed side is the camera's: the cut is what it sees
plane = ISEC.SectionPlane(QVector3D(0, 0, 0), QVector3D(side, 0, 0)); app.scene.section_planes.append(plane); app.scene.set_active_section(plane)
panel.section_tab.apply({"cap": True, "style": "flat", "color": [0.8, 0.8, 0.8], "outline": True, "outline_color": [1.0, 0.0, 0.0], "outline_width": 4.0})
wait(lambda: panel._live is not None and panel._live.active and panel._live._ready)
n = len(finished)
win.render_btn.click(); qa.processEvents()
ok(wait(lambda: len(finished) == n + 1) and finished[-1] is not None, "a render with a section finishes")
ok(win.lines is not None and len(win.lines[0].cut) >= 4, f"the window has the rim of the cap as vector lines ({0 if win.lines is None else len(win.lines[0].cut)} of them)")
redpx = lambda a: int(((a[..., 0].astype(int) - a[..., 1]) > 120).sum())
ok(redpx(win.shown) > 150, f"…in the colour asked for, on the picture ({redpx(win.shown)} red pixels)")
r_before = redpx(win.shown)
win.cut_colour.set_rgb([0.0, 0.0, 1.0]); win._recompose()
ok(redpx(win.shown) < r_before * 0.1, "…and restyled at once without rendering again")
win.back_btn.click(); qa.processEvents()
app.scene.section_planes.clear()
panel.section_tab.apply({})
wait(lambda: panel._live is not None and panel._live.active and panel._live._ready)
# Render and save…: the lines are in the file as it was set in the panel
wait(lambda: panel._live is not None and panel._live.active and panel._live._ready)
asked = []
asks = [str(Path(tmp) / "saved.png")]
P.QFileDialog.getSaveFileName = staticmethod(lambda parent, cap, start, filt: (asks.pop(0), ""))
n = len(finished)
win.render_save_btn.trigger(); qa.processEvents()
ok(wait(lambda: len(finished) == n + 1), "Render and save… finishes")
ok(dark(arr(QImage(str(Path(tmp) / "saved.png")))) > d_base + 100, "…and its file has the outlines")
panel._stop_live()
_restore_settings()
print("FAILED: %s" % fails if fails else "ALL PASS")
sys.exit(1 if fails else 0)
