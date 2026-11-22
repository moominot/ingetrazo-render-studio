"""A model material on the generated ground: copied, laid out in metres, still melting into the horizon."""
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
sc.world = bpy.data.worlds.new("W"); sc.world.use_nodes = True
mat = bpy.data.materials.new("Paving.001"); mat.use_nodes = True
img = bpy.data.images.new("tiles", 8, 8)
tex = mat.node_tree.nodes.new("ShaderNodeTexImage"); tex.image = img
bsdf = mat.node_tree.nodes["Principled BSDF"]
mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
studio["core"]["add_ground"](sc, -0.002, 400.0, [0.4, 0.4, 0.4])
ground = bpy.data.objects["IngeTrazo ground"]
ok(studio["set_ground_material"](sc, {"name": "Paving", "tile": [2.0, 0.5], "color": [0.5, 0.5, 0.5]}), "the model's material is found (the importer's .001 suffix too)")
m = ground.data.materials[0]
ok(m.name == "IngeTrazo ground" and len(ground.data.materials) == 1, "the ground wears a copy named as the ground's material")
ok(any(n.type == "TEX_IMAGE" and n.image is img for n in m.node_tree.nodes), "…with the picture of the model's material")
ok(mat.name == "Paving.001" and not any(n.type == "TEX_IMAGE" for n in bpy.data.materials["IngeTrazo ground"].node_tree.nodes if False), "the model's own material is untouched")
uvs = [tuple(round(c, 3) for c in l.uv) for l in ground.data.uv_layers.active.data]
ok(max(u for u, v in uvs) == 100.0 and max(v for u, v in uvs) == 400.0, f"the picture repeats every 2 x 0.5 m (corner uv {max(uvs)})")
studio["haze_ground"](sc, 30.0, 300.0)
mm = ground.data.materials[0]
ok(any(n.type == "MIX_SHADER" for n in mm.node_tree.nodes), "the ground still melts into the horizon")
# a name the file does not have: the colour, no failure
bpy.ops.object.select_all(action="DESELECT")
studio["core"]["add_ground"](sc, -0.002, 400.0, [0.4, 0.4, 0.4])
ok(studio["set_ground_material"](sc, {"name": "Nowhere", "tile": [1, 1], "color": [1.0, 0.0, 0.0]}) is not False, "a material that is not in the file is made and put on the ground")

