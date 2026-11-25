"""Presets as files, the gallery and the ambients (offscreen, no Blender).
argv: <ingetrazo-src> <render-studio repo>"""
import json, os, sys, tempfile, zipfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HOME = tempfile.mkdtemp(); os.environ["RENDER_STUDIO_HOME"] = HOME
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from pathlib import Path
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QColor, QImage
import reference_cases as R
from render_studio import look_model as M, preset_files as F, preset_gallery as G, settings_store as S, user_presets

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

work = Path(tempfile.mkdtemp())
pano = work / "pati.hdr"; pano.write_bytes(b"HDR-bytes")
full = {"look": "golden_hour", "engine": "cycles", "quality": 2, "width": 3000, "section": {"cap": False}, "style": R._style(mode="watercolour"),
        "hdri": {"path": str(pano), "rotation": 40, "brightness": 0, "height": 2.5, "light": True},
        "sliders": {"clouds": 0.7, "dof": 0.5, "focus": 4.0}}
look = F.look_of(full)
ok(not set(F.NOT_OF_THE_LOOK) & set(look) and look["sliders"] == {"clouds": 0.7}, "a preset keeps the look: not the quality, the width, the section, the output or the camera")
now = S.clean({"look": "clear", "width": 800, "quality": 0, "sliders": {"dof": 0.9, "vignette": 0.5}})
worn = F.apply_to(now, look)
ok(worn["look"] == "golden_hour" and worn["width"] == 800 and worn["quality"] == 0 and worn["sliders"]["dof"] == 0.9 and worn["sliders"]["clouds"] == 0.7,
   "put on, it changes the look and leaves the width, the quality and the camera")
ok(abs(worn["sliders"]["vignette"] - 0.22) < 1e-6, "…a slider it does not name goes back to its look's value")

# the file: settings, thumbnail and pictures inside
file = work / "x.rspreset"
F.write(file, "Pati", full, b"PNG-thumb")
with zipfile.ZipFile(file) as z:
    names = set(z.namelist())
ok(names == {"preset.json", "thumb.png", "assets/hdri_pati.hdr"}, f"the file holds the settings, the thumbnail and the panorama ({sorted(names)})")
ok(str(work) not in zipfile.ZipFile(file).read("preset.json").decode() and "Users" not in zipfile.ZipFile(file).read("preset.json").decode(),
   "…and it says nothing of this computer's folders")
pano.unlink()
name, got, thumb = F.read(file, work / "out")
ok(name == "Pati" and thumb == b"PNG-thumb" and Path(got["hdri"]["path"]).read_bytes() == b"HDR-bytes" and Path(got["hdri"]["path"]).parent == work / "out",
   "read on another computer: the panorama comes out of the file")
bad = work / "bad.rspreset"
with zipfile.ZipFile(bad, "w") as z:
    z.writestr("preset.json", json.dumps({F.FILE_KEY: 2, "name": "x", "settings": dict(look, hdri={"path": "assets/../../evil.hdr"})}))
    z.writestr("assets/../../evil.hdr", b"evil")
F.read(bad, work / "safe" / "in")
ok(not (work / "evil.hdr").exists() and not (work / "safe" / "evil.hdr").exists(), "a file cannot write outside its folder")
(work / "junk.rspreset").write_text("junk")
ok(F.read(work / "junk.rspreset") is None, "what is not a preset is refused")
old = work / "vell.json"; old.write_text(user_presets.to_file("Vell", full), encoding="utf-8")
ok(F.read(old)[0] == "Vell", "a file exported by the version before is still read")

# the folder
folder = F.Folder(work / "mine")
p = folder.save("Meu: 1/2", look, b"t")
ok(p.parent == work / "mine" and p.is_file() and [e[1] for e in folder.entries()] == ["Meu: 1/2"], "any name makes a safe file name")
folder.save("Meu: 1/2", dict(look, look="night"))
ok(len(folder.entries()) == 1 and folder.load(p)[1]["look"] == "night" and folder.load(p)[2] == b"t", "saved again: the same file, its thumbnail kept")
q = folder.rename(p, "Altre")
ok(not p.exists() and [e[1] for e in folder.entries()] == ["Altre"], "renamed")
folder.duplicate("Altre", look)
ok([e[1] for e in folder.entries()] == ["Altre", "Altre 2"], "duplicated")
pano.write_bytes(b"HDR-bytes"); F.write(file, "Pati", full, b"PNG-thumb"); pano.unlink()
ok(folder.import_file(file) is not None and "Pati" in [e[1] for e in folder.entries()] and folder.import_file(work / "junk.rspreset") is None, "imported (junk is not)")
pati = folder.find("Pati")
ok(Path(folder.load(pati)[1]["hdri"]["path"]).read_bytes() == b"HDR-bytes", "…and its panorama is there to use")
renamed = folder.rename(pati, "Pati nou")
ok(Path(folder.load(renamed)[1]["hdri"]["path"]).read_bytes() == b"HDR-bytes", "…also after renaming it")
folder.delete(renamed)
ok(folder.find("Pati nou") is None and not folder.assets_of(renamed).exists(), "deleted with its pictures")
raw = user_presets.dump_all({"Antic": user_presets.make(full), "Altre": user_presets.make(full)})
ok(folder.migrate(raw) == 1 and "Antic" in [e[1] for e in folder.entries()], "the presets of before become files; one already there stays")

