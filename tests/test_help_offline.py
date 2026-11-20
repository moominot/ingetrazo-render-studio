"""The «?» help of Render Studio. Offscreen, no Blender needed.
argv: <ingetrazo-src> <render-studio repo> [png dir]"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
PNG = sys.argv[3] if len(sys.argv) > 3 else None
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from render_studio import help_text, presets, materials as M, panel as P, ui_help
from render_studio import material_editor as ME

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

ok(set(help_text.LOOKS) == set(presets.ORDER), "every look has a description, and only real looks")
ok(set(help_text.PRESET_NOTES) == set(M.PRESETS), "every material preset has a note, and only real ones")
page = help_text.html()
ok(all(presets.label(k) in page for k in presets.ORDER), "every look name is in the help")
ok(all(M.preset_label(k) in page for k in M.PRESETS), "every material preset name is in the help")
ok(all(label in page for label, *_ in presets.SLIDERS.values()), "every panel slider is explained")
ok(all(f"<b>{label}</b>" in page for _k, label, *_ in ME._FIELDS), "every material setting is explained")
ok("Transparency" in page, "the help explains the transparency")
ok("Ripple size" in page, "the help explains the water ripples")
ok("Cube preview" in page, "the help explains the cube preview")
ok("live view" in page and "saved in the document" in page, "the help explains the live view and the saved settings")
ok("Open preview…" in page and "Render and save…" in page and "<b>Back to preview</b>" in page and "Two kinds of sliders" in page,
   "the help explains the preview window, Render, Render and save… and the two kinds of sliders")
ok("Zoom and move" in page and "100 %" in page and "mouse wheel" in page, "the help explains zoom and pan")
ok("Change picture…" in page and "Keep proportions" in page, "the help explains Change picture")
from render_studio import pbr
ok("Full texture sets" in page and pbr.MANIFEST_SUFFIX in page and "Poly Haven" in page and "ambientCG" in page,
   "the help explains the full texture sets, their manifest and the two libraries' names")
ok("Grass height" in page and "<b>Grass</b>" in page and "only in the render" in page,
   "the help explains the grass type and its height")
ok("Texture set: …" in page, "the help explains how the editor shows a texture set")
ok("<b>quick</b>" in page and "same Blender" in page, "the help explains the quick image and the rebuild in the same Blender")
ok("<b>Follow the camera</b>" in page and "<b>Follow changes</b>" in page, "the help explains the two live switches")
ok(all(a in page for a in ('name="panel"', 'name="image"', 'name="materials"', 'name="hdri"')), "anchors present")
from core import render_blender as rb
ok(f"{rb.SAMPLES['eevee'][0]} / {rb.SAMPLES['eevee'][1]} / {rb.SAMPLES['eevee'][2]}" in page
   and f"{rb.SAMPLES['cycles'][0]} / {rb.SAMPLES['cycles'][1]} / {rb.SAMPLES['cycles'][2]}" in page,
   "quality samples in the help match the code")

class VP:
    scene = None
    def update(self): pass
class App:
    api_version = 2; viewport = VP(); scene = None
    def document_data(self, default=None): return default
    def set_document_data(self, v): pass
    def on_document_changed(self, fn): pass
panel = P.StudioPanel(App())
ok(panel.help_btn.text() == "?" and panel.help_btn.toolTip(), "panel has a ? button")
panel.help_btn.click(); qa.processEvents()
d = ui_help._dialog
ok(d is not None and d.isVisible() and "Look" in d.view.toPlainText(), "the panel's ? opens the help")
win = P.ImageWindow()
btn = [b for b in win.findChildren(type(panel.help_btn)) if b.text() == "?"]
ok(len(btn) == 1, "image window has a ? button")
btn[0].click(); qa.processEvents()
ok(ui_help._dialog is d, "the same help window is reused")
try:
    ed = ME.MaterialEditor(App(), "en")
    mbtn = [b for b in ed.findChildren(type(panel.help_btn)) if b.text() == "?"]
    ok(len(mbtn) == 1, "material editor has a ? button")
    mbtn[0].click(); qa.processEvents()
except Exception as e:  # noqa: BLE001
    ok(False, f"material editor builds offscreen ({e!r})")
d.find.setText("vignette"); qa.processEvents()
ok(d.view.textCursor().selectedText().lower() == "vignette", "search finds a word")
if PNG:
    d.find.setText(""); d.goto("materials"); qa.processEvents(); d.grab().save(os.path.join(PNG, "rs_help_materials.png"))
    d.goto("panel"); qa.processEvents(); d.view.verticalScrollBar().setValue(0); d.grab().save(os.path.join(PNG, "rs_help_panel.png"))
# the Lights tab
from render_studio import lights as LT
ok('<a name="lights"></a>' in page and all(f"<b>{k}</b>" in page for k in ("Point light", "Spot", "Area light", "Sun")),
   "the help has a Lights section with the four kinds")
words = {"candle": "candle", "bulb": "bulbs", "bulb_big": "bulbs", "lantern": "bulbs", "downlight": "downlight",
         "track": "track spot", "street": "street lamp", "flood": "floodlight", "panel": "LED panel",
         "tube": "fluorescent tube", "strip": "LED strip", "window": "window fill", "disk": "ceiling disc",
         "sun": "second sun", "moon": "moonlight"}
ok(set(words) == {p[0] for p in LT.PRESETS} and all(w in page for w in words.values()), "the ready-made lights are named in the help")
ok("IES profile" in page and "Cycles" in page and str(int(LT.LM_PER_W)) in page, "the help explains IES profiles and the lumens")
ok("Every copy of the component" in page and "Make it a Render Studio light" in page, "the help explains lights on objects and the Render tab's")
# the Sun and Output tabs
from render_studio import output as OUT
ok('<a name="sun"></a>' in page and all(f"<b>{k}</b>" in page for k in ("Latitude, longitude", "North", "Date", "Hour", "Time zone")),
   "the help explains the Sun tab's controls")
ok("Golden hour" in page and "solstices" in page, "the help says what the looks do with the sun, and the season buttons")
ok('<a name="output"></a>' in page and all(OUT.FORMATS[k][0].split(",")[0].split(" (")[0] in page for k in OUT.FORMAT_ORDER)
   and "Transparent sky" in page and "Print resolution" in page and "{document}" in page,
   "the help explains the Output tab: sizes, formats, transparent sky, saving every render")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
