"""Texture sets through the panel's own job writer and IngeTrazo's own GLB export (offscreen Qt):
a loose floor textured with a Poly Haven-style set, a group painted whole with an ambientCG-style set
(tinted, so the model wears a tinted copy), a face with a plain picture. The job must carry the two
sets by the names the GLB gives the pictures; with a Blender path, the job is rendered and the
script must find both sets in the imported model.
argv: <ingetrazo-src> <render-studio repo> <out dir> [blender.exe]"""
import json, math, os, subprocess, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, OUT = [os.path.abspath(a) for a in sys.argv[1:4]]
BLENDER = sys.argv[4] if len(sys.argv) > 4 else None
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QColor, QImage, QVector3D
from core.camera import OrbitCamera
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from render_studio import panel as P

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

out = Path(OUT); tex = out / "textures"
def image(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = QImage(64, 64, QImage.Format_RGB32); im.fill(QColor(color)); im.save(str(path)); return str(path)
ph = tex / "ph"
floor_pic = image(ph / "tiles_diff_1k.jpg", "#c8b89a")
for n, c in (("tiles_nor_gl_1k.png", "#8080ff"), ("tiles_rough_1k.png", "#303030"), ("tiles_ao_1k.png", "#e0e0e0")):
    image(ph / n, c)
acg = tex / "acg"
wall_pic = image(acg / "Planks017_1K-JPG_Color.jpg", "#7a4a2a")
for n in ("NormalDX", "Roughness", "Metalness", "Opacity"):
    image(acg / f"Planks017_1K-JPG_{n}.jpg", "#808080" if n != "Opacity" else "#ffffff")
# A tinted copy, as IngeTrazo's tint makes it: the model wears the copy, the original has the set.
tinted = image(tex / "cache" / "Planks017_tint_3fa2.png", "#8a5a3a")
plain_pic = image(tex / "plain" / "photo.png", "#a0a0a0")

def quad(mesh, pts):
    return mesh.add_face([QVector3D(*p) for p in pts])

scene = Scene()
f = quad(scene.mesh, [(-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)])
f.attrs["texture"] = {"path": floor_pic, "sw": 1.0, "sh": 1.0, "rot": 0.0}
f = quad(scene.mesh, [(-2, -2, 0), (-2, 1.5, 0), (-2, 1.5, 2.5), (-2, -2, 2.5)])
f.attrs["texture"] = {"path": plain_pic, "sw": 1.0, "sh": 1.0, "rot": 0.0}
m = Mesh()
quad(m, [(-2, 1.5, 0), (2, 1.5, 0), (2, 1.5, 2.5), (-2, 1.5, 2.5)])
g = Group(m, name="Wall")
g.material = {"texture": {"path": tinted, "base": wall_pic, "sw": 1.0, "sh": 1.0, "tint": (0.9, 0.7, 0.6)}}
scene.groups.append(g)

cam = OrbitCamera(); cam.target = QVector3D(0, 0, 1); cam.distance = 7
cam.yaw = math.radians(-60); cam.pitch = math.radians(15)
job, script = P.write_studio_job(scene, cam, out / "job", "clear", {}, engine="eevee", quality=0, width=480, height=300)
data = json.loads(job.read_text(encoding="utf-8"))
sets = data["studio"].get("pbr") or {}
ok(set(sets) == {"tiles_diff_1k.jpg", "Planks017_tint_3fa2.png"}, f"the job carries both sets, by the names the model wears ({sorted(sets)})")
ok(sets.get("tiles_diff_1k.jpg", {}).get("normal", "").endswith("tiles_nor_gl_1k.png"), "…the floor's normal map, absolute")
w = sets.get("Planks017_tint_3fa2.png", {})
ok(w.get("normal_flip_green") is True and w.get("metalness", "").endswith("_Metalness.jpg"),
   "…the tinted wall: its original's ambientCG set (DirectX normal flipped, metalness)")
ok(all(os.path.isabs(v) for s in sets.values() for k, v in s.items() if isinstance(v, str) and k != "found"), "…every path absolute")

if BLENDER:
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)],
                       capture_output=True, text=True, errors="replace")
    lines = [l for l in r.stdout.splitlines() if "texture set" in l]
    print("\n".join(lines))
    ok(r.returncode == 0 and Path(data["output"]).is_file(), f"Blender rendered the job (rc {r.returncode})")
    ok(len(lines) == 2 and any("normal, roughness, ambient occlusion" in l for l in lines)
       and any("normal (green flipped)" in l and "metalness" in l and "opacity" in l for l in lines),
       "Blender found both sets in IngeTrazo's own GLB: the floor's and the painted wall's")
else:
    print("SKIP no Blender given")

print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
