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

from core.camera import OrbitCamera
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

pic = str(Path(tempfile.mkdtemp()) / "back.png")
img = QImage(32, 16, QImage.Format_RGB32); img.fill(QColor(20, 120, 200)); img.save(pic)

doc = Doc(); panel = P.StudioPanel(doc); doc.panels.append(panel)
panel.show()
TAB = {panel.tabs.tabText(i): i for i in range(panel.tabs.count())}
ok(list(TAB) == ['Main', 'Image', 'Environment', 'Section', 'Output'], f"the tabs: {list(TAB)}")
panel.tabs.setCurrentIndex(TAB['Environment'])
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
ok(all(panel.slider_rows[k].isVisible() for k in ("exposure_bias", "saturation", "vignette", "fog", "fog_start")),
   "Image: the simple sliders and the «Effects» group (vignette, depth of field, fog) are all in view")
# the camera group: three projections (big icons) and the angle of view, the 3D view's own
cam = doc.viewport.camera
panel.show(); P.QApplication.processEvents()
ok(set(panel.proj_buttons) == {"parallel", "perspective", "two_point"} and all(b.iconSize().width() >= 32 for b in panel.proj_buttons.values()), "the three projections are big buttons")
panel.proj_buttons["two_point"].click(); ok(cam.projection_mode() == "two_point", "…two-point puts the camera in two-point perspective")
panel.proj_buttons["parallel"].click(); ok(cam.projection_mode() == "parallel" and not panel.fov.isEnabled(), "…parallel has no angle of view")
panel.proj_buttons["perspective"].click(); ok(cam.projection_mode() == "perspective" and panel.fov.isEnabled(), "…perspective gives it back")
panel.fov.setValue(80.0); ok(abs(cam.fov_deg - 80.0) < 0.5, f"the angle-of-view slider sets the camera's ({cam.fov_deg})")
cam.fov_deg = 30.0; cam.set_projection("two_point"); panel.refresh_camera()
ok(abs(panel.fov.value() - 30.0) < 1.0 and panel.proj_buttons["two_point"].isChecked(), "…and follows the camera when it is changed elsewhere")
ok(all(panel.slider_rows[k].isVisible() for k in ("ao", "ao_distance")), "«Effects» has the ambient occlusion")
panel.tabs.setCurrentIndex(0); P.QApplication.processEvents()
ok(panel.tabs.indexOf(panel.tabs.currentWidget()) == 0 and panel.fov.isVisibleTo(panel) and panel.slider_rows["dof"].isVisibleTo(panel) and panel.slider_rows["focus"].isVisibleTo(panel), "the Camera group is in the Main tab with depth of field and the focal point")
cam.set_projection("perspective"); cam.fov_deg = 45.0; cam.distance = 10.0; d0 = cam.distance
panel.fov.setValue(90.0); ok(cam.distance < d0 * 0.6, f"a wider angle brings the camera closer: it is not a zoom ({d0} → {cam.distance:.2f})")
panel.fov.setValue(45.0); ok(abs(cam.distance - d0) < 0.5, "…and back again")
ok(panel.slider_rows["focus"].value_label.text() == "Auto", "the focal point reads Auto at 0")
panel.sliders["focus"].setValue(panel.sliders["focus"].maximum() // 10); ok(panel.slider_values()["focus"] > 0 and "m" in panel.slider_rows["focus"].value_label.text(), "…and metres otherwise")
ok([b.text() for b in panel.quality._buttons] == ["Draft", "Medium", "High"] and all(b.isVisibleTo(panel) for b in panel.quality._buttons), "Quality is three buttons in a row")
panel.quality.setCurrentIndex(2); ok(panel.quality.currentIndex() == 2 and panel.quality._buttons[2].isChecked(), "…one chosen")
ok(not panel.engine.isVisibleTo(panel) or panel.final_more.isExpanded() if hasattr(panel.final_more, "isExpanded") else True, "the engine is inside Advanced")
# the colour buttons show Blender's linear colours as the eye sees them, and what they hand back is linear again
from render_studio.section_panel import ColourButton as CB
cbn = CB([0.2, 0.2, 0.2], "t", linear=True)
shown = QColor(cbn.styleSheet().split("background-color:")[1].split(";")[0].strip())
ok(abs(shown.redF() - 0.484) < 0.02, f"a linear 0.2 is shown as the mid grey it renders as ({shown.redF():.2f})")
ok(all(abs(a - b) < 1e-3 for a, b in zip(CB._decode(cbn._shown([0.2, 0.05, 0.9])), [0.2, 0.05, 0.9])), "…and the chooser's colour goes back to linear")
panel.preset.setCurrentIndex(panel.preset.findData("white_model")); panel._ground_color = None; panel._swatches_follow()
ok(all(abs(a - b) < 1e-6 for a, b in zip(panel.ground_colour.rgb(), presets.studio("white_model")[0]["ground_color"])), "a ground colour not chosen shows the look's")
panel.skyline_type.setCurrentIndex(panel.skyline_type.findData("forest")); panel._skyline_color = None; panel._swatches_follow()
ok(panel.skyline_colour.rgb() == presets.SKYLINE_COLOURS["forest"], "…and a skyline's, the type's")
panel.skyline_type.setCurrentIndex(0); panel.preset.setCurrentIndex(panel.preset.findData("clear"))
ok(panel.slider_rows["dof"].slider.property("hi") == 1.0 and "dof" in panel.slider_values(), "depth of field is a slider of the panel")
panel.tabs.setCurrentIndex(TAB["Environment"])
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

# ---- the ground's material, the sun's group, «Lights the scene» out of the fold ---------------------
from core.group import Group
from core.mesh import Mesh
from core.materials import Material
from PySide6.QtGui import QVector3D
doc.scene.materials["Paving"] = Material("Paving", color=(0.5, 0.5, 0.5), texture={"path": pic, "sw": 1.5, "sh": 1.5})
mm = Mesh(); mm.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0)]).attrs["mat"] = "Paving"
doc.scene.groups.append(Group(mm, name="slab")); doc.scene.version += 1
panel.ground_material._fill = None
panel._fill_ground_materials()
ok(panel.ground_material.currentData() == "" and panel.ground_material.findData("Paving") >= 0, "the ground's list offers the look's colour and the model's materials")
ok(panel.ground_material_settings() is None, "the look's colour: no material in the settings")
panel.ground_material.setCurrentIndex(panel.ground_material.findData("Paving")); panel.ground_tile.setValue(3.0)
gm = panel.settings_dict()["ground_material"]
ok(gm == {"name": "Paving", "tile": 3.0}, f"the choice is in the settings ({gm})")
ok(SS.clean(panel.settings_dict())["ground_material"] == gm and SS.clean({"look": "clear", "ground_material": {"name": ""}})["ground_material"] is None, "…and survives the document's cleaning")
blk = P.apply_ground_material({}, doc.scene, gm)["ground_material"]
ok(blk["tile"] == [3.0, 3.0] and blk["name"] == "Paving", "the job asks for the tile size chosen")
blk = P.apply_ground_material({}, doc.scene, {"name": "Paving", "tile": 0.0})["ground_material"]
ok(blk["tile"] == [1.5, 1.5], "tile size 0 takes the picture's own size")
doc.scene.materials["Paving stone"] = Material("Paving stone", color=(0.5, 0.5, 0.5))
ok(P.apply_ground_material({}, doc.scene, {"name": "Paving stone", "tile": 1.0}).get("ground_material", {}).get("name") == "Paving_stone",
   "a material painted on nothing is put on the ground all the same (Blender makes it from its picture and settings)")
