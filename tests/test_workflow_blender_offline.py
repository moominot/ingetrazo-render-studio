"""The preview → Render → retouch → Save workflow, and Render and save…, with a REAL Blender (offscreen
Qt, IngeTrazo's source): a small house on a lawn. Checks the three states of the window, that Render
stops the live view and shows the retouch tools, Back to preview, Render and save… (PNG and JPEG, no
retouching, asks the file first), Cancel, and closing the window during a render.
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
panel.width.setValue(320); panel.quality.setCurrentIndex(0)          # a small draft render
finished = []
panel.finished.connect(lambda p: finished.append(p))
which = lambda: panel.window.mode if panel.window is not None else None

# ---- the preview ---------------------------------------------------------------------------------
win = panel.open_preview()
ok(win is not None and win.isVisible() and which() == "preview", "Open preview opens the window as the live preview")
ok(wait(lambda: win.has_image() and panel._live is not None and panel._live.active), "the live view gives it a picture")
ok(wait(lambda: panel._live._ready and not panel._live._busy and panel._live._done_key is not None), "…and settles (quick image, then the draft)")
ok(win.original is None, "no final picture yet, so nothing to retouch")

# ---- Render: final picture, retouch tools --------------------------------------------------------------
t0 = time.time()
win.render_btn.click(); qa.processEvents()
ok(which() == "rendering" and win.bar.isVisibleTo(win) and win.cancel_btn.isVisibleTo(win), "Render: the window shows the progress and Cancel")
ok(not panel._live.active, "…and the live Blender is stopped")
ok(wait(lambda: len(finished) == 1), "the render finishes")
print(f"   Render took {time.time() - t0:.1f} s")
ok(finished and finished[0] is not None and Path(finished[0]).is_file(), "…with a picture")
ok(which() == "final" and win.bar_final.isVisibleTo(win) and not win.bar_preview.isVisibleTo(win), "…the window shows the final picture with the retouch tools")
ok(win.original is not None and win.original.shape[1] == 320, f"…at the panel's width ({win.original.shape[1]} px)")
ok(not panel._live.active, "…and the live view stays off (it would draw over the final picture)")
ex = win.adj["exposure"]; ex.setValue(int(ex.maximum() * 0.8))
mean = lambda a: float(a.mean())
ok(mean(win.shown) > mean(win.original) + 1, f"retouching changes it at once ({mean(win.original):.0f} → {mean(win.shown):.0f})")
out = Path(tmp) / "retouched.png"
ok(win.save_to(str(out)) and out.is_file(), "Save image… writes the retouched picture")
win._reset()

# ---- Back to preview -------------------------------------------------------------------------------------
win.back_btn.click(); qa.processEvents()
ok(which() == "preview" and win.bar_preview.isVisibleTo(win), "Back to preview: the Render buttons again")
ok(wait(lambda: panel._live.active and panel._live._ready and panel._live._done_key is not None), "…and the live view is back")

# ---- Render and save… --------------------------------------------------------------------------------------
asked = []
def ask(parent, caption, start, filt):
    asked.append((caption, start, filt)); return asks.pop(0), ""
asks = [str(Path(tmp) / "saved.png")]
P.QFileDialog.getSaveFileName = staticmethod(ask)
n = len(finished); t0 = time.time()
win.render_save_btn.click(); qa.processEvents()
ok(len(asked) == 1 and asked[0][0] == "Render and save" and "PNG" in asked[0][2], "Render and save…: it asks where to save first")
ok(which() == "rendering", "…then renders")
ok(wait(lambda: len(finished) == n + 1), "…and finishes")
print(f"   Render and save took {time.time() - t0:.1f} s")
saved = Path(tmp) / "saved.png"
img = QImage(str(saved))
ok(saved.is_file() and img.width() == 320, f"…the picture is saved ({img.width()}×{img.height()})")
rendered = QImage(str(finished[-1]))
ok(img == rendered, "…exactly as rendered (no retouching)")
ok(which() == "preview" and "Saved" in panel.status.text() and str(saved) in panel.status.text(), f"…and the window is the live preview again («{panel.status.text()}»)")
ok(win.status.text() == panel.status.text() or "Saved" in win.status.text(), "…saying where it saved")
ok(wait(lambda: panel._live.active), "…with the live view resumed")
ok(win.original is not None and win.mode == "preview", "(the earlier final picture is not shown over the preview)")

asks.append(str(Path(tmp) / "saved.jpg")); n = len(finished)
win.render_save_btn.click(); qa.processEvents()
ok(wait(lambda: len(finished) == n + 1), "a JPEG: renders")
jpg = QImage(str(Path(tmp) / "saved.jpg"))
ok(not jpg.isNull() and jpg.width() == 320 and (Path(tmp) / "saved.jpg").read_bytes()[:3] == b"\xff\xd8\xff", "…and saves a real JPEG")
asks.append(""); n = len(finished)
win.render_save_btn.click(); qa.processEvents()
ok(which() == "preview" and panel.proc is None and len(finished) == n, "cancelling the file dialog renders nothing")

# ---- Cancel -------------------------------------------------------------------------------------------------
n = len(finished)
win.render_btn.click(); qa.processEvents()
ok(wait(lambda: panel.proc is not None and which() == "rendering"), "a render starts")
win.cancel_btn.click(); qa.processEvents()
ok(wait(lambda: panel.proc is None and len(finished) == n + 1), "Cancel stops it")
ok(finished[-1] is None and "cancelled" in panel.status.text().lower(), f"…says so («{panel.status.text()}»)")
ok(which() == "preview" and wait(lambda: panel._live.active), "…and the live preview is back")

# ---- Closing the window during a render -------------------------------------------------------------------
n = len(finished)
win.render_btn.click(); qa.processEvents()
win.close(); qa.processEvents()
ok(panel.proc is not None and not win.isVisible(), "closing the window during a render does not stop it")
ok(wait(lambda: len(finished) == n + 1) and finished[-1] is not None, "…it finishes")
ok(win.isVisible() and which() == "final", "…and the window comes back with the final picture")
win.close(); qa.processEvents()
ok(not panel._live.active and panel._live._proc is None, "closing the window stops the live Blender")

_restore_settings()
print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
