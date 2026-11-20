"""Proxies in the render: a tall red block kept in an .igz as a proxy's original, its orange
stand-in box placed twice in the drawing (a component and its copy), a third placement hidden,
and a proxy whose original file is gone.

Checks: the job lists the original once with the two placements; the hidden one and the lost
one are not in it, the lost one is named; the stand-ins are out of the model file but the lost
one's box is in it; the drawing is left as it was (nothing hidden); the original's .glb is
cached and reused, and another paint makes another one. With Blender: it builds two instances
and the picture shows the red blocks where the stand-ins stand.

argv: <ingetrazo-src> <render-studio repo> <out dir> [<blender.exe> | bpy]
"""
import json, math, os, struct, subprocess, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, OUT = [os.path.abspath(a) for a in sys.argv[1:4]]
BLENDER = sys.argv[4] if len(sys.argv) > 4 else None
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QImage, QMatrix4x4, QVector3D
from core.camera import OrbitCamera
from core.group import Group, copy_group
from core.mesh import Mesh
from core.scene import Scene
from formats import igz
from render_studio import panel as P, proxies

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

def block(m, lo, hi, colour):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    V = QVector3D
    for q in ([V(x0,y0,z0),V(x0,y1,z0),V(x1,y1,z0),V(x1,y0,z0)], [V(x0,y0,z1),V(x1,y0,z1),V(x1,y1,z1),V(x0,y1,z1)],
              [V(x0,y0,z0),V(x1,y0,z0),V(x1,y0,z1),V(x0,y0,z1)], [V(x0,y1,z0),V(x0,y1,z1),V(x1,y1,z1),V(x1,y1,z0)],
              [V(x0,y0,z0),V(x0,y0,z1),V(x0,y1,z1),V(x0,y1,z0)], [V(x1,y0,z0),V(x1,y1,z0),V(x1,y1,z1),V(x1,y0,z1)]):
        m.add_face(q).attrs["color"] = colour
    return m

out = Path(OUT); out.mkdir(parents=True, exist_ok=True)
proj = out / "project"; proj.mkdir(exist_ok=True)
doc = proj / "plaça.igz"
cache = out / "cache"

# The original: a red block 2 × 2 × 4 standing on its origin, with a red cap as a part.
orig = Group(block(Mesh(), (-1, -1, 0), (1, 1, 4), (0.8, 0.05, 0.05, 1.0)), name="Bloc")
orig.xform = QMatrix4x4()
cap = Group(block(Mesh(), (-0.5, -0.5, 0), (0.5, 0.5, 0.3), (0.8, 0.05, 0.05, 1.0)), name="Cap")
cap.xform = QMatrix4x4(); cap.xform.translate(0, 0, 4); orig.children = [cap]
orig.ext = {"proxy_tool": {"id": "bloc0000000000001"}}
orig_file = proj / "plaça_proxies" / "Bloc_bloc00.igz"; orig_file.parent.mkdir(exist_ok=True)
oscene = Scene(); oscene.groups.append(orig); igz.save_scene(oscene, orig_file)

def stand_in(name, x, info):
    g = Group(block(Mesh(), (-1, -1, 0), (1, 1, 4.3), (0.95, 0.55, 0.15, 1.0)), name=name)
    g.xform = QMatrix4x4(); g.xform.translate(x, 0, 0)
    g.ext = {"proxy_tool": dict(info)}
    return g

info = {"id": "bloc0000000000001", "file": str(out / "elsewhere" / "Bloc_bloc00.igz"),   # moved project:
        "rel": os.path.join("plaça_proxies", "Bloc_bloc00.igz"), "state": "proxy", "name": "Bloc"}  # rel wins
scene = Scene()
ground = scene.mesh.add_face([QVector3D(-8, -8, 0), QVector3D(8, -8, 0), QVector3D(8, 8, 0), QVector3D(-8, 8, 0)])
ground.attrs["color"] = (0.6, 0.6, 0.6, 1.0)
a = stand_in("Bloc", -3, info); scene.groups.append(a)
b = copy_group(a, QVector3D(6, 0, 0)); scene.groups.append(b)
hid = copy_group(a, QVector3D(0, 5, 0)); hid.hidden = True; scene.groups.append(hid)
lost = Group(block(Mesh(), (-0.5, -0.5, 0), (0.5, 0.5, 1.0), (0.95, 0.55, 0.15, 1.0)), name="Perdut")
lost.xform = QMatrix4x4(); lost.xform.translate(0, -5, 0)
lost.ext = {"proxy_tool": {"id": "lost", "file": str(out / "nowhere.igz"), "state": "proxy", "name": "Perdut"}}
scene.groups.append(lost)
version = scene.version

cam = OrbitCamera(); cam.target = QVector3D(0, 0, 0); cam.distance = 16
cam.yaw = math.radians(0); cam.pitch = math.radians(80)

def glb_json(path):
    data = Path(path).read_bytes()
    n = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20:20 + n])

