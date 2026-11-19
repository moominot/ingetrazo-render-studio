"""Full texture sets rendered by a REAL Blender, through the extension's own Blender script.

Makes two tiny texture sets (a Poly Haven-style tile floor, an ambientCG-style plank wall with a
DirectX normal map, metal strip and see-through slots) and a picture with no companions; packs them
in a GLB the way IngeTrazo's export does (one material per picture, the image named by its file
name); writes the job's "pbr" block with render_studio.pbr; renders with and without the sets
(EEVEE and Cycles) with studio_scene.py, exactly as the panel runs it; checks the materials' nodes in
the saved .blend and that the pictures differ.

Run:  blender -b --factory-startup --python tests/test_pbr_blender.py -- <repo> <render_scene.py> <out dir>
"""
import json, os, struct, subprocess, sys

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
REPO = os.path.abspath(argv[0]) if argv else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDER_SCENE = os.path.abspath(argv[1]) if len(argv) > 1 else os.environ.get("INGETRAZO_RENDER_SCENE", "")
OUT = os.path.abspath(argv[2]) if len(argv) > 2 else os.path.join(REPO, "tests", "_out_pbr")
sys.path.insert(0, REPO)
from render_studio import pbr  # noqa: E402

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

os.makedirs(OUT, exist_ok=True)
TEX = os.path.join(OUT, "textures")
PH, ACG, PLAIN = (os.path.join(TEX, d) for d in ("polyhaven", "ambientcg", "plain"))
for d in (PH, ACG, PLAIN):
    os.makedirs(d, exist_ok=True)
N = 128


def save(path, rgb):
    """rgb: H×W×3 (or H×W) floats 0..1, top row first."""
    rgb = np.asarray(rgb, np.float32)
    if rgb.ndim == 2:
        rgb = np.repeat(rgb[..., None], 3, axis=2)
    h, w = rgb.shape[:2]
    img = bpy.data.images.new("tmp", w, h, alpha=False)
    try:
        img.colorspace_settings.name = "Non-Color"
    except (TypeError, ValueError):
        pass
    px = np.concatenate([rgb[::-1], np.ones((h, w, 1), np.float32)], axis=2)
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw = path
    img.file_format = "JPEG" if path.lower().endswith(".jpg") else "PNG"
    img.save()
    bpy.data.images.remove(img)
    return path


def normal_from_height(hgt, k, dx_convention=False):
    """Tangent-space normal map of a height field (rows top to bottom): OpenGL has green up."""
    gy, gx = np.gradient(hgt)
    nx, ny = -gx * k, gy * k                     # image rows run down: up is -row
    if dx_convention:
        ny = -ny
    n = np.stack([nx, ny, np.ones_like(nx)], axis=2)
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return n * 0.5 + 0.5


yy, xx = np.mgrid[0:N, 0:N] / float(N)
# Poly Haven-style tiles: 4×4 tiles a picture, grout grooves.
grout = ((np.abs(((xx * 4) % 1) - 0.5) > 0.44) | (np.abs(((yy * 4) % 1) - 0.5) > 0.44)).astype(np.float32)
height = 1.0 - grout
colour = np.where(grout[..., None] > 0, (0.55, 0.53, 0.50), (0.80, 0.74, 0.62)).astype(np.float32)
save(os.path.join(PH, "tiles_diff_1k.jpg"), colour)
save(os.path.join(PH, "tiles_nor_gl_1k.png"), normal_from_height(height, 6.0))
save(os.path.join(PH, "tiles_rough_1k.png"), np.where(grout > 0, 0.95, 0.12))
save(os.path.join(PH, "tiles_ao_1k.png"), np.where(grout > 0, 0.35, 1.0))
save(os.path.join(PH, "tiles_disp_1k.png"), height)
# ambientCG-style planks: vertical planks with bevelled joints, a steel strip, slots.
joint = (np.abs(((xx * 5) % 1) - 0.5) > 0.45).astype(np.float32)
strip = ((yy > 0.45) & (yy < 0.55)).astype(np.float32)
slot = ((np.abs(((xx * 5) % 1) - 0.5) > 0.46) & (yy > 0.6)).astype(np.float32)
wood = np.stack([0.45 + 0.1 * np.sin(yy * 60), 0.28 + 0.05 * np.sin(yy * 60), 0.15 + 0 * yy], axis=2)
wood = np.where(strip[..., None] > 0, (0.7, 0.7, 0.72), wood).astype(np.float32)
base = "Planks017_1K-PNG"
save(os.path.join(ACG, f"{base}_Color.png"), wood)
save(os.path.join(ACG, f"{base}_NormalDX.png"), normal_from_height(1.0 - joint, 6.0, dx_convention=True))
save(os.path.join(ACG, f"{base}_Roughness.png"), np.where(strip > 0, 0.25, 0.7))
save(os.path.join(ACG, f"{base}_Metalness.png"), strip)
save(os.path.join(ACG, f"{base}_AmbientOcclusion.png"), np.where(joint > 0, 0.4, 1.0))
save(os.path.join(ACG, f"{base}_Opacity.png"), 1.0 - slot)
save(os.path.join(PLAIN, "plaster.png"), 0.7 + 0.1 * np.sin(xx * 40)[..., None] * np.ones(3))

