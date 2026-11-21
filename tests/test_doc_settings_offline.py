"""Render Studio's settings kept in the document. argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, copy, json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from core.scene import Scene
from render_studio import panel as P, settings_store as SS, presets

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

class VP:
    def update(self): pass
class Doc:
    """An IngeTrazo document's plugin data, as ExtensionApp.document_data/set_document_data keep it."""
    def __init__(self): self.scene = Scene(); self.viewport = VP(); self.sets = 0; self.panels = []
    def document_data(self, default=None):
        d = (self.scene.plugin_data or {}).get("render_studio")
        return copy.deepcopy(d) if d is not None else default
    def set_document_data(self, v):
        self.scene.plugin_data = {**(self.scene.plugin_data or {}), "render_studio": json.loads(json.dumps(v))}
        self.sets += 1
        for p in self.panels: p.document_changed()
    def on_document_changed(self, fn): pass

doc = Doc(); panel = P.StudioPanel(doc); doc.panels.append(panel)
ok(doc.sets == 0 and "render_studio" not in (doc.scene.plugin_data or {}), "opening a panel on a plain document writes nothing")

# the user changes things
panel.preset.setCurrentIndex(panel.preset.findData("golden_hour"))
panel.engine.setCurrentIndex(panel.engine.findData("cycles"))
panel.quality.setCurrentIndex(2); panel.width.setValue(2560)
sl = panel.sliders["clouds"]; sl.setValue(sl.maximum() // 2)
ok(doc.sets == 0, "nothing is written before the pause (debounced)")
panel._save_timer.stop(); panel._save_document_settings()
st = doc.scene.plugin_data["render_studio"]["settings"]
ok(doc.sets == 1 and st["look"] == "golden_hour" and st["engine"] == "cycles" and st["quality"] == 2 and st["width"] == 2560 and st["version"] == 1,
   f"saved in the document in the documented format ({ {k: st[k] for k in ('look','engine','quality','width')} })")
ok(abs(st["sliders"]["clouds"] - 0.5) < 0.01 and set(st["sliders"]) == set(presets.SLIDERS) and st["hdri"] is None, "sliders saved by name, no 360° background")
panel._save_document_settings(); ok(doc.sets == 1, "saving the same settings again writes nothing")
SS_read = SS.read(doc.scene.plugin_data); ok(SS_read == SS.clean(st), "settings_store.read gives them back (what any other reader would use)")

# materials saved by the material editor are not lost by a settings save
doc.scene.plugin_data["render_studio"]["materials"] = {"Brick": {"roughness": 0.7}}
panel.quality.setCurrentIndex(0); panel._save_timer.stop(); panel._save_document_settings()
ok(doc.scene.plugin_data["render_studio"]["materials"] == {"Brick": {"roughness": 0.7}}, "the materials already in the document are kept")

# the same document in a new panel (reopened file / another tab)
p2 = P.StudioPanel(doc); doc.panels.append(p2)
ok(p2.preset.currentData() == "golden_hour" and p2.engine.currentData() == "cycles" and p2.quality.currentIndex() == 0 and p2.width.value() == 2560,
   "a new panel on that document shows its settings")
ok(doc.sets == 2, "applying them did not save them again")

# undo/redo or an external change under a live panel
ext = SS.clean({**doc.scene.plugin_data["render_studio"]["settings"], "look": "night", "width": 1280})
doc.scene.plugin_data["render_studio"]["settings"] = ext
p2.document_changed()
ok(p2.preset.currentData() == "night" and p2.width.value() == 1280, "a change of the stored settings (undo, redo) reaches the controls")
ok(doc.sets == 2, "...without writing anything")

# another tab: a different document
other = Doc(); other.scene.plugin_data = {"render_studio": {"settings": {"look": "interior", "engine": "cycles"}}}
p2.app = other; other.panels.append(p2); p2.document_changed()
ok(p2.preset.currentData() == "interior", "another document brings its own settings (missing values fall back)")

# garbage is cleaned, not trusted
bad = SS.clean({"look": "nonsense", "engine": "x", "quality": 99, "width": -5, "sliders": {"clouds": "abc", "sun_scale": 99}, "hdri": {"path": 3}})
ok(bad["look"] == "clear" and bad["engine"] == "eevee" and bad["quality"] == 2 and bad["width"] == 320 and "clouds" not in bad["sliders"]
   and bad["sliders"]["sun_scale"] == 2.0 and bad["hdri"] is None, f"unknown values fall back and numbers are clamped ({bad})")
ok(SS.clean(None) is None and SS.clean({}) is None and SS.read(None) is None and SS.read({"render_studio": 5}) is None, "nothing usable -> None")

# 360° background survives (a real file)
import tempfile
f = os.path.join(tempfile.mkdtemp(), "sky.hdr"); open(f, "wb").write(b"x")
panel.set_hdri_path(f); panel.hdri_light.setChecked(False)
panel._save_timer.stop(); panel._save_document_settings()
h = doc.scene.plugin_data["render_studio"]["settings"]["hdri"]
ok(h and h["path"] == f and h["light"] is False, "the 360° background is saved")
p3 = P.StudioPanel(doc)
ok(p3.hdri.currentData() == f and not p3.hdri_light.isChecked(), "and restored")
# the generated ground: on by default, off is kept in the document and reaches every job
ok(panel.ground.isChecked() and SS.clean({"look": "clear"})["ground"] is True, "the generated ground is on by default")
panel.ground.setChecked(False)
panel._save_timer.stop(); panel._save_document_settings()
ok(doc.scene.plugin_data["render_studio"]["settings"]["ground"] is False, "switching the ground off is saved in the document")
p4 = P.StudioPanel(doc)
ok(not p4.ground.isChecked(), "and a new panel on that document has it off")
seen = []; doc.viewport.camera = None
real_write = P.write_studio_job
P.write_studio_job = lambda *a, **k: (seen.append(k.get("ground")), (_ for _ in ()).throw(RuntimeError("stop")))[0]
try:
    for call in (lambda: panel.live_job(__import__("pathlib").Path(tempfile.mkdtemp()), 320, 200),):
        try:
            call()
        except RuntimeError:
            pass
finally:
    P.write_studio_job = real_write
ok(seen == [False], f"the live job is written without the ground ({seen})")
panel.ground.setChecked(False); k_off = panel.live_key()
panel.ground.setChecked(True); k_on = panel.live_key()
ok(k_off != k_on and k_off[0] == k_on[0], "the ground changes the live scene's key, not the model's (the model file is kept)")
# the 360° image's viewpoint height: kept, restored, clamped, default 2.5 m
panel.hdri_height.setValue(int(round((8.0 - 0.5) / 29.5 * panel.hdri_height.maximum())))
panel._save_timer.stop(); panel._save_document_settings()
ok(abs(panel.hdri_settings()["height"] - 8.0) < 0.2, f"the viewpoint height reaches the job's 360° settings ({panel.hdri_settings()['height']:.2f})")
ok(abs(doc.scene.plugin_data["render_studio"]["settings"]["hdri"]["height"] - 8.0) < 0.2, "and is saved in the document")
p5 = P.StudioPanel(doc)
ok(abs(P.apply_hdri({}, {"path": "x"})["hdri_height"] - 2.5) < 1e-6 and abs(SS.clean({"hdri": {"path": f}})["hdri"]["height"] - 2.5) < 1e-6,
   "without it the default is 2.5 m")
ok(SS.clean({"hdri": {"path": f, "height": 999}})["hdri"]["height"] == 30.0, "an absurd height is clamped")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
