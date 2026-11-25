"""The finer settings (``Param.extra``): made from the register alone, kept in the document only when not at their default, part
of a preset (with their pictures), shown in their group and in the Expert page, and sent to Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import json, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["RENDER_STUDIO_HOME"] = tempfile.mkdtemp()
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from pathlib import Path
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
import reference_cases as R
from render_studio import look_model, params, preset_files as F, settings_store as S

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

# -- the register and the document
ok(params.EXTRA_KEYS and all(params.BY_KEY[k].extra for k in params.EXTRA_KEYS), f"the finer settings are marked ({len(params.EXTRA_KEYS)})")
ok(all(set(params.CHOICE_NAMES[k]) == set(params.BY_KEY[k].choices) for k in params.EXTRA_KEYS if params.BY_KEY[k].kind == "choice"),
   "every choice has its name")
for key in params.EXTRA_KEYS:
    p = params.BY_KEY[key]
    if p.kind in ("number", "int") and p.default is not None:
        steps = (p.default - p.lo) / (p.step or 0.05)
        ok(abs(steps - round(steps)) < 1e-6, f"{key}: the default is a position of its slider")
plain = S.clean({"look": "clear"})
ok("fine" not in plain and "fine" not in look_model.to_v1(look_model.from_v1(plain), plain), "a drawing that uses none is saved as before")
asked = {"finish.texture": "canvas", "finish.texture_strength": 7, "finish.texture_scale": 1.0, "nothing": 1, "finish.kind": "watercolour"}
kept = S.clean({"look": "clear", "fine": asked})["fine"]
ok(kept == {"finish.texture": "canvas", "finish.texture_strength": 1.0}, f"kept: made safe, only what is not at its default ({kept})")
ok("fine" not in S.clean({"look": "clear", "fine": {"finish.texture": "marble"}}), "an unknown choice is the default")
model = look_model.from_v1({"look": "clear", "fine": kept})
ok(model["finish.texture"] == "canvas" and look_model.to_v1(model)["fine"] == kept, "to the new model and back")

# -- the panel
panel = R.panel()
fine, e = panel.fine, panel.expert
def row_visible(key):
    control, form = fine.rows[key]
    return form.isRowVisible(control)
ok(set(fine.rows) == set(params.EXTRA_KEYS) and set(params.EXTRA_KEYS) <= set(e.rows), "each has its control and its row in Expert")
ok("fine" not in panel.settings_dict(), "the untouched panel keeps none")
ok(row_visible("finish.texture") and not row_visible("finish.texture_strength") and not row_visible("finish.texture_path"),
   "with no texture, only its choice shows")
fine.control("finish.texture").setCurrentIndex(fine.control("finish.texture").findData("paper")); qa.processEvents()
ok(panel.settings_dict().get("fine") == {"finish.texture": "paper"}, f"chosen: it is kept ({panel.settings_dict().get('fine')})")
ok(row_visible("finish.texture_strength") and not row_visible("finish.texture_path"), "…its strength and size show")
fine.control("finish.texture_strength").setValue(0.8); qa.processEvents()
ok(panel.settings_dict()["fine"]["finish.texture_strength"] == 0.8, "…and its strength is kept")
e.refresh(); qa.processEvents()
ok(e.rows["finish.texture_strength"].mark.isVisibleTo(e.rows["finish.texture_strength"]), "Expert marks what is not at its default")
e.reset_value("finish.texture_strength"); qa.processEvents()
ok(panel.settings_dict()["fine"] == {"finish.texture": "paper"}, "…and puts it back")
e.rows["finish.texture"].mirror.pull()
mirror = e.rows["finish.texture"].mirror.widget
mirror.setCurrentIndex(mirror.findData("rough")); mirror.activated.emit(mirror.currentIndex()); qa.processEvents()
ok(panel.settings_dict()["fine"]["finish.texture"] == "rough", "the copy in Expert acts on the panel's control")
e.set_eye("finish.texture", False)
ok(not row_visible("finish.texture"), "an eye closed takes it out of its page")
e.set_eye("finish.texture", True)
ok(row_visible("finish.texture"), "…and open puts it back")

# -- the job
job, _script = panel.live_job(Path(tempfile.mkdtemp()), 320, 180)
block = json.loads(job.read_text(encoding="utf-8"))["studio"]
ok(block.get("fine") == {"finish.texture": "rough"}, f"it goes to Blender ({block.get('fine')})")
panel.apply_settings({"look": "clear"}); qa.processEvents()
job, _script = panel.live_job(Path(tempfile.mkdtemp()), 320, 180)
ok("fine" not in json.loads(job.read_text(encoding="utf-8"))["studio"], "an untouched job says nothing of them")
panel.apply_settings({"look": "clear", "fine": {"finish.texture": "image"}}); qa.processEvents()
job, _script = panel.live_job(Path(tempfile.mkdtemp()), 320, 180)
ok("fine" not in json.loads(job.read_text(encoding="utf-8"))["studio"], "a picture texture with no picture is left out")

# -- the light and the picture
def studio_block(**extra):
    panel.apply_settings(dict({"look": "clear"}, **extra)); qa.processEvents()
    job, _script = panel.live_job(Path(tempfile.mkdtemp()), 320, 180)
    return json.loads(job.read_text(encoding="utf-8"))["studio"]
base = studio_block()
b = studio_block(fine={"image.kelvin": 9000, "image.tint": 20, "image.contrast": "punchy", "image.bloom": 0.3, "image.exposure_target": 0.2,
                       "sky.cloud_scale": 2.0, "sky.cloud_seed": 5, "shadows.softness": 6, "surface.albedo_cap": 0.9},
                 sliders={"warmth": 0.5})
ok(b["white_balance"] == 9750 and b["tint"] == 30 and b["looks"] == ["AgX - Punchy"] and b["bloom"] == 0.3 and b["exposure_target"] == 0.2,
   "the picture's settings take the look's place, and the warmth adds to the balance")
ok(b["cloud_scale"] == 0.5 and b["cloud_seed"] == 5, "twice the cloud size is half Blender's noise scale")
ok(b["sun_angle"] == 6 and b["sun_jitter"] and b["albedo_cap"] == 0.9 and "sun_jitter" not in base, "a soft edge asks EEVEE for it too")
golden = {"sky.golden_elevation": 15}
ok(studio_block(look="golden_hour", fine=golden)["sun_elevation"] == 15 and studio_block(fine=golden).get("sun_elevation") == base.get("sun_elevation"),
   "the golden hour's sun height only in the golden hour")
panel.apply_settings({"look": "golden_hour"}); qa.processEvents()
ok(row_visible("sky.golden_elevation") or "sky.golden_elevation" not in e.shown, "…and its row only then")
ok(studio_block() == base, "back to the defaults, the job is as before")

# -- the transparent background (a plain colour that is not painted)
see = {"color": [1.0, 1.0, 1.0], "transparent": True}
kept = S.clean({"look": "clear", "flat": see})
ok(kept["flat"] == see and S.clean({"look": "clear", "flat": {"color": [1, 1, 1], "transparent": False}})["flat"] == {"color": [1.0, 1.0, 1.0]},
   "transparent is kept, and only when it is so")
model = look_model.from_v1(kept)
ok(model["background.kind"] == "transparent" and look_model.to_v1(model)["flat"] == see, "…to the new model and back")
block = studio_block(flat=see, ground=False)
ok(panel.bg_mode.currentData() == "transparent" and panel.settings_dict()["flat"] == see and block["flat"]["transparent"] and panel.ground_shadow.isEnabled(),
   "chosen in the panel: it goes to Blender, and the shadow on the floor is offered")
panel.output_tab.format.setCurrentIndex(panel.output_tab.format.findData("jpeg"))
panel._background_chosen(panel.bg_mode.currentIndex())
ok(panel.output_tab.format.currentData() == "png", "choosing it takes the output off JPEG, which has no transparency")
panel.apply_settings({"look": "clear", "flat": {"color": [1, 1, 1]}}); qa.processEvents()
ok(panel.bg_mode.currentData() == "flat", "a plain colour is still a plain colour")

# -- the line round the shadows
block = studio_block(fine={"shadows.outline": 1.5}, style={"mode": "none", "width": 0, "color": [0.0, 0.0, 1.0]})
ok(block["fine"] == {"shadows.outline": 1.5} and block["shadow_ink"] == [0.0, 0.0, 1.0] and "shadows.outline" in panel.expert.shown,
   f"a shadow outline goes to Blender with the outlines' ink, and shows in the simple view ({block.get('shadow_ink')})")
ok("shadow_ink" not in studio_block(), "with none, the job says nothing of it")
import json as _json
_ca = _json.load(open(os.path.join(REPO, "render_studio", "locales", "ca.json"), encoding="utf-8-sig"))
_twice = [p.special for p in params.PARAMS if p.special and _ca.get(_ca.get(p.special, ""), None) not in (None, _ca.get(p.special))]
ok(not _twice, f"no slider's word translates into another English word that would be translated again ({_twice})")

# -- presets
folder = Path(tempfile.mkdtemp())
picture = folder / "paper.png"
img = QImage(64, 64, QImage.Format_RGB32); img.fill(QColor("#bbbbbb")); img.save(str(picture))
settings = {"look": "clear", "fine": {"finish.texture": "image", "finish.texture_path": str(picture)}}
F.write(folder / "p.rspreset", "With paper", settings)
picture.unlink()
got = F.read(folder / "p.rspreset", folder / "assets")
path = Path(got[1]["fine"]["finish.texture_path"])
ok(path.is_file() and path.parent == folder / "assets", "a preset carries the texture's picture")
panel.apply_preset(got[1]); qa.processEvents()
ok(panel.settings_dict()["fine"] == got[1]["fine"] and row_visible("finish.texture_path"), "worn: the picture is the texture")
panel.apply_preset(F.builtins()[0][2]); qa.processEvents()
ok("fine" not in panel.settings_dict(), "a preset without them takes them away")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
