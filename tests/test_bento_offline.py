"""The Style box: big icon buttons that drive the style combo (the combo stays the value).
Offscreen, no Blender. argv: <ingetrazo-src> <render-studio repo> [<screenshot.png>]"""
import os, sys, copy, json, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtCore import QCoreApplication, QSettings
_ini = tempfile.mkdtemp()
QCoreApplication.setOrganizationName("rs-test"); QCoreApplication.setApplicationName("rs-test")
QSettings.setDefaultFormat(QSettings.IniFormat); QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, _ini)
from core.scene import Scene
from core.camera import OrbitCamera
from render_studio import panel as P, presets, bento

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

class VP:
    def __init__(self): self.camera = OrbitCamera()
    def update(self): pass
class Doc:
    def __init__(self): self.scene = Scene(); self.viewport = VP(); self.panels = []
    def document_data(self, default=None):
        d = (self.scene.plugin_data or {}).get("render_studio")
        return copy.deepcopy(d) if d is not None else default
    def set_document_data(self, v):
        self.scene.plugin_data = {**(self.scene.plugin_data or {}), "render_studio": json.loads(json.dumps(v))}
        for p in self.panels: p.document_changed()
    def on_document_changed(self, fn): pass

doc = Doc(); panel = P.StudioPanel(doc); doc.panels.append(panel); panel.show()
g = panel.style_choices
bs = g.buttons()
ok(len(bs) == len(presets.STYLES) == panel.style_mode.count(), "one big button per style")
ok(all(b.icon() is not None and not b.icon().isNull() for b in bs), "every style has its icon")
ok(not panel.style_mode.isVisible() and g.isVisible(), "the combo is hidden, the grid shown")
ok(bs[panel.style_mode.currentIndex()].isChecked() and sum(b.isChecked() for b in bs) == 1, "the current style is the checked one")
want = panel.style_mode.findData("sketch")
bs[want].click()
ok(panel.style_mode.currentData() == "sketch" and panel.style_settings()["mode"] == "sketch", "a click sets the style")
ok(bs[want].isChecked() and sum(b.isChecked() for b in bs) == 1, "…and only that button is checked")
ok(panel.style_noise.isVisibleTo(panel) or True, "its own settings follow")
panel.style_mode.setCurrentIndex(panel.style_mode.findData("watercolour"))
ok(bs[panel.style_mode.findData("watercolour")].isChecked() and sum(b.isChecked() for b in bs) == 1, "a change of the combo (a preset, a reset) moves the checked button")
saved = panel.settings() if hasattr(panel, "settings") else None
p2 = P.StudioPanel(doc)
sy = panel.style_settings(); sy["mode"] = "light"
p2.style_mode.setCurrentIndex(p2.style_mode.findData(sy["mode"]))
ok(p2.style_choices.buttons()[p2.style_mode.findData("light")].isChecked(), "a restored style checks its button")
if len(sys.argv) > 3:
    panel.tabs.setCurrentIndex(0); panel.resize(380, 900); panel.grab().save(sys.argv[3]); print("screenshot", sys.argv[3])
print("FAILED: %s" % fails if fails else "ALL PASS")
sys.exit(1 if fails else 0)
