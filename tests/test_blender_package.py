"""A material edited in Blender comes back whole (its node tree, and for grass the group that grows it) and the render
uses it exactly as it was left.  Plain Python driving a real Blender:
   python test_blender_package.py <repo> <blender.exe> <outdir> <render_scene.py>"""
import json, os, shutil, subprocess, sys
REPO, BLENDER, OUT, RS = (os.path.abspath(a) for a in sys.argv[1:5])
sys.path.insert(0, REPO)
os.makedirs(OUT, exist_ok=True)
from render_studio import blender_edit as BE
EDIT = os.path.join(REPO, "render_studio", "blender", "edit_scene.py")
fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)
def blender(*args, env=None):
    r = subprocess.run([BLENDER, "-b", "--factory-startup", *args], capture_output=True, text=True, timeout=300, env=env)
    if r.returncode: print(r.stdout[-1500:], r.stderr[-600:])
    return r

# ---- a plain material: a Noise texture on its roughness, added in Blender ------------------------------------------------
d = os.path.join(OUT, "mat"); os.makedirs(d, exist_ok=True)
BE.dump(__import__("pathlib").Path(d, "in.json"), [{"name": "Pave", "color": [0.6, 0.5, 0.4], "roughness": 0.5, "metallic": 0.0, "glow": 0.0, "texture": None, "grass": None, "package": None}])
blender("--python", EDIT, "--", "make", "materials", os.path.join(d, "in.json"), os.path.join(d, "s.blend"))
# nothing changed: no package
blender(os.path.join(d, "s.blend"), "--python", EDIT, "--", "read", "materials", os.path.join(d, "r0.json"))
r0 = json.load(open(os.path.join(d, "r0.json")))
ok(len(r0) == 1 and "package" not in r0[0], "an untouched material comes back as numbers only, no package")
mod = os.path.join(d, "mod.py")
open(mod, "w").write("""
import bpy
m = bpy.data.materials["Pave"]
nt = m.node_tree
noise = nt.nodes.new("ShaderNodeTexNoise"); noise.inputs["Scale"].default_value = 37.0
b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
nt.links.new(noise.outputs["Fac"], b.inputs["Roughness"])
bpy.ops.wm.save_mainfile()
""")
blender(os.path.join(d, "s.blend"), "--python", mod)
blender(os.path.join(d, "s.blend"), "--python", EDIT, "--", "read", "materials", os.path.join(d, "r1.json"))
r1 = json.load(open(os.path.join(d, "r1.json")))
pkg = r1[0].get("package")
ok(pkg is not None and pkg["material"] == "Pave" and len(pkg["blend"]) > 1000, f"an edited node tree comes back as a package ({len(pkg['blend']) if pkg else 0} chars)")
changed = BE.materials_from_blender({}, r1, {})
ok(changed.get("Pave", {}).get("blender") == pkg, "…and goes into the material's settings")

