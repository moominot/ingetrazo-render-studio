"""Import a GLB written by IngeTrazo, apply Render Studio's water type and render. usage: glbpool.py <glb> <out> [type]"""
import math, os, shutil, sys
import bpy, mathutils
GLB, OUT = sys.argv[1], sys.argv[2]; KIND = sys.argv[3] if len(sys.argv) > 3 else "water"
work = os.path.dirname(os.path.abspath(OUT))
shutil.copyfile(os.environ.get("INGETRAZO_RENDER_SCENE", "/home/user/ingetrazo/resources/blender/render_scene.py"), work + "/render_scene.py")
shutil.copyfile(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render_studio", "blender", "studio_scene.py"), work + "/studio_scene.py")
src = open(work + "/studio_scene.py").read().rstrip().rsplit("\nmain()", 1)[0]
ns = {"__name__": "lib", "__file__": work + "/studio_scene.py"}; exec(compile(src + "\n", ns["__file__"], "exec"), ns)
core = ns["core"]
bpy.ops.wm.read_factory_settings(use_empty=True); scene = bpy.context.scene
core["import_model"](GLB)
print("MATERIALS", [(m.name, round(m.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value, 2), bool(m.node_tree.nodes["Principled BSDF"].inputs["Alpha"].links)) for m in bpy.data.materials if m.node_tree])
specs = {"agua": {"type": KIND, "roughness": 0.02, "metallic": 0.0, "bump": 0.5, "ripple_size": 0.8}}
if KIND == "glass": specs["agua"]["transparency"] = float(os.environ.get("TRANSP", "0.85"))
ns["mark_material_types"](specs); core["apply_finishes"](); ns["apply_material_specs"](specs)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scene.collection.objects.link(cam); scene.camera = cam
cam.location = (0, -7.5, 3.0); cam.rotation_euler = (mathutils.Vector((0, 0, -0.5)) - cam.location).to_track_quat("-Z", "Y").to_euler(); cam.data.lens = 30
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); scene.collection.objects.link(sun); sun.data.energy = 4
sun.rotation_euler = mathutils.Vector((0.15, -0.5, -0.85)).to_track_quat("-Z", "Y").to_euler()
world = bpy.data.worlds.new("w"); world.use_nodes = True; scene.world = world
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND"); bg.inputs["Color"].default_value = (0.6, 0.75, 1, 1)
r = scene.render; r.engine = "CYCLES"; r.resolution_x, r.resolution_y = 640, 360; r.image_settings.file_format = "PNG"
scene.cycles.samples = 48; scene.cycles.device = "CPU"; scene.cycles.use_denoising = False; scene.view_settings.view_transform = "AgX"
r.filepath = OUT + ".png"; bpy.ops.render.render(write_still=True); print("rendered", OUT)
