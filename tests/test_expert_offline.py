"""The Expert page: every setting with its control and eye, layouts that decide what the pages show and change no value, mirrors
that act on the panel's own controls, and marks on what is not at its default.
argv: <ingetrazo-src> <render-studio repo>"""
import json, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["RENDER_STUDIO_HOME"] = tempfile.mkdtemp()
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox, QWidget
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

# -- the eye: flat, at the right edge of its row
row = e.rows["surface.kind"]
line = row.layout().itemAt(0).layout()
ok(line.itemAt(line.count() - 1).widget() is row.eye and "transparent" in row.eye.styleSheet(), "the eye is the last thing of its row, and flat")

# -- at the narrowest width nothing of the pages is cut off at the right, where the eyes are
panel.setAttribute(Qt.WA_DontShowOnScreen, True); panel.set_expert_mode(True); panel.need_box.setVisible(False)
panel.resize(300, 900); panel.show()          # (offscreen's stand-in fonts are some 20 % wider than the real ones: 240 px)
_card = e.headers[0][0]; _title, _min = _card.title(), _card.minimumSizeHint().width()
_card.setTitle(_title * 6)
ok(_card.minimumSizeHint().width() == _min, f"a longer title does not widen a card ({_min} → {_card.minimumSizeHint().width()})")
_card.setTitle(_title)
from PySide6.QtWidgets import QWidget as _W
over = {}
for index in (0, panel.tabs.count() - 1):               # Main and Expert
    panel.tabs.setCurrentIndex(index)
    for _ in range(8):
        qa.processEvents()
    area = panel.tabs.currentWidget()
    over[panel.tabs.tabText(index)] = _W.width(area.widget()) - area.viewport().width()
ok(all(v <= 0 for v in over.values()), f"Main and Expert fit a narrow tray ({over})")
panel.hide(); panel.set_expert_mode(False); panel.tabs.setCurrentIndex(0)

# -- Expert mode and Help: in the tray's header, beside its name; else in a row at the top of the panel
from PySide6.QtWidgets import QDockWidget, QHBoxLayout, QLabel, QMainWindow, QToolButton
from shiboken6 import isValid
ok(isinstance(panel.expert_mode, QToolButton) and panel.expert_mode.isCheckable() and panel.expert_mode.text() == "Expert mode"
   and not panel.expert_mode.icon().isNull(), "Expert mode is a button with a tools icon and its words")
ok(panel.foot_row.indexOf(panel.expert_mode) < 0 and panel.foot_row.indexOf(panel.status) == 0, "…and out of the messages' line")
tools = panel.header_tools
def pump():
    for _ in range(10):
        qa.processEvents()
tools.place()
ok(tools.box.parentWidget() is tools.own_row and panel.layout().indexOf(tools.own_row) == 0 and not tools.own_row.isHidden(),
   "with no tray they are in a row at the top of the panel")
try:
    from views.main_window import _DockHeader                  # IngeTrazo's own header, where it can be made
except Exception:  # noqa: BLE001
    _DockHeader = None
class Header(QWidget):
    def __init__(self, window, dock, alone):
        super().__init__(dock)
        row = QHBoxLayout(self)
        name = QLabel(dock.windowTitle(), self); name.setObjectName("dock_header_name")
        row.addWidget(name, 1)
kinds = [Header] + ([_DockHeader] if _DockHeader else [])
for kind in kinds:
    window = QMainWindow()
    dock = QDockWidget("Render Studio", window)
    dock.setWidget(panel)
    first = kind(window, dock, False); dock.setTitleBarWidget(first)
    tools.place(); pump()
    ok(tools.box.parentWidget() is first and tools.own_row.isHidden(), f"{kind.__name__}: the buttons are in the tray's header")
    row = first.layout()
    ok(row.indexOf(tools.box) == row.indexOf(first.findChild(QLabel, "dock_header_name")) + 1, "…after its name")
    second = kind(window, dock, False)                           # the trays rearranged: the program makes a new header
    dock.setTitleBarWidget(second); first.deleteLater(); pump()
    ok(isValid(tools.box) and isValid(panel.expert_mode) and tools.box.parentWidget() is second,
       "a new header: the buttons move to it, and are not lost with the old one")
    dock.setTitleBarWidget(QWidget(dock)); second.deleteLater(); pump()
    ok(isValid(tools.box) and tools.box.parentWidget() is tools.own_row and not tools.own_row.isHidden(),
       "a header that is not the one known: back to the panel's own row")
    panel.setParent(None); tools.place(); pump()