PICTURES = {"Floor": os.path.join(PH, "tiles_diff_1k.jpg"),
            "Wall": os.path.join(ACG, f"{base}_Color.png"),
            "Plaster": os.path.join(PLAIN, "plaster.png")}


# ---- a GLB as IngeTrazo writes it --------------------------------------------------------
SCENE_QUADS = {   # material: 4 corners (counter-clockwise from outside), tile size 1 m
        "Floor": [(-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)],
        "Wall": [(-2, 1.5, 0), (2, 1.5, 0), (2, 1.5, 2.5), (-2, 1.5, 2.5)],
        "Plaster": [(-2, -2, 0), (-2, 1.5, 0), (-2, 1.5, 2.5), (-2, -2, 2.5)],
}


def write_glb(path, quads=SCENE_QUADS, pictures=PICTURES):
    buf = bytearray(); views, accessors, meshes, nodes, materials, images, textures = [], [], [], [], [], [], []

    def add(data, target=None):
        while len(buf) % 4:
            buf.append(0)
        v = {"buffer": 0, "byteOffset": len(buf), "byteLength": len(data)}
        if target:
            v["target"] = target
        buf.extend(data); views.append(v)
        return len(views) - 1

    for i, (name, pts) in enumerate(quads.items()):
        p = np.array(pts, np.float32)
        e1, e2 = p[1] - p[0], p[3] - p[0]
        n = np.cross(e1, e2); n /= np.linalg.norm(n)
        u_ax, v_ax = e1 / np.linalg.norm(e1), e2 / np.linalg.norm(e2)
        uv = np.array([[(q - p[0]) @ u_ax, -((q - p[0]) @ v_ax)] for q in p], np.float32)   # 1 m tiles
        gl = p[:, [0, 2, 1]] * np.array([1, 1, -1], np.float32)                                # Z up → glTF Y up
        ng = np.tile(n[[0, 2, 1]] * np.array([1, 1, -1], np.float32), (4, 1))
        idx = np.array([0, 1, 2, 0, 2, 3], np.uint16)
        acc = []
        for arr, typ in ((gl, "VEC3"), (ng, "VEC3"), (uv, "VEC2")):
            a = {"bufferView": add(arr.astype(np.float32).tobytes(), 34962), "componentType": 5126,
                 "count": 4, "type": typ}
            if arr is gl:
                a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
            accessors.append(a); acc.append(len(accessors) - 1)
        accessors.append({"bufferView": add(idx.tobytes(), 34963), "componentType": 5123, "count": 6, "type": "SCALAR"})
        with open(pictures[name], "rb") as fh:
            data = fh.read()
        images.append({"bufferView": add(data), "name": os.path.basename(pictures[name]),
                       "mimeType": "image/jpeg" if pictures[name].endswith(".jpg") else "image/png"})
        textures.append({"source": len(images) - 1, "sampler": 0})
        materials.append({"name": name, "doubleSided": True,
                          "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0,
                                                   "baseColorTexture": {"index": len(textures) - 1}},
                          "extras": {"ingetrazo_finish": "matte"}})
        meshes.append({"name": name, "primitives": [{"attributes": {"POSITION": acc[0], "NORMAL": acc[1],
                       "TEXCOORD_0": acc[2]}, "indices": len(accessors) - 1, "material": i}]})
        nodes.append({"name": name, "mesh": i})
    while len(buf) % 4:
        buf.append(0)
    gltf = {"asset": {"version": "2.0", "generator": "IngeTrazo-like test"}, "scene": 0,
            "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes,
            "materials": materials, "images": images, "textures": textures,
            "samplers": [{"wrapS": 10497, "wrapT": 10497}], "accessors": accessors, "bufferViews": views,
            "buffers": [{"byteLength": len(buf)}]}
    js = json.dumps(gltf).encode()
    js += b" " * (-len(js) % 4)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(buf)))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A)); fh.write(js)
        fh.write(struct.pack("<II", len(buf), 0x004E4942)); fh.write(bytes(buf))


