"""The outlines of a render are drawn by the app (outlines.py, Croquis' engine), not by Blender's Freestyle: a transparent layer from the
model's geometry and the render's camera. Offscreen, no Blender. argv: <ingetrazo-src> <render-studio repo>"""
import math, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QImage, QVector3D
from core.camera import OrbitCamera
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from render_studio import outlines, settings_store, panel as P

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

scene = Scene()
m = Mesh(); V = QVector3D
x0, y0, x1, y1, z1 = -2, -1.5, 2, 1.5, 2
for q in ([V(x0, y0, 0), V(x1, y0, 0), V(x1, y0, z1), V(x0, y0, z1)], [V(x1, y0, 0), V(x1, y1, 0), V(x1, y1, z1), V(x1, y0, z1)],
          [V(x1, y1, 0), V(x0, y1, 0), V(x0, y1, z1), V(x1, y1, z1)], [V(x0, y1, 0), V(x0, y0, 0), V(x0, y0, z1), V(x0, y1, z1)],
          [V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]):
    m.add_face(q)
scene.groups.append(Group(m, name="box"))
cam = OrbitCamera(); cam.target = V(0, 0, 1); cam.distance = 9; cam.yaw = math.radians(-40); cam.pitch = math.radians(25)
class VP:                                         # no 3D view: the scene's own geometry
    def __init__(self): self.scene = scene
tmp = Path(tempfile.mkdtemp())
st = lambda **kw: settings_store.style({"mode": "none", "width": 2.0, "color": [0.0, 0.0, 0.0], **kw})

ok(not outlines.wanted({"mode": "none", "width": 0}) and outlines.wanted({"mode": "none", "width": 1}) and outlines.wanted({"mode": "sketch", "width": 0}),
   "outlines are wanted with a width, and always in a sketch")
ok(outlines.write_layer(VP(), cam, 640, 360, st(width=0.0), tmp / "none.png") is None, "no width, no layer")
p = outlines.write_layer(VP(), cam, 640, 360, st(), tmp / "a.png")
img = QImage(p)
ok(p and img.width() == 640 and img.height() == 360 and img.hasAlphaChannel(), "the layer is a transparent picture of the render's size")
ink = sum(1 for y in range(0, 360, 2) for x in range(0, 640, 2) if img.pixelColor(x, y).alpha() > 128)
ok(60 < ink < 6000, f"…with ink on the box's edges and nothing elsewhere ({ink} sampled pixels)")
ok(img.pixelColor(2, 2).alpha() == 0, "…transparent where there is no line")
thick = QImage(outlines.write_layer(VP(), cam, 640, 360, st(width=6.0), tmp / "b.png"))
ink2 = sum(1 for y in range(0, 360, 2) for x in range(0, 640, 2) if thick.pixelColor(x, y).alpha() > 128)
ok(ink2 > ink * 1.5, f"a thicker width inks more ({ink} → {ink2})")
red = QImage(outlines.write_layer(VP(), cam, 640, 360, st(color=[1.0, 0.0, 0.0]), tmp / "c.png"))
px = next(red.pixelColor(x, y) for y in range(360) for x in range(640) if red.pixelColor(x, y).alpha() > 200)
ok(px.red() > 200 and px.green() < 40 and px.blue() < 40, "…in the colour chosen")
ls0, ls1 = outlines.line_style({"mode": "sketch", "width": 1.5, "noise": 0.0, "extend": 0.0}, 360), outlines.line_style({"mode": "sketch", "width": 1.5, "noise": 1.0, "extend": 1.0}, 360)
ok(ls0.hand == 0.0 and ls0.overshoot == 0.0 and ls1.hand == 1.0 and ls1.overshoot == 2.0, "the sketch's two sliders are the hand and the overshoot")
ok(abs(ls0.width * 360 / 1000 - 1.5) < 1e-9, "the width stays in pixels of the picture, whatever its size")
loose = QImage(outlines.write_layer(VP(), cam, 640, 360, st(mode="sketch", noise=1.0, extend=1.0), tmp / "d.png"))
tidy = QImage(outlines.write_layer(VP(), cam, 640, 360, st(mode="sketch", noise=0.0, extend=0.0), tmp / "e.png"))
diff = sum(1 for y in range(0, 360, 2) for x in range(0, 640, 2) if (loose.pixelColor(x, y).alpha() > 128) != (tidy.pixelColor(x, y).alpha() > 128))
ok(diff > 40, f"a loose hand draws other lines than a ruler ({diff} pixels differ)")
again = QImage(outlines.write_layer(VP(), cam, 640, 360, st(mode="sketch", noise=1.0, extend=1.0), tmp / "f.png"))
ok(again == loose, "…and the same view always gives the same drawing")
# ---- edges from a triangle soup (an original that comes without its edge list)
import numpy as np
def cube_tris(h=1.0):
    P = np.array([[x, y, z] for z in (0, h) for y in (0, 1) for x in (0, 1)], dtype=float)
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return np.array([[P[a], P[b], P[c]] for q in quads for a, b, c in ((q[0], q[1], q[2]), (q[0], q[2], q[3]))])
hard, soft, sn = outlines.edges_from_triangles(cube_tris())
ok(len(hard) == 12 and len(soft) == 0, f"a cube's triangles give its 12 edges, and no line for the diagonals of its faces ({len(hard)} hard, {len(soft)} soft)")
ang = np.linspace(0, 2 * math.pi, 25)[:-1]
ring = [(math.cos(a), math.sin(a)) for a in ang]
side = np.array([t for i in range(24) for t in (
    [(*ring[i], 0), (*ring[(i + 1) % 24], 0), (*ring[(i + 1) % 24], 1)], [(*ring[i], 0), (*ring[(i + 1) % 24], 1), (*ring[i], 1)])], dtype=float)
