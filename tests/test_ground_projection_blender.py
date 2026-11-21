"""The ground of a 360° image laid under the model, by a REAL Blender, through the extension's own script.

The generated ground melts into the image. It used to look the horizon row of the image up for every point of
the ground, so every row of the ground was the same colour: vertical stripes (a street panorama taken by a
camera, with trees at the horizon). Now each point is looked up in the direction from an eye ``eye_height``
metres above the ground, in the middle of the model, so the ground shows the image's own lower half.

The image has a red ramp that grows toward the bottom (nadir), nothing else. Checks: with the eye height the
ground's rows differ from near (bottom of the picture) to far (the horizon); without it they are all one;
a higher eye puts the same ramp farther (a given row is a different colour); and the ground is projected
about the MODEL's middle, not about the world origin.

Run:  blender -b --factory-startup --python tests/test_ground_projection_blender.py -- <repo> <render_scene.py> <out dir>
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
core = studio["core"]

W, H = 512, 256


def ramp_png(path):
    """Red grows toward the nadir (bottom row), the sky is flat grey: only the lower half matters."""
    v = 1.0 - (np.mgrid[0:H, 0:W][0] + 0.5) / H          # top row = 1
    red = np.where(v < 0.5, 2.0 * (0.5 - v) * 0.9 + 0.05, 0.3)
    rgb = np.stack([red, np.full_like(red, 0.1), np.full_like(red, 0.1)], axis=2).astype(np.float32)
    img = bpy.data.images.new("ramp", W, H, alpha=False)
    img.pixels.foreach_set(np.concatenate([rgb[::-1], np.ones((H, W, 1), np.float32)], axis=2).ravel())
    img.filepath_raw = path; img.file_format = "PNG"; img.save()
    bpy.data.images.remove(img)
    return path


def build(eye, box_at=(0.0, 0.0)):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"; sc.cycles.samples = 2; sc.cycles.device = "CPU"
    sc.render.resolution_x, sc.render.resolution_y = 24, 48
    sc.view_settings.view_transform = "Standard"
    studio["set_hdri"](sc, PNG, 0.0, 1.0, True)
    core["add_ground"](sc, -0.5, 4000.0, (0.4, 0.4, 0.4))
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(box_at[0], box_at[1], 0.0))   # the "model"
    studio["haze_ground"](sc, 0.0, 1.0, eye_height=eye)      # fully the image from the first metre
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam); sc.camera = cam
    cam.data.lens = 20
    cam.location = (box_at[0], box_at[1] - 12.0, 1.2)
    cam.rotation_euler = (math.radians(86.0), 0.0, 0.0)       # level, a touch down
    return sc


def column(sc, name):
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.filepath = os.path.join(OUT, name + ".exr")
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(sc.render.filepath)
    px = np.array(img.pixels[:], dtype=np.float32).reshape(48, 24, 4)[:, 10:14, 0].mean(axis=1)   # red, middle columns
    bpy.data.images.remove(img)
    return px[::-1]                                           # top row first


PNG = ramp_png(os.path.join(OUT, "ramp.png"))

old = column(build(None), "old")
new = column(build(2.5), "eye25")
hi = column(build(12.0), "eye12")
# only the rows that show ground: below the horizon (the picture's lower part)
low_old, low_new = old[26:], new[26:]
ok(float(np.ptp(low_old)) < 0.04, f"without the projection every ground row is the same colour (spread {np.ptp(low_old):.3f})")
ok(float(np.ptp(low_new)) > 0.1, f"with it the ground's rows differ, near to far (spread {np.ptp(low_new):.3f})")
ok(float(low_new.max()) > float(low_new[-1]) + 0.1,
   f"the ground beside the model (seen from the eye in its middle: nearly straight down) is redder than the "
   f"ground at the camera, 12 m off ({low_new.max():.2f} vs {low_new[-1]:.2f})")
ok(abs(float(hi[40]) - float(new[40])) > 0.03, f"a higher eye gives a different ground at the same row ({new[40]:.2f} vs {hi[40]:.2f})")

# the middle of the model, not the origin: the same picture when the whole scene is moved 200 m
moved = column(build(2.5, box_at=(200.0, 80.0)), "moved")
ok(float(np.abs(moved[26:] - new[26:]).max()) < 0.03, "the projection follows the model (moving it moves nothing in the picture)")

print("FAILS:", fails, flush=True)
sys.exit(1 if fails else 0)
