"""Render Studio's lights from IngeTrazo to the picture: a night square with a lamp post (a component,
copied once) carrying a spot, and a free warm area light; the job is written with the panel's own code
and rendered by a real Blender through the extension's script.

Checks: the job carries the lights (the copy's spot too, where the copy stands); Blender says it built
them; the ground under each lamp is lit and the dark corner is not; with the lights switched off the
picture is dark.

argv: <ingetrazo-src> <render-studio repo> <out dir> [<blender.exe> | bpy]
      «bpy» runs the script with this Python's bpy module instead of a Blender program.
"""
import json, math, os, subprocess, sys
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
from render_studio import lights as L, panel as P

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

def quad(mesh, pts):
    return mesh.add_face([QVector3D(*p) for p in pts])

scene = Scene()
f = quad(scene.mesh, [(-6, -6, 0), (6, -6, 0), (6, 6, 0), (-6, 6, 0)])
f.attrs["color"] = (0.6, 0.6, 0.6)
post = Mesh()                                   # a thin post, 3 m tall
quad(post, [(-0.05, -0.05, 0), (0.05, -0.05, 0), (0.05, -0.05, 3), (-0.05, -0.05, 3)])
lamp = Group(post, name="Lamp post"); lamp.xform = QMatrix4x4(); lamp.xform.translate(-3, 0, 0)
lamp.ext = {"render_studio": {"lights": [L.new_light("spot", pos=(0, 0.4, 2.9), unit="lm", power=6000,
                                                       spot_angle=70, spot_blend=0.4, kelvin=3000)]}}
scene.groups.append(lamp)
twin = copy_group(lamp, QVector3D(6, 0, 0)); scene.groups.append(twin)
scene.plugin_data["render_studio"] = {"lights": [
    L.new_light("area", pos=(0, -3, 0.8), unit="lm", power=3000, shape="disk", size=0.5, kelvin=2400,
                dir=[0, 0, -1])]}

cam = OrbitCamera(); cam.target = QVector3D(0, 0, 0); cam.distance = 14
cam.yaw = math.radians(0); cam.pitch = math.radians(80)
out = Path(OUT); out.mkdir(parents=True, exist_ok=True)


def render(name):
    job, script = P.write_studio_job(scene, cam, out / name, "night", {}, engine="eevee", quality=0,
                                     width=320, height=240)
    data = json.loads(job.read_text(encoding="utf-8"))
    if not BLENDER:
        return data, None, ""
    argv = ([sys.executable, str(script), "--", str(job)] if BLENDER == "bpy"
            else [BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)])
    r = subprocess.run(argv, capture_output=True, text=True, timeout=900)
    img = QImage(data["output"])
    return data, (None if img.isNull() else img), r.stdout + r.stderr


def lum(img, fx, fy, r=6):
    w, h = img.width(), img.height()
    cx, cy = int(fx * w), int(fy * h)
    tot = n = 0
    for x in range(cx - r, cx + r + 1):
        for y in range(cy - r, cy + r + 1):
            c = img.pixelColor(max(0, min(w - 1, x)), max(0, min(h - 1, y)))
            tot += 0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue(); n += 1
    return tot / n


data, img, log = render("on")
lights = data["studio"]["lights"]
spots = sorted((l for l in lights if l["type"] == "spot"), key=lambda l: l["pos"][0])
ok(len(lights) == 3 and data["lights"] == [], "the job carries three lights (two spots, one area), none twice")
ok(len(spots) == 2 and all(abs(a - b) < 1e-6 for a, b in zip(spots[0]["pos"], (-3, 0.4, 2.9)))
   and all(abs(a - b) < 1e-6 for a, b in zip(spots[1]["pos"], (3, 0.4, 2.9))),
   "each lamp post's spot is at its head, the copy's where the copy stands")

if BLENDER:
    ok(img is not None, "Blender rendered the picture")
    ok("studio lights 3" in log, "Blender built the three lights")
    if img is not None:
        img.save(str(out / "lights_on.png"))
        # The view looks almost straight down with +X up the picture: the two lamps above and
        # below its middle, the area light to the left, a corner of the floor bottom left.
        under_a, under_b = lum(img, 0.55, 0.26), lum(img, 0.55, 0.77)
        area, corner = lum(img, 0.30, 0.50), lum(img, 0.20, 0.95)
        print(f"under the lamps {under_a:.1f} and {under_b:.1f}, under the area light {area:.1f}, corner {corner:.1f}")
        ok(under_a > corner + 40 and under_b > corner + 40 and abs(under_a - under_b) < 0.25 * max(under_a, under_b),
           "the ground under both lamps is lit alike, the corner is dark")
        ok(area > corner + 40, "the area light lights the ground under it")
    for g in (lamp, twin):
        g.ext["render_studio"]["lights"][0]["on"] = False
    scene.plugin_data["render_studio"]["lights"][0]["on"] = False
    data_off, img_off, _log = render("off")
    ok(data_off["studio"]["lights"] == [], "switched off, no light goes to Blender")
    if img is not None and img_off is not None:
        img_off.save(str(out / "lights_off.png"))
        ok(lum(img_off, 0.55, 0.26) < lum(img, 0.55, 0.26) - 40,
           "without them the night is dark under the lamp")
else:
    print("(no Blender given: the job only)")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
