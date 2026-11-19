"""The cube preview of the material editor. argv: <ingetrazo-src> <render-studio repo> [png dir]"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
PNG = sys.argv[3] if len(sys.argv) > 3 else None
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QImage, QColor, QVector3D, QMatrix4x4
from core.scene import Scene
from core.group import Group
from core.mesh import Mesh
from core.materials import Material
from render_studio import cube_preview as C, material_editor as ME

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

def img(params, size=120): return C.render(params, size).toImage()
def painted(im): return sum(1 for x in range(im.width()) for y in range(im.height()) if im.pixelColor(x, y).alpha() > 10)
def mean(im, region=None):
    n = r = g = b = 0
    for x in range(im.width()):
        for y in range(im.height()):
            c = im.pixelColor(x, y)
            if c.alpha() > 200: n += 1; r += c.red(); g += c.green(); b += c.blue()
    return (r / n, g / n, b / n) if n else (0, 0, 0)
def variance(im):
    vals = [im.pixelColor(x, y).lightness() for x in range(40, 80) for y in range(40, 80) if im.pixelColor(x, y).alpha() > 200]
    m = sum(vals) / len(vals); return sum((v - m) ** 2 for v in vals) / len(vals)
def grain(im):
    """Mean difference between neighbouring pixels on the left face: fine detail."""
    tot = n = 0
    for x in range(30, 52):
        for y in range(62, 90):
            a, b = im.pixelColor(x, y), im.pixelColor(x + 1, y)
            if a.alpha() > 200 and b.alpha() > 200: tot += abs(a.lightness() - b.lightness()); n += 1
    return tot / max(1, n)
def bright_pixels(im): return sum(1 for x in range(im.width()) for y in range(im.height())
                                  if im.pixelColor(x, y).alpha() > 200 and im.pixelColor(x, y).lightness() > 200)

tmp = Path(tempfile.mkdtemp())
red = tmp / "red.png"; im = QImage(32, 32, QImage.Format_RGB32); im.fill(QColor(200, 30, 30)); im.save(str(red))
chk = tmp / "chk.png"; im = QImage(32, 32, QImage.Format_RGB32); im.fill(QColor("white"))
for x in range(16):
    for y in range(16): im.setPixelColor(x, y, QColor("black")); im.setPixelColor(x + 16, y + 16, QColor("black"))
im.save(str(chk))

base = {"color": (0.5, 0.5, 0.5), "roughness": 0.8}
ok(C.render(base, 120).width() == 120 and 600 < painted(img(base)) < 14400 * 0.75, "a 120 px pixmap with the cube in it, room around it")
red_m = mean(img({"texture": str(red), "roughness": 0.9}))
ok(red_m[0] > 100 and red_m[0] > 3 * red_m[2], f"a picture colours the cube ({tuple(round(v) for v in red_m)})")
col = mean(img({"color": (0.1, 0.7, 0.1), "roughness": 0.9}))
ok(col[1] > 2 * col[0], "without a picture the material's colour is used")
ok(variance(img({"texture": str(chk), "tile": (0.25, 0.25), "roughness": 0.9})) > variance(img({"texture": str(chk), "tile": (4.0, 4.0), "roughness": 0.9})) * 0.1
   and img({"texture": str(chk), "tile": (0.25, 0.25), "roughness": 0.9}) != img({"texture": str(chk), "tile": (1.0, 1.0), "roughness": 0.9}), "the tile size changes how the picture repeats")
ok(bright_pixels(img({"color": (0.6, 0.1, 0.1), "roughness": 0.05})) > bright_pixels(img({"color": (0.6, 0.1, 0.1), "roughness": 0.95})) + 20, "polished (low roughness) shows a reflection; matte does not")
m0, m1 = mean(img({"color": (0.8, 0.8, 0.8), "roughness": 0.4})), mean(img({"color": (0.8, 0.8, 0.8), "roughness": 0.4, "metallic": 1.0}))
ok(sum(m1) < sum(m0) - 30, "metal darkens the body")
ok(grain(img({"color": (0.5, 0.5, 0.5), "roughness": 0.9, "bump": 1.0})) > grain(img({"color": (0.5, 0.5, 0.5), "roughness": 0.9, "bump": 0.0})) + 3, "relief adds grain")
solid = img({"color": (0.2, 0.4, 0.6), "roughness": 0.9}); glass = img({"kind": "glass", "color": (0.2, 0.4, 0.6), "roughness": 0.9})
ok(mean(glass)[2] > mean(solid)[2] + 20 and variance(glass) > variance(solid) + 5, "glass is see-through: lighter, with the checkerboard showing")
g0, g1 = img({"kind": "glow", "color": (1.0, 0.7, 0.2), "glow": 0.0}), img({"kind": "glow", "color": (1.0, 0.7, 0.2), "glow": 20.0})
ok(painted(g1) > painted(g0), "a glowing material has a halo around it")
ok(img({"color": (0.5, 0.5, 0.5)}) == img({"color": (0.5, 0.5, 0.5)}), "deterministic: the same inputs give the same picture")
ok(painted(C.render({"texture": "/does/not/exist.png"}, 100).toImage()) > 300, "a missing picture falls back to the colour")

# the editor
scene = Scene()
scene.materials["Brick"] = Material("Brick", texture={"path": str(red), "sw": 1.0, "sh": 1.0})
scene.materials["Plain"] = Material("Plain", color=(0.1, 0.7, 0.1))
g = Group(Mesh(), name="wall"); g.xform = QMatrix4x4(); g.material = {"mat": "Brick"}; scene.groups.append(g)
class App:
    def __init__(self): self.scene = scene; self.viewport = None
    def document_data(self, d=None): return d
    def set_document_data(self, v): pass
ed = ME.MaterialEditor(App(), "en")
ok(ed.cube.pixmap() is not None and not ed.cube.pixmap().isNull(), "the editor shows a cube for the selected material")
ed.select("Brick"); a = ed.cube.pixmap().toImage()
ok(mean(a)[0] > 100 and mean(a)[0] > 3 * mean(a)[2], "…with the material's picture")
ed.select("Plain"); b = ed.cube.pixmap().toImage()
ok(mean(b)[1] > 2 * mean(b)[0], "…and another material gives another cube")
before = ed.cube.pixmap().toImage()
s = ed.sliders["roughness"]; s.setValue(0)
ok(ed.cube.pixmap().toImage() != before, "moving a slider redraws it at once")
n = ed.kind.findData("glass"); ed.kind.setCurrentIndex(n)
ok(ed.cube.pixmap().toImage() != before, "changing the type redraws it")
ed.list.clear(); ed._show(None)
ok(ed.cube.pixmap() is None or ed.cube.pixmap().isNull(), "no material: no cube")
if PNG:
    ed2 = ME.MaterialEditor(App(), "en"); ed2.select("Brick"); ed2.resize(880, 640); ed2.show(); qa.processEvents(); ed2.grab().save(os.path.join(PNG, "editor_cube.png"))
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
