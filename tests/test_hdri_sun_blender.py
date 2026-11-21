"""The sun of a 360° panorama, found by a REAL Blender, through the extension's own Blender script.

A JPEG/PNG panorama only PAINTS its sun (clipped to white), so lighting with the whole picture floods the
scene with the sky's blue and casts no shadow. ``studio_scene.hdri_sun`` puts a lamp where the picture is
brightest. Checks: the lamp points at the bright spot the camera really sees there (turned or not by the
rotation slider: the spot is the brightest thing in a render of the world looked at along the lamp's axis);
its colour and strength; a radiance file (HDR) carries its own sun and gets no lamp; an even sky gets none;
a sun under the horizon gets none.

Run:  blender -b --factory-startup --python tests/test_hdri_sun_blender.py -- <repo> <render_scene.py> <out dir>
"""
import math, os, shutil, sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
REPO = os.path.abspath(argv[0])
RENDER_SCENE = os.path.abspath(argv[1])
OUT = os.path.abspath(argv[2])
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

W, H = 1024, 512


def panorama(path, spot=(0.30, 0.75), value=1.0, fmt="PNG", sky=True):
    """A blue sky (brighter toward the top) with a white disc at (u, v) (v up)."""
    yy, xx = np.mgrid[0:H, 0:W]
    v = 1.0 - (yy + 0.5) / H                       # top row = 1
    u = (xx + 0.5) / W
    rgb = np.stack([np.full_like(v, 0.25), np.full_like(v, 0.45), np.full_like(v, 0.9)], axis=2) \
        * (0.4 + 0.6 * v)[..., None] if sky else np.full((H, W, 3), 0.4, np.float32)
    if spot is not None:
        dist = np.hypot((u - spot[0]) * W, (v - spot[1]) * H)
        rgb = np.where((dist < 9)[..., None], np.array([value, value, value * 0.95]), rgb)
    rgb = rgb.astype(np.float32)
    img = bpy.data.images.new("pano", W, H, alpha=False, float_buffer=(fmt == "HDR"))
    img.pixels.foreach_set(np.concatenate([rgb[::-1], np.ones((H, W, 1), np.float32)], axis=2).ravel())
    img.filepath_raw = path
    img.file_format = fmt
    img.save()
    bpy.data.images.remove(img)
    return path


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 4
    sc.cycles.device = "CPU"
    sc.render.resolution_x = sc.render.resolution_y = 16
    sc.view_settings.view_transform = "Standard"
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.lens = 300
    sc.collection.objects.link(cam)
    sc.camera = cam
    return sc, cam


def look(sc, cam, direction, name):
    cam.location = (0, 0, 0)
    cam.rotation_euler = Vector(direction).normalized().to_track_quat("-Z", "Y").to_euler()
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.filepath = os.path.join(OUT, name + ".exr")
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(sc.render.filepath)
    px = np.array(img.pixels[:], dtype=np.float32).reshape(16, 16, 4)[6:10, 6:10, :3].reshape(-1, 3)   # the middle
    bpy.data.images.remove(img)
    return float(px.mean(axis=0) @ np.array([0.2126, 0.7152, 0.0722]))


def sun_axis(sun):
    bpy.context.view_layer.update()
    return sun.matrix_world.to_3x3() @ Vector((0, 0, 1))      # a sun shines along -Z: +Z is toward it


png = panorama(os.path.join(OUT, "sky.png"))
for rotation in (0.0, 90.0, 200.0):
    sc, cam = fresh()
    img = studio["set_hdri"](sc, png, rotation, 1.0, True)
    sun = studio["hdri_sun"](sc, img, rotation, 1.0, 4.0)
    ok(sun is not None, f"rotation {rotation:.0f}°: a lamp is made for the painted sun")
    if sun is None:
        continue
    ax = sun_axis(sun)
    ok(ax.z > 0.6, f"rotation {rotation:.0f}°: it is high (elevation {math.degrees(math.asin(ax.z)):.0f}°, expect ~45°)")
    at_sun = look(sc, cam, ax, f"at_{int(rotation)}")
    others = [look(sc, cam, d, f"off_{int(rotation)}_{i}") for i, d in enumerate(
        (Vector((1, 0, 0.7)), Vector((-1, 0, 0.7)), Vector((0, 1, 0.7)), Vector((0, -1, 0.7))))]
    ok(at_sun > 0.93, f"rotation {rotation:.0f}°: the world looked at along the lamp is the white disc ({at_sun:.2f})")
    ok(all(o < 0.85 for o in others), f"rotation {rotation:.0f}°: and the sky elsewhere is dimmer ({max(others):.2f})")
    if rotation == 0.0:
        ok(abs(sun.data.energy - 4.0) < 1e-6, "its strength is the one given")
        ok(sun.data.color[0] > 0.9 and sun.data.color[2] > 0.9 and sun.data.color[1] > 0.9, "a near-white disc gives a near-white lamp")

# the user's brightness slider scales the lamp too
sc, cam = fresh()
img = studio["set_hdri"](sc, png, 0.0, 2.0, True)
sun = studio["hdri_sun"](sc, img, 0.0, 2.0, 4.0)
ok(sun is not None and abs(sun.data.energy - 8.0) < 1e-6, "the brightness slider scales the lamp")

# a radiance file carries its own sun: no second one
hdr = panorama(os.path.join(OUT, "real.hdr"), value=60.0, fmt="HDR")
sc, cam = fresh()
img = studio["set_hdri"](sc, hdr, 0.0, 1.0, True)
ok(studio["hdri_sun"](sc, img, 0.0, 1.0, 4.0) is None, "an HDR file (its real sun is in the picture) gets no lamp")

# an even sky: nothing stands out
even = panorama(os.path.join(OUT, "even.png"), spot=None, sky=False)
sc, cam = fresh()
img = studio["set_hdri"](sc, even, 0.0, 1.0, True)
ok(studio["hdri_sun"](sc, img, 0.0, 1.0, 4.0) is None, "an even overcast sky gets no lamp")

# a sun under the horizon lights nothing
low = panorama(os.path.join(OUT, "low.png"), spot=(0.3, 0.2))
sc, cam = fresh()
img = studio["set_hdri"](sc, low, 0.0, 1.0, True)
ok(studio["hdri_sun"](sc, img, 0.0, 1.0, 4.0) is None, "a bright spot below the horizon gets no lamp")

print("FAILS:", fails, flush=True)
sys.exit(1 if fails else 0)
