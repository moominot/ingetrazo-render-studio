"""The plain-colour background with the ground's shadows, in a REAL Blender: the background is exactly the colour, the ground shows only
as its shadow over it, the model stays.
argv: <ingetrazo-src> <render-studio repo> <out dir> <blender.exe>"""
import json, math, os, subprocess, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, OUT = [os.path.abspath(a) for a in sys.argv[1:4]]
BLENDER = sys.argv[4]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QImage, QVector3D
from core.camera import OrbitCamera
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from render_studio import panel as P, settings_store as S

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

ok(S.flat(None) is None and S.flat({}) == {"color": [1.0, 1.0, 1.0]}, "settings: none, or white")
ok(S.clean({"look": "clear", "flat": {"color": [0, 0.5, 2]}})["flat"] == {"color": [0.0, 0.5, 1.0]}, "…kept in the document, clamped")
ok(S.shadows(None)["draw"] == "render" and S.shadows({"draw": "weird", "spacing": 999})["draw"] == "render"
   and S.shadows({"draw": "dots", "spacing": 999})["spacing"] == 60.0, "shadows: as rendered by default, cleaned")
old = S.clean({"look": "clear", "style": {"mode": "sketch", "hatch": "cross", "hatch_spacing": 11, "color": [0.0, 0.0, 0.0]}})
ok(old["shadows"]["draw"] == "cross" and old["shadows"]["spacing"] == 11 and "hatch" not in old["style"], "a sketch's old hatching moves to the shadows")

V = QVector3D
scene = Scene()
m = Mesh()
x0, y0, z0, x1, y1, z1 = 0, 0, 0, 2, 2, 3
for q in ([V(x0,y0,z0),V(x1,y0,z0),V(x1,y0,z1),V(x0,y0,z1)], [V(x1,y0,z0),V(x1,y1,z0),V(x1,y1,z1),V(x1,y0,z1)],
          [V(x1,y1,z0),V(x0,y1,z0),V(x0,y1,z1),V(x1,y1,z1)], [V(x0,y1,z0),V(x0,y0,z0),V(x0,y0,z1),V(x0,y1,z1)],
          [V(x0,y0,z1),V(x1,y0,z1),V(x1,y1,z1),V(x0,y1,z1)], [V(x0,y1,z0),V(x1,y1,z0),V(x1,y0,z0),V(x0,y0,z0)]):
    m.add_face(q).attrs["color"] = (0.7, 0.15, 0.1, 1.0)
scene.groups.append(Group(m, name="block"))
cam = OrbitCamera(); cam.target = V(1, 1, 1); cam.distance = 16; cam.yaw = math.radians(-60); cam.pitch = math.radians(40)

def render(name, flat, engine="eevee", style=None, ground=True, floor=True, shadows=None):
    job, script = P.write_studio_job(scene, cam, Path(OUT) / name, "clear", {}, engine=engine, quality=0, width=480, height=270,
                                     ground=ground, ground_shadow=floor, flat=flat, style=style, shadows=shadows)
    data = json.loads(job.read_text(encoding="utf-8"))
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)], capture_output=True, text=True, timeout=900)
    img = QImage(data["output"])
    if img.isNull():
        print((r.stdout + r.stderr)[-4000:])
    return img, r.stdout + r.stderr

def stats(img):
    white = shade = red = other = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y); R, G, B = c.red(), c.green(), c.blue()
            if (R, G, B) == (255, 255, 255): white += 1
            elif abs(R - G) < 4 and abs(G - B) < 4 and R > 120: shade += 1
            elif R > G + 30: red += 1
            else: other += 1
    return white, shade, red, other, (img.width() // 2) * (img.height() // 2)

white = {"color": [1.0, 1.0, 1.0]}
for engine in ("eevee", "cycles"):
    img, log = render(engine, white, engine)
    ok(not img.isNull(), f"{engine}: a picture")
    if img.isNull():
        continue
    w, s, r, o, n = stats(img)
    corners = {img.pixelColor(x, y).getRgb()[:3] for x in (1, img.width() - 2) for y in (1, img.height() - 2)}
    ok(corners == {(255, 255, 255)}, f"{engine}: the corners (sky and ground) are pure white ({corners})")
    ok(w > 0.7 * n and r > 0.01 * n, f"{engine}: mostly white, the red block stays (white {w/n:.0%}, red {r/n:.1%})")
    ok(0.003 * n < s < 0.2 * n and o < 0.03 * n, f"{engine}: the ground's shadow is a light grey over the white (shade {s/n:.1%}, other {o/n:.1%})")
    img.save(str(Path(OUT) / f"{engine}.png"))

img, _ = render("nofloor", white, floor=False)
w, sh, r, o, n = stats(img)
ok(sh < 0.003 * n, f"«Shadow on the floor» off: none ({sh/n:.2%})")
img, _ = render("noground", white, ground=False)
w, sh, r, o, n = stats(img)
ok(img.pixelColor(1, 1).getRgb()[:3] == (255, 255, 255) and sh > 0.003 * n and r > 0.01 * n, f"no generated ground: the floor's shadow all the same ({sh/n:.2%})")
img, _ = render("blue", {"color": [0.2, 0.4, 0.8]})
ok(img.pixelColor(1, 1).getRgb()[:3] == (51, 102, 204), f"another colour is exact ({img.pixelColor(1, 1).getRgb()[:3]})")

def greens(img):
    return sum(1 for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
               if img.pixelColor(x, y).green() > img.pixelColor(x, y).red() + 60) / ((img.width() // 2) * (img.height() // 2))
green = {"draw": "colour", "color": [0.0, 1.0, 0.0], "opacity": 1.0}
for engine in ("eevee", "cycles"):
    img, _ = render("green_" + engine, white, engine, shadows=green)
    ok(greens(img) > 0.004 and img.pixelColor(1, 1).getRgb()[:3] == (255, 255, 255), f"{engine}: the shadows in the colour chosen, over white ({greens(img):.2%})")
    img.save(str(Path(OUT) / f"green_{engine}.png"))
solid = greens(img)
img, _ = render("hatched", white, shadows=dict(green, draw="lines", spacing=6.0))
ok(0.0 < greens(img) < solid, f"hatched: less ink than the flat colour ({greens(img):.2%} < {solid:.2%})")
img, _ = render("sky_green", None, shadows=green)
ok(greens(img) > 0.004 and img.pixelColor(1, 1).getRgb()[:3] != (255, 255, 255), f"with the sky and its ground too, in any style ({greens(img):.2%})")
img.save(str(Path(OUT) / "sky_green.png"))
img, _ = render("sketch", white, style={"mode": "sketch", "base": False, "width": 1.0}, shadows={"draw": "lines"})
ok(img.pixelColor(1, 1).getRgb()[:3] == (255, 255, 255), f"sketch: the paper is the colour ({img.pixelColor(1, 1).getRgb()[:3]})")
img.save(str(Path(OUT) / "sketch.png"))
img, _ = render("noflat", None)
ok(img.pixelColor(1, 1).getRgb()[:3] != (255, 255, 255), "without it, the sky as before")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
