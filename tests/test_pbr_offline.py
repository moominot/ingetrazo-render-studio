"""Full texture sets: finding a colour picture's companion maps (manifest, then the two
libraries' file names), checking the manifest, and collecting the model's pictures.
Plain Python: no Qt, no Blender, no IngeTrazo.
argv: [render-studio repo]"""
import json, os, sys, tempfile
from pathlib import Path
from types import SimpleNamespace as NS

REPO = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from render_studio import pbr  # noqa: E402

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

tmp = Path(tempfile.mkdtemp())
def touch(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).parent.mkdir(parents=True, exist_ok=True)
        (folder / n).write_bytes(b"\x89PNG\r\n\x1a\n fake")
    return folder

# ---- Poly Haven names, no manifest --------------------------------------------------
ph = touch(tmp / "ph", "wood_floor_diff_1k.jpg", "wood_floor_nor_gl_1k.png", "wood_floor_nor_dx_1k.jpg",
           "wood_floor_rough_1k.jpg", "wood_floor_ao_1k.jpg", "wood_floor_disp_1k.exr",
           "wood_floor_arm_1k.jpg", "other_rough_1k.jpg", "wood_floor_rough_2k.jpg")
m = pbr.find_maps(ph / "wood_floor_diff_1k.jpg")
ok(m is not None and m["found"] == "names", "Poly Haven: companions found by name")
ok(m["normal"] == str((ph / "wood_floor_nor_gl_1k.png").resolve()) and m["normal_flip_green"] is False,
   "…the OpenGL normal map wins over the DirectX one (another extension is fine)")
ok(m["roughness"].endswith("wood_floor_rough_1k.jpg"), "…roughness of the SAME resolution, not 2k nor another asset's")
ok(m["displacement"].endswith("wood_floor_disp_1k.exr") and m["ao"].endswith("wood_floor_ao_1k.jpg")
   and m["arm"].endswith("wood_floor_arm_1k.jpg"), "…displacement (exr), AO and the packed ARM")
ok("metalness" not in m and "opacity" not in m, "…and only the maps that exist")
ok(all(os.path.isabs(m[k]) for k in pbr.JOB_MAPS if k in m), "…every path absolute")

touch(tmp / "ph_dx", "brick_diff_2k.png", "brick_nor_dx_2k.png", "brick_metal_2k.png")
m = pbr.find_maps(tmp / "ph_dx" / "brick_diff_2k.png")
ok(m and m["normal"].endswith("brick_nor_dx_2k.png") and m["normal_flip_green"] is True,
   "Poly Haven DirectX normal only: used with the green channel flipped")
ok(m and m["metalness"].endswith("brick_metal_2k.png"), "…metalness")

touch(tmp / "ph_case", "Tiles_Diff_4K.JPG", "tiles_rough_4k.jpg")
m = pbr.find_maps(tmp / "ph_case" / "Tiles_Diff_4K.JPG")
ok(m and m["roughness"].lower().endswith("tiles_rough_4k.jpg"), "names matched whatever their case")

# ---- ambientCG names ---------------------------------------------------------------------
acg = touch(tmp / "acg", "Bricks059_1K-JPG_Color.jpg", "Bricks059_1K-JPG_NormalGL.jpg", "Bricks059_1K-JPG_NormalDX.jpg",
            "Bricks059_1K-JPG_Roughness.jpg", "Bricks059_1K-JPG_AmbientOcclusion.jpg",
            "Bricks059_1K-JPG_Displacement.jpg", "Bricks059_1K-JPG_Metalness.jpg", "Bricks059_1K-JPG_Opacity.jpg",
            "Bricks059_2K-JPG_Roughness.jpg")
m = pbr.find_maps(acg / "Bricks059_1K-JPG_Color.jpg")
ok(m and m["found"] == "names" and m["normal"].endswith("_NormalGL.jpg") and not m["normal_flip_green"],
   "ambientCG: NormalGL")
