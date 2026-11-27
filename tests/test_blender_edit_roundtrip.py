"""«Edit in Blender»: the lights and the materials make the trip to a real Blender and back.

Plain Python (no Qt): ``python test_blender_edit_roundtrip.py <repo> <blender.exe> <outdir>``.
"""
import json
import os
import subprocess
import sys

REPO, BLENDER, OUT = (os.path.abspath(a) for a in sys.argv[1:4])
sys.path.insert(0, REPO)
os.makedirs(OUT, exist_ok=True)
from render_studio import blender_edit as BE, lights as L  # noqa: E402

fails = []


def ok(c, what):
    print(("PASS " if c else "FAIL ") + what, flush=True)
    if not c:
        fails.append(what)


def blender(*args):
    r = subprocess.run([BLENDER, "-b", "--factory-startup", *args], capture_output=True, text=True, timeout=240)
    if r.returncode:
        print(r.stdout[-1500:], r.stderr[-800:])
    return r.returncode == 0


# ---- lights ------------------------------------------------------------------------------------
point = L.new_light("point", pos=(1, 2, 2.5), name="Lamp", power=900)                   # lumens
spot = L.new_light("spot", pos=(-2, 0, 3), name="Downlight", dir=[0.0, 0.3, -1.0], spot_angle=35.0)
area = L.new_light("area", pos=(0, 3, 2), name="Panel", shape="rectangle", size=1.2, size_y=0.4,
                   dir=[0.0, -1.0, 0.0], spin=30.0)
sun = L.new_light("sun", pos=(0, 0, 10), name="Moon", power=0.05, dir=[0.3, 0.2, -1.0])
old = [point, spot, area, sun]
BE.dump(__import__("pathlib").Path(OUT, "lights_in.json"), BE.lights_to_blender(old))
blend = os.path.join(OUT, "lights.blend")
ok(blender("--python", os.path.join(REPO, "render_studio", "blender", "edit_scene.py"), "--", "make", "lights",
           os.path.join(OUT, "lights_in.json"), blend), "Blender makes the lights scene")
out1 = os.path.join(OUT, "lights_out1.json")
ok(blender(blend, "--python", os.path.join(REPO, "render_studio", "blender", "edit_scene.py"), "--", "read",
           "lights", out1), "Blender reads it back")
read = json.load(open(out1))
ok(len(read) == 4, f"four lights come out ({len(read)})")
back = BE.lights_from_blender(old, read)
ok(BE.same(back, old),
   "an untouched round trip changes nothing (units, kelvin, aim, spin, size kept)")
if back != old:
    for a, b in zip(old, back):
        for k in a:
            if a[k] != b.get(k):
                print("  differs", a["name"], k, a[k], b.get(k))

# the person's edits in Blender: the lamp twice as bright and moved, the sun deleted, a new point light
mod = os.path.join(OUT, "mod.py")
open(mod, "w").write('''
import bpy
for o in list(bpy.data.objects):
    if o.type == "LIGHT" and o.get("rs_id") == %r:
        o.data.energy *= 2.0
        o.location.x += 1.0
    if o.type == "LIGHT" and o.get("rs_id") == %r:
        bpy.data.objects.remove(o)
d = bpy.data.lights.new("Candle", "POINT")
d.energy = 20.0
d.color = (1.0, 0.5, 0.2)
n = bpy.data.objects.new("Candle", d)
bpy.context.scene.collection.objects.link(n)
n.location = (4, 4, 1)
bpy.ops.wm.save_mainfile()
''' % (point["id"], sun["id"]))
ok(blender(blend, "--python", mod), "the edits are made in Blender and saved")
out2 = os.path.join(OUT, "lights_out2.json")
blender(blend, "--python", os.path.join(REPO, "render_studio", "blender", "edit_scene.py"), "--", "read", "lights", out2)
new = BE.lights_from_blender(old, json.load(open(out2)))
by = {lt["name"]: lt for lt in new}
ok(set(by) == {"Lamp", "Downlight", "Panel", "Candle"}, f"the sun is gone and the candle is in ({sorted(by)})")
lamp = by["Lamp"]
ok(lamp["unit"] == "lm" and abs(lamp["power"] - 1800) < 2 and lamp["kelvin"] == point["kelvin"],
   f"the lamp is twice as bright, still in lumens and with its temperature ({lamp['power']:.0f} {lamp['unit']})")