ps = Mesh(); ps.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0)]).attrs["mat"] = "Paving stone"
doc.scene.groups.append(Group(ps, name="stone")); doc.scene.version += 1
ok(P.apply_ground_material({}, doc.scene, {"name": "Paving stone", "tile": 1.0})["ground_material"]["name"] == "Paving_stone",
   "Blender is asked for the material under the name the export gives it (spaces become _)")
hd = P.apply_hdri({}, {"path": pic, "rotation": 0, "strength": 1.0, "light": True})
ok("hdri" in hd, "(a 360° background in the job)")
panel.apply_settings(dict(panel.settings_dict(), ground_material=None))
ok(panel.ground_material.currentData() == "" and panel.ground_tile.value() == 0.0, "applying settings with no ground material clears it")
panel.ground.setChecked(False)
ok(not panel.ground_more.isEnabled(), "no generated ground: its advanced part is off")
panel.ground.setChecked(True)
box_titles = {g.title(): g for g in panel.findChildren(P.QGroupBox)}
ok(panel.sun_more.parentWidget() is not None and box_titles["Sky"].isAncestorOf(panel.sun_more), "the sun's place and date are inside the sun group")
panel.bg_mode.setCurrentIndex(panel.bg_mode.findData("pano"))
ok(not box_titles["Background"].isAncestorOf(panel.hdri_light) is False and not panel.bg_more.isAncestorOf(panel.hdri_light), "«Lights the scene» is out of the advanced fold…")
ok(panel.bg_more.isAncestorOf(panel.hdri_rotation_row) and panel.bg_more.isAncestorOf(panel.hdri_strength_row), "…and rotation and brightness are in it")

