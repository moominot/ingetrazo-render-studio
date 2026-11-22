"""Water waves in real geometry, and grass that keeps its cover when it is short.

Run:  blender -b --factory-startup --python tests/test_water_waves_blender.py -- <repo> <render_scene.py> <out dir>
"""
import math, os, sys
import bpy
import bmesh

argv = sys.argv[sys.argv.index("--") + 1:]
REPO, RS, OUT = (os.path.abspath(a) for a in argv[:3])
os.makedirs(OUT, exist_ok=True)
import shutil
shutil.copyfile(RS, os.path.join(OUT, "render_scene.py"))
src = open(os.path.join(REPO, "render_studio", "blender", "studio_scene.py"), encoding="utf-8").read().rstrip().rsplit("\nmain()", 1)[0]
studio = {"__name__": "studio_scene", "__file__": os.path.join(OUT, "studio_scene.py")}
exec(compile(src, "studio_scene.py", "exec"), studio)
fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

def pool(body, waves):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    water = bpy.data.materials.new("Aigua"); water.use_nodes = True
    stone = bpy.data.materials.new("Stone"); stone.use_nodes = True
    me = bpy.data.meshes.new("pool")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(8.0, 4.0, 1.0), verts=bm.verts)
    bm.to_mesh(me); bm.free()
    me.materials.append(stone); me.materials.append(water)
    for p in me.polygons:
        p.material_index = 1 if p.normal.z > 0.9 else 0
    ob = bpy.data.objects.new("pool", me)
    sc.collection.objects.link(ob)
    specs = {"Aigua": {"type": "water", "water_body": body, "waves": waves, "bump": 0.3, "ripple_size": 0.8}}
    n = studio["build_water_waves"](specs)
    return ob, n

ob, n = pool("lake", 1.0)
ok(n == 1 and any(m.type == "NODES" for m in ob.modifiers), "a lake with waves gets the modifier")
dg = bpy.context.evaluated_depsgraph_get()
ev = ob.evaluated_get(dg).to_mesh()
zs = [v.co.z for v in ev.vertices if v.co.z > 0.3]
ok(len(ev.vertices) > 250, f"the water is divided ({len(ev.vertices)} vertices)")
ok(max(zs) - min(zs) > 0.01, f"the surface is lifted and lowered ({max(zs) - min(zs):.3f} m)")
# the edge stays: the top rim of the pool is at z = 0.5 exactly
rim = [v.co.z for v in ev.vertices if v.co.z > 0.3 and (abs(abs(v.co.x) - 4.0) < 1e-4 or abs(abs(v.co.y) - 2.0) < 1e-4)]
ok(rim and max(abs(z - 0.5) for z in rim) < 1e-4, "the water does not leave its edge (no crack against the walls)")
ob, n = pool("pool", 0.0)
ok(n == 0 and not ob.modifiers, "waves 0: flat water, no modifier")
ob, n = pool("ocean", 1.0)
dg = bpy.context.evaluated_depsgraph_get()
ev = ob.evaluated_get(dg).to_mesh()
ok(len(ev.vertices) < 100_000, f"the division stays light ({len(ev.vertices)})")
ob, n = pool("pool", 1.0)
ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
ok(1000 < len(ev.vertices) < 100_000, f"a pool's fine waves need a finer division ({len(ev.vertices)})")

# grass: the tuft's footprint follows the density, not the height
f_low = studio["grass_footprint"](260.0, 0.02)
f_tall = studio["grass_footprint"](260.0, 0.06)
ok(abs(f_low - f_tall) < 1e-9, "a short lawn and a mown one cover alike at the same density")
ok(studio["grass_footprint"](520.0, 0.04) < studio["grass_footprint"](130.0, 0.04), "denser grass: smaller tufts, more of them")
bpy.ops.wm.read_factory_settings(use_empty=True)
print("FAILED" if fails else "ALL PASS")
sys.exit(1 if fails else 0)