ok(abs(lamp["pos"][0] - 2.0) < 1e-3, "…and moved a metre")
ok(by["Panel"] == area, "the panel is as it was")
cand = by["Candle"]
ok(cand["type"] == "point" and cand["kelvin"] is None and abs(cand["color"][1] - 0.5) < 1e-3 and cand["id"] != "",
   "the new candle is a point light of its own colour, with an id of its own")
ok(len({lt["id"] for lt in new}) == 4, "ids are unique")

# ---- materials ---------------------------------------------------------------------------------
specs = [{"name": "Paint", "color": [0.9, 0.2, 0.2], "roughness": 0.5, "metallic": 0.0, "glow": 0.0},
         {"name": "Steel", "color": [0.6, 0.6, 0.65], "roughness": 0.3, "metallic": 1.0, "glow": 0.0},
         {"name": "Lamp", "color": [1.0, 0.9, 0.7], "roughness": 0.5, "metallic": 0.0, "glow": 4.0}]
BE.dump(__import__("pathlib").Path(OUT, "mats_in.json"), specs)
mblend = os.path.join(OUT, "mats.blend")
ok(blender("--python", os.path.join(REPO, "render_studio", "blender", "edit_scene.py"), "--", "make", "materials",
           os.path.join(OUT, "mats_in.json"), mblend), "Blender makes the materials scene")
mout = os.path.join(OUT, "mats_out.json")
blender(mblend, "--python", os.path.join(REPO, "render_studio", "blender", "edit_scene.py"), "--", "read", "materials", mout)
read = json.load(open(mout))
ok(len(read) == 3, f"three materials come out ({len(read)})")
doc = {"Steel": {"type": "generic", "roughness": 0.3, "metallic": 1.0, "bump": 0.0, "glow": 0.0}}
current = dict(doc, Paint={"type": "generic", "roughness": 0.5, "metallic": 0.0, "bump": 0.0, "glow": 0.0},
               Lamp={"type": "glowing", "roughness": 0.5, "metallic": 0.0, "bump": 0.0, "glow": 4.0})
ok(BE.materials_from_blender(doc, read, current) == {}, "an untouched round trip changes no material")
mod2 = os.path.join(OUT, "mod2.py")
open(mod2, "w").write('''
import bpy
m = bpy.data.materials["Paint"]
b = m.node_tree.nodes["Principled BSDF"]
b.inputs["Roughness"].default_value = 0.1
b.inputs["Metallic"].default_value = 0.8
bpy.ops.wm.save_mainfile()
''')
ok(blender(mblend, "--python", mod2), "a material is changed in Blender")
blender(mblend, "--python", os.path.join(REPO, "render_studio", "blender", "edit_scene.py"), "--", "read", "materials", mout)
ch = BE.materials_from_blender(doc, json.load(open(mout)), current)
ok(set(ch) == {"Paint"} and abs(ch["Paint"]["roughness"] - 0.1) < 1e-3 and abs(ch["Paint"]["metallic"] - 0.8) < 1e-3
   and ch["Paint"]["type"] == "generic", f"only Paint changed: roughness and metal taken ({list(ch)})")


