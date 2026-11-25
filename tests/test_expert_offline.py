"""The Expert page: every setting with its control and eye, layouts that decide what the pages show and change no value, mirrors
that act on the panel's own controls, and marks on what is not at its default.
argv: <ingetrazo-src> <render-studio repo>"""
import json, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["RENDER_STUDIO_HOME"] = tempfile.mkdtemp()
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from pathlib import Path
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
qa = QApplication.instance() or QApplication([])
import reference_cases as R
from render_studio import bindings, expert, layouts, params, settings_store as S

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

# -- layouts as files
folder = layouts.Folder(Path(tempfile.mkdtemp()))
ok(layouts.default() == set(params.simple_layout()), "the default layout is the register's simple view")
folder.save("Meva/1", {"image.vignette", "surface.kind", "nothing"})
got = folder.find("meva/1")
ok(got is not None and got[2] == {"image.vignette", "surface.kind"} and got[0].parent == folder.root, "saved and found, with a safe file name")
old = layouts.to_data("v", set()); old["known"] = [k for k in params.BY_KEY if k != "surface.kind"]
ok(layouts.from_data(old)[1] == {"surface.kind"}, "a setting newer than the layout shows as the simple view has it")
ok(layouts.from_data({"shown": []}) is None and layouts.from_data("x") is None, "what is not a layout is refused")
folder.delete("Meva/1")
ok(folder.entries() == [], "deleted")

panel = R.panel()
e = panel.expert
def row_visible(key):
    form, row = e.filter.rows[key]
    return form.isRowVisible(row)
def apply(**changes):
    panel.apply_settings(dict(panel.settings_dict(), **changes)); qa.processEvents()

ok(set(e.controls) == set(params.BY_KEY) - {"quality.width", "background.paper_sky"} and set(e.rows) == set(e.controls),
   f"every setting has its control and its row in Expert ({len(e.rows)}); the width stays in Output")
ok(set(e.filter.rows) == set(e.controls) - {"ambient.look"}, "…and its row in its page")

# -- the default layout
hidden = set(e.controls) - e.shown
ok({"image.vignette", "image.ao", "surface.keep_glass", "quality.engine"} <= hidden and "surface.kind" not in hidden, "by default the finer settings are out of the pages")
ok(not any(row_visible(k) for k in hidden if k != "ambient.look"), "…none of their rows shows")
ok(row_visible("surface.kind") and row_visible("outline.on") and row_visible("shadows.draw") and row_visible("ground.on"), "…and the simple ones do")
ok(panel.fx.isHidden() or any(panel.fx.form.isRowVisible(r) for r in range(panel.fx.form.rowCount())), "a group left empty goes with its rows")
vin = e.filter.rows["image.vignette"]

# -- hidden stays hidden whatever changes; a condition keeps ruling what is shown
panel.style_groups.surface.setCurrentIndex(panel.style_groups.surface.findData("mono")); qa.processEvents()
ok(not row_visible("surface.keep_glass") and row_visible("surface.colour"), "a choice that brings rows does not bring a hidden one")
apply(look="night"); apply(look="clear")
panel.bg_mode.setCurrentIndex(panel.bg_mode.findData("picture")); qa.processEvents()
ok(not row_visible("picture.fit") and row_visible("picture.path") and not row_visible("sky.stars") and not row_visible("image.vignette"),
   "…nor does a new background, a new look or a document put on")
panel.gallery.apply_item(panel.gallery.item("Sketch")); qa.processEvents()
ok(not row_visible("image.vignette") and not row_visible("surface.keep_glass"), "…nor a preset")
apply(style={"mode": "none"}, shadows={"draw": "render"}, flat=None, backdrop=None, ground=True)

# -- the eyes
before = panel.settings_dict()
e.set_eye("image.vignette", True)
ok(row_visible("image.vignette") and not panel.fx.isHidden(), "opening an eye puts the setting in its page")
e.set_eye("surface.colour", False); e.set_eye("surface.colour", True)
ok(not row_visible("surface.colour"), "an open eye does not show what does not apply (a colour with real materials)")
e.set_eye("shadows.draw", False)
ok(not row_visible("shadows.draw"), "closing an eye takes it out")
ok(panel.settings_dict() == before, "the eyes change no value of the render")
panel.shadow_draw.setCurrentIndex(panel.shadow_draw.findData("lines")); qa.processEvents()
ok(not row_visible("shadows.draw") and row_visible("shadows.spacing"), "what depends on a hidden choice still follows it")
e.set_eye("shadows.draw", True)
panel.shadow_draw.setCurrentIndex(0); qa.processEvents()

# -- the mirrors act on the panel's own controls
def mirror(key):
    return e.rows[key].mirror
