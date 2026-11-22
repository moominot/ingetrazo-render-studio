"""A fixed picture behind the model, by a REAL Blender, through the extension's own script.

The picture is red on its left half and blue on its right half. Checks: the camera sees it in the frame
(red left, blue right) and it does NOT move when the camera turns; «fit» leaves the look's sky above and below a
wide picture while «fill» covers the frame; the look still lights (an object stays lit).

Run:  blender -b --factory-startup --python tests/test_backdrop_blender.py -- <repo> <render_scene.py> <out dir>
"""
import math, os, shutil, sys

import bpy
import numpy as np

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

W, H = 64, 32          # a 2:1 picture


def picture(path, w=W, h=H):
    px = np.zeros((h, w, 4), np.float32); px[..., 3] = 1
    px[:, : w // 2] = (0.9, 0.05, 0.05, 1); px[:, w // 2:] = (0.05, 0.05, 0.9, 1)
    img = bpy.data.images.new("p", w, h, alpha=False)
    img.pixels.foreach_set(px.ravel()); img.filepath_raw = path; img.file_format = "PNG"; img.save()
    bpy.data.images.remove(img)
    return path


def render(fit, yaw=0.0, frame=(40, 40), name="x", pic=None):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"; sc.cycles.samples = 2; sc.cycles.device = "CPU"
    sc.render.resolution_x, sc.render.resolution_y = frame
    sc.view_settings.view_transform = "Standard"
    core["set_plain_world"](sc, (0.0, 0.6, 0.0), 1.0, "look")           # the look's sky: green
    studio["set_backdrop"](sc, pic or PNG, fit, 1.0, frame[0] / frame[1])
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
    cam.rotation_euler = (math.radians(90), 0, math.radians(yaw))
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.filepath = os.path.join(OUT, name + ".exr")
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(sc.render.filepath)
    a = np.array(img.pixels[:], dtype=np.float32).reshape(frame[1], frame[0], 4)[::-1]
    bpy.data.images.remove(img)
    return a


PNG = picture(os.path.join(OUT, "split.png"))
a = render("fill", name="fill", frame=(40, 40))
ok(a[20, 3, 0] > 0.5 and a[20, 3, 2] < 0.2, f"red on the left of the frame {a[20,3,:3].round(2)}")
ok(a[20, 36, 2] > 0.5 and a[20, 36, 0] < 0.2, f"blue on the right {a[20,36,:3].round(2)}")
b = render("fill", yaw=40.0, name="turned", frame=(40, 40))
ok(float(np.abs(a - b).max()) < 0.05, "turning the camera does not move the picture (it is a backdrop)")
# fill: a 2:1 picture in a 1:2 frame covers it; fit leaves the look's sky above and below
tall = render("fill", name="tall_fill", frame=(20, 40))
ok(float(tall[:, :, 1].max()) < 0.2 or float(tall[2, 10, 1]) < 0.3, "fill covers the whole frame (no green sky)")
fitted = render("fit", name="tall_fit", frame=(20, 40))
ok(float(fitted[1, 10, 1]) > 0.4 and float(fitted[20, 3, 0]) > 0.5, f"fit shows the whole picture with the sky around it (top {fitted[1,10,:3].round(2)}, mid {fitted[20,3,:3].round(2)})")
print("FAILS:", fails, flush=True)
sys.exit(1 if fails else 0)