# ---- the job block -------------------------------------------------------------------------
sets = {os.path.basename(p): m for p in PICTURES.values() if (m := pbr.find_maps(p))}
ok(set(sets) == {"tiles_diff_1k.jpg", f"{base}_Color.png"}, f"the job's sets: both libraries, not the plain picture ({sorted(sets)})")
ok(set(k for k in pbr.JOB_MAPS if k in sets.get("tiles_diff_1k.jpg", {})) == {"normal", "roughness", "ao", "displacement"},
   "…Poly Haven set: normal, roughness, AO, displacement")
acg = sets.get(f"{base}_Color.png", {})
ok(acg.get("normal_flip_green") is True and {"metalness", "opacity", "roughness", "ao"} <= set(acg),
   "…ambientCG set: DirectX normal (flipped), metalness, opacity, roughness, AO")

SPECS = {"Floor": {"type": "generic", "roughness": 0.5, "metallic": 0.0, "bump": 0.4},   # automatic relief
         "Wall": {"type": "generic", "roughness": 0.25, "metallic": 0.0, "bump": 0.0}}


CAMERA = {"eye": [2.6, -4.2, 1.7], "target": [-0.3, 0.6, 0.7], "up": [0, 0, 1], "perspective": True,
          "fov_deg": 50.0, "half_height": 2.0, "near": 0.05, "far": 1000.0}


def run(tag, engine, with_sets, quads=SCENE_QUADS, pictures=PICTURES, the_sets=None, specs=None,
        camera=CAMERA, size=(480, 300), sun=(0.55, -0.45, 0.35)):
    work = os.path.join(OUT, tag)
    os.makedirs(work, exist_ok=True)
    glb = os.path.join(work, "model.glb")
    write_glb(glb, quads, pictures)
    studio = {"looks": ["AgX - Medium High Contrast", "Medium High Contrast"], "clouds": 0.0,
              "auto_exposure": True, "materials": SPECS if specs is None else specs}
    if with_sets:
        studio["pbr"] = sets if the_sets is None else the_sets
    job = {"glb": glb, "output": os.path.join(work, "render.png"), "blend": os.path.join(work, "render.blend"),
           "width": size[0], "height": size[1], "engine": engine, "samples": 32 if engine == "cycles" else 16,
           "camera": camera,
           "ambience": "day", "exposure": -0.6, "sun": list(sun), "sun_strength": 3.0,
           "lights": [], "ground": None, "studio": studio}
    jp = os.path.join(work, "job.json")
    with open(jp, "w", encoding="utf-8") as fh:
        json.dump(job, fh, indent=2)
    import shutil
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


def nodes_of(blend):
    bpy.ops.wm.open_mainfile(filepath=blend)
    return {m.name: m for m in bpy.data.materials}


