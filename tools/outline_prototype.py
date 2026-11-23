"""Prototype: Croquis' outline engine over a Blender render, against Freestyle.

Renders a model twice with Render Studio and a real Blender (outlines off, outlines on = Freestyle), draws the visible
edges with Croquis' depth-buffer engine (visibility.py, strokes.py: NumPy only) from the SAME camera, and compares time
and where the lines fall. Writes PNGs and a small report into <outdir>.

argv: <ingetrazo-src> <render-studio repo> <blender.exe> <croquis-src dir> <model.igz> <outdir> [width] [tile]
(<croquis-src dir> holds croquis' visibility.py and strokes.py)"""
import importlib.util, json, math, os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, BLENDER, CQ, MODEL, OUT = [os.path.abspath(a) for a in sys.argv[1:7]]
WIDTH = int(sys.argv[7]) if len(sys.argv) > 7 else 1280
TILE = int(sys.argv[8]) if len(sys.argv) > 8 else 1          # TILE × TILE copies of the model: a big scene
sys.path[:0] = [SRC, REPO]
os.makedirs(OUT, exist_ok=True)
tmp = tempfile.mkdtemp()
os.environ["XDG_CACHE_HOME"] = os.path.join(tmp, "cache")
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtCore import QCoreApplication, QSettings, Qt
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
qa.setOrganizationName("RenderStudioProto"); qa.setApplicationName("outlines")
from PySide6.QtGui import QImage, QVector3D, QPainter, QPen, QColor
from core import render_blender as rb, hlr
from core.camera import OrbitCamera
from core.scene import Scene
from formats import igz
from render_studio import panel as P


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(CQ, name + ".py"))
    mod = importlib.util.module_from_spec(spec); sys.modules["croquis_" + name] = mod
    spec.loader.exec_module(mod)
    return mod
vis, st = load("visibility"), load("strokes")


def wait(cond, secs=600.0):
    t0 = time.time()
    while not cond() and time.time() - t0 < secs:
        qa.processEvents(); time.sleep(0.01)
    return cond()


def to_array(path):
    img = QImage(str(path)).convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), dtype=np.uint8, count=img.bytesPerLine() * h)
    return a.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4)[:, :, :3].astype(np.float64)


def save_array(a, path):
    a = np.ascontiguousarray(np.clip(a, 0, 255).astype(np.uint8))
    h, w = a.shape[:2]
    QImage(a.data, w, h, w * 3, QImage.Format_RGB888).copy().save(str(path))


scene = Scene()
t0 = time.time(); igz.load_into(scene, Path(MODEL)); print(f"loaded {Path(MODEL).name} in {time.time() - t0:.1f} s", flush=True)
if TILE > 1:
    from core.group import copy_group
    t0 = time.time(); _t, _h, _s = hlr.collect_geometry(scene)
    _p = np.asarray(_t, dtype=np.float64).reshape(-1, 3).reshape(-1, 3); _ext = _p.max(axis=0) - _p.min(axis=0)
    base = list(scene.groups)
    for i in range(TILE):
        for j in range(TILE):
            if i or j:
                for g in base:
                    scene.groups.append(copy_group(g, QVector3D(i * _ext[0] * 1.3, j * _ext[1] * 1.3, 0)))
    print(f"tiled {TILE}x{TILE}: {len(scene.groups)} groups, {time.time() - t0:.1f} s", flush=True)
t0 = time.time(); tris, hard, soft = hlr.collect_geometry(scene)
print(f"collect_geometry: {len(tris)} triangles, {len(hard)} hard, {len(soft)} soft edges, {time.time() - t0:.1f} s", flush=True)
T = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
H = np.asarray([(a, b) for a, b in hard], dtype=np.float64).reshape(-1, 2, 3)
S = np.asarray([(a, b) for a, b, *_ in soft], dtype=np.float64).reshape(-1, 2, 3)
SN = np.full((len(soft), 2, 3), np.nan)
for i, (_a, _b, na, nb) in enumerate(soft):
    SN[i, 0] = na
    if nb is not None:
        SN[i, 1] = nb

cam = OrbitCamera()
lo, hi = T.reshape(-1, 3).min(axis=0), T.reshape(-1, 3).max(axis=0)
ctr, size = (lo + hi) / 2, float(np.linalg.norm(hi - lo))
cam.target = QVector3D(*ctr); cam.distance = size * 1.1
cam.yaw = math.radians(-50); cam.pitch = math.radians(20)
cam.aspect = 16 / 9


class VP:
    def __init__(self): self.camera = cam; self.scene = scene
    def width(self): return 1600
    def height(self): return 900
    def update(self): pass
class App:
    api_version = 2
    def __init__(self): self.scene = scene; self.viewport = VP(); self.data = {}
    def document_data(self, d=None): return json.loads(json.dumps(self.data)) if self.data else d
    def set_document_data(self, v): self.data = json.loads(json.dumps(v))
    def on_document_changed(self, fn): pass