# ---- the ground types ---------------------------------------------------------------------------
ok(panel.ground_type.itemData(0) == "" and panel.ground_type.findData("wet") >= 0 and panel.ground_type.findData("custom") >= 0, "the ground has types: the look's own, grass, asphalt…, custom")
panel.ground_type.setCurrentIndex(panel.ground_type.findData("grass")); panel._ground_type_chosen(0)
gl = panel.ground_look_settings()
ok(gl["type"] == "grass" and gl["color"] == presets.GROUND_TYPES["grass"][1] and abs(gl["roughness"] - 0.95) < 0.011, f"a type puts its colour and roughness in the controls ({gl})")
blk = P.apply_ground_look({}, gl)
ok(blk["ground_color"] == gl["color"] and abs(blk["ground_roughness"] - 0.95) < 0.011 and "haze_scale" not in blk and "ground_offset" not in blk, "the job gets the colour and roughness, nothing else that is usual")
panel.ground_rough.setValue(int(round(0.3 * panel.ground_rough.maximum())))
ok(panel.ground_type.currentData() == "custom", "changing the roughness by hand makes it Custom")
panel.ground_haze.setValue(0); panel.ground_offset.setValue(-0.2)
blk = P.apply_ground_look({}, panel.ground_look_settings())
ok(blk["haze"] is False and abs(blk["ground_offset"] + 0.2) < 1e-6, "haze 0 turns it off; the offset is sent")
st2 = panel.settings_dict()
ok(SS.clean(st2)["ground_look"] == SS.ground_look(st2["ground_look"]), "the ground's look survives cleaning")
panel.ground_type.setCurrentIndex(panel.ground_type.findData("")); panel._ground_type_chosen(0)
ok(panel.ground_look_settings()["color"] is None, "the look's own: no colour of its own")
panel.apply_settings(st2)
ok(panel.ground_type.currentData() == "custom" and panel.ground_look_settings() == st2["ground_look"], "applying settings puts the ground's look back")
ok(SS.ground_look({"type": "nonsense", "color": "x", "roughness": 9, "haze": -1, "offset": 99}) == {"type": "", "color": None, "roughness": 1.0, "haze": 0.0, "offset": 10.0, "grass_radius": 0.0, "ground_radius": 0.0}, "junk in the ground's look is cleaned")
panel.ground_grass.setValue(35)
ok(panel.ground_look_settings()["grass_radius"] == 35.0 and P.apply_ground_look({}, panel.ground_look_settings())["ground_grass_radius"] == 35.0,
   "the grass radius is in the ground's look and in the job")