def job(name, **kw):
    j, script = P.write_studio_job(scene, cam, out / name, "clear", {}, engine="eevee", quality=0,
                                   width=320, height=240, doc_path=str(doc), **kw)
    return json.loads(j.read_text(encoding="utf-8")), j, script

proxies.cache_dir = lambda: cache        # the test's own cache
data, jpath, script = job("one")
st = data["studio"]
ent = st.get("proxies") or []
ok(len(ent) == 1 and len(ent[0]["matrices"]) == 2, "one original, placed twice (the hidden one is not)")
xs = sorted(r[0][3] for r in ent[0]["matrices"]) if ent else []
ok(xs == [-3.0, 3.0], "each placement where its stand-in stands")
ok(st.get("proxies_missing") == ["Perdut"], "the proxy without its file is named")
ok(ent and Path(ent[0]["glb"]).parent == cache and Path(ent[0]["glb"]).is_file(), "the original's .glb is in the cache")
model = glb_json(data["glb"])
pos = [model["accessors"][p["attributes"]["POSITION"]] for m in model["meshes"] for p in m["primitives"]]
top = max(acc["max"][1] for acc in pos)            # glTF: Y up
ok(abs(top - 1.0) < 1e-6, f"the stand-ins are out of the model file, the lost one's box in it (top {top:.2f} m)")
ok(not a.hidden and not b.hidden and hid.hidden and not lost.hidden and scene.version == version,
   "the drawing is left as it was")
ok(data.get("ground") is not None, "the ground is there")
og = glb_json(ent[0]["glb"]) if ent else {"nodes": []}
ok(sorted(n.get("name") for n in og["nodes"]) == ["Bloc", "Cap"], "the original keeps its part")

stamp = Path(ent[0]["glb"]).stat().st_mtime_ns if ent else 0
data2, _j, _s = job("two")
ok(data2["studio"]["proxies"][0]["glb"] == ent[0]["glb"] and Path(ent[0]["glb"]).stat().st_mtime_ns == stamp,
   "a second render reuses the cached .glb")
b.material = {"color": (0.1, 0.3, 0.9)}
data3, _j, _s = job("three")
ok(len(data3["studio"]["proxies"]) == 2, "a copy with another paint gets its own original")
b.material = None

# Only proxies in the drawing: the model file is empty, the ground still sits under them.
solo = Scene(); solo.groups.append(copy_group(a))
sj, _s = P.write_studio_job(solo, cam, out / "solo", "clear", {}, engine="eevee", quality=0,
                            width=320, height=240, doc_path=str(doc))
sd = json.loads(sj.read_text(encoding="utf-8"))
ok(sd.get("ground") is not None and len(sd["studio"]["proxies"]) == 1,
   "a drawing of proxies only: ground and original there")


def lum_rgb(img, fx, fy, r=4):
    w, h = img.width(), img.height()
    cx, cy = int(fx * w), int(fy * h)
    acc = [0, 0, 0]; n = 0
    for x in range(cx - r, cx + r + 1):
        for y in range(cy - r, cy + r + 1):
            c = img.pixelColor(max(0, min(w - 1, x)), max(0, min(h - 1, y)))
            acc[0] += c.red(); acc[1] += c.green(); acc[2] += c.blue(); n += 1
    return [v / n for v in acc]


if BLENDER:
    for name, path in (("one", jpath), ("solo", sj)):
        argv = ([sys.executable, str(path.parent / "studio_scene.py"), "--", str(path)] if BLENDER == "bpy"
                else [BLENDER, "-b", "--factory-startup", "--python", str(path.parent / "studio_scene.py"),
                      "--", str(path)])
        r = subprocess.run(argv, capture_output=True, text=True, timeout=900)
        log = r.stdout + r.stderr
        (out / f"{name}.log").write_text(log, encoding="utf-8")
        want = "proxies 1 models, 2 placements" if name == "one" else "proxies 1 models, 1 placements"
        ok(want in log, f"[{name}] Blender placed the originals ({want})")
        img = QImage(json.loads(path.read_text(encoding="utf-8"))["output"])
        ok(not img.isNull(), f"[{name}] Blender rendered the picture")
        if name == "one" and not img.isNull():
            img.save(str(out / "proxies.png"))
            spots = {"x=+3": lum_rgb(img, 0.5, 0.26), "x=-3": lum_rgb(img, 0.5, 0.77),
                     "ground": lum_rgb(img, 0.15, 0.5)}
            print({k: [round(c) for c in v] for k, v in spots.items()})
            # Red, not orange: the green is a small share of the red.
            red = all(spots[k][0] > 60 and spots[k][1] < 0.4 * spots[k][0] for k in ("x=+3", "x=-3"))
            ok(red, "the picture shows the red originals, not the orange stand-ins, at both places")
            ok(abs(spots["ground"][0] - spots["ground"][1]) < 25, "the ground beside them is grey")
else:
    print("(no Blender given: the job only)")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
