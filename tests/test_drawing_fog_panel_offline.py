"""The Fog group of the Environment page follows the drawing's own fog (IngeTrazo 0.6.3): a note and waiting sliders while it is on, and the live
view is told. Offscreen, no Blender. argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
SRC, REPO = sys.argv[1:3]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication([])
from PySide6.QtCore import QCoreApplication, QSettings
QSettings.setDefaultFormat(QSettings.IniFormat); QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
QCoreApplication.setOrganizationName("f"); QCoreApplication.setApplicationName("f")
from core.scene import Scene
from core.camera import OrbitCamera
from render_studio import panel as P
class VP:
    def __init__(self): self.camera = OrbitCamera(); self.scene = sc
    def update(self): pass
    def width(self): return 1600
    def height(self): return 900
sc = Scene()
class App:
    api_version = 2
    def __init__(self): self.scene = sc; self.viewport = VP(); self.data = {}
    def document_data(self, d=None): return d
    def set_document_data(self, v): pass
    def on_document_changed(self, fn): pass
panel = P.StudioPanel(App()); panel.show()
fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)
panel._update_fog_note()
ok(panel.fog_note.isHidden() and panel.slider_rows["fog"].isEnabled(), "no fog in the drawing: the Fog group's sliders are the render's")
k0 = panel.live_key()
st = sc.display_style
for k, v in (("fog_enabled", True), ("fog_distance", 12.0), ("fog_thickness", 30.0), ("fog_color", (0.7, 0.7, 0.8)), ("fog_use_background", False)): setattr(st, k, v)
panel._update_fog_note()
ok(panel.fog_note.isHidden() is False and "12" in panel.fog_note.text() and not panel.slider_rows["fog"].isEnabled(), "fog on in the drawing: a note says so and the sliders wait")
ok(panel.live_key() != k0, "…and the live view is told it changed")
st.fog_enabled = False
panel._update_fog_note()
ok(panel.fog_note.isHidden() and panel.slider_rows["fog"].isEnabled(), "fog off again: the sliders are the render's again")

print("FAILED: %s" % fails if fails else "ALL PASS")
sys.exit(1 if fails else 0)
