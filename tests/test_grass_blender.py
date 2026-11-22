"""Grass rendered by a REAL Blender, through the extension's own Blender script.

A 6 × 6 m lawn (its picture reddish on the left half, green on the right) and a paved path, in a GLB
laid out as IngeTrazo's export does. The lawn is typed «grass» in the job's material settings.
Checks: the blades grow on the lawn only (a geometry-nodes modifier, tufts thinned only past the
limit), their colour is the picture's where they stand, the height slider changes the picture, the
path is unchanged, the model's own mesh is untouched, EEVEE and Cycles both render.

Run:  blender -b --factory-startup --python tests/test_grass_blender.py -- <repo> <render_scene.py> <out dir>
"""
import json, os, shutil, struct, subprocess, sys

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
REPO = os.path.abspath(argv[0])
RENDER_SCENE = os.path.abspath(argv[1])
OUT = os.path.abspath(argv[2])
os.makedirs(OUT, exist_ok=True)

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)


def save(path, rgb):
    rgb = np.asarray(rgb, np.float32)
    h, w = rgb.shape[:2]
    img = bpy.data.images.new("tmp", w, h, alpha=False)
    img.pixels.foreach_set(np.concatenate([rgb[::-1], np.ones((h, w, 1), np.float32)], axis=2).ravel())
    img.filepath_raw = path; img.file_format = "PNG"; img.save()
    bpy.data.images.remove(img)
    return path


N = 64
rng = np.random.default_rng(1)
yy, xx = np.mgrid[0:N, 0:N] / float(N)
lawn = np.where((xx < 0.5)[..., None], (0.55, 0.16, 0.08), (0.12, 0.42, 0.08)).astype(np.float32)
lawn *= rng.uniform(0.85, 1.1, (N, N, 1)).astype(np.float32)
PICS = {"Lawn": save(os.path.join(OUT, "lawn.png"), lawn),
        "Path": save(os.path.join(OUT, "paving.png"), np.full((N, N, 3), 0.55, np.float32))}
# The lawn's picture covers the whole lawn once (one 6 m tile): left half reddish, right half green.
QUADS = {"Lawn": ([(-3, -3, 0), (3, -3, 0), (3, 3, 0), (-3, 3, 0)], 6.0),
         "Path": ([(-3, -4.2, 0), (3, -4.2, 0), (3, -3, 0), (-3, -3, 0)], 1.0)}


def write_glb(path):
    buf = bytearray(); views, accessors, meshes, nodes, materials, images, textures = [], [], [], [], [], [], []

    def add(data, target=None):
        while len(buf) % 4:
            buf.append(0)
        v = {"buffer": 0, "byteOffset": len(buf), "byteLength": len(data)}
        if target:
            v["target"] = target
        buf.extend(data); views.append(v)
        return len(views) - 1

    for i, (name, (pts, tile)) in enumerate(QUADS.items()):
        p = np.array(pts, np.float32)
        uv = np.array([[(q[0] - p[0][0]) / tile, -(q[1] - p[0][1]) / tile] for q in p], np.float32)
        gl = p[:, [0, 2, 1]] * np.array([1, 1, -1], np.float32)
        ng = np.tile(np.array([0, 1, 0], np.float32), (4, 1))
        idx = np.array([0, 1, 2, 0, 2, 3], np.uint16)
        acc = []
        for arr, typ in ((gl, "VEC3"), (ng, "VEC3"), (uv, "VEC2")):
            a = {"bufferView": add(arr.tobytes(), 34962), "componentType": 5126, "count": 4, "type": typ}
            if arr is gl:
                a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
            accessors.append(a); acc.append(len(accessors) - 1)
        accessors.append({"bufferView": add(idx.tobytes(), 34963), "componentType": 5123, "count": 6, "type": "SCALAR"})
        with open(PICS[name], "rb") as fh:
            images.append({"bufferView": add(fh.read()), "name": os.path.basename(PICS[name]), "mimeType": "image/png"})
        textures.append({"source": i, "sampler": 0})
        materials.append({"name": name, "doubleSided": True,
                          "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0,
                                                   "baseColorTexture": {"index": i}},
                          "extras": {"ingetrazo_finish": "matte"}})
        meshes.append({"name": name, "primitives": [{"attributes": {"POSITION": acc[0], "NORMAL": acc[1],
                       "TEXCOORD_0": acc[2]}, "indices": len(accessors) - 1, "material": i}]})
        nodes.append({"name": name, "mesh": i})
    while len(buf) % 4:
        buf.append(0)
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
            "nodes": nodes, "meshes": meshes, "materials": materials, "images": images, "textures": textures,
            "samplers": [{"wrapS": 10497, "wrapT": 10497}], "accessors": accessors, "bufferViews": views,
            "buffers": [{"byteLength": len(buf)}]}
    js = json.dumps(gltf).encode(); js += b" " * (-len(js) % 4)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(buf)))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A)); fh.write(js)
        fh.write(struct.pack("<II", len(buf), 0x004E4942)); fh.write(bytes(buf))