ok("ground_grass_radius" not in P.apply_ground_look({}, dict(panel.ground_look_settings(), grass_radius=0.0)), "0 is automatic: nothing is sent")
panel.apply_settings(dict(panel.settings_dict(), ground_look=dict(panel.ground_look_settings(), grass_radius=15.0)))
ok(panel.ground_grass.value() == 15.0, "applying settings puts the grass radius back")

# the grass radius: the note says how far the density reaches; the constant is the render's
from render_studio import materials as _M
src_s = open(os.path.join(REPO, "render_studio", "blender", "studio_scene.py"), encoding="utf-8").read()
ok(f"GRASS_MAX_TUFTS = {_M.GRASS_MAX_TUFTS:_}" in src_s, "the panel and the render agree on the tuft limit")
ok(abs(_M.grass_reach(260.0) - 27.0) < 0.5, f"260 tufts/m2 reach {_M.grass_reach(260.0):.0f} m")

# ---- the horizon: a skyline of mountains, hills, forest or city ----------------------------------------------------------------------
ok(panel.skyline_type.itemData(0) == "" and [panel.skyline_type.itemData(i) for i in range(1, 5)] == ["mountains", "hills", "forest", "city"], "the horizon offers none, mountains, hills, forest and city")
panel.ground.setChecked(True)
ok(not panel.skyline_height.isEnabled(), "with no skyline chosen its height is off")
panel.skyline_type.setCurrentIndex(panel.skyline_type.findData("mountains")); panel.skyline_height.setValue(6.5); panel.skyline_seed.setValue(7)
ok(panel.skyline_height.isEnabled() and panel.skyline_settings() == {"type": "mountains", "height": 6.5, "distance": 0.0, "seed": 7, "color": None}, f"choosing one: {panel.skyline_settings()}")
panel.skyline_distance.setValue(800)
blk = P.write_studio_job.__defaults__ and None
st3 = panel.settings_dict()
ok(SS.clean(st3)["skyline"] == SS.skyline(st3["skyline"]) and st3["skyline"]["type"] == "mountains", "it is in the document's settings")
panel.apply_settings(dict(st3, skyline={"type": "city", "height": 3.0, "distance": 0, "seed": 2, "color": [0.1, 0.2, 0.3]}))
ok(panel.skyline_type.currentData() == "city" and panel.skyline_height.value() == 3.0 and panel.skyline_settings()["color"] == [0.1, 0.2, 0.3], "applying settings puts it back")
panel.ground.setChecked(False)
ok(not panel.skyline_type.isEnabled() and panel.skyline_note.text(), "with no generated ground the skyline is off and says why")
panel.ground.setChecked(True)
ok(SS.skyline({"type": "volcano", "height": 99, "seed": -4, "color": "red"}) == {"type": "", "height": 20.0, "distance": 0.0, "seed": 0, "color": None}, "junk in the skyline is cleaned")

# ---- the style: none, white, model, light, sketch, watercolour -----------------------------------------------------------------------------
ok([panel.style_mode.itemData(i) for i in range(panel.style_mode.count())] == ["none", "white", "model", "light", "sketch", "watercolour"], "the styles: none, white, model, light, sketch, watercolour")
TABW = panel.tabs.widget(0).widget()
def shown(w):
    return w.isVisibleTo(TABW)