# ---- a Blender WITH a window (the one the person gets): it must build the scene and save it ------------------
if "--no-gui" not in sys.argv:
    gdir = os.path.join(OUT, "gui"); os.makedirs(gdir, exist_ok=True)
    BE.dump(__import__("pathlib").Path(gdir, "in.json"), BE.lights_to_blender(old))
    BE.dump(__import__("pathlib").Path(gdir, "min.json"), specs)
    env = dict(os.environ, RENDER_STUDIO_EDIT_QUIT="1")
    for kind, data in (("lights", "in.json"), ("materials", "min.json")):
        target = os.path.join(gdir, kind + ".blend")
        subprocess.run([BLENDER, "--python", os.path.join(REPO, "render_studio", "blender", "edit_scene.py"), "--",
                        "make", kind, os.path.join(gdir, data), target], capture_output=True, text=True, timeout=240, env=env)
        ok(os.path.isfile(target) and not os.path.isfile(os.path.join(gdir, "error.txt")),
           f"Blender with a window builds the {kind} scene and saves it")
        if os.path.isfile(target):
            outj = os.path.join(gdir, kind + "_out.json")
            blender(target, "--python", os.path.join(REPO, "render_studio", "blender", "edit_scene.py"), "--", "read", kind, outj)
            got = json.load(open(outj))
            ok(len(got) == (4 if kind == "lights" else 3), f"…with its {len(got)} {kind} inside")

    # one material with its picture, as «Edit in Blender» sends the chosen material: the nodes are there, side by side
    import struct, zlib                                  # (a picture file to hang on the material: an 8 x 8 PNG)
    pic = os.path.join(gdir, "bricks.png")
    raw = b"".join(b"\x00" + bytes((180, 70, 50)) * 8 for _ in range(8))
    def _chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    sig = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    open(pic, "wb").write(sig + _chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
                          + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))
    BE.dump(__import__("pathlib").Path(gdir, "one.json"),
            [{"name": "Bricks", "color": [0.7, 0.3, 0.2], "roughness": 0.4, "metallic": 0.0, "glow": 0.0, "texture": {"path": pic}}])
    one = os.path.join(gdir, "one.blend")
    subprocess.run([BLENDER, "--python", os.path.join(REPO, "render_studio", "blender", "edit_scene.py"), "--",
                    "make", "materials", os.path.join(gdir, "one.json"), one], capture_output=True, text=True, timeout=240, env=env)
    ok(os.path.isfile(one) and not os.path.isfile(os.path.join(gdir, "error.txt")), "the chosen material alone opens in a Blender with a window")
    probe = os.path.join(gdir, "probe.py")
    open(probe, "w").write("""
import bpy
m = bpy.data.materials["Bricks"]
ball = next(o for o in bpy.data.objects if o.type == "MESH" and o.data.materials and o.data.materials[0] == m)
print("OUTWARDS", all(p.normal.dot(p.center) > 0 for p in ball.data.polygons), flush=True)
types = sorted(n.type for n in m.node_tree.nodes)
linked = any(l.from_node.type == "TEX_IMAGE" and l.to_socket.name == "Base Color" for l in m.node_tree.links)
spheres = [o.name for o in bpy.data.objects if o.type == "MESH" and o.data.materials and o.data.materials[0] == m]
print("PROBE", types, linked, spheres, len(bpy.data.materials))
""")
    r = subprocess.run([BLENDER, "-b", one, "--python", probe], capture_output=True, text=True, timeout=120)
    line = next((l for l in r.stdout.splitlines() if l.startswith("PROBE")), "")
    ok("OUTWARDS True" in r.stdout, "the sphere faces outwards (bumps stand out, grass grows out)")
    ok("TEX_IMAGE" in line and "BSDF_PRINCIPLED" in line and "True" in line and "['Bricks']" in line,
       f"…with its picture linked to the colour, one sphere, its nodes made ({line[:90]})")


    # a grass material: the render's own scripts are next to the data, and the patch grows its blades
    if len(sys.argv) > 4 and os.path.isfile(sys.argv[4]):
        import shutil
        gg = os.path.join(gdir, "grass"); os.makedirs(gg, exist_ok=True)
        shutil.copyfile(sys.argv[4], os.path.join(gg, "render_scene.py"))
        shutil.copyfile(os.path.join(REPO, "render_studio", "blender", "studio_scene.py"), os.path.join(gg, "studio_scene.py"))
        BE.dump(__import__("pathlib").Path(gg, "in.json"),
                [{"name": "Gespa", "color": [0.2, 0.5, 0.1], "roughness": 0.85, "metallic": 0.0, "glow": 0.0, "texture": None,
                  "grass": {"type": "grass", "grass_height": 0.06, "grass_density": 200.0}}])
        gb = os.path.join(gg, "scene.blend")
        subprocess.run([BLENDER, "--python", os.path.join(REPO, "render_studio", "blender", "edit_scene.py"), "--",
                        "make", "materials", os.path.join(gg, "in.json"), gb], capture_output=True, text=True, timeout=300, env=env)
        ok(os.path.isfile(gb) and not os.path.isfile(os.path.join(gg, "error.txt")), "a grass material opens in a Blender with a window")
        pr = os.path.join(gg, "probe.py")
        open(pr, "w").write("""
import bpy
patch = bpy.data.objects.get("Gespa patch")
print("PROBE", patch is not None and any(m.type == "NODES" for m in patch.modifiers), len([o for o in bpy.data.objects if "grass" in o.name]))
""")
        r = subprocess.run([BLENDER, "-b", gb, "--python", pr], capture_output=True, text=True, timeout=120)
        line = next((l for l in r.stdout.splitlines() if l.startswith("PROBE")), "")
        ok("True" in line, f"…with a patch that has the grass modifier and its tufts ({line})")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
