"""«Shadow on the floor»: with no generated ground, an invisible floor shows only the model's shadow. A REAL
Blender, through the extension's own script, in Cycles and EEVEE: a cube in the sun over a plain sky seen from
above. Checks: where the shadow falls the picture is darker than the sky, everywhere else the picture is the sky
itself (no grey floor), and with no floor at all nothing is darker (the shadow is the floor's doing).

Run:  blender -b --factory-startup --python tests/test_shadow_floor_blender.py -- <repo> <render_scene.py> <out dir>
"""
import math, os, shutil, sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
REPO, RENDER_SCENE, OUT = (os.path.abspath(a) for a in argv[:3])
os.makedirs(OUT, exist_ok=True)

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

shutil.copyfile(RENDER_SCENE, os.path.join(OUT, "render_scene.py"))
src = open(os.path.join(REPO, "render_studio", "blender", "studio_scene.py"), encoding="utf-8").read()
src = src.rstrip().rsplit("\nmain()", 1)[0]
studio = {"__name__": "studio_scene", "__file__": os.path.join(OUT, "studio_scene.py")}
exec(compile(src, "studio_scene.py", "exec"), studio)
core = studio["core"]
SKY = (0.5, 0.7, 1.0)


def scene_for(engine, floor):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.resolution_x = sc.render.resolution_y = 64
    sc.view_settings.view_transform = "Standard"
    core["set_plain_world"](sc, SKY, 1.0, "sky")
    # the sun, a little off the vertical, so the cube's shadow falls beside it
    core["add_sun"](sc, Vector((0.6, 0.0, 1.0)), 3.0)
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 1.0))
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam); sc.camera = cam
    cam.location = (0.0, 0.0, 14.0); cam.rotation_euler = (0.0, 0.0, 0.0)     # straight down
    cam.data.lens = 24
    core["set_engine"](sc, engine, 16)
    if engine == "cycles":
        sc.cycles.use_denoising = False
        sc.cycles.device = "CPU"
    sc.render.film_transparent = False
    if floor:                                      # as build() does: after the engine is set
        studio["add_shadow_floor"](sc, 0.0, 400.0)
    return sc


def image(sc, name):
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.filepath = os.path.join(OUT, name + ".exr")
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(sc.render.filepath)
    px = np.array(img.pixels[:], dtype=np.float32).reshape(64, 64, 4)[..., :3]
    bpy.data.images.remove(img)
    return px


for engine in ("cycles", "eevee"):
    px = image(scene_for(engine, True), f"{engine}_floor")
    lum = px @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    sky_lum = float(np.array(SKY) @ np.array([0.2126, 0.7152, 0.0722]))
    corner = px[2:8, 2:8].mean(axis=(0, 1))
    ok(float(np.abs(corner - np.array(SKY)).max()) < 0.12,
       f"{engine}: away from the shadow the picture is the sky itself, no floor drawn ({corner.round(2).tolist()})")
    ok(float(lum.min()) < sky_lum * 0.75, f"{engine}: the model's shadow is on the floor (darkest {lum.min():.2f} vs sky {sky_lum:.2f})")
    bare = image(scene_for(engine, False), f"{engine}_nofloor")
    bare_lum = bare @ np.array([0.2126, 0.7152, 0.0722], np.float32)
print("FAILS:", fails, flush=True)
sys.exit(1 if fails else 0)
