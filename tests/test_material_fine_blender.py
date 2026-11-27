"""The finer material settings reach Blender's nodes: refraction index, varnish, sheen, the relief's height,
an inverted normal map and the strength of a texture set's relief. With a REAL Blender.
Plain Python: ``python test_material_fine_blender.py <ingetrazo-src> <repo> <blender> <out dir>``."""
import json, os, shutil, struct, subprocess, sys, zlib

SRC, REPO, BLENDER, OUT = (os.path.abspath(a) for a in sys.argv[1:5])
os.makedirs(OUT, exist_ok=True)
shutil.copyfile(os.path.join(SRC, "resources", "blender", "render_scene.py"), os.path.join(OUT, "render_scene.py"))
shutil.copyfile(os.path.join(REPO, "render_studio", "blender", "studio_scene.py"), os.path.join(OUT, "studio_scene.py"))


def png(path, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * 8 for _ in range(8))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as fh:
        fh.write(bytes([137, 80, 78, 71, 13, 10, 26, 10]) + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


pic, nrm = png(os.path.join(OUT, "pic.png"), (180, 140, 90)), png(os.path.join(OUT, "nrm.png"), (128, 128, 255))
probe = os.path.join(OUT, "probe.py")
with open(probe, "w", encoding="utf-8") as fh:
    fh.write(f'''
import bpy, json
src = open(r"{os.path.join(OUT, 'studio_scene.py')}", encoding="utf-8").read().rstrip().rsplit("\\nmain()", 1)[0]
ns = {{"__name__": "studio_scene", "__file__": r"{os.path.join(OUT, 'studio_scene.py')}"}}
exec(compile(src, ns["__file__"], "exec"), ns)

def make(name, finish=None):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    t = m.node_tree.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(r"{pic}", check_existing=True)
    m.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
    if finish: m["ingetrazo_finish"] = finish
    return m, b

def apply(name, spec, finish=None, sets=None):
    m, b = make(name, finish)
    ns["finishes_for"]({{name}})
    ns["apply_material_specs"]({{name: spec}}, sets or {{}}, {{name}})
    if sets: ns["apply_texture_sets"](sets, {{name: spec}})
    ns["apply_last_touches"]({{name: spec}}, {{name}})
    nodes = m.node_tree.nodes
    out = {{k: round(b.inputs[s].default_value, 4) for k, s in (("ior", "IOR"), ("coat", "Coat Weight"),
           ("coat_rough", "Coat Roughness"), ("sheen", "Sheen Weight"))}}
    out["bumps"] = [round(n.inputs["Distance"].default_value, 4) for n in nodes if n.type == "BUMP"]
    out["normal_strength"] = [round(n.inputs["Strength"].default_value, 4) for n in nodes if n.type == "NORMAL_MAP"]
    out["inverted"] = any(n.type == "COMBINE_COLOR" for n in nodes)
    out["ranges"] = [[round(n.inputs["To Min"].default_value, 3), round(n.inputs["To Max"].default_value, 3)]
                     for n in nodes if n.label == "Roughness range"]
    out["pictures"] = len([n for n in nodes if n.type == "TEX_IMAGE"])
    out["mixes"] = sorted(n.label for n in nodes if n.label.startswith("Repetition"))
    out["tone"] = len([n for n in nodes if n.label == "Tone variation"])
    end = next(n for n in nodes if n.type == "OUTPUT_MATERIAL").inputs["Surface"].links[0].from_node
    out["surface"] = end.label or end.type
    out["through"] = [round(n.inputs[0].default_value, 3) for n in nodes if n.label == "Translucency"]
    out["ao"] = [round(ns["_socket"](n, "Factor_Float", 0).default_value, 3) for n in nodes
                 if n.type == "MIX" and n.data_type == "RGBA" and n.blend_type == "MULTIPLY"]
    return out

base = {{"type": "generic", "roughness": 0.5, "metallic": 0.0, "bump": 0.0}}
got = {{
 "gloss_untouched": apply("a", dict(base), "gloss"),
 "gloss_no_coat": apply("b", dict(base, coat=0.0), "gloss"),
 "fine": apply("c", dict(base, ior=1.8, coat=0.7, coat_roughness=0.3, sheen=0.4)),
 "height_auto": apply("d", dict(base, bump=0.5, maps={{"bump": {{"source": "grain"}}}})),
 "height_20mm": apply("e", dict(base, bump=0.5, relief_height=20.0, maps={{"bump": {{"source": "grain"}}}})),
 "normal": apply("f", dict(base, bump=0.5, maps={{"bump": {{"source": "normal", "path": r"{nrm}"}}}})),
 "normal_dx": apply("g", dict(base, bump=0.5, maps={{"bump": {{"source": "normal", "path": r"{nrm}", "flip_green": True}}}})),
 "set_auto": apply("h", dict(base), sets={{"h": {{"normal": r"{nrm}"}}}}),
 "set_half": apply("i", dict(base, set_relief=0.5), sets={{"i": {{"normal": r"{nrm}"}}}}),
 "range": apply("j", dict(base, rough_min=0.2, rough_max=0.7, maps={{"roughness": {{"source": "picture"}}}})),
 "range_no_map": apply("k", dict(base, rough_min=0.2, rough_max=0.7)),
 "ao_auto": apply("l", dict(base), sets={{"l": {{"ao": r"{pic}"}}}}),
 "ao_low": apply("m", dict(base, ao_strength=0.25), sets={{"m": {{"ao": r"{pic}"}}}}),
 "untile": apply("n", dict(base, untile=True, bump=0.5, maps={{"bump": {{"source": "normal", "path": r"{nrm}"}}}})),
 "variation": apply("o", dict(base, variation=0.5)),
 "leaf": apply("p", dict(base, type="foliage")),
 "curtain": apply("q", dict(base, translucency=1.0)),
 "edited": apply("r", dict(base, untile=True, translucency=1.0, blender={{"blend": "x"}})),
}}
print("PROBE" + json.dumps(got))
''')
r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", probe], capture_output=True, text=True, timeout=240)
line = next((l for l in r.stdout.splitlines() if l.startswith("PROBE")), None)
if line is None:
    print(r.stdout[-3000:], r.stderr[-1500:])
    sys.exit(1)
g = json.loads(line[5:])
fails = []


def ok(c, what):
    print(("PASS " if c else "FAIL ") + what)
    if not c:
        fails.append(what)


ok(g["gloss_untouched"]["coat"] == 0.5, f"untouched: the gloss finish keeps its varnish ({g['gloss_untouched']['coat']})")
ok(g["gloss_no_coat"]["coat"] == 0.0, "a varnish of 0 takes it away")
f = g["fine"]
ok((f["ior"], f["coat"], f["coat_rough"], f["sheen"]) == (1.8, 0.7, 0.3, 0.4), f"IOR, varnish and sheen as chosen ({f})")
ok(g["height_auto"]["bumps"] == [0.004] and g["height_20mm"]["bumps"] == [0.02],
   f"the relief's height: {g['height_auto']['bumps']} by itself, {g['height_20mm']['bumps']} at 20 mm")
ok(g["normal"]["normal_strength"] == [1.0] and not g["normal"]["inverted"], "a normal map at Relief 0.5: as drawn")
ok(g["normal_dx"]["inverted"], "a DirectX one: its green inverted")
ok(g["set_auto"]["normal_strength"] == [1.0] and g["set_half"]["normal_strength"] == [0.5],
   f"a texture set's relief: {g['set_auto']['normal_strength']} by itself, {g['set_half']['normal_strength']} at 50 %")
ok(g["range"]["ranges"] == [[0.2, 0.7]] and g["range_no_map"]["ranges"] == [],
   f"the roughness range works on a map only ({g['range']['ranges']}, {g['range_no_map']['ranges']})")
ok(g["ao_auto"]["ao"] == [0.75] and g["ao_low"]["ao"] == [0.25], f"ambient occlusion strength ({g['ao_auto']['ao']}, {g['ao_low']['ao']})")
u = g["untile"]
ok(u["pictures"] == 4 and u["mixes"] == ["Repetition Color", "Repetition Color"],
   f"repetition broken: picture and normal map each read twice and melted ({u['pictures']}, {u['mixes']})")
ok(g["variation"]["tone"] == 1, "tone variation on the colour")
ok(g["leaf"]["through"] == [0.3] and g["curtain"]["through"] == [0.6] and g["gloss_untouched"]["through"] == [],
   f"translucency: foliage by itself {g['leaf']['through']}, 100 % {g['curtain']['through']}, others none")
ok(g["edited"]["through"] == [] and g["edited"]["pictures"] == 1, "a material edited in Blender is left as it is")
print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