panel.style_mode.setCurrentIndex(panel.style_mode.findData("none")); qa.processEvents()
ok(shown(panel.style_width) and not shown(panel.style_lux) and not shown(panel.style_noise) and not shown(panel.style_wet) and not shown(panel.style_material), "None: only the outlines' thickness")
ok(not shown(panel.style_colour_box), "…and the outlines' colour only when there are outlines")
panel.style_width.setValue(2.0); qa.processEvents()
ok(shown(panel.style_colour_box), "…it appears with a line")
panel.style_mode.setCurrentIndex(panel.style_mode.findData("model")); qa.processEvents()
ok(shown(panel.style_material) and shown(panel.style_model_colour) and not shown(panel.style_lux), "Model: the material and the colour")
panel.style_mode.setCurrentIndex(panel.style_mode.findData("light")); qa.processEvents()
ok(shown(panel.style_lux) and not shown(panel.style_material), "Light: the scale")
panel.style_mode.setCurrentIndex(panel.style_mode.findData("sketch")); qa.processEvents()
ok(shown(panel.style_noise) and shown(panel.style_extend) and shown(panel.style_colour_box), "Sketch: irregular stroke, line extension and the colour")
panel.style_mode.setCurrentIndex(panel.style_mode.findData("watercolour")); qa.processEvents()
ok(shown(panel.style_wet) and shown(panel.style_edges) and shown(panel.style_paper) and not shown(panel.style_noise), "Watercolour: wetness, edges and paper")
panel.style_mode.setCurrentIndex(panel.style_mode.findData("white")); qa.processEvents()
ok(panel.style_width.value() > 0.0 and not shown(panel.style_noise), "White: a thin outline by default")
panel.style_mode.setCurrentIndex(panel.style_mode.findData("none")); qa.processEvents()
ok(panel.style_width.value() == 0.0, "None goes back to no outlines")
panel.style_mode.setCurrentIndex(panel.style_mode.findData("sketch")); panel.style_noise.setValue(0.8); panel.style_extend.setValue(0.3)
stl = panel.settings_dict()["style"]
ok(stl["mode"] == "sketch" and stl["noise"] == 0.8 and stl["extend"] == 0.3 and SS.clean(panel.settings_dict())["style"] == SS.style(stl), "the style is in the document's settings")
blk = P.apply_style_block({}, doc.scene, stl)["style"]
ok(blk["mode"] == "sketch" and blk["noise"] == 0.8 and "wetness" not in blk and "lux_max" not in blk, "the job carries only what the style uses")
ok(P.apply_style_block({}, doc.scene, {"mode": "none", "width": 0}) == {}, "no style, no outlines: nothing in the job")
ok(P.apply_style_block({}, doc.scene, {"mode": "none", "width": 3})["style"]["width"] == 3.0, "outlines alone are a style of the job")
doc.scene.materials["Cardboard"] = Material("Cardboard", color=(0.7, 0.6, 0.4))
mm2 = Mesh(); mm2.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0)]).attrs["mat"] = "Cardboard"
doc.scene.groups.append(Group(mm2, name="card")); doc.scene.version += 1
mb = P.apply_style_block({}, doc.scene, {"mode": "model", "material": "Cardboard", "width": 1})["style"]
ok(mb["material"] == "Cardboard" and mb["model_color"] == [0.7, 0.6, 0.4], "a model of a drawing's material carries its name and colour")
panel._fill_style_materials()
ok(panel.style_material.findData("Cardboard") >= 0 and panel.style_material.itemData(0) == "", "the Model's list: «A colour» and the drawing's materials")
panel.apply_settings(dict(panel.settings_dict(), style={"mode": "watercolour", "width": 0.0, "wetness": 0.9, "paper": 0.2, "edges": 0.1}))
ok(panel.style_mode.currentData() == "watercolour" and panel.style_wet.value() == 0.9, "applying settings puts the style back")
ok(SS.style({"mode": "oil", "width": 99, "noise": -3, "color": "x"})["mode"] == "none" and SS.style({"width": 99})["width"] == 4.0, "junk in the style is cleaned")
if len(sys.argv) > 3:
    for name in ("Main", "Image", "Environment"):
        panel.tabs.setCurrentIndex(TAB[name]); panel.resize(320, 700); panel.grab().save(sys.argv[3].replace(".png", f"_{name}.png"))
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