def run(tag, engine, lawn_spec):
    work = os.path.join(OUT, tag); os.makedirs(work, exist_ok=True)
    glb = os.path.join(work, "model.glb"); write_glb(glb)
    job = {"glb": glb, "output": os.path.join(work, "render.png"), "blend": os.path.join(work, "render.blend"),
           "width": 480, "height": 300, "engine": engine, "samples": 32 if engine == "cycles" else 16,
           "camera": {"eye": [0.0, -5.5, 1.1], "target": [0.0, 0.5, 0.0], "up": [0, 0, 1], "perspective": True,
                      "fov_deg": 45.0, "half_height": 2.0, "near": 0.05, "far": 1000.0},
           "ambience": "day", "exposure": -0.6, "sun": [0.4, -0.5, 0.6], "sun_strength": 3.0,
           "lights": [], "ground": None,
           "studio": {"looks": ["AgX - Medium High Contrast", "Medium High Contrast"], "clouds": 0.0,
                      "auto_exposure": True, "materials": {"Lawn": lawn_spec,
                                                           "Path": {"type": "generic", "roughness": 0.8}}}}
    jp = os.path.join(work, "job.json")
    with open(jp, "w", encoding="utf-8") as fh:
        json.dump(job, fh, indent=2)
    shutil.copyfile(RENDER_SCENE, os.path.join(work, "render_scene.py"))
    script = os.path.join(work, "studio_scene.py")
    shutil.copyfile(os.path.join(REPO, "render_studio", "blender", "studio_scene.py"), script)
    r = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python", script, "--", jp],
                       capture_output=True, text=True, errors="replace")
    log = r.stdout + r.stderr
    with open(os.path.join(work, "blender.log"), "w", encoding="utf-8") as fh:
        fh.write(log)
    ok(r.returncode == 0 and os.path.isfile(job["output"]), f"[{tag}] Blender rendered (rc {r.returncode})")
    return job, log


def pixels(path):
    img = bpy.data.images.load(path)
    w, h = img.size
    a = np.empty(w * h * 4, np.float32); img.pixels.foreach_get(a)
    bpy.data.images.remove(img)
    return a.reshape(h, w, 4)[::-1, :, :3]


