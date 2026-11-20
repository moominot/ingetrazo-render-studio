"""The Sun and Output tabs, without Blender. argv: <ingetrazo-src> <render-studio repo>

Sun: it edits IngeTrazo's own date, hour, zone, location and north (one undo step each), the
render job's sun follows, the readout and the look's note; the live preview keeps its model.
Output: sizes (view, ready, paper at a dpi, custom, proportions, turned), formats, the document,
the job's final file, the preview window with a transparent sky, saving and saving every render."""
import json, math, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication, QWidget
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QColor, QImage, QVector3D
import numpy as np
from core import render_blender as rb, sun as core_sun
from core.camera import OrbitCamera
from core.history import History
from core.scene import Scene
from render_studio import light_ops, lights as L, output as O, panel as P, sun_site as S

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

class VP:
    def __init__(self, scene):
        self.scene = scene; self.history = History(scene); self.listeners = []; self.camera = OrbitCamera()
    def notify_scene_changed(self):
        for fn in self.listeners: fn()
    def update(self): pass
    def width(self): return 1600
    def height(self): return 900
class App:
    api_version = 2; key = "render_studio"
    def __init__(self):
        self.scene = Scene(); self.viewport = VP(self.scene)
    def document_data(self, default=None):
        d = (self.scene.plugin_data or {}).get(self.key)
        return json.loads(json.dumps(d)) if d is not None else default
    def set_document_data(self, v):
        from core.history import SetPluginDataCommand
        self.viewport.history.execute(SetPluginDataCommand(self.key, v)); self.viewport.notify_scene_changed()
    def on_document_changed(self, fn): self.viewport.listeners.append(fn)

app = App(); scene = app.scene; hist = app.viewport.history
scene.mesh.add_face([QVector3D(*p) for p in ((-3, -3, 0), (3, -3, 0), (3, 3, 0), (-3, 3, 0))])
panel = P.StudioPanel(app); app.on_document_changed(panel.document_changed)
sun = panel.sun_tab

# ---- Sun ---------------------------------------------------------------------------------
s = S.site(scene)
ok(not s["located"] and abs(s["lat"] - core_sun.DEFAULT_LAT) < 1e-9, "no location: IngeTrazo's default place, said so")
ok(S.seasons(-16)["summer"] == (12, 21) and S.seasons(41)["summer"] == (6, 21), "summer is December in the south, June in the north")
sun._season("summer"); sun.flush()
ok((scene.shadows.month, scene.shadows.day) == (12, 21), "the summer solstice button writes IngeTrazo's own date")
hist.undo()
ok((scene.shadows.month, scene.shadows.day) == (3, 21), "…one undo step puts the old date back")
sun.refresh()
model_key, live_key = panel.live_model_key(), panel.live_key()
sun._quick("noon"); sun.flush()
i = S.info(S.site(scene))
ok(abs(scene.shadows.hour * 60 + scene.shadows.minute - i["noon"]) <= 1 and i["up"] and i["elevation"] > 60,
   f"Noon puts the hour at the solar noon (sun {i['elevation']:.0f}° high)")
ok(panel.live_model_key() == model_key and panel.live_key() != live_key,
   "a sun change: the preview keeps its model and gets the new sun")
sun.set_minutes(23 * 60); sun.flush()
ok("Below the horizon" in sun.sun_now.text(), "at 23:00 the readout says it is night")
sun._quick("morning"); sun.flush()
day = S.info(S.site(scene))["daylight"]
ok(scene.shadows.hour * 60 + scene.shadows.minute == day[0] + 60, "Sunrise + 1 h")
sun.zone.setCurrentIndex(sun.zone.findData(-3)); sun.flush()
ok(scene.shadows.utc_offset == -3, "a real time zone")
sun.zone.setCurrentIndex(0); sun.flush()
ok(scene.shadows.utc_offset is None, "…and back to the longitude's")
sun.north.setValue(30.0); sun.flush()
ok(abs(core_sun.scene_north_deg(scene) - 30) < 1e-9 and scene.georef is None, "north without a location: the scene's own")
sun.lat.setValue(41.3874); sun.lon.setValue(2.1686); sun.flush()
ok(scene.georef is not None and abs(scene.georef.lat - 41.3874) < 1e-6 and abs(scene.georef.north - 30) < 1e-9,
   "typing a place makes it the model's location, north kept")