ok(m and all(m.get(k, "").endswith(s) for k, s in (("roughness", "1K-JPG_Roughness.jpg"),
   ("ao", "_AmbientOcclusion.jpg"), ("displacement", "_Displacement.jpg"), ("metalness", "_Metalness.jpg"),
   ("opacity", "_Opacity.jpg"))), "…roughness (same resolution), AO, displacement, metalness, opacity")
touch(tmp / "acg_png", "Metal012_2K-PNG_Color.png", "Metal012_2K-PNG_NormalDX.png", "Metal012_2K-PNG_Metalness.png")
m = pbr.find_maps(tmp / "acg_png" / "Metal012_2K-PNG_Color.png")
ok(m and m["normal_flip_green"] is True and m["metalness"].endswith("_Metalness.png"), "ambientCG PNG set, DirectX normal flipped")

# ---- nothing to find --------------------------------------------------------------------
touch(tmp / "plain", "my_photo.jpg", "my_photo_rough.jpg", "wall_diff_1k.jpg")
ok(pbr.find_maps(tmp / "plain" / "my_photo.jpg") is None, "a picture named by neither library: None (as before)")
ok(pbr.find_maps(tmp / "plain" / "wall_diff_1k.jpg") is None, "a Poly Haven name with no siblings: None")
ok(pbr.find_maps(tmp / "missing" / "gone_diff_1k.jpg") is None, "a picture whose folder is gone: None, no error")
ok(pbr.find_maps("") is None and pbr.find_maps(None) is None, "no picture: None")

# ---- the manifest ----------------------------------------------------------------------------
man = touch(tmp / "man", "wood_floor_diff_1k.jpg", "n.png", "r.jpg", "a.jpg", "d.png", "sub/m.jpg",
            "wood_floor_rough_1k.jpg", "o.png", "arm.jpg", "ndx.png")
touch(tmp, "outside.png")
def write_manifest(folder, colour, data):
    p = pbr.manifest_path(folder / colour)
    p.write_text(json.dumps(data), encoding="utf-8")
    return p
p = write_manifest(man, "wood_floor_diff_1k.jpg", {"version": 1, "color": "wood_floor_diff_1k.jpg",
                   "normal_gl": "n.png", "roughness": "r.jpg", "ao": "a.jpg", "displacement": "d.png",
                   "metalness": "sub/m.jpg", "opacity": "o.png", "arm": "arm.jpg",
                   "size_m": [2, 2], "source": "polyhaven", "id": "wood_floor"})
ok(p.name == "wood_floor_diff_1k.pbr.json", "the manifest is <picture stem>.pbr.json")
m = pbr.find_maps(man / "wood_floor_diff_1k.jpg")
ok(m and m["found"] == "manifest" and m["roughness"].endswith("r.jpg"),
   "a manifest wins over the names (r.jpg, not wood_floor_rough_1k.jpg)")
ok(m and m["metalness"] == str((man / "sub" / "m.jpg").resolve()), "…a file in a subfolder is allowed, made absolute")
ok(m and all(m.get(k) for k in ("normal", "ao", "displacement", "opacity", "arm")), "…every map of the manifest")
raw = pbr.read_manifest(p)
ok(raw["size_m"] == [2.0, 2.0] and raw["source"] == "polyhaven" and raw["id"] == "wood_floor", "…size, source and id kept")

p = write_manifest(man, "wood_floor_diff_1k.jpg", {"version": 1, "color": "wood_floor_diff_1k.jpg",
                   "normal_dx": "ndx.png", "roughness": "../outside.png", "ao": str((man / "a.jpg").resolve()),
                   "displacement": "C:\\Windows\\win.ini", "metalness": "/etc/passwd", "opacity": "missing.png",
                   "arm": "sub/../arm.jpg", "size_m": [0, "x"], "id": 7})
raw = pbr.read_manifest(p)
ok(set(raw) == {"normal_dx"}, f"refused: .., absolute (both kinds), missing, a path through .. ; bad size and id dropped ({sorted(raw)})")
m = pbr.find_maps(man / "wood_floor_diff_1k.jpg")
ok(m["normal_flip_green"] is True and set(k for k in pbr.JOB_MAPS if k in m) == {"normal"},
   "…the rest of the manifest still used: its DirectX normal, flipped")