# the render: the package takes the place of the material the settings made
test = os.path.join(d, "apply.py")
open(test, "w").write("""
import bpy, json, os, sys
argv = sys.argv[sys.argv.index("--") + 1:]
REPO, RS, OUTDIR, PKG = argv
shutil = __import__("shutil"); shutil.copyfile(RS, os.path.join(OUTDIR, "render_scene.py"))
src = open(os.path.join(REPO, "render_studio", "blender", "studio_scene.py"), encoding="utf-8").read().rstrip().rsplit("\\nmain()", 1)[0]
studio = {"__name__": "studio_scene", "__file__": os.path.join(OUTDIR, "studio_scene.py")}
exec(compile(src, "studio_scene.py", "exec"), studio)
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
mat = bpy.data.materials.new("Pave"); mat.use_nodes = True
me = bpy.data.meshes.new("w"); me.from_pydata([(0,0,0),(1,0,0),(1,1,0)], [], [(0,1,2)]); me.materials.append(mat)
ob = bpy.data.objects.new("wall", me); sc.collection.objects.link(ob)
pkg = json.load(open(PKG))
n = studio["apply_blender_packages"]({"Pave": {"type": "generic", "roughness": 0.9, "blender": pkg}})
m = ob.material_slots[0].material
types = sorted({x.type for x in m.node_tree.nodes})
print("RESULT", n, m.name, m.get("rs_blender"), "TEX_NOISE" in types, len([x for x in bpy.data.materials if x.name.startswith("Pave")]))
studio["cap_albedo"](0.1)
b = next(x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED")
print("ALBEDO", [round(c, 2) for c in b.inputs["Base Color"].default_value[:3]])
""")
json.dump(pkg, open(os.path.join(d, "pkg.json"), "w"))
r = blender("--python", test, "--", REPO, RS, d, os.path.join(d, "pkg.json"))
line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT")), "")
ok(line.split()[1:5] == ["1", "Pave", "True", "True"] and line.split()[-1] == "1", f"the render puts the edited material on the object under its own name ({line})")
alb = next((l for l in r.stdout.splitlines() if l.startswith("ALBEDO")), "")
ok("0.6" in alb, f"…and the albedo cap leaves it as it was left ({alb})")

# ---- grass: its geometry-nodes group edited in Blender -----------------------------------------------------------------
g = os.path.join(OUT, "grass"); os.makedirs(g, exist_ok=True)
shutil.copyfile(RS, os.path.join(g, "render_scene.py"))
shutil.copyfile(os.path.join(REPO, "render_studio", "blender", "studio_scene.py"), os.path.join(g, "studio_scene.py"))
BE.dump(__import__("pathlib").Path(g, "in.json"), [{"name": "Gespa", "color": [0.2, 0.5, 0.1], "roughness": 0.85, "metallic": 0.0, "glow": 0.0, "texture": None,
        "grass": {"type": "grass", "grass_height": 0.06, "grass_density": 200.0}, "package": None}])
blender("--python", EDIT, "--", "make", "materials", os.path.join(g, "in.json"), os.path.join(g, "s.blend"))
blender(os.path.join(g, "s.blend"), "--python", EDIT, "--", "read", "materials", os.path.join(g, "r0.json"))
ok("package" not in json.load(open(os.path.join(g, "r0.json")))[0], "untouched grass: no package")
open(os.path.join(g, "mod.py"), "w").write("""
import bpy
patch = bpy.data.objects["Gespa patch"]
ng = next(m.node_group for m in patch.modifiers if m.type == "NODES")
for n in ng.nodes:
    if n.bl_idname == "GeometryNodeDistributePointsOnFaces":
        n.inputs["Density"].default_value = 123.0
bpy.ops.wm.save_mainfile()
""")
blender(os.path.join(g, "s.blend"), "--python", os.path.join(g, "mod.py"))
blender(os.path.join(g, "s.blend"), "--python", EDIT, "--", "read", "materials", os.path.join(g, "r1.json"))
gp = json.load(open(os.path.join(g, "r1.json")))[0].get("package")
ok(gp is not None and gp.get("group") and gp.get("tuft"), f"an edited grass group comes back with its tuft ({gp and (gp.get('group'), gp.get('tuft'))})")
json.dump(gp, open(os.path.join(g, "pkg.json"), "w"))
open(os.path.join(g, "apply.py"), "w").write("""
import bpy, json, os, sys
argv = sys.argv[sys.argv.index("--") + 1:]
REPO, OUTDIR, PKG = argv
src = open(os.path.join(REPO, "render_studio", "blender", "studio_scene.py"), encoding="utf-8").read().rstrip().rsplit("\\nmain()", 1)[0]
studio = {"__name__": "studio_scene", "__file__": os.path.join(OUTDIR, "studio_scene.py")}
exec(compile(src, "studio_scene.py", "exec"), studio)
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
mat = bpy.data.materials.new("Gespa"); mat.use_nodes = True
me = bpy.data.meshes.new("w"); me.from_pydata([(0,0,0),(5,0,0),(5,5,0),(0,5,0)], [], [(0,1,2,3)]); me.materials.append(mat)
ob = bpy.data.objects.new("lawn", me); sc.collection.objects.link(ob)
specs = {"Gespa": {"type": "grass", "grass_height": 0.06, "grass_density": 200.0, "blender": json.load(open(PKG))}}
studio["build_grass"](specs, 1.0)                  # the generated grass leaves it alone
studio["apply_blender_packages"](specs)
mods = [m for m in ob.modifiers if m.type == "NODES"]
dens = [n.inputs["Density"].default_value for n in mods[0].node_group.nodes if n.bl_idname == "GeometryNodeDistributePointsOnFaces"] if mods else []
sel = [n.inputs["Material"].default_value.name for n in mods[0].node_group.nodes if n.bl_idname == "GeometryNodeMaterialSelection"] if mods else []
print("GRASS", len(mods), dens, sel, ob.material_slots[0].material.name)
""")
r = blender("--python", os.path.join(g, "apply.py"), "--", REPO, g, os.path.join(g, "pkg.json"))
line = next((l for l in r.stdout.splitlines() if l.startswith("GRASS")), "")
ok(line.startswith("GRASS 1 [123.0]") and "Gespa" in line, f"the render grows the grass with the group as it was edited, once ({line})")


