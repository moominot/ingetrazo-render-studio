"""The Output tab from IngeTrazo to the files: a box on a floor under a clear sky, written with the
panel's own code and rendered by a real Blender through the extension's script.

Checks: a size of its own (400 × 300); a transparent sky (alpha 0 in the sky, 255 on the ground) with
the same exposure as the opaque picture (it is measured with the sky); a 16-bit PNG, a 16-bit TIFF and
an OpenEXR (float, linear) written beside the PNG the preview window reads.

argv: <ingetrazo-src> <render-studio repo> <out dir> <blender.exe | bpy>
      «bpy» runs Blender as this Python's bpy module (and reads the files back with it).
"""
import json, math, os, re, struct, subprocess, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, OUT = [os.path.abspath(a) for a in sys.argv[1:4]]
BLENDER = sys.argv[4] if len(sys.argv) > 4 else None
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QImage, QVector3D
from core.camera import OrbitCamera
from core.scene import Scene
from render_studio import output as O, panel as P

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

if not BLENDER:
    print("(no Blender given)"); sys.exit(0)

def quad(pts, color):
    f = scene.mesh.add_face([QVector3D(*p) for p in pts]); f.attrs["color"] = color

scene = Scene()
quad([(-20, -20, 0), (20, -20, 0), (20, 20, 0), (-20, 20, 0)], (0.5, 0.5, 0.45))
for a, b in (((-1, -1), (1, -1)), ((1, -1), (1, 1)), ((1, 1), (-1, 1)), ((-1, 1), (-1, -1))):
    quad([(a[0], a[1], 0), (b[0], b[1], 0), (b[0], b[1], 2), (a[0], a[1], 2)], (0.8, 0.8, 0.8))
quad([(-1, -1, 2), (1, -1, 2), (1, 1, 2), (-1, 1, 2)], (0.8, 0.8, 0.8))
scene.shadows.month, scene.shadows.day, scene.shadows.hour = 6, 21, 10
cam = OrbitCamera(); cam.target = QVector3D(0, 0, 1.5); cam.distance = 12
cam.yaw = math.radians(30); cam.pitch = math.radians(5)       # low: the sky fills the top half
out = Path(OUT); out.mkdir(parents=True, exist_ok=True)


def render(name, settings, w=400, h=300):
    job, script = P.write_studio_job(scene, cam, out / name, "clear", {}, engine="eevee", quality=0,
                                     width=w, height=h, output=settings)
    data = json.loads(job.read_text(encoding="utf-8"))
    argv = ([sys.executable, str(script), "--", str(job)] if BLENDER == "bpy"
            else [BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)])
    r = subprocess.run(argv, capture_output=True, text=True, timeout=900)
    log = r.stdout + r.stderr
    m = re.findall(r"INGETRAZO exposure (-?[0-9.]+)", log)
    return data, log, (float(m[-1]) if m else None)


opaque, log0, ev0 = render("opaque", O.clean({"size": "custom", "height": 300}))
img0 = QImage(opaque["output"])
ok(not img0.isNull() and (img0.width(), img0.height()) == (400, 300), "a size of its own: 400 × 300")

clear, log1, ev1 = render("transparent", O.clean({"format": "png", "transparent": True}))
img1 = QImage(clear["output"])
ok(img1.hasAlphaChannel(), "a transparent sky: the PNG has alpha")
if img1.hasAlphaChannel():
    sky, ground = img1.pixelColor(200, 10).alpha(), img1.pixelColor(200, 290).alpha()
    ok(sky == 0 and ground == 255, f"…none in the sky ({sky}), all on the ground ({ground})")
ok(ev0 is not None and ev1 is not None and abs(ev0 - ev1) < 0.15,
   f"…measured with the sky: the same exposure ({ev0} / {ev1})")

for fmt in ("png16", "tiff16", "exr"):
    data, log, _ev = render(fmt, O.clean({"format": fmt, "transparent": fmt != "tiff16"}))
    final = Path(data["studio"]["output"]["path"])
    ok(final.is_file(),
       f"{fmt}: the final file is written beside the PNG ({final.name})")
    if not final.is_file():
        print(log[-1500:]); continue
    head = final.read_bytes()[:32]
    if fmt == "png16":
        depth, ctype = head[24], head[25]
        ok(head[:8] == b"\x89PNG\r\n\x1a\n" and depth == 16 and ctype == 6, f"…a PNG of 16 bits per channel, RGBA (depth {depth}, type {ctype})")
    if fmt == "tiff16":
        ok(head[:4] in (b"II*\x00", b"MM\x00*"), "…a TIFF")
    if fmt == "exr":
        ok(head[:4] == b"\x76\x2f\x31\x01", "…an OpenEXR")
    if BLENDER == "bpy":
        import bpy
        im = bpy.data.images.load(str(final))
        im.reload()
        px = list(im.pixels[:])
        if fmt == "exr":
            ok(im.is_float and max(px[0::4]) > 1.0, f"…float, linear light (brightest {max(px[0::4]):.2f} > 1)")
        elif fmt == "tiff16":
            ok(im.is_float or im.depth >= 48, f"…16 bits per channel (depth {im.depth})")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