for bad, what in (({"version": 2, "color": "x.jpg", "roughness": "r.jpg"}, "another version"),
                  ({"version": True, "color": "x.jpg", "roughness": "r.jpg"}, "version true"),
                  ({"roughness": "r.jpg", "version": 1}, "no colour"),
                  (["r.jpg"], "not an object")):
    write_manifest(man, "wood_floor_diff_1k.jpg", bad)
    m = pbr.find_maps(man / "wood_floor_diff_1k.jpg")
    ok(m and m["found"] == "names" and m["roughness"].endswith("wood_floor_rough_1k.jpg"),
       f"a manifest with {what} is ignored: the names are guessed")
pbr.manifest_path(man / "wood_floor_diff_1k.jpg").write_text("{not json", encoding="utf-8")
m = pbr.find_maps(man / "wood_floor_diff_1k.jpg")
ok(m and m["found"] == "names", "a manifest that is not JSON is ignored")
pbr.manifest_path(man / "wood_floor_diff_1k.jpg").write_text(" " * (pbr.MANIFEST_MAX_BYTES + 1), encoding="utf-8")
ok(pbr.read_manifest(pbr.manifest_path(man / "wood_floor_diff_1k.jpg")) is None, "a huge manifest is not read")

own = touch(tmp / "own", "my_wall.png", "my_wall_n.png")
write_manifest(own, "my_wall.png", {"version": 1, "color": "my_wall.png", "normal_gl": "my_wall_n.png"})
m = pbr.find_maps(own / "my_wall.png")
ok(m and m["normal"].endswith("my_wall_n.png"), "a manifest works for any picture name, not only the libraries'")
write_manifest(own, "my_wall.png", {"version": 1, "color": "my_wall.png", "normal_gl": "nothing.png"})
ok(pbr.find_maps(own / "my_wall.png") is None, "a manifest none of whose maps exist: None")

# ---- the model's pictures (duck-typed scene) --------------------------------------------------
def face(tex=None, **kw):
    return NS(attrs={"texture": tex, **kw} if tex else dict(kw))
ph_pic = str(ph / "wood_floor_diff_1k.jpg")
acg_pic = str(acg / "Bricks059_1K-JPG_Color.jpg")
tinted = str(tmp / "cache" / "wood_floor_diff_1k_tint_ab12.png")
proto = NS(faces=[face({"path": acg_pic, "sw": 1, "sh": 1})])
inner = NS(mesh=proto, material=None, children=[])
comp1 = NS(mesh=NS(faces=[]), material={"texture": {"path": tinted, "base": ph_pic, "sw": 2, "sh": 2}}, children=[inner])
comp2 = NS(mesh=proto, material=None, children=[inner])       # same prototype: visited once
plain = str(tmp / "plain" / "my_photo.jpg")
scene = NS(mesh=NS(faces=[face(), face({"path": plain, "sw": 1, "sh": 1}), face(color=(1, 0, 0, 1))]),
           groups=[comp1, comp2],
           materials={"Reg": NS(texture={"path": str(tmp / "ph_dx" / "brick_diff_2k.png")}),
                      "Col": NS(texture=None)})
pics = pbr.model_pictures(scene)
ok(pics.get("Bricks059_1K-JPG_Color.jpg") == acg_pic, "a picture nested in a component is found")
ok(pics.get(Path(tinted).name) == ph_pic, "a tinted picture: keyed by the tinted file's name, looked up from the original")
ok("my_photo.jpg" in pics and "brick_diff_2k.png" in pics, "loose faces and the registry's materials too")
block = pbr.job_block(scene)
ok(set(block) == {"Bricks059_1K-JPG_Color.jpg", Path(tinted).name, "brick_diff_2k.png"},
   f"the job block: only pictures with companions ({sorted(block)})")
ok(block[Path(tinted).name]["normal"].endswith("wood_floor_nor_gl_1k.png"), "…the tinted one carries the original's maps")
json.dumps(block)
ok(True, "the block is JSON")
ok(pbr.job_block(NS()) == {}, "an empty scene: nothing")

print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
