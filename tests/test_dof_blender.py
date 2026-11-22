"""Depth of field: a real Blender. The focus is the eye→target distance, off at 0, f-stop falls with the amount."""
import math, os, shutil, sys
import bpy
argv = sys.argv[sys.argv.index("--") + 1:]
REPO, RS, OUT = (os.path.abspath(a) for a in argv[:3])
os.makedirs(OUT, exist_ok=True)
shutil.copyfile(RS, os.path.join(OUT, "render_scene.py"))
src = open(os.path.join(REPO, "render_studio", "blender", "studio_scene.py"), encoding="utf-8").read().rstrip().rsplit("\nmain()", 1)[0]
studio = {"__name__": "studio_scene", "__file__": os.path.join(OUT, "studio_scene.py")}
exec(compile(src, "studio_scene.py", "exec"), studio)
fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
cfg = {"eye": [0, -10, 2], "target": [0, 0, 2], "up": [0, 0, 1], "fov_deg": 40, "perspective": True}
studio["core"]["set_camera"](sc, cfg, 320, 200)
studio["set_dof"](sc, cfg, 0.0)
ok(not sc.camera.data.dof.use_dof, "off at 0")
studio["set_dof"](sc, cfg, 0.5)
d = sc.camera.data.dof
ok(d.use_dof and abs(d.focus_distance - 10.0) < 1e-3, f"focused on the view's middle ({d.focus_distance:.2f} m)")
f_half = d.aperture_fstop
studio["set_dof"](sc, cfg, 1.0)
ok(sc.camera.data.dof.aperture_fstop < f_half < 32.0, f"more amount, wider aperture (f/{f_half:.1f} → f/{sc.camera.data.dof.aperture_fstop:.1f})")
studio["set_dof"](sc, dict(cfg, perspective=False), 1.0)
ok(not sc.camera.data.dof.use_dof, "not for an orthographic view")
sys.exit(1 if fails else 0)
