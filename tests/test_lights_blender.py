"""Render Studio's lights rendered by a REAL Blender, through the extension's own Blender script.

A 6 × 6 m floor seen from above. Lights made by ``lights.job_block`` (as the panel writes them) and
built by ``studio_scene.add_studio_lights``. Checks: every kind becomes the right Blender light (power,
cone, shape, size, disc, axes); a spot's lumens go into its cone (Blender's spot is a masked point);
an IES profile keeps the light's power (Cycles' scale per candela is still the one measured) and only
shapes it; an area light faces where it is aimed; EEVEE renders them all (IES ignored).

Run:  blender -b --factory-startup --python tests/test_lights_blender.py -- <repo> <render_scene.py> <out dir>
or, with the bpy module:  python tests/test_lights_blender.py -- <repo> <render_scene.py> <out dir>
"""
import math, os, shutil, sys
from types import SimpleNamespace as NS

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
REPO = os.path.abspath(argv[0])
RENDER_SCENE = os.path.abspath(argv[1])
OUT = os.path.abspath(argv[2])
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, REPO)
from render_studio import lights as L  # noqa: E402

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

# The extension's Blender script, without running its main(): copied next to IngeTrazo's.
shutil.copyfile(RENDER_SCENE, os.path.join(OUT, "render_scene.py"))
src = open(os.path.join(REPO, "render_studio", "blender", "studio_scene.py"), encoding="utf-8").read()
src = src.rstrip().rsplit("\nmain()", 1)[0]
studio = {"__name__": "studio_scene", "__file__": os.path.join(OUT, "studio_scene.py")}
exec(compile(src, "studio_scene.py", "exec"), studio)


def block(*lights):
    return L.job_block(NS(plugin_data={"render_studio": {"lights": [L.clean_light(l) for l in lights]}}, groups=[]))


def floor_scene(engine="CYCLES", size=32, view=0.2):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES" if engine == "CYCLES" else "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in \
        [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
    if engine == "CYCLES":
        sc.cycles.samples = 64
        sc.cycles.device = "CPU"
    sc.render.resolution_x = sc.render.resolution_y = size
    bpy.ops.mesh.primitive_plane_add(size=6)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.location = (0, 0, 5)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = view
    sc.view_settings.view_transform = "Standard"
    return sc


def mean_red(sc, name):
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.filepath = os.path.join(OUT, name + ".exr")
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(sc.render.filepath)
    px = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
    bpy.data.images.remove(img)
    return float(px[:, :3].mean())


def lit(*lights, name="x", engine="CYCLES", view=0.2):
    sc = floor_scene(engine, view=view)
    objs = studio["add_studio_lights"](sc, block(*lights))
    return mean_red(sc, name), objs


def ies_file(name, vert, cd):
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="latin-1") as fh:
        fh.write("IESNA:LM-63-2002\nTILT=NONE\n1 -1 1 %d 1 1 2 0 0 0\n1 1 0\n%s\n0\n%s\n"
                 % (len(vert), " ".join(map(str, vert)), " ".join(map(str, cd))))
    return p


white = {"kelvin": None, "color": [1, 1, 1], "radius": 0.0, "shadow": True}

# ---- the Blender lights ---------------------------------------------------------------------
sc = floor_scene()
made = studio["add_studio_lights"](sc, block(
    dict(L.new_light("point", pos=(0, 0, 2), unit="lm", power=800), name="bulb"),
    dict(L.new_light("spot", pos=(1, 0, 2), spot_angle=40, spot_blend=0.3), dir=L.aim_from_angles(90, 60)),
    dict(L.new_light("area", pos=(0, 1, 2.5), shape="rectangle", size=1.2, size_y=0.3, spread=120),
         dir=[0, 0, -1], spin=30),
    dict(L.new_light("sun", pos=(0, 0, 9), power=2.5, sun_angle=1.5), dir=L.aim_from_angles(315, 45))))
kinds = {o.data.type: o for o in made}
ok(set(kinds) == {"POINT", "SPOT", "AREA", "SUN"}, "four kinds of Blender light")
ok(abs(kinds["POINT"].data.energy - 800 / L.LM_PER_W) < 1e-4 and kinds["POINT"].name == "bulb", "the bulb: 800 lm → Blender watts, its name")
sp = kinds["SPOT"].data
ok(abs(math.degrees(sp.spot_size) - 40) < 1e-3 and abs(sp.spot_blend - 0.3) < 1e-6, "the spot: its cone and soft edge")
ar = kinds["AREA"].data
ok(ar.shape == "RECTANGLE" and abs(ar.size - 1.2) < 1e-6 and abs(ar.size_y - 0.3) < 1e-6
   and abs(math.degrees(ar.spread) - 120) < 1e-3, "the area: rectangle, size, length, spread")