# ---- the ground's own look: colour, roughness, height, haze ---------------------------------------
def ground_of(st):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.world = bpy.data.worlds.new("W"); sc.world.use_nodes = True
    studio["make_ground"](sc, {"z": -0.002, "size": 400.0, "color": [0.42, 0.42, 0.4]}, st)
    g = bpy.data.objects["IngeTrazo ground"]
    b = next(n for n in g.data.materials[0].node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    return g, b
g, b = ground_of({"ground_color": [0.1, 0.2, 0.3], "ground_roughness": 0.12, "ground_offset": 0.5})
ok(abs(g.location.z - 0.498) < 1e-6, f"the height offset moves the ground ({g.location.z})")
ok(abs(b.inputs["Roughness"].default_value - 0.12) < 1e-6, "its roughness is the one asked for")
ok(tuple(round(c, 3) for c in b.inputs["Base Color"].default_value[:3]) == (0.1, 0.2, 0.3), "its colour is the one asked for")
g, b = ground_of({})
ok(abs(b.inputs["Roughness"].default_value - 0.9) < 1e-6 and abs(g.location.z + 0.002) < 1e-6, "nothing asked: the ground as before")
def mix_range(g):
    mm = g.data.materials[0].node_tree
    r = next(n for n in mm.nodes if n.type == "MAP_RANGE")
    return r.inputs["From Min"].default_value, r.inputs["From Max"].default_value
g, b = ground_of({"haze_scale": 2.0})
ok(mix_range(g) == (240.0, 2400.0), f"haze ×2 melts twice as far {mix_range(g)}")
g, b = ground_of({"haze": False})
ok(not any(n.type == "MAP_RANGE" for n in g.data.materials[0].node_tree.nodes), "no haze: the ground does not melt")

# ---- the material's own parameters reach the ground, and a later change of them too ----------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.world = bpy.data.worlds.new("W"); sc.world.use_nodes = True
mat = bpy.data.materials.new("Pave"); mat.use_nodes = True
mb = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"); mb.inputs["Roughness"].default_value = 0.05; mb.inputs["Metallic"].default_value = 1.0
st = {"ground_material": {"name": "Pave", "tile": [1.0, 1.0], "color": [0.5, 0.5, 0.5]}, "ground_roughness": 0.9}
gdict = {"z": -0.002, "size": 400.0, "color": [0.4, 0.4, 0.4]}
studio["make_ground"](sc, gdict, st)
b = next(n for n in bpy.data.objects["IngeTrazo ground"].data.materials[0].node_tree.nodes if n.type == "BSDF_PRINCIPLED")
ok(abs(b.inputs["Roughness"].default_value - 0.05) < 1e-6 and b.inputs["Metallic"].default_value == 1.0,
   "the material's own roughness and metal rule the ground (the ground type's roughness does not override them)")
mb.inputs["Roughness"].default_value = 0.6                 # what the live view does to the model's material
studio["remake_ground"](sc, gdict, st)
grounds = [o for o in bpy.data.objects if o.name.startswith("IngeTrazo ground")]
b = next(n for n in grounds[0].data.materials[0].node_tree.nodes if n.type == "BSDF_PRINCIPLED")
ok(len(grounds) == 1 and abs(b.inputs["Roughness"].default_value - 0.6) < 1e-6, "made again, the ground follows a changed material (one ground only)")

# ---- a grass material on the ground: its blades grow on a patch round the model ----------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.world = bpy.data.worlds.new("W"); sc.world.use_nodes = True
lawn = bpy.data.materials.new("Gespa"); lawn.use_nodes = True
me = bpy.data.meshes.new("house"); me.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
ho = bpy.data.objects.new("house", me); sc.collection.objects.link(ho)
st = {"ground_material": {"name": "Gespa", "tile": [2.0, 2.0], "color": [0.2, 0.4, 0.1]}, "ground_roughness": 0.9,
      "materials": {"Gespa": {"type": "grass", "grass_height": 0.08, "grass_density": 100}}}
studio["make_ground"](sc, {"z": -0.002, "size": 400.0, "color": [0.4, 0.4, 0.4]}, st)
patch = bpy.data.objects.get("IngeTrazo ground grass patch")
ok(patch is not None and any(m.type == "NODES" for m in patch.modifiers), "a grass material makes a patch of grass round the model")
ok(patch is not None and patch.data.materials[0] is lawn and abs(patch.location.z - 0.001) < 0.01, "…wearing the model's own material, just over the ground")
studio["remake_ground"](sc, {"z": -0.002, "size": 400.0, "color": [0.4, 0.4, 0.4]}, st)
ok(len([o for o in bpy.data.objects if o.name.startswith("IngeTrazo ground grass patch")]) == 1, "made again, there is one patch only")
def patch_radius():
    pt = bpy.data.objects["IngeTrazo ground grass patch"]
    return max(math.hypot(v.co.x, v.co.y) for v in pt.data.vertices)
# the circle: the model's farthest point (the 2 x 2 m house: 1.41 m from its middle) plus 10 m; or the person's radius
ok(abs(patch_radius() - (math.hypot(1, 1) + 10.0)) < 0.5, f"automatic radius: the farthest point of the model plus 10 m ({patch_radius():.1f} m)")
studio["remake_ground"](sc, {"z": -0.002, "size": 400.0, "color": [0.4, 0.4, 0.4]}, dict(st, ground_grass_radius=25.0))
ok(abs(patch_radius() - 25.0) < 0.01, f"a radius of the person's: 25 m ({patch_radius():.1f} m)")
pt = bpy.data.objects["IngeTrazo ground grass patch"]
ok(len(pt.data.polygons) > 60 and all(len(p.vertices) == 3 for p in pt.data.polygons), "…and it is a circle (a fan of triangles)")
# the circle is centred on the centroid of the model's objects (the mean of their centres), at the ground's own height
for o_ in [o for o in bpy.data.objects if o.name == "house"]:
    o_.location = (0, 0, 0)
extra = bpy.data.objects.new("annex", me.copy()); sc.collection.objects.link(extra); extra.location = (30.0, 6.0, 0.0)
studio["remake_ground"](sc, {"z": -0.002, "size": 400.0, "color": [0.4, 0.4, 0.4]}, st)
pt = bpy.data.objects["IngeTrazo ground grass patch"]
ok(abs(pt.location.x - 15.0) < 0.01 and abs(pt.location.y - 3.0) < 0.01 and abs(pt.location.z - 0.001) < 1e-6,
   f"centred on the centroid of the objects (15, 3) at the ground's height ({[round(c, 3) for c in pt.location]})")
bpy.data.objects.remove(extra)
studio["remake_ground"](sc, {"z": -0.002, "size": 400.0, "color": [0.4, 0.4, 0.4]}, dict(st, ground_grass_centre=[7.0, -3.0]))
pt = bpy.data.objects["IngeTrazo ground grass patch"]
ok(abs(pt.location.x - 7.0) < 1e-6 and abs(pt.location.y + 3.0) < 1e-6, f"the centre worked out from the drawing is the one used ({[round(c, 2) for c in pt.location]})")
# the density is per m² whatever the radius: a radius that would pass the tuft limit is cut, not the density
studio["remake_ground"](sc, {"z": -0.002, "size": 400.0, "color": [0.4, 0.4, 0.4]}, dict(st, ground_grass_radius=300.0))
reach = math.sqrt(studio["GRASS_MAX_TUFTS"] / (math.pi * 100.0))
ok(abs(patch_radius() - reach) < 0.5, f"a radius past the tuft limit is cut to {reach:.0f} m at 100 tufts/m2 ({patch_radius():.1f} m)")
for r_ in (10.0, 30.0):
    studio["remake_ground"](sc, {"z": -0.002, "size": 400.0, "color": [0.4, 0.4, 0.4]}, dict(st, ground_grass_radius=r_))
    pt = bpy.data.objects["IngeTrazo ground grass patch"]
    mod = next(m for m in pt.modifiers if m.type == "NODES")
    dens = [n.inputs["Density"].default_value for n in mod.node_group.nodes if n.bl_idname == "GeometryNodeDistributePointsOnFaces"]
    ok(dens == [100.0], f"radius {r_:.0f} m: the density given to Blender is 100 per m2 ({dens})")

# ---- a material painted on nothing is made from its picture and settings, and put on the ground all the same ---------------------
import struct, zlib
def _png(path, rgb):
    raw = b"".join(bytes([0]) + bytes(rgb) * 8 for _ in range(8))
    ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    open(path, "wb").write(bytes([137, 80, 78, 71, 13, 10, 26, 10]) + ch(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))
pic = os.path.join(OUT, "slab.png"); _png(pic, (200, 60, 60))
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.world = bpy.data.worlds.new("W"); sc.world.use_nodes = True
me = bpy.data.meshes.new("h"); me.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
sc.collection.objects.link(bpy.data.objects.new("house", me))
st = {"ground_material": {"name": "Slab", "tile": [1.0, 1.0], "color": [0.5, 0.5, 0.5], "texture": pic},
      "materials": {"Slab": {"type": "generic", "roughness": 0.15, "metallic": 0.0, "bump": 0.0, "glow": 0.0}}}
studio["make_ground"](sc, {"z": -0.002, "size": 400.0, "color": [0.4, 0.4, 0.4]}, st)
gm_ = bpy.data.objects["IngeTrazo ground"].data.materials[0]
bs = next(n for n in gm_.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
ok(any(n.type == "TEX_IMAGE" for n in gm_.node_tree.nodes), "a material the model does not wear still gets its picture on the ground")
ok(abs(bs.inputs["Roughness"].default_value - 0.15) < 1e-6, "…and its own settings (roughness 0.15)")
# the ground's radius: the size of the plane, and the haze melts it over its outer two thirds
studio["remake_ground"](sc, {"z": -0.002, "size": 4000.0, "color": [0.4, 0.4, 0.4]}, {"ground_radius": 150.0})
g_ = bpy.data.objects["IngeTrazo ground"]
ok(abs(g_.dimensions.x - 300.0) < 0.01, f"a ground radius of 150 m makes a ground 300 m across ({g_.dimensions.x:.0f})")
rr = next(n for n in g_.data.materials[0].node_tree.nodes if n.type == "MAP_RANGE")
ok(abs(rr.inputs["From Max"].default_value - 150.0) < 1e-6 and abs(rr.inputs["From Min"].default_value - 52.5) < 1e-6,
   "…and the haze ends at its edge, starting at 35 % of it")

# ---- no generated ground: the sky all round -------------------------------------------------------------------------------------
def sky_world():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc2 = bpy.context.scene
    w = bpy.data.worlds.new("W"); w.use_nodes = True
    sky = w.node_tree.nodes.new("ShaderNodeTexSky")
    bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
    w.node_tree.links.new(sky.outputs["Color"], bg.inputs["Color"])
    sc2.world = w
    return sc2, sky
sc2, sky = sky_world()
ok(studio["sky_whole_sphere"](sc2) is True and any(n.type == "MATH" and n.operation == "ABSOLUTE" for n in sc2.world.node_tree.nodes),
   "the sky below the horizon is the sky above it, mirrored: all round")
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc2.collection.objects.link(cam)
cam.location = (0, 0, 2); cam.rotation_euler = (0, 0, 0)          # looking straight down
sc2.camera = cam
sc2.render.resolution_x = sc2.render.resolution_y = 16
sc2.render.engine = "CYCLES"; sc2.cycles.samples = 2; sc2.view_settings.view_transform = "Standard"
def mean_colour(path):
    sc2.render.filepath = path; bpy.ops.render.render(write_still=True)
    im = bpy.data.images.load(path); px = list(im.pixels); n = len(px) // 4
    return [sum(px[i::4]) / n for i in range(3)]
with_sky = mean_colour(os.path.join(OUT, "down_sky.png"))
sc3, sky3 = sky_world(); cam3 = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc3.collection.objects.link(cam3)
cam3.location = (0, 0, 2); sc3.camera = cam3
sc3.render.resolution_x = sc3.render.resolution_y = 16; sc3.render.engine = "CYCLES"; sc3.cycles.samples = 2; sc3.view_settings.view_transform = "Standard"
sc2 = sc3
without = mean_colour(os.path.join(OUT, "down_plain.png"))
ok(with_sky[2] > without[2] * 1.5 or with_sky[2] > with_sky[0] * 1.15, f"looking down, the world is sky (blue {with_sky[2]:.2f}) and not the dark ground below the horizon ({without[2]:.2f})")

# ---- the distant skyline ----------------------------------------------------------------------------------------------------------------------
import math as _math
for kind in ("mountains", "hills", "forest", "city"):
    prof = studio["skyline_profile"](kind, 720, 3)
    ok(len(prof) == 720 and 0.0 <= min(prof) and max(prof) <= 1.0001 and max(prof) > 0.9 and max(prof) - min(prof) > 0.15, f"the {kind} outline varies (from {min(prof):.2f} to {max(prof):.2f})")
    ok(studio["skyline_profile"](kind, 720, 3) == prof and studio["skyline_profile"](kind, 720, 4) != prof, f"…the same for the same seed, another for another")
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.world = bpy.data.worlds.new("W"); sc.world.use_nodes = True
me = bpy.data.meshes.new("h"); me.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
sc.collection.objects.link(bpy.data.objects.new("house", me))
studio["make_ground"](sc, {"z": -0.002, "size": 4000.0, "color": [0.4, 0.4, 0.4]}, {"skyline": {"type": "mountains", "height": 5.0, "seed": 2}, "ground_radius": 1000.0})
sk = [o for o in bpy.data.objects if o.name.startswith("IngeTrazo skyline")]
ok(len(sk) == 3 and all(o.visible_shadow is False for o in sk), f"mountains are three layers that cast no shadow ({len(sk)})")
tallest = max(max(v.co.z for v in o.data.vertices) for o in sk)
far_ = max(max(_math.hypot(v.co.x, v.co.y) for v in o.data.vertices) for o in sk)
ok(abs(far_ - 1000.0) < 1.0, f"the farthest layer is at the ground's radius ({far_:.0f} m)")
ok(abs(_math.degrees(_math.atan2(tallest, far_)) - 5.0) < 0.6, f"the tallest peak reaches the angle asked for ({_math.degrees(_math.atan2(tallest, far_)):.1f}°)")
ok(all(any(n.type == "MAP_RANGE" for n in o.data.materials[0].node_tree.nodes) for o in sk), "each layer melts into the sky's horizon with distance")
studio["make_ground"](sc, {"z": -0.002, "size": 4000.0, "color": [0.4, 0.4, 0.4]}, {})
ok(True, "")
sys.exit(1 if fails else 0)
