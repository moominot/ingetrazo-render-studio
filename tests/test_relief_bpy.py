"""Relief from a picture, rendered by a REAL Blender (the `bpy` module, Blender 5.3): the wall must
look different with the relief on, and the height map must not be blank or noisy.
Skipped when `bpy` is not installed (pip install bpy; needs the Python it was built for).
argv: [render-studio repo]"""
import json, math, os, shutil, sys, tempfile
try:
    import bpy
    import numpy as np
except ImportError:
    print("SKIP bpy is not installed"); sys.exit(0)
REPO = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUDIO = os.path.join(REPO, "render_studio", "blender", "studio_scene.py")
RENDER_SCENE = os.environ.get("INGETRAZO_RENDER_SCENE", "/home/user/ingetrazo/resources/blender/render_scene.py")
work = tempfile.mkdtemp()
shutil.copyfile(RENDER_SCENE, os.path.join(work, "render_scene.py")); shutil.copyfile(STUDIO, os.path.join(work, "studio_scene.py"))
src = open(os.path.join(work, "studio_scene.py"), encoding="utf-8").read().rstrip().rsplit("\nmain()", 1)[0]
ns = {"__name__": "studio_scene_lib", "__file__": os.path.join(work, "studio_scene.py")}
exec(compile(src + "\n", ns["__file__"], "exec"), ns)

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

# a brick picture: 1 m x 0.5 m at 1024 px/m, 215x65 mm bricks, 10 mm joints, speckle
rng = np.random.default_rng(3)
W, H, ppm = 1024, 512, 1024.0
img = np.zeros((H, W, 3), np.float32); img[:] = (0.78, 0.78, 0.76)
bw, bh, j = int(0.215 * ppm), int(0.065 * ppm), int(0.010 * ppm)
for row in range(int(H / (bh + j)) + 1):
    y0 = row * (bh + j); off = (bw + j) // 2 if row % 2 else 0
    for col in range(-1, W // (bw + j) + 2):
        x0 = col * (bw + j) + off
        xs, xe, ys, ye = max(0, x0), min(W, x0 + bw), y0, min(H, y0 + bh)
        if xs < xe and ys < ye: img[ys:ye, xs:xe] = np.array((0.80, 0.42, 0.22)) * rng.uniform(0.85, 1.1)
img = np.clip(img * (1.0 + rng.normal(0, 0.035, (H, W, 1))), 0, 1).astype(np.float32)
tex = os.path.join(work, "brick.png")
im0 = bpy.data.images.new("brick_tmp", W, H)
im0.pixels.foreach_set(np.concatenate([img[::-1], np.ones((H, W, 1), np.float32)], axis=2).ravel())
im0.filepath_raw = tex; im0.file_format = "PNG"; im0.save()

pic = bpy.data.images.load(tex)
v = ns["relief_height"](pic, True, 0.5)
ok(v.shape == (512, 1024) and 0.0 <= v.min() and v.max() <= 1.0 and v.std() > 0.15, f"the height map uses the range (std {v.std():.2f})")
step = float(np.abs(np.diff(v, axis=1)).max())
ok(step < 0.35, f"…and it is smooth: no pixel jumps (largest step {step:.2f}; the picture's own speckle and 1-px edges would give ~1)")

def render(bump, tag):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    me = bpy.data.meshes.new("wall"); me.from_pydata([(-3, 0, 0), (3, 0, 0), (3, 0, 3), (-3, 0, 3)], [], [(0, 1, 2, 3)]); me.update()
    uv = me.uv_layers.new(name="UV")
    for loop, uvc in zip(me.loops, [(0, 0), (6, 0), (6, 6), (0, 6)]): uv.data[loop.index].uv = uvc
    ob = bpy.data.objects.new("wall", me); scene.collection.objects.link(ob)
    mat = bpy.data.materials.new("brick_clay"); mat.use_nodes = True
    nt = mat.node_tree; bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    node = nt.nodes.new("ShaderNodeTexImage"); node.image = bpy.data.images.load(tex)
    nt.links.new(node.outputs["Color"], bsdf.inputs["Base Color"]); me.materials.append(mat)
    ns["apply_material_specs"]({"brick_clay": {"type": "generic", "roughness": 0.97, "metallic": 0.0, "bump": bump,
                                               "maps": {"bump": {"source": "picture", "invert": True, "contrast": 0.5}}}})
    if bump > 0:
        hn = next((n for n in nt.nodes if n.type == "TEX_IMAGE" and n is not node), None)
        a = np.empty(hn.image.size[0] * hn.image.size[1] * 4, np.float32); hn.image.pixels.foreach_get(a)
        ok(a.reshape(-1, 4)[:, :3].std() > 0.1, "the height image carries the relief (not blank: setting the colour space after the pixels wipes it)")
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scene.collection.objects.link(cam); scene.camera = cam
    import mathutils
    cam.location = (-2.2, -5.5, 1.5)
    cam.rotation_euler = (mathutils.Vector((0, 0, 1.5)) - cam.location).to_track_quat("-Z", "Y").to_euler(); cam.data.lens = 28
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); scene.collection.objects.link(sun)
    sun.data.energy = 3.5; sun.rotation_euler = (math.radians(55), 0, math.radians(35))
    world = bpy.data.worlds.new("w"); world.use_nodes = True; scene.world = world
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND"); bg.inputs["Color"].default_value = (0.55, 0.7, 0.95, 1); bg.inputs["Strength"].default_value = 0.8
    r = scene.render; r.engine = "CYCLES"; r.resolution_x, r.resolution_y = 640, 360; r.image_settings.file_format = "PNG"
    scene.cycles.samples = 24; scene.cycles.device = "CPU"; scene.cycles.use_denoising = False
    scene.view_settings.view_transform = "AgX"; scene.view_settings.exposure = -0.3
    r.filepath = os.path.join(work, tag + ".png"); bpy.ops.render.render(write_still=True)
    im = bpy.data.images.load(r.filepath); w, h = im.size
    return np.array(im.pixels[:], np.float32).reshape(h, w, 4)[::-1, :, :3]