ok(abs(kinds["SUN"].data.energy - 2.5) < 1e-6 and abs(math.degrees(kinds["SUN"].data.angle) - 1.5) < 1e-4,
   "the sun: W/m² and its disc")
for o, lt in zip(made, block(  # the same lights again, for their axes
        dict(L.new_light("point", pos=(0, 0, 2))), dict(L.new_light("spot", pos=(1, 0, 2)), dir=L.aim_from_angles(90, 60)),
        dict(L.new_light("area", pos=(0, 1, 2.5)), dir=[0, 0, -1], spin=30),
        dict(L.new_light("sun", pos=(0, 0, 9)), dir=L.aim_from_angles(315, 45)))):
    m = o.matrix_world
    shine = -m.col[2].xyz.normalized()
    ok(all(abs(shine[k] - lt["dir"][k]) < 1e-4 for k in range(3))
       and all(abs(m.col[0][k] - lt["basis"][0][k]) < 1e-4 for k in range(3)),
       f"{o.data.type}: it shines where it was aimed, with the axes the viewport draws")

# ---- power ------------------------------------------------------------------------------------
point, _ = lit(dict(L.new_light("point", pos=(0, 0, 2), unit="lm", power=800), **white), name="point")
spot, _ = lit(dict(L.new_light("spot", pos=(0, 0, 2), unit="lm", power=800, spot_angle=40, spot_blend=0.0), **white), name="spot")
want = 4 * math.pi / L.cone_solid_angle(40)
ok(point > 0 and abs(spot / point / want - 1) < 0.05,
   f"a 40° spot of 800 lm is {spot / point:.2f}× brighter in its beam than an 800 lm bulb (lumens into the cone: {want:.2f})")
w2, _ = lit(dict(L.new_light("point", pos=(0, 0, 2), unit="W", power=2 * 800 / L.LM_PER_W), **white), name="w2")
ok(abs(w2 / point - 2) < 0.04, "twice the watts, twice the light")

# ---- IES ----------------------------------------------------------------------------------------
vert = list(range(0, 181, 5))
uni = ies_file("uniform.ies", vert, [1000] * len(vert))
down = ies_file("down.ies", vert, [1000 if a <= 90 else 0 for a in vert])
p_uni, objs = lit(dict(L.new_light("point", pos=(0, 0, 2), unit="lm", power=800), ies=uni, **white), name="ies_uni")
ok(any(n.type == "TEX_IES" for n in objs[0].data.node_tree.nodes), "the profile is a node of the light")
ok(abs(p_uni / point - 1) < 0.04,
   f"a uniform profile changes nothing: the power is kept (×{p_uni / point:.3f}; Cycles' {L.CYCLES_IES_PER_CD} per candela)")
p_down, _ = lit(dict(L.new_light("point", pos=(0, 0, 2), unit="lm", power=800), ies=down, **white), name="ies_down")
want = 4 * math.pi * 1000 / L.read_ies(down)["flux"]
ok(abs(p_down / point / want - 1) < 0.05, f"a downward-only profile puts it all below: ×{p_down / point:.2f} (expected {want:.2f})")
s_uni, _ = lit(dict(L.new_light("spot", pos=(0, 0, 2), unit="lm", power=800, spot_angle=60, spot_blend=0.0), ies=uni, **white),
               name="ies_spot")
ok(abs(s_uni / point - 1) < 0.05, "a spot with a profile: the profile spreads it, its cone only cuts it")

# ---- areas face where they are aimed ----------------------------------------------------------
a_down, _ = lit(dict(L.new_light("area", pos=(0, 0, 2), power=3600), dir=[0, 0, -1], **white), name="area_down")
a_up, _ = lit(dict(L.new_light("area", pos=(0, 0, 2), power=3600), dir=[0, 0, 1], **white), name="area_up")
ok(a_down > 0.01 and a_up < a_down * 0.01, f"an area aimed down lights the floor ({a_down:.3f}); aimed up, not ({a_up:.5f})")
off, _ = lit(dict(L.new_light("point", pos=(0, 0, 2), power=800), on=False), name="off")
ok(off < 1e-4, "a light switched off is not in the job")

# ---- EEVEE --------------------------------------------------------------------------------------
eevee, objs = lit(dict(L.new_light("point", pos=(-1, 0, 2), power=800), ies=uni),
                  dict(L.new_light("spot", pos=(1, 0, 2))), dict(L.new_light("area", pos=(0, 1, 2))),
                  dict(L.new_light("sun", pos=(0, 0, 5))), name="eevee", engine="EEVEE", view=6.0)
ok(len(objs) == 4 and eevee > 0.0, f"EEVEE renders every kind, a profile on a light included ({eevee:.3f})")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