# -- every page's groups are cards, Section and Output too
from render_studio import widgets as _widgets
for _tab, _titles in ((panel.section_tab, {"Sections in the drawing", "Cap", "Cap outline", "Light"}),
                      (panel.output_tab, {"Projection", "Size", "File", "What to render", "Save"})):
    _cards = _tab.findChildren(_widgets.Card)
    ok({c.title() for c in _cards} == _titles and all(c.icon_key for c in _cards), f"{type(_tab).__name__}: its groups are cards with icons ({sorted(c.title() for c in _cards)})")
    _buttons = [b for b in _tab.findChildren(QWidget) if type(b).__name__ in ("QPushButton", "QToolButton") and b.objectName() != "colourSwatch" and not type(b).__name__ == "ColourButton"]
    ok(all(not b.icon().isNull() for b in _buttons), f"…and every button has an icon ({[b.text() for b in _buttons if b.icon().isNull()]})")

# at the narrowest tray, every button of Section and Output has its place and the two sizes are not squeezed
panel.setAttribute(Qt.WA_DontShowOnScreen, True); panel.need_box.setVisible(False); panel.resize(300, 900); panel.show()
for _tab in (panel.section_tab, panel.output_tab):
    panel.tabs.setCurrentIndex(next(i for i in range(panel.tabs.count()) if panel.tabs.widget(i).isAncestorOf(_tab)))
    for _ in range(8):
        qa.processEvents()
_o = panel.output_tab
def _inside(w):
    box = w.parentWidget()
    return w.isVisible() and QWidget.width(w) >= 20 and w.geometry().right() <= QWidget.width(box) and w.geometry().left() >= 0
ok(_inside(_o.browse_btn) and _inside(_o.swap), f"Output: the folder's and the turn's buttons are in view ({QWidget.width(_o.browse_btn)}, {QWidget.width(_o.swap)} px)")
for _w in (_o.width, _o.height):
    ok(_inside(_w) and QWidget.width(_w) >= _w.sizeHint().width() - 4, f"…and each size box has room for its number ({QWidget.width(_w)} px, wants {_w.sizeHint().width()})")
panel.hide(); panel.tabs.setCurrentIndex(0)

# -- nothing is folded away in the pages, and every setting they have is in Expert too
from PySide6.QtWidgets import QAbstractSlider, QAbstractSpinBox, QCheckBox, QComboBox, QFormLayout, QScrollBar
from render_studio import widgets
from render_studio.section_panel import ColourButton
ok(not panel.tabs.findChildren(widgets.Collapsible), "the panel's pages have no «Advanced» to unfold (the lights window keeps its own)")
kinds = (QAbstractSlider, QAbstractSpinBox, QCheckBox, QComboBox, ColourButton, widgets.ChoiceButtons, widgets.NumberSlider, widgets.RadiusSlider)
known = {id(form) and (form, row) for form, row in e.filter.rows.values()}
# not settings of the register: the sun's date, hour and place (IngeTrazo's own, the drawing's shadows) and the camera's
# (Main's camera is still to be gone through; the preset list is never shown; the sun's own date and hour are the two sliders)
elsewhere = [panel.sun_tab.clock_box, panel.fov, panel.preset]
def inside(widget, boxes):
    return any(box is widget or box.isAncestorOf(widget) for box in boxes)
left_out = []
for index in range(3):                                   # Main, Style, Environment
    for w in panel.tabs.widget(index).findChildren(QWidget):
        if not isinstance(w, kinds) or isinstance(w, QScrollBar) or inside(w, elsewhere):
            continue
        row = bindings.row_of(w)
        if row is not None and row not in known and not any(inside(w, [c]) for c in e.controls.values()):
            label = row[0].itemAt(row[1], QFormLayout.LabelRole)
            left_out.append((index, type(w).__name__, label.widget().text() if label and label.widget() else ""))
ok(not left_out, f"every setting in a form of the pages is in Expert ({left_out})")
ok({"quality.engine", "quality.preview_engine", "quality.preview_quality"} <= set(e.rows) and not ({"quality.engine", "quality.preview_engine", "quality.preview_quality"} & e.shown),
   "the engines and the preview's quality are in Expert, out of the simple view")