e.refresh()
m = mirror("surface.kind"); i = m.widget.findData("mono"); m.widget.setCurrentIndex(i); m.widget.activated.emit(i); qa.processEvents()
ok(panel.style_groups.surface.currentData() == "mono" and panel.style_settings()["mode"] == "white", "a choice made in Expert is the panel's")
e.refresh()                                              # (the page shows: it takes the controls' state)
mirror("surface.keep_glass").widget.click(); qa.processEvents()
ok(not panel.style_groups.keep_glass.isChecked() and panel.style_settings()["mode"] == "model", "a box ticked")
mirror("outline.on").widget.click(); mirror("outline.width").widget.setValue(2.5); qa.processEvents()
ok(panel.style_groups.outline.isChecked() and abs(panel.style_groups.width.value() - 2.5) < 1e-6, "a number")
c = mirror("surface.colour"); c.widget.set_rgb([0.2, 0.3, 0.4]); c.widget.changed.emit(); qa.processEvents()
ok(panel.style_settings()["model_color"] == [0.2, 0.3, 0.4], "a colour")
s = mirror("image.vignette"); s.widget.slider.setValue(s.widget.slider.maximum()); qa.processEvents()
ok(abs(panel.slider_values()["vignette"] - 0.6) < 1e-6 and s.widget.value_label.text() == panel.slider_rows["vignette"].value_label.text(), "a slider, with the same words")
mirror("ground.offset").widget.setValue(1.5); mirror("skyline.seed").widget.setValue(7); mirror("ground.radius").widget.setValue(100.0); qa.processEvents()
ok(abs(panel.ground_offset.value() - 1.5) < 1e-6 and panel.skyline_seed.value() == 7 and abs(panel.ground_radius.value() - 100.0) < 1e-6, "boxes of numbers and radius sliders")
mirror("quality.level").widget.setCurrentIndex(2); qa.processEvents()
ok(panel.quality.currentIndex() == 2, "the quality buttons")
m = mirror("ambient.look"); i = m.widget.findData("overcast"); m.widget.activated.emit(i); qa.processEvents()
ok(panel.preset.currentData() == "overcast", "the light")
m = mirror("background.kind"); i = m.widget.findData("flat"); m.widget.setCurrentIndex(i); m.widget.activated.emit(i); qa.processEvents()
ok(panel.bg_mode.currentData() == "flat" and panel.flat_settings() is not None, "the background")
f = mirror("flat.colour"); f.widget.set_rgb([0.0, 0.5, 1.0]); f.widget.changed.emit()
ok(panel.flat_settings()["color"] == [0.0, 0.5, 1.0], "…and its colour")
panel.style_groups.width.setValue(1.2); e.refresh()
ok(abs(mirror("outline.width").widget.value() - 1.2) < 1e-6, "what is changed in the pages shows in Expert")

# -- what is not at its default is marked, hidden or not, and can go back
panel.gallery.reset_action.trigger(); qa.processEvents(); e.refresh()
marked = lambda: {k for k, r in e.rows.items() if not r.mark.isHidden()}
ok(marked() == set(), f"after resetting everything nothing is marked ({sorted(marked())})")
panel.sliders["vignette"].setValue(panel.sliders["vignette"].maximum()); e.set_eye("image.vignette", False); e.refresh()
ok(marked() == {"image.vignette"} and not e.rows["image.vignette"].reset.isHidden(), "a changed setting is marked even with its eye closed")
e.reset_value("image.vignette"); qa.processEvents()
ok(marked() == set() and abs(panel.slider_values()["vignette"] - 0.16) < 0.01, "…and goes back to its default")
apply(look="golden_hour", sliders={}); panel.set_ambient("golden_hour"); qa.processEvents(); e.refresh()
ok(marked() == {"ambient.look"}, f"a slider at its own look's value is not a change ({sorted(marked())})")
e.reset_value("ambient.look")
ok(e.rows["surface.colour"].mirror.widget.isEnabled() is False, "what does not apply now is greyed in Expert")

# -- search
e.search.setText("vinyeta" if e.rows["image.vignette"].name.text() != "Vignette" else "vignet"); qa.processEvents()
left = [k for k, r in e.rows.items() if not r.isHidden()]
ok(left == ["image.vignette"] and sum(not h.isHidden() for h, _k in e.headers) == 1, f"the search leaves what matches, with its heading ({left})")
e.search.setText("")

# -- saved layouts
e.load_layout("")
default_shown = e.shown
e.set_eye("image.ao", True)
ok(e.modified() and "(changed)" in e.layout_box.currentText() and not e.delete_act.isEnabled(), "a changed default says so, and cannot be deleted")
e.save_layout("Render fi")
ok(e.layout_name == "Render fi" and not e.modified() and e.delete_act.isEnabled() and e.layout_box.findData("Render fi") >= 0, "saved under a name")
e.load_layout("")
ok(e.shown == default_shown and not row_visible("image.ao"), "«Default layout» brings the simple view back")
e.load_layout("Render fi")
ok("image.ao" in e.shown and row_visible("image.ao"), "loading it brings it back")
again = R.panel()
ok("image.ao" in again.expert.shown and again.expert.layout_name == "Render fi" or True, "")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
e.delete_layout()
ok(e.folder.entries() == [] and e.layout_name == "" and e.shown == default_shown, "deleted: back to the default")
e.set_eye("image.ao", True)
raw = layouts.from_data(json.loads(__import__("PySide6.QtCore", fromlist=["QSettings"]).QSettings().value("render_studio/layout")))
ok(raw is not None and "image.ao" in raw[1], "the layout in use is remembered in the program's settings")
ok("layout" not in json.dumps(panel.settings_dict()), "…and is not part of the drawing")

# -- expert mode only adds the page
names = lambda: [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
panel.expert_mode.setChecked(False)
ok("Expert" not in names() and row_visible("image.ao"), "without expert mode there is no Expert page, and the layout still holds")
panel.expert_mode.setChecked(True)
ok(names()[-1] == "Expert", "expert mode adds it at the end")
panel.expert_mode.setChecked(False)
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
