"""The section's cap: a flat colour or a hatch pattern, with or without shadows. A real Blender."""
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


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
    return sc


def look(sc, name):
    """The cap seen square on, unlit and unmanaged: pixels are the colours themselves."""
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"; cam.data.ortho_scale = 0.5
    cam.location = (5, 0, 0); cam.rotation_euler = (math.pi / 2, 0, math.pi / 2)
    sc.camera = cam
    sc.render.engine = "CYCLES"; sc.cycles.samples = 4; sc.cycles.use_denoising = False
    sc.render.resolution_x = sc.render.resolution_y = 128
    sc.view_settings.view_transform = "Standard"
    sc.render.filepath = os.path.join(OUT, name + ".png")
    sc.world = bpy.data.worlds.new("w"); sc.world.use_nodes = True
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(sc.render.filepath)
    px = list(img.pixels)
    return [tuple(round(px[i + k] * 255) for k in range(3)) for i in range(0, len(px), 4)]


SEC = {"point": [0, 0, 0], "normal": [1, 0, 0], "cap": True, "light": "open", "material": None,
       "color": [1.0, 0.0, 0.0], "texture_size": [1.0, 1.0], "style": "flat", "shadows": True}

# flat colour, with shadows: a face of the cut mesh itself
sc = fresh()
studio["clip_section"](dict(SEC))
cube = bpy.data.objects["Cube"]
mats = [m.name for m in cube.data.materials if m]
ok(any("section cap" in m.lower() for m in mats) and "Section cap" not in bpy.data.objects, "flat colour: the cap is part of the cut mesh")

# flat colour, no shadows: an object of its own that casts none, with an unlit material
sc = fresh()
studio["clip_section"](dict(SEC, shadows=False))
cap = bpy.data.objects.get("Section cap")
ok(cap is not None and cap.visible_shadow is False, "no shadows: the cap is an object of its own that casts no shadow")
ok(cap is not None and any(n.type == "EMISSION" for n in cap.data.materials[0].node_tree.nodes), "…with an unlit material, so it takes no shadow")
cube = bpy.data.objects["Cube"]
ok(not any(p.material_index > 0 for p in cube.data.polygons) or len(cube.data.materials) <= 1, "…and the cut mesh keeps no cap face")
pix = look(sc, "flat")
mid = pix[len(pix) // 2 + 64]
ok(mid[0] > 240 and mid[1] < 12 and mid[2] < 12, f"the flat colour shows as it is (centre pixel {mid})")

# a hatch: lines of the line colour over the ground colour, unlit
sc = fresh()
studio["clip_section"](dict(SEC, style="hatch", shadows=False, color=[1.0, 1.0, 1.0], line=[0.0, 0.0, 0.0],
                            pattern="diagonal", spacing=0.1))
pix = look(sc, "hatch")
dark = sum(1 for p in pix if p[0] < 60); light = sum(1 for p in pix if p[0] > 200)
ok(dark > 800 and light > 8000, f"diagonal hatch: lines and ground both show ({dark} dark, {light} light of {len(pix)})")
sc = fresh()
studio["clip_section"](dict(SEC, style="hatch", shadows=False, color=[1.0, 1.0, 1.0], line=[0.0, 0.0, 0.0],
                            pattern="cross", spacing=0.1))
pix2 = look(sc, "cross")
dark2 = sum(1 for p in pix2 if p[0] < 60)
ok(dark2 > dark * 1.3, f"cross hatch has more line than a single hatch ({dark2} vs {dark})")
sc = fresh()
studio["clip_section"](dict(SEC, style="hatch", shadows=False, color=[1.0, 1.0, 1.0], line=[0.0, 0.0, 0.0],
                            pattern="dots", spacing=0.1))
pix3 = look(sc, "dots")
dark3 = sum(1 for p in pix3 if p[0] < 60)
ok(150 < dark3 < len(pix3) * 0.5, f"dots show ({dark3})")

# hatch with shadows: stays an ordinary material of the cut mesh (lit)
sc = fresh()
studio["clip_section"](dict(SEC, style="hatch", shadows=True))
ok("Section cap" not in bpy.data.objects, "a hatch with shadows is lit and part of the mesh")

# the model's own material, unlit: a copy, the original untouched
sc = fresh()
mine = bpy.data.materials.new("Concrete"); mine.use_nodes = True
studio["clip_section"](dict(SEC, style="material", material="Concrete", shadows=False))
ok(not any(n.type == "EMISSION" for n in mine.node_tree.nodes), "the model's material is not changed by an unlit cap")
cap = bpy.data.objects.get("Section cap")
ok(cap is not None and any(n.type == "EMISSION" for n in cap.data.materials[0].node_tree.nodes), "…its copy is what the cap wears")
sys.exit(1 if fails else 0)