for engine in ("eevee", "cycles"):
    job_on, log_on = run(f"{engine}_sets", engine, True)
    job_off, log_off = run(f"{engine}_plain", engine, False)
    ok("texture set" in log_on and "texture set" not in log_off, f"[{engine}] the script reports the sets only when the job has them")
    ok("relief Floor from its texture set" in log_on, f"[{engine}] the automatic relief gives way to the set")
    if fails and not os.path.isfile(job_on["output"]):
        break
    a, b = pixels(job_on["output"]), pixels(job_off["output"])
    diff = float(np.abs(a - b).mean())
    ok(diff > 0.01, f"[{engine}] the pictures differ with the sets (mean |Δ| {diff:.3f})")

    mats = nodes_of(job_off["blend"])
    plain_off = sorted(n.bl_idname for n in mats["Plaster"].node_tree.nodes)
    ok(any(i.name.startswith("studio relief") for i in bpy.data.images), f"[{engine}] without sets: the Floor's relief is guessed from its picture, as before")
    mats = nodes_of(job_on["blend"])
    ok(not any(i.name.startswith("studio relief") for i in bpy.data.images), f"[{engine}] with sets: no relief guessed from the picture")
    ok(sorted(n.bl_idname for n in mats["Plaster"].node_tree.nodes) == plain_off,
       f"[{engine}] a picture with no companions: its material is exactly as without sets")

    def labelled(mat, what):
        return next((n for n in mat.node_tree.nodes if n.label == "Texture set: " + what), None)

    def feeds(sock):
        l = next(iter(sock.links), None)
        return l.from_node if l else None

    for name, maps in (("Floor", ("normal", "roughness", "ambient occlusion")),
                       ("Wall", ("normal", "roughness", "metalness", "ambient occlusion", "opacity"))):
        mat = mats[name]
        bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        pic = next(n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and not n.label.startswith("Texture set: "))
        ok(all(labelled(mat, w) is not None for w in maps), f"[{engine}] {name}: maps {maps}")
        ok(all(labelled(mat, w).image.colorspace_settings.name == "Non-Color" for w in maps), f"[{engine}] {name}: read as data")
        vec = lambda n: tuple((l.from_node.name, l.from_socket.identifier) for l in n.inputs["Vector"].links)
        ok(all(vec(labelled(mat, w)) == vec(pic) for w in maps), f"[{engine}] {name}: the maps use the picture's own coordinates")
        nm = feeds(bsdf.inputs["Normal"])
        ok(nm is not None and nm.type == "NORMAL_MAP", f"[{engine}] {name}: Normal ← normal map")
        ok(feeds(bsdf.inputs["Base Color"]).type == "MIX", f"[{engine}] {name}: colour darkened by AO")
    floor, wall = mats["Floor"], mats["Wall"]
    ok(labelled(floor, "displacement") is None, f"[{engine}] Floor: displacement not added on top of its normal map")
    fb = next(n for n in floor.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    ok(feeds(fb.inputs["Roughness"]) == labelled(floor, "roughness"), f"[{engine}] Floor: roughness map as it is (slider 0.5)")
    wb = next(n for n in wall.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    mul = feeds(wb.inputs["Roughness"])
    ok(mul is not None and mul.type == "MATH" and mul.operation == "MULTIPLY" and abs(mul.inputs[1].default_value - 0.5) < 1e-6,
       f"[{engine}] Wall: roughness map × 0.5 (slider 0.25)")
    ok(any(n.type == "COMBINE_COLOR" for n in wall.node_tree.nodes), f"[{engine}] Wall: DirectX normal's green flipped")
    ok(feeds(wb.inputs["Alpha"]) == labelled(wall, "opacity"), f"[{engine}] Wall: Alpha ← opacity map")
    ok(feeds(wb.inputs["Metallic"]) == labelled(wall, "metalness"), f"[{engine}] Wall: Metallic ← metalness map")

# ---- the normal maps' conventions, from above ----------------------------------------------------
# The same relief three times, side by side, seen straight down under a grazing sun: as an OpenGL
# map (Poly Haven names), as a DirectX map (ambientCG names, green flipped by the script) — these
# two must render alike — and an OpenGL map wrongly NAMED DirectX, which must not.
bumps = (0.5 + 0.5 * np.sin(xx * 2 * np.pi * 2) * np.sin(yy * 2 * np.pi * 2)).astype(np.float32)
bumps = bumps + 0.6 * yy                       # not symmetric top to bottom: a wrong green shows
CHK = os.path.join(TEX, "check")
grey = np.full((N, N, 3), 0.6, np.float32)
for folder, colour_name, normal_name, dx in (("gl", "bumps_diff_1k.png", "bumps_nor_gl_1k.png", False),
                                             ("dx", "Bumps_1K-PNG_Color.png", "Bumps_1K-PNG_NormalDX.png", True),
                                             ("wrong", "Bumps_1K-PNG_Color.png", "Bumps_1K-PNG_NormalDX.png", False)):
    d = os.path.join(CHK, folder); os.makedirs(d, exist_ok=True)
    save(os.path.join(d, colour_name), grey)
    save(os.path.join(d, normal_name), normal_from_height(bumps, 8.0, dx_convention=dx))
    rough = normal_name.replace("nor_gl", "rough").replace("NormalDX", "Roughness")
    save(os.path.join(d, rough), np.ones((N, N), np.float32))
check_pics = {"GL": os.path.join(CHK, "gl", "bumps_diff_1k.png"), "DX": os.path.join(CHK, "dx", "Bumps_1K-PNG_Color.png"),
              "Wrong": os.path.join(CHK, "wrong", "Bumps_1K-PNG_Color.png")}
# Two pictures may share a file name (DX and Wrong): give the wrong one its own name in the model.
wrong_copy = os.path.join(CHK, "wrong", "Bumpz_1K-PNG_Color.png")
import shutil
shutil.copyfile(check_pics["Wrong"], wrong_copy)
shutil.copyfile(os.path.join(CHK, "wrong", "Bumps_1K-PNG_NormalDX.png"), os.path.join(CHK, "wrong", "Bumpz_1K-PNG_NormalDX.png"))
shutil.copyfile(os.path.join(CHK, "wrong", "Bumps_1K-PNG_Roughness.png"), os.path.join(CHK, "wrong", "Bumpz_1K-PNG_Roughness.png"))
check_pics["Wrong"] = wrong_copy
check_sets = {os.path.basename(p): pbr.find_maps(p) for p in check_pics.values()}
ok(check_sets["bumps_diff_1k.png"]["normal_flip_green"] is False and check_sets["Bumps_1K-PNG_Color.png"]["normal_flip_green"] is True,
   "convention check: OpenGL map as is, DirectX map flipped")
quads = {name: [(x0, -1, 0), (x0 + 2, -1, 0), (x0 + 2, 1, 0), (x0, 1, 0)]
         for name, x0 in (("GL", -3.75), ("DX", -1.0), ("Wrong", 1.75))}
top = {"eye": [0, 0, 10], "target": [0, 0, 0], "up": [0, 1, 0], "perspective": False, "fov_deg": 50.0,
       "half_height": 0.25, "near": 0.05, "far": 100.0}   # IngeTrazo: ortho scale = 2·half·aspect, fitted to the height
job, _log = run("conventions", "eevee", True, quads, check_pics, check_sets, {}, top, (800, 200), (0.0, 0.8, 0.35))
if os.path.isfile(job["output"]):
    px = pixels(job["output"])
    crop = lambda x0: px[10:190, x0 + 10:x0 + 190]
    gl, dx, wrong = crop(25), crop(300), crop(575)
    d_ok, d_bad = float(np.abs(gl - dx).mean()), float(np.abs(gl - wrong).mean())
    ok(gl.std() > 0.02, f"the relief shows from above (std {gl.std():.3f})")
    ok(d_ok < 0.25 * d_bad, f"DirectX flipped renders like OpenGL (|Δ| {d_ok:.4f}), a wrong convention does not (|Δ| {d_bad:.4f})")

print(f"\nrenders in {OUT}\n{len(fails)} failure(s)", flush=True)
sys.stdout.flush()
os._exit(1 if fails else 0)