GRASS = {"type": "grass", "roughness": 0.85, "grass_height": 0.08}
for engine in ("eevee", "cycles"):
    j_grass, log = run(f"{engine}_grass", engine, GRASS)
    j_tall, _ = run(f"{engine}_tall", engine, {**GRASS, "grass_height": 0.35})
    j_flat, log_flat = run(f"{engine}_flat", engine, {"type": "generic", "roughness": 0.85})
    line = next((l for l in log.splitlines() if "INGETRAZO grass" in l), "")
    ok("Lawn 8 cm" in line and "tufts" in line and "thinned" not in line, f"[{engine}] the script grows the lawn: {line.strip()}")
    ok("INGETRAZO grass" not in log_flat, f"[{engine}] no grass when the material is not grass")
    if not all(os.path.isfile(j["output"]) for j in (j_grass, j_tall, j_flat)):
        continue
    g, t, f = pixels(j_grass["output"]), pixels(j_tall["output"]), pixels(j_flat["output"])
    h, w = g.shape[:2]
    lawn_rows = slice(int(h * 0.55), int(h * 0.80))
    path_rows = slice(int(h * 0.93), h)
    d_lawn = float(np.abs(g[lawn_rows] - f[lawn_rows]).mean())
    d_tall = float(np.abs(t[lawn_rows] - g[lawn_rows]).mean())
    ok(d_lawn > 0.01, f"[{engine}] the lawn looks different with grass (|Δ| {d_lawn:.3f})")
    ok(d_tall > 0.008, f"[{engine}] the height slider changes it (8 cm vs 35 cm, |Δ| {d_tall:.3f})")
    # (the auto exposure follows how much of the picture is grass: compare the path's own pattern, not its level)
    gp, fp = g[path_rows], f[path_rows]
    d_path = float(np.abs(gp / max(gp.mean(), 1e-6) - fp / max(fp.mean(), 1e-6)).mean()) * float(fp.mean())
    ok(d_path < 0.5 * d_lawn, f"[{engine}] the path in front is (nearly) unchanged (|Δ| {d_path:.3f}; shadows of blades allowed)")
    left, right = g[lawn_rows, : w // 2 - 20], g[lawn_rows, w // 2 + 20:]
    red_l = float((left[..., 0] - left[..., 1]).mean()); red_r = float((right[..., 0] - right[..., 1]).mean())
    ok(red_l > red_r + 0.05, f"[{engine}] the blades take the picture's colour where they stand (red−green left {red_l:.3f}, right {red_r:.3f})")

    bpy.ops.wm.open_mainfile(filepath=j_grass["blend"])
    lawn = bpy.data.objects.get("Lawn")
    path = bpy.data.objects.get("Path")
    mods = [m for m in lawn.modifiers if m.type == "NODES"] if lawn else []
    ok(len(mods) == 1 and mods[0].node_group is not None, f"[{engine}] the lawn object carries the grass (geometry nodes)")
    ok(path is not None and not any(m.type == "NODES" for m in path.modifiers), f"[{engine}] the path does not")
    ok(lawn is not None and len(lawn.data.polygons) <= 2, f"[{engine}] the model's own mesh is untouched ({len(lawn.data.polygons)} faces)")
    dg = bpy.context.evaluated_depsgraph_get()
    n = sum(1 for inst in dg.object_instances if inst.is_instance and inst.parent and inst.parent.name == "Lawn")
    ok(n > 36 * 200 * 0.8, f"[{engine}] tufts on the lawn: {n} (about 36 m² × {200}+ per m²)")

# The density chosen in the editor: tufts per m², the same in the live view's draft.
counts = {}
for tag, extra, live in (("d100", {"grass_density": 100}, False), ("d400", {"grass_density": 400}, False),
                         ("d400_live", {"grass_density": 400}, True)):
    job, log = run(tag, "eevee", {**GRASS, **extra})
    if live:                                   # what the live view sends: a draft, same density
        job["studio"]["live"] = True
        jp = os.path.join(OUT, tag, "job.json")
        with open(jp, "w", encoding="utf-8") as fh:
            json.dump(job, fh, indent=2)
        r = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python",
                            os.path.join(OUT, tag, "studio_scene.py"), "--", jp],
                           capture_output=True, text=True, errors="replace")
        log = r.stdout + r.stderr
    line = next((l for l in log.splitlines() if "INGETRAZO grass" in l), "")
    try:
        counts[tag] = int(line.split("- ")[-1].split()[0])
    except (ValueError, IndexError):
        counts[tag] = 0
    ok(f"{extra['grass_density']}/m2" in line, f"[{tag}] the script uses the chosen density: {line.strip()}")
ok(3.5 < counts["d400"] / max(1, counts["d100"]) < 4.5,
   f"400/m² grows four times the tufts of 100/m² ({counts['d100']} → {counts['d400']})")
ok(counts["d400_live"] == counts["d400"], f"the live view's draft grows the same grass ({counts['d400_live']})")

print(f"\nrenders in {OUT}\n{len(fails)} failure(s)", flush=True)
os._exit(1 if fails else 0)