hard, soft, sn = outlines.edges_from_triangles(side)
ok(len(soft) == 24 and len(hard) == 48 and np.isfinite(sn).all(), f"a smooth tube: its sides are soft edges with two normals, its open rims hard ({len(hard)} hard, {len(soft)} soft)")
ok(len(outlines.edges_from_triangles(np.empty((0, 3, 3)))[0]) == 0, "no triangles, no lines")
# ---- the render window: the outlines stay vectors until the picture is saved
from PySide6.QtGui import QColor
from render_studio import preview
base_png = tmp / "base.png"
bimg = QImage(640, 360, QImage.Format_RGB32); bimg.fill(QColor(200, 210, 220)); bimg.save(str(base_png))
ls = outlines.lineset(VP(), cam, 640, 360)
ok(ls is not None and len(ls) > 8 and ls.width == 640 and ls.height == 360, f"the lines are found once, apart from how they are drawn ({len(ls)} of them)")
win = preview.ImageWindow()
win.set_image(base_png)
ok(not win.lines_box.isVisibleTo(win) and win.lines is None, "a picture without outlines shows no outline controls")
style0 = outlines.window_style({"mode": "none", "width": 2.0, "color": [0.0, 0.0, 0.0]})
win.set_outlines(ls, style0, base_png)
dark = lambda a: int((a.astype(int).sum(axis=2) < 300).sum())
ok(win.lines_box.isVisibleTo(win) and dark(win.shown) > 150, f"…with them, the controls show and the lines are in the picture ({dark(win.shown)} dark pixels)")
d0 = dark(win.shown)
win.lines_width.setValue(6.0); win._recompose()
ok(dark(win.shown) > d0 * 1.5, f"thickness restyles the lines at once ({d0} → {dark(win.shown)})")
win.lines_width.setValue(2.0); win.lines_hand.setValue(1.0); win.lines_extend.setValue(1.0); win._recompose()
ok(dark(win.shown) != d0 and win.lines_style()["hand"] == 1.0, "…the hand and the extension too")
win.lines_hand.setValue(0.0); win.lines_extend.setValue(0.0); win.lines_width.setValue(2.0); win._recompose()
win.lines_colour.set_rgb([1.0, 0.0, 0.0]); win._recompose()
red = ((win.shown[..., 0].astype(int) - win.shown[..., 1]) > 120).sum()
ok(red > 100, f"…and the colour ({red} red pixels)")
win.lines_on.setChecked(False); win._recompose()
ok(np.array_equal(win.shown, win.original) and dark(win.shown) == 0, "Show off: the picture as Blender rendered it")
win.lines_on.setChecked(True); win.lines_colour.set_rgb([0.0, 0.0, 0.0]); win._recompose()
out_png = tmp / "saved_flat.png"
ok(win.save_to(str(out_png)) and dark(np.asarray(QImage(str(out_png)).convertToFormat(QImage.Format_RGB888).constBits()).reshape(-1)[: 640 * 360 * 3].reshape(360, 640, 3)) > 100,
   "saving puts the lines in the file")