# ---- a material with maps is opened as the render makes it: the roughness map is nodes, not a number ------------------------
m = os.path.join(OUT, "maps"); os.makedirs(m, exist_ok=True)
shutil.copyfile(RS, os.path.join(m, "render_scene.py"))
shutil.copyfile(os.path.join(REPO, "render_studio", "blender", "studio_scene.py"), os.path.join(m, "studio_scene.py"))
import struct, zlib
raw = b"".join(bytes([0]) + bytes((90, 90, 90)) * 8 for _ in range(8))
def _chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
pic = os.path.join(m, "rock.png")
open(pic, "wb").write(bytes([137, 80, 78, 71, 13, 10, 26, 10]) + _chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
                      + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))
BE.dump(__import__("pathlib").Path(m, "in.json"), [{"name": "Rock", "color": [0.4, 0.4, 0.4], "roughness": 0.7, "metallic": 0.0, "glow": 0.0,
        "texture": {"path": pic}, "grass": None, "package": None, "pbr": {},
        "spec": {"type": "generic", "roughness": 0.7, "metallic": 0.0, "bump": 0.6, "glow": 0.0,
                 "maps": {"roughness": {"source": "picture", "invert": True, "contrast": 0.3}},
                 "image": {"hue": 10}}}])
blender("--python", EDIT, "--", "make", "materials", os.path.join(m, "in.json"), os.path.join(m, "s.blend"))
open(os.path.join(m, "probe.py"), "w").write("""
import bpy
mt = bpy.data.materials["Rock"]
types = sorted({n.type for n in mt.node_tree.nodes})
b = next(n for n in mt.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
print("MAPS", types, b.inputs["Roughness"].is_linked, b.inputs["Normal"].is_linked)
""")
r = blender(os.path.join(m, "s.blend"), "--python", os.path.join(m, "probe.py"))
line = next((l for l in r.stdout.splitlines() if l.startswith("MAPS")), "")
ok("RGBTOBW" in line and "True" in line.split("]")[-1].split()[0:1] or ("RGBTOBW" in line and "True" in line), f"the roughness map is nodes in the material, and the relief ({line[:150]})")
blender(os.path.join(m, "s.blend"), "--python", EDIT, "--", "read", "materials", os.path.join(m, "r.json"))
ok("package" not in json.load(open(os.path.join(m, "r.json")))[0], "…and opened as it is, it comes back with no package")

