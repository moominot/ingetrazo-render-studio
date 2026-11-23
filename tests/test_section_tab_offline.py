"""The Section tab: it says what cuts now (plane, box, both, off, nothing), offers the cap «like the drawing» and shows the controls each
choice needs; the cap's outline. Offscreen, no Blender. argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtCore import QCoreApplication, QSettings
QSettings.setDefaultFormat(QSettings.IniFormat); QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
QCoreApplication.setOrganizationName("s"); QCoreApplication.setApplicationName("s")
from PySide6.QtGui import QVector3D as V
from core.scene import Scene
from core.camera import OrbitCamera
from core import section as ISEC
from render_studio import panel as P, section as SEC

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

sc = Scene()
class VP:
    def __init__(self): self.camera = OrbitCamera(); self.scene = sc
    def update(self): pass
    def width(self): return 1600
    def height(self): return 900
class App:
    api_version = 2
    def __init__(self): self.scene = sc; self.viewport = VP(); self.data = {}
    def document_data(self, d=None): return d
    def set_document_data(self, v): pass
    def on_document_changed(self, fn): pass
panel = P.StudioPanel(App()); panel.show(); qa.processEvents()
tab = panel.section_tab
tab.catch_up()
ok(SEC.describe(sc) == "none" and "whole model" in tab.state.text(), "no cut: the tab says the render shows the whole model")
plane = ISEC.SectionPlane(V(1, 0, 0), V(1, 0, 0)); sc.section_planes.append(plane); sc.set_active_section(plane)
tab.catch_up()
ok(SEC.describe(sc) == "plane" and "section plane" in tab.state.text() and "box" not in tab.state.text(), "an active plane: the tab says so")
sc.show_section_cuts = False
tab.catch_up()
ok(SEC.describe(sc) == "off" and "switched off" in tab.state.text(), "Section Cuts off in the 3D view: the tab says why the render is whole")
sc.show_section_cuts = True
# a box, faked (this IngeTrazo may have none)
sc.active_section_box = lambda: object()
ok(SEC.describe(sc) == "both", "a plane and a box: both are named")
sc.section_planes.clear()
ok(SEC.describe(sc) == "box", "a box alone")
del sc.active_section_box
# the cap choices
idx = tab.style.findData("drawing")
ok(idx >= 0, "the cap can be «Like the drawing»")
tab.style.setCurrentIndex(idx); qa.processEvents()
ok(not tab.drawing_note.isHidden() and tab.colour.isHidden() and tab.material.isHidden() and tab.pattern.isHidden(), "«Like the drawing»: a line says how, and no colour, material or pattern to choose")
tab.style.setCurrentIndex(tab.style.findData("flat")); qa.processEvents()
ok(tab.drawing_note.isHidden() and not tab.colour.isHidden() and tab.pattern.isHidden(), "a flat colour: its colour only")
tab.style.setCurrentIndex(tab.style.findData("hatch")); qa.processEvents()
ok(not tab.colour.isHidden() and not tab.pattern.isHidden() and not tab.line.isHidden() and not tab.spacing.isHidden(), "a hatch: colour, pattern, lines and spacing")
s = tab.settings()
tab.apply(dict(s, style="drawing", outline=False, outline_width=5.0))
ok(tab.settings()["style"] == "drawing" and tab.settings()["outline"] is False and abs(tab.settings()["outline_width"] - 5.0) < 1e-6, "the options go and come back")
print("FAILED: %s" % fails if fails else "ALL PASS")
sys.exit(1 if fails else 0)