flat, relief = render(0.0, "flat"), render(1.0, "relief")
reg = (slice(120, 220), slice(170, 370))
diff = float(np.abs(flat - relief)[reg].mean())
ok(diff > 0.006, f"the wall renders differently with the relief on (mean difference {diff:.4f}; 0 would mean no relief at all)")
half = render(0.5, "half"); d_half = float(np.abs(flat - half)[reg].mean())
ok(0.0 < d_half < diff, f"half the relief is in between ({d_half:.4f} < {diff:.4f})")

# ---- water: a pool seen obliquely, with the sun glinting; flat (Relief 0) vs ripples
def pool(relief, size, tag):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    import mathutils
    def quad(name, pts, mat):
        me = bpy.data.meshes.new(name); me.from_pydata(pts, [], [(0, 1, 2, 3)]); me.update()
        o = bpy.data.objects.new(name, me); scene.collection.objects.link(o); me.materials.append(mat)
    floor = bpy.data.materials.new("floor"); floor.use_nodes = True
    next(n for n in floor.node_tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Base Color"].default_value = (0.03, 0.12, 0.18, 1)
    quad("floor", [(-5, -3, -1), (5, -3, -1), (5, 3, -1), (-5, 3, -1)], floor)
    wmat = bpy.data.materials.new("agua"); wmat.use_nodes = True; wmat["ingetrazo_finish"] = "water"
    quad("water", [(-5, -3, 0), (5, -3, 0), (5, 3, 0), (-5, 3, 0)], wmat)
    ns["core"]["apply_finishes"]()
    ns["apply_material_specs"]({"agua": {"type": "water", "roughness": 0.02, "metallic": 0.0, "bump": relief, "ripple_size": size}})
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scene.collection.objects.link(cam); scene.camera = cam
    cam.location = (0, -7.5, 1.6)
    cam.rotation_euler = (mathutils.Vector((0, 0, 0.3)) - cam.location).to_track_quat("-Z", "Y").to_euler(); cam.data.lens = 30
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); scene.collection.objects.link(sun)
    sun.data.energy = 5; sun.rotation_euler = mathutils.Vector((0.15, -0.80, -0.58)).to_track_quat("-Z", "Y").to_euler(); sun.data.angle = math.radians(1.0)
    world = bpy.data.worlds.new("w"); world.use_nodes = True; scene.world = world
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND"); bg.inputs["Color"].default_value = (0.6, 0.75, 1, 1)
    r = scene.render; r.engine = "CYCLES"; r.resolution_x, r.resolution_y = 640, 360; r.image_settings.file_format = "PNG"
    scene.cycles.samples = 32; scene.cycles.device = "CPU"; scene.cycles.use_denoising = False
    scene.view_settings.view_transform = "AgX"
    r.filepath = os.path.join(work, tag + ".png"); bpy.ops.render.render(write_still=True)
    im = bpy.data.images.load(r.filepath); w, h = im.size
    return np.array(im.pixels[:], np.float32).reshape(h, w, 4)[::-1, :, :3]

flat_w, ripple_w = pool(0.0, 0.8, "water_flat"), pool(0.5, 0.8, "water_ripples")
reg = (slice(180, 270), slice(60, 580))
d = float(np.abs(flat_w - ripple_w)[reg].mean())
ok(d > 0.005, f"water with ripples renders differently from flat water (mean difference {d:.4f})")
ok(abs(ns["water_scale"](0.0) - 108.6) < 1e-6 and abs(ns["water_scale"](1.0) - 4.0) < 1e-6, "the ripple size runs from the recipe's 108.6 per metre to broad waves")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
