"""The Background group: sky / 360° panorama / fixed picture, the reset button and the folded advanced parts.
Offscreen, no Blender. argv: <ingetrazo-src> <render-studio repo> [<screenshot.png>]"""
import os, sys, copy, json, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtCore import QCoreApplication, QSettings
_ini = tempfile.mkdtemp()                       # settings in a temp folder: never the person's own
QCoreApplication.setOrganizationName("rs-test"); QCoreApplication.setApplicationName("rs-test")
QSettings.setDefaultFormat(QSettings.IniFormat); QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, _ini)
from core.scene import Scene
from render_studio import panel as P, settings_store as SS, presets

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

class VP:
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

pic = str(Path(tempfile.mkdtemp()) / "back.png")
img = QImage(32, 16, QImage.Format_RGB32); img.fill(QColor(20, 120, 200)); img.save(pic)

doc = Doc(); panel = P.StudioPanel(doc); doc.panels.append(panel)
panel.show()
TAB = {panel.tabs.tabText(i): i for i in range(panel.tabs.count())}
ok(list(TAB) == ['Main', 'Image', 'Sky', 'Lights', 'Section', 'Output'], f"the tabs: {list(TAB)}")
panel.tabs.setCurrentIndex(TAB['Sky'])
ok(panel.bg_mode.currentData() == "sky" and panel.hdri_settings() is None and panel.backdrop_settings() is None, "starts on the look's own sky")
ok(not panel.backdrop.isVisible() and not panel.hdri.isVisible(), "no background controls shown for the sky of the look")
panel.set_backdrop_path(pic)
ok(panel.bg_mode.currentData() == "picture" and panel.backdrop.isVisible() and not panel.hdri.isVisible(), "choosing a picture shows its controls only")
b = panel.backdrop_settings()
ok(b and b["path"] == pic and b["fit"] == "fill" and abs(b["strength"] - 1.0) < 1e-6 and panel.hdri_settings() is None, f"its settings reach the job ({b})")
blk = P.apply_backdrop({}, b)
ok(blk["backdrop"] == pic and blk["backdrop_fit"] == "fill", "…as the studio block's backdrop")
panel.backdrop_fit.setCurrentIndex(panel.backdrop_fit.findData("fit"))
panel._save_timer.stop(); panel._save_document_settings()
saved = doc.scene.plugin_data["render_studio"]["settings"]
ok(saved["backdrop"]["fit"] == "fit" and saved["hdri"] is None, "saved in the document (and no panorama with it)")
p2 = P.StudioPanel(doc); p2.apply_settings(saved)
ok(p2.bg_mode.currentData() == "picture" and p2.backdrop.currentData() == pic and p2.backdrop_fit.currentData() == "fit", "…and restored")
ok(SS.clean({"backdrop": {"path": pic, "fit": "weird"}})["backdrop"]["fit"] == "fill" and SS.clean({"look": "clear"})["backdrop"] is None, "clean(): odd fit falls back, none by default")
panel.bg_mode.setCurrentIndex(panel.bg_mode.findData("sky"))
ok(panel.backdrop_settings() is None and panel.settings_dict()["backdrop"] is None, "back to the sky: nothing sent")

# the output's transparent sky hides any background: the panel says so
panel.bg_mode.setCurrentIndex(panel.bg_mode.findData("picture"))
panel.output_tab.transparent.setChecked(True)
ok(panel.bg_note.isVisible() and "transparent" in panel.bg_note.text().lower(), "a note appears when the output leaves the sky transparent")
panel.output_tab.transparent.setChecked(False)
ok(not panel.bg_note.isVisible(), "…and goes when it does not")

# reset to the look, and the folded adjustments
panel.tabs.setCurrentIndex(TAB["Image"])
panel.sliders["vignette"].setValue(panel.sliders["vignette"].maximum())
panel.sliders["exposure_bias"].setValue(panel.sliders["exposure_bias"].maximum())
panel.reset_btn.click()
ok(abs(panel.slider_values()["exposure_bias"]) < 0.05 and abs(panel.slider_values()["vignette"] - presets.studio(panel.preset.currentData())[0].get("vignette", 0.16)) < 0.1,
   "the reset button puts the sliders back to the look's values")
ok(panel.slider_rows["exposure_bias"].isVisible() and panel.slider_rows["saturation"].isVisible() and not panel.slider_rows["vignette"].isVisible()
   and not panel.slider_rows["dof"].isVisible(), "Image: the simple sliders in view, the effects folded")
panel.fx.header.setChecked(True)
ok(panel.slider_rows["vignette"].isVisible() and panel.slider_rows["dof"].isVisible(), "…and «Effects» opens them")
ok(panel.slider_rows["dof"].slider.property("hi") == 1.0 and "dof" in panel.slider_values(), "depth of field is a slider of the panel")
panel.tabs.setCurrentIndex(TAB["Sky"])
ok(panel.slider_rows["clouds"].isVisible() and panel.slider_rows["sun_scale"].isVisible() and not panel.sun_tab.isVisible(), "Sky: clouds and sun in view, the sun's place and date folded")
panel.sun_more.header.setChecked(True)
ok(panel.sun_tab.isVisible(), "…and they open")
panel.tabs.setCurrentIndex(TAB["Main"])
ok(not panel.preview_engine.isVisible(), "Main: the preview engine is under Advanced")

# the person's presets
from render_studio import user_presets as UP
panel.preset.setCurrentIndex(panel.preset.findData("golden_hour"))
panel.sliders["clouds"].setValue(panel.sliders["clouds"].maximum())
panel.set_backdrop_path(pic)
mine = UP.make(panel.settings_dict())
ok(mine is not None and "section" not in mine and mine["backdrop"]["path"] == pic and mine["look"] == "golden_hour", "a preset keeps the look, adjustments and background, not the section")
panel._store_user_preset("Evening", mine)
ok([panel.user_presets.itemText(i) for i in range(panel.user_presets.count())][-1] == "Evening" and panel.user_presets.currentData() == "Evening", "saved presets are listed")
panel.preset.setCurrentIndex(panel.preset.findData("overcast")); panel.bg_mode.setCurrentIndex(panel.bg_mode.findData("sky"))
panel.user_presets.setCurrentIndex(panel.user_presets.findData("Evening")); panel._apply_user_preset()
ok(panel.preset.currentData() == "golden_hour" and panel.bg_mode.currentData() == "picture" and abs(panel.slider_values()["clouds"] - 1.0) < 0.02, "choosing a preset puts it back in the panel")
text = UP.to_file("Evening", panel.settings_dict())
got = UP.from_file(text)
ok(got and got[0] == "Evening" and got[1]["look"] == "golden_hour", "a preset file reads back")
ok(UP.from_file("{}") is None and UP.from_file("nonsense") is None and UP.clean_name("  a" + chr(10) + " b  ") == "a b", "other files are refused; names are tidied")
ok(set(UP.load_all(UP.dump_all({"x": mine, "": mine}))) == {"x"}, "stored presets load, nameless ones drop")
if len(sys.argv) > 3:
    for name in ("Main", "Image", "Sky"):
        panel.tabs.setCurrentIndex(TAB[name]); panel.resize(320, 700); panel.grab().save(sys.argv[3].replace(".png", f"_{name}.png"))
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