win._lines_to_initial()
ok(abs(win.lines_width.value() - 2.0) < 0.06 and win.lines_hand.value() == 0.0, "«As rendered» puts the controls back")
win.set_image(base_png)
ok(win.lines is None and not win.lines_box.isVisibleTo(win), "a new picture forgets the outlines")
# ---- a slider whose label changes its text must not change its size while it is dragged
from render_studio import widgets as W
ns = W.NumberSlider(0.0, 4.0, 0.1, "{:.1f} px", special="No outlines")
ns.resize(300, 30); ns.show(); qa.processEvents()
w0, t0 = ns.label.width(), ns.label.text()
ns.setValue(1.5); qa.processEvents()
ok(ns.label.text() != t0 and ns.label.width() == w0 and ns.slider.width() == ns.slider.width(), f"the value label keeps its width when «{t0}» becomes «{ns.label.text()}» ({w0} px)")
widths = set()
for v in (0.0, 0.1, 2.5, 4.0):
    ns.setValue(v); qa.processEvents(); widths.add((ns.label.width(), ns.slider.width()))
ok(len(widths) == 1, f"…and so does the slider, along the whole range ({widths})")
# the side panel: its buttons are inside it, every retouch slider is in view, a handle on its edge hides and shows it
win = preview.ImageWindow(); win.resize(1100, 700); win.set_image(base_png); win.show(); qa.processEvents()
ok(all(win.side.isAncestorOf(b) for b in (win.reset_btn, win.back_btn, win.save_btn)), "Reset, Back to preview and Save are inside the side panel")
ok(all(win.adj_rows[k].isVisibleTo(win) for k in win.adj_rows) and len(win.adj_rows) == 5, "every retouch slider is in view (none folded away)")
ok(win.side.isVisibleTo(win) and win.side_handle.isVisibleTo(win), "the panel and its handle show with the finished picture")
win.side_handle.click(); qa.processEvents()
ok(not win.side.isVisibleTo(win) and win.side_handle.isVisibleTo(win), "the handle hides the panel and stays to show it again")
win.side_handle.click(); qa.processEvents()
ok(win.side.isVisibleTo(win), "…and shows it")
win.set_mode("preview"); qa.processEvents()
ok(not win.side.isVisibleTo(win) and not win.side_handle.isVisibleTo(win), "in the live preview there is neither panel nor handle")
empty = Scene()
ok(outlines.write_layer(type("E", (), {"scene": empty})(), cam, 640, 360, st(), tmp / "g.png") is None, "an empty view gives no layer (and no error)")
blk = P.apply_style_block({}, scene, {"mode": "none", "width": 3}, lines=str(tmp / "a.png"))
ok(blk["style"]["lines"] == str(tmp / "a.png") and P.apply_style_block({}, scene, {"mode": "none", "width": 3})["style"].get("lines") is None, "the job carries the layer's path")
print("FAILED: %s" % fails if fails else "ALL PASS")
sys.exit(1 if fails else 0)