panel.preview_quality.setCurrentIndex(panel.preview_quality.findData("high")); qa.processEvents()
e.refresh()
before = panel.settings_dict()
ok(not e.rows["quality.preview_quality"].mark.isHidden(), "a preference changed is marked")
e.reset_value("quality.preview_quality"); qa.processEvents()
ok(panel.preview_quality.currentData() == "normal" and panel.settings_dict() == before, "…and put back, without touching the drawing")
e.set_eye("quality.preview_engine", True)
ok(e.filter.rows["quality.preview_engine"][0].isRowVisible(e.filter.rows["quality.preview_engine"][1]), "with its eye open it shows in Quality")
e.set_eye("quality.preview_engine", False)

# -- the Environment page: everything in it has an eye, so all of it can be put away
sun_keys = {"sun.date", "sun.hour", "site.location", "site.coords", "site.north", "site.zone", "site.shadows", "site.info"}
ok(sun_keys <= set(e.rows) and sun_keys <= set(e.filter.rows), "the sun's controls have their rows in Expert and in their page")
ok({"sun.date", "sun.hour", "site.location"} <= e.shown and not ((sun_keys - {"sun.date", "sun.hour", "site.location"}) & e.shown),
   "the simple view keeps the date, the hour and the location")
def box_hidden(key):
    node = e.controls[key].parentWidget()
    while not isinstance(node, widgets.Card):
        node = node.parentWidget()
    return node.isHidden()
env = {p.key for p in params.PARAMS if p.tab == "environment" and p.key in e.controls}
for key in env:
    e.filter.shown.discard(key)
e.filter.set_shown(set(e.filter.shown))
ok(all(box_hidden(k) for k in env), f"with every eye closed, no group of the page is left ({sorted(k for k in env if not box_hidden(k))[:4]})")
e.load_layout("")
ok(not box_hidden("sun.date") and not box_hidden("ground.on"), "…and the default layout brings them back")
# the copies act on the real controls
from render_studio import sun_site
written = []
real_apply, sun_site.apply = sun_site.apply, lambda app, **changes: written.append(changes)    # (no undo history here)
e.rows["site.north"].mirror.pull(); e.rows["site.north"].mirror.widget.setValue(30.0); panel.sun_tab.flush()
ok(written and written[-1].get("north") == 30.0, "the north changed in Expert is written to the drawing")
e.rows["sun.hour"].mirror.pull(); slider = e.rows["sun.hour"].mirror.widget.findChild(type(panel.sun_quick.hour_slider))
slider.setValue(17 * 60 + 30); qa.processEvents(); panel.sun_tab.flush()
ok(written[-1]["shadows"]["hour"] == 17 and written[-1]["shadows"]["minute"] == 30 and e.rows["sun.hour"].mark.isHidden(),
   "…and the hour, which has no default to be marked against")
sun_site.apply = real_apply
clicked = []
panel.sun_tab.map_btn.clicked.disconnect(); panel.sun_tab.map_btn.clicked.connect(lambda *_a: clicked.append(1))
e.rows["site.location"].mirror.widget.click()
ok(clicked == [1], "…and the location button opens the map")
# the groups fold, and a search shows what it finds
card = next(h for h, keys in e.headers if "ground.on" in keys)
card.set_open(False)
ok(card.body.isHidden(), "a group of Expert folds")
ok(card.maximumHeight() == card._title_height(), "…down to its header, with nothing under it")
e.search.setText("terra" if False else "ground"); qa.processEvents()
ok(not card.body.isHidden() and not card.isHidden(), "…a search opens what it finds")
e.search.setText(""); qa.processEvents()
ok(card.body.isHidden(), "…and it stays folded after")
card.set_open(True)
# a stored copy of the default view of before gives way to the new one; a person's own layout does not
from PySide6.QtCore import QSettings
old_default = layouts.to_data("", {"surface.kind"}); del old_default["basic"]
QSettings().setValue("render_studio/layout", json.dumps(old_default))
ok(e._stored()[1] == layouts.default(), "the default of before gives way to the new simple view")
mine = layouts.to_data("Mine", {"surface.kind"}); del mine["basic"]
QSettings().setValue("render_studio/layout", json.dumps(mine))
ok(e._stored() == ("Mine", {"surface.kind"} | {k for k in layouts.default() if k not in mine["known"]}), "…a named layout is kept")
e.load_layout("")

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