ok(S.site(scene)["located"] and "model's location" in sun.where.text(), "…and the tab says so")
hist.undo()
ok(scene.georef is None, "undo takes the location away")
hist.redo()
ok(scene.georef is not None, "redo puts it back")
sun.north.setValue(-20.0); sun.flush()
ok(abs(scene.georef.north + 20) < 1e-9 and abs(scene.georef.lat - 41.3874) < 1e-6, "north with a location: the datum's, place kept")
sun.shadows.setChecked(True); sun.flush()
ok(scene.shadows.enabled, "Shadows in the 3D view switches IngeTrazo's own")
# the job's sun is IngeTrazo's sun for this date and hour
sun.date.setDate(sun.date.date().fromString("2026-06-21", "yyyy-MM-dd")); sun.set_minutes(10 * 60); sun.flush()
cam = OrbitCamera(); cam.target = QVector3D(0, 0, 0); cam.distance = 10
work = Path(tempfile.mkdtemp())
job, _sc = P.write_studio_job(scene, cam, work / "j", "clear", {}, engine="eevee", quality=0, width=320, height=180)
data = json.loads(job.read_text(encoding="utf-8"))
want = rb.sun_toward(scene)
ok(data["sun"] is not None and all(abs(a - b) < 1e-9 for a, b in zip(data["sun"], want)),
   "the render's sun is the one of this date, hour, place and north")
el = math.degrees(math.asin(data["sun"][2]))
ok(abs(el - S.info(S.site(scene))["elevation"]) < 0.05, f"…as high as the tab says ({el:.1f}°)")
panel.preset.setCurrentIndex(panel.preset.findData("golden_hour"))
ok("Golden hour" in sun.look.text() and sun.look.isVisibleTo(sun), "the Golden hour look says it lowers the sun")
panel.preset.setCurrentIndex(panel.preset.findData("clear"))
ok(not sun.look.text(), "a clear day uses it as it is")
# a light's change does not re-export the model either
mk = panel.live_model_key()
light_ops.add_free(app, L.new_light("point", pos=(0, 0, 2)))
ok(panel.live_model_key() == mk, "a light's change: the preview keeps its model")

# ---- Output: sizes ---------------------------------------------------------------------------
ok(O.frame(1920, {"size": "view"}, 16 / 9) == (1920, 1080), "the 3D view's shape from the width")
ok(O.frame(0, {"size": "a4", "dpi": 300}, 1.0) == (3508, 2480), "A4 landscape at 300 dpi is 3508 × 2480")
ok(O.frame(0, {"size": "a3p", "dpi": 150}, 1.0) == (1754, 2480), "A3 portrait at 150 dpi")
ok(O.frame(1000, {"size": "custom", "height": 3000}, 2.0) == (1000, 3000), "a size of your own")
ok(O.clean({"size": "x", "format": "gif", "transparent": True, "dpi": 5})["format"] == "png"
   and O.clean({"format": "jpeg", "transparent": True})["transparent"] is False, "junk cleaned; no transparency in a JPEG")
ok("16:9" in O.describe(1920, 1080, 300) and "16.3 × 9.1 cm" in O.describe(1920, 1080, 300), "the size is described")
ok(O.file_name("{document}/{look}:{date}", "Casa", "Clear day", "20261120", ".png") == "Casa_Clear day_20261120.png",
   "a safe file name from the pattern")

out = panel.output_tab
ok(abs(panel._aspect() - 16 / 9) < 1e-9 and out.frame() == (1920, 1080), "by default: the 3D view's shape")
out.size.setCurrentIndex(out.size.findData("square"))
ok(out.frame() == (2048, 2048) and abs(panel._aspect() - 1.0) < 1e-9, "a ready square: the preview frames it too")
out.width.setValue(1500)
ok(out.size.currentData() == "custom" and out.frame() == (1500, 2048), "typing a width makes it custom")
out.keep.setChecked(True); out.width.setValue(750)
ok(out.frame() == (750, 1024), "keeping proportions, the height follows")
out._swap()
ok(out.frame() == (1024, 750), "⇄ turns it")
out.keep.setChecked(False)
out.size.setCurrentIndex(out.size.findData("a4")); out.dpi.setValue(150)
ok(out.frame() == (1754, 1240), "a paper size follows the dpi")
out.format.setCurrentIndex(out.format.findData("jpeg"))
ok(not out.transparent.isEnabled() and not out.jpeg_quality.isHidden(), "JPEG: its quality shown, no transparency")
out.format.setCurrentIndex(out.format.findData("png16")); out.transparent.setChecked(True)
ok(out.transparent.isEnabled() and out.jpeg_quality.isHidden() and "as Blender wrote it" in out.file_note.text(),
   "16-bit PNG: transparency possible, saved as rendered")
panel._save_timer.stop(); panel._save_document_settings()
st = scene.plugin_data["render_studio"]["settings"]
ok(st["output"] == {"size": "a4", "height": 1240, "dpi": 150, "format": "png16", "jpeg_quality": 92,
                    "transparent": True}, f"saved in the document ({st['output']})")