# ---- a light edited in Blender comes back as a proxy and the render uses it as it was left ------------------------------------
from render_studio import lights as L
lt = L.new_light("point", pos=(1.0, 2.0, 2.5), name="Lamp", power=900)
ld = os.path.join(OUT, "light"); os.makedirs(ld, exist_ok=True)
BE.dump(__import__("pathlib").Path(ld, "in.json"), BE.lights_to_blender([lt]))
blender("--python", EDIT, "--", "make", "lights", os.path.join(ld, "in.json"), os.path.join(ld, "s.blend"))
blender(os.path.join(ld, "s.blend"), "--python", EDIT, "--", "read", "lights", os.path.join(ld, "r0.json"))
ok("package" not in json.load(open(os.path.join(ld, "r0.json")))[0], "a light opened as it is comes back with no package")
open(os.path.join(ld, "mod.py"), "w").write("""
import bpy
o = next(o for o in bpy.data.objects if o.type == "LIGHT")
o.data.use_custom_distance = True          # something Render Studio's light format has no place for
o.data.cutoff_distance = 7.5
o.data.energy *= 2
bpy.ops.wm.save_mainfile()
""")
blender(os.path.join(ld, "s.blend"), "--python", os.path.join(ld, "mod.py"))
blender(os.path.join(ld, "s.blend"), "--python", EDIT, "--", "read", "lights", os.path.join(ld, "r1.json"))
r1 = json.load(open(os.path.join(ld, "r1.json")))
ok(r1[0].get("package", {}).get("blend"), "a light with a setting of Blender's own comes back as a package")
back = BE.lights_from_blender([lt], r1)
proxy = back[0]
ok(proxy.get("blender", {}).get("blend") and proxy["type"] == "point" and proxy["name"] == "Lamp" and proxy["id"] == lt["id"],
   "…as a proxy: the same light in the list (kind, name, id) with the Blender light inside")
# opened again, unchanged: no new package; the proxy is kept as it is
BE.dump(__import__("pathlib").Path(ld, "in2.json"), BE.lights_to_blender([proxy]))
blender("--python", EDIT, "--", "make", "lights", os.path.join(ld, "in2.json"), os.path.join(ld, "s2.blend"))
blender(os.path.join(ld, "s2.blend"), "--python", EDIT, "--", "read", "lights", os.path.join(ld, "r2.json"))
r2 = json.load(open(os.path.join(ld, "r2.json")))
ok("package" not in r2[0], "a proxy opened again and left alone comes back with no new package")
again = BE.lights_from_blender([proxy], r2)
ok(again[0].get("blender") == proxy["blender"], "…and keeps the one it had")
# the render
json.dump({"lights": [dict(proxy, energy=1.0, basis=[[1, 0, 0], [0, 1, 0], [0, 0, 1]], pos=[4.0, 5.0, 3.0])]}, open(os.path.join(ld, "job.json"), "w"))
open(os.path.join(ld, "render.py"), "w").write("""
import bpy, json, os, sys
argv = sys.argv[sys.argv.index("--") + 1:]
REPO, RS, OUTDIR, JOB = argv
import shutil; shutil.copyfile(RS, os.path.join(OUTDIR, "render_scene.py"))
src = open(os.path.join(REPO, "render_studio", "blender", "studio_scene.py"), encoding="utf-8").read().rstrip().rsplit("\\nmain()", 1)[0]
studio = {"__name__": "studio_scene", "__file__": os.path.join(OUTDIR, "studio_scene.py")}
exec(compile(src, "studio_scene.py", "exec"), studio)
bpy.ops.wm.read_factory_settings(use_empty=True)
made = studio["add_studio_lights"](bpy.context.scene, json.load(open(JOB))["lights"])
o = made[0]
print("LIGHT", len(made), o.data.use_custom_distance, round(o.data.cutoff_distance, 2), [round(c, 2) for c in o.location], round(o.data.energy, 3))
""")
r = blender("--python", os.path.join(ld, "render.py"), "--", REPO, RS, ld, os.path.join(ld, "job.json"))
line = next((l for l in r.stdout.splitlines() if l.startswith("LIGHT")), "")
ok(line.startswith("LIGHT 1 True 7.5 [4.0, 5.0, 3.0]"), f"the render uses the Blender light as it was left, moved to where the list says ({line})")
print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