# the ones that come with it
built = F.builtins()
ok([k for k, _n, _s in built] == ["realistic", "white_model", "sketch", "watercolour", "plan", "lines", "lux"], "seven presets come with it")
ok(all((Path(REPO) / "render_studio" / "preset_thumbs" / f"{k}.png").is_file() for k, _n, _s in built), "…each with its thumbnail")
ok(M.from_v1(dict(built[2][2]))["background.paper_sky"] and M.from_v1(dict(built[4][2]))["background.kind"] == "flat" and M.from_v1(dict(built[6][2]))["surface.kind"] == "lux",
   "the sketch is on paper, the plan on a plain colour, the analysis shows lux")

# the gallery in the panel
panel = R.panel()
g = panel.gallery
ok(sum(b.isChecked() for b in panel.ambient.buttons.values()) == 1, "on opening, one light button says what will be rendered")
ok([g.list.item(i).text() for i in range(g.list.count())][:7] == ["Realistic", "White model", "Sketch", "Watercolour", "Plan on white", "Line drawing", "Light analysis"], "the gallery lists them")
panel.width.setValue(1234); panel.quality.setCurrentIndex(2)
for name, check in (("Sketch", lambda: panel.bg_mode.currentData() == "paper" and panel.style_groups.hand.value() > 0 and panel.shadow_draw.currentData() == "lines"),
                    ("Plan on white", lambda: panel.bg_mode.currentData() == "flat" and not panel.ground.isChecked()),
                    ("Line drawing", lambda: panel.style_groups.surface.currentData() == "paper" and panel.style_groups.outline.isChecked()
                     and panel.bg_mode.currentData() == "flat" and not panel.ground_shadow.isChecked() and panel.flat_settings()["color"] == [1.0, 1.0, 1.0]),
                    ("Watercolour", lambda: panel.style_groups.finish.currentData() == "watercolour" and panel.bg_mode.currentData() == "sky"),
                    ("Realistic", lambda: panel.style_groups.surface.currentData() == "real" and panel.shadow_draw.currentData() == "render" and panel.ground.isChecked())):
    g.apply_item(g.item(name)); qa.processEvents()
    ok(check() and panel.width.value() == 1234 and panel.quality.currentIndex() == 2, f"«{name}» puts its look on, and the width and quality stay")
acts = lambda it: [a.text() for a in g.menu_for(it).actions() if a.text()]
ok(acts(g.item("Sketch")) == ["Apply", "Duplicate", "Export…"], "a built-in one cannot be changed or deleted")
QInputDialog.getText = staticmethod(lambda *a, **k: ("El meu", True))
shot = QImage(640, 480, QImage.Format_RGB32); shot.fill(QColor(200, 30, 30))
panel.preview_picture = lambda: shot
g.save_current()
mine = g.item("El meu")
ok(mine is not None and acts(mine) == ["Apply", "Update with the current look", "Rename…", "Duplicate", "Export…", "Delete this preset"], "one of yours has them all")
img = QImage(); img.loadFromData(g.contents(mine)[2])
ok((img.width(), img.height()) == G.THUMB and img.pixelColor(10, 10).red() > 150, "its thumbnail is the preview's picture, cut to shape")
panel.preview_picture = lambda: None
asked = []
g.render_thumbnail = lambda path: asked.append(path)
g.keep("Sense")
ok(len(asked) == 1, "with no preview a small render is asked for")
g.export_item(g.item("El meu"), str(work / "export"))
ok((work / "export.rspreset").is_file(), "exported")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
g.delete_item(g.item("El meu"))
ok(g.item("El meu") is None, "deleted")
g.import_file(str(work / "export.rspreset"))
ok(g.item("El meu") is not None, "and imported again")

# the ambients: only the light
g.apply_item(g.item("Sketch"))
before = panel.style_settings(), panel.shadow_settings(), panel.bg_mode.currentData()
panel._sun_has_set = lambda: False
for look_key in ("overcast", "golden_hour", "night", "interior", "clear"):
    panel.ambient.buttons[look_key].click(); qa.processEvents()
    ok(panel.preset.currentData() == look_key and panel.ambient.buttons[look_key].isChecked()
       and (panel.style_settings(), panel.shadow_settings(), panel.bg_mode.currentData()) == before, f"ambient «{look_key}» changes the light and not the style")
panel._sun_has_set = lambda: True
panel._ambient_state()
ok(panel.ambient.buttons["night"].isChecked() and not panel.ambient.buttons["clear"].isChecked() and panel.ambient.note.text(), "with the sun down, «Night» is pressed and it says why")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