app = App(); panel = P.StudioPanel(app)
panel.blender = lambda: rb.BlenderFound([BLENDER], BLENDER)
panel.width.setValue(WIDTH); panel.quality.setCurrentIndex(0)
finished = []
panel.finished.connect(lambda p: finished.append(p))
win = panel.open_preview()
wait(lambda: win is not None)
panel._live.stop() if panel._live is not None else None


def render(width_px):
    panel.style_mode.setCurrentIndex(panel.style_mode.findData("none"))
    panel.style_width.setValue(width_px)
    n = len(finished)
    if win.mode == "final":                      # the render button is the preview's: back to it first
        win.back_btn.click(); qa.processEvents()
        panel._live.stop() if panel._live is not None else None
    t = time.time()
    win.render_btn.click(); qa.processEvents()
    if not wait(lambda: len(finished) == n + 1, 1500.0):
        raise SystemExit(f"the render did not finish in 1500 s (window mode {win.mode})")
    return finished[-1], time.time() - t


plain, t_plain = render(0.0)
print(f"Blender, no outlines: {t_plain:.1f} s", flush=True)
lined, t_lined = render(1.5)
print(f"Blender, Freestyle 1.5 px: {t_lined:.1f} s   (Freestyle costs {t_lined - t_plain:+.1f} s)", flush=True)
A, B = to_array(plain), to_array(lined)
h, w = A.shape[:2]
save_array(A, Path(OUT) / "1_blender_plain.png"); save_array(B, Path(OUT) / "2_blender_freestyle.png")

# ---- Croquis' lines from the same camera -------------------------------------------------------------------------------
cam.aspect = w / h
geom = (T, H, S, SN)
t0 = time.time()
zbuf, index = vis.depth_buffer(T, vis.clip_matrix(cam), min(w, 2000), int(round(min(w, 2000) * h / w)), bool(cam.perspective))
t_z = time.time() - t0
bw = zbuf.shape[1]; scale = bw / w
segs, outline = vis.visible_lines(geom, cam, bw, zbuf.shape[0], zbuf=zbuf)
segs, outline = vis.merge_collinear(segs, outline, tol=1.5)
t_lines = time.time() - t0
print(f"Croquis engine: depth buffer {t_z:.2f} s, lines {t_lines:.2f} s in total, {len(segs)} segments", flush=True)
segs = segs / scale

def draw(base, segs, outline, colour=(20, 20, 20), width_px=1.5):
    img = QImage(np.ascontiguousarray(base.astype(np.uint8)).data, w, h, w * 3, QImage.Format_RGB888).copy()
    p = QPainter(img); p.setRenderHint(QPainter.Antialiasing, True)
    for (x0, y0, x1, y1), o in zip(segs, outline):
        p.setPen(QPen(QColor(*colour), width_px * (1.6 if o else 1.0), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(x0, y0, x1, y1)
    p.end()
    return img
t0 = time.time(); over = draw(A, segs, outline); t_draw = time.time() - t0
over.save(str(Path(OUT) / "3_blender_plain_plus_croquis_lines.png"))
print(f"drawing them over the picture: {t_draw:.2f} s", flush=True)

# ---- Where do the lines fall? Freestyle's lines = what changed between the two renders -----------------------------------
diff = np.abs(B - A).max(axis=2) > 24
mine = np.zeros((h, w), dtype=bool)
mask = QImage(w, h, QImage.Format_Grayscale8); mask.fill(0)
p = QPainter(mask); p.setRenderHint(QPainter.Antialiasing, False); p.setPen(QPen(QColor(255, 255, 255), 1.0))
for x0, y0, x1, y1 in segs: p.drawLine(x0, y0, x1, y1)
p.end()
m = np.frombuffer(mask.constBits(), dtype=np.uint8, count=mask.bytesPerLine() * h).reshape(h, mask.bytesPerLine())[:, :w] > 0


def dilate(a, r):
    out = a.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(a, dy, axis=0), dx, axis=1)
    return out
for r in (1, 2, 3):
    rec = (diff & dilate(m, r)).sum() / max(1, diff.sum())          # Freestyle's pixels that Croquis' lines reach
    prec = (m & dilate(diff, r)).sum() / max(1, m.sum())            # Croquis' pixels that Freestyle also drew
    print(f"within {r} px: Freestyle's line pixels covered {rec:.0%}; Croquis' line pixels that Freestyle has {prec:.0%}", flush=True)
vis_img = np.zeros((h, w, 3)); vis_img[...] = 255
vis_img[diff] = (220, 40, 40); vis_img[m & ~diff] = (40, 90, 220); vis_img[m & diff] = (40, 40, 40)
save_array(vis_img, Path(OUT) / "4_lines_compared_red_freestyle_blue_croquis_black_both.png")
print("done ->", OUT)
