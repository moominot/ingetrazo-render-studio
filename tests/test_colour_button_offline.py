"""A colour button's swatch colour stays on the button: the colour dialog it opens (a child of the button) and any other widget below it keep
their own look (the dialog's OK and Cancel took the colour chosen). Offscreen, no Blender. argv: <ingetrazo-src> <render-studio repo>"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication, QPushButton, QWidget, QVBoxLayout
qa = QApplication.instance() or QApplication([])
from render_studio.section_panel import ColourButton

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

host = QWidget(); lay = QVBoxLayout(host)
btn = ColourButton([1.0, 0.0, 0.0], "Cap colour")
lay.addWidget(btn)
child = QPushButton("OK", btn)               # what the dialog's buttons were: widgets below the swatch
child.setGeometry(0, 0, 60, 24)
host.resize(200, 80); host.show(); qa.processEvents()
def centre(w):
    img = w.grab().toImage(); c = img.pixelColor(6, 6); return c.red(), c.green(), c.blue()
img0 = btn.grab().toImage(); c0 = img0.pixelColor(img0.width() // 2, 4); r, g, b = c0.red(), c0.green(), c0.blue()
ok(r > 200 and g < 60 and b < 60, f"the swatch is its colour ({(r, g, b)})")
cr, cg, cb = centre(child)
ok(not (cr > 200 and cg < 60 and cb < 60), f"a button below it keeps its own look ({(cr, cg, cb)}), not the swatch's red")
btn.set_rgb([0.0, 0.0, 1.0]); qa.processEvents()
ok(btn.styleSheet().count("#colourSwatch") == 1 and "QPushButton {" not in btn.styleSheet(), "the rule is for this button only (by its name)")
src = open(os.path.join(REPO, "render_studio", "section_panel.py"), encoding="utf-8").read()
ok("self.window(), tr(self._title)" in src, "the colour dialog is not a child of the swatch")
print("FAILED: %s" % fails if fails else "ALL PASS")
sys.exit(1 if fails else 0)