p2 = P.StudioPanel(app)
ok(p2.output_tab.settings() == out.settings() and p2.output_tab.frame() == (1754, 1240), "a new panel shows it again")

# the job: the final file
job, _sc = P.write_studio_job(scene, cam, work / "k", "clear", {}, engine="eevee", quality=0, width=1754,
                              height=1240, output=out.settings())
o = json.loads(job.read_text(encoding="utf-8"))["studio"]["output"]
ok(o["format"] == "png16" and o["path"].endswith("-final.png") and o["image_settings"]["color_depth"] == "16"
   and o["image_settings"]["color_mode"] == "RGBA" and o["transparent"], "the job asks Blender for a 16-bit PNG with alpha")
job, _sc = P.write_studio_job(scene, cam, work / "l", "clear", {}, engine="eevee", quality=0, width=320, height=180,
                              output={"format": "jpeg", "jpeg_quality": 80})
o = json.loads(job.read_text(encoding="utf-8"))["studio"]["output"]
ok("path" not in o and o["image_settings"]["quality"] == 80, "JPEG: made from the PNG, no file of its own")
job, _sc = P.write_studio_job(scene, cam, work / "m", "clear", {}, engine="eevee", quality=0, width=320, height=180,
                              output={"format": "exr", "transparent": True}, live=True, serve=True)
ok("output" not in json.loads(job.read_text(encoding="utf-8"))["studio"], "the live preview writes no final file")

# ---- the preview window with a transparent sky ------------------------------------------------
png = work / "alpha.png"
img = QImage(40, 20, QImage.Format_RGBA8888); img.fill(QColor(200, 100, 50, 255))
for x in range(40):
    for y in range(10):
        img.setPixelColor(x, y, QColor(0, 0, 0, 0))
img.save(str(png))
win = panel.preview(); win.set_image(png)
ok(win.alpha is not None and win.alpha[0, 0] == 0 and win.alpha[15, 0] == 255, "the window keeps the alpha apart")
win.save_to(str(work / "keep.png"))
k = QImage(str(work / "keep.png"))
ok(k.hasAlphaChannel() and k.pixelColor(0, 0).alpha() == 0 and k.pixelColor(0, 15).alpha() == 255,
   "a retouched PNG keeps the transparent sky")
win.save_to(str(work / "flat.jpg"))
j = QImage(str(work / "flat.jpg"))
ok(not j.hasAlphaChannel() and j.pixelColor(2, 2).lightness() > 240, "a JPEG puts it over white")
# saving as rendered and every render
panel.output = png
deep = work / "deep.tif"; deep.write_bytes(b"II*\x00fake")
panel.rendered = {"format": "tiff16", "file": deep, "jpeg_quality": 90}
ok(panel._save_as_rendered(str(work / "copy.tif")) and (work / "copy.tif").read_bytes() == deep.read_bytes(),
   "a 16-bit TIFF is saved as Blender wrote it")
panel.rendered = {"format": "jpeg", "file": png, "jpeg_quality": 60}
ok(panel._save_as_rendered(str(work / "r.jpg")) and (work / "r.jpg").read_bytes()[:3] == b"\xff\xd8\xff",
   "a JPEG is made from the PNG")
auto = work / "every"
out.folder.setText(str(auto)); out.autosave.setChecked(True); out.pattern.setText("{document}-{look}-{date}")
panel.rendered = {"format": "png", "file": png, "jpeg_quality": 92}
kept = panel._autosave()
ok(kept and Path(kept).is_file() and Path(kept).parent == auto and Path(kept).suffix == ".png", f"every render saved ({kept})")
out.autosave.setChecked(False)
ok(panel._autosave() is None, "…only when asked")

# ---- a narrow tray --------------------------------------------------------------------------
# Laid out for real at 240 px, with every kind of light chosen (a minimum size hint can hide a
# label that does not wrap: the sun's note made the Lights tab 600 px wide).
for kind in L.TYPES:
    light_ops.add_free(app, L.new_light(kind, pos=(0, 0, 3)))
panel.need_box.setVisible(False)
panel.resize(240, 900); panel.show()
for i, name in ((1, "Lights"), (2, "Sun"), (3, "Output")):
    panel.tabs.setCurrentIndex(i); qa.processEvents()
    area = panel.tabs.currentWidget()
    inner = area.widget()
    keys = [e["key"] for e in L.all_lights(scene)] if name == "Lights" else [None]
    widest = 0
    for key in keys:
        if key is not None:
            inner.select(key)
        qa.processEvents()
        widest = max(widest, QWidget.width(inner) - area.viewport().width())
    ok(widest <= 0, f"the {name} tab fits a 240 px tray with every light chosen ({widest} px too wide)")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
