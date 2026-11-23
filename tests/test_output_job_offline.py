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
from PySide6.QtGui import QColor, QImage, QVector3D
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
    render.last_log = log
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


# ---- panoramas: a 360° (equirectangular) picture and a flat (cylindrical) one --------------------
pano360, logp, _e = render("pano360", O.clean({"projection": "360"}), 400, 200)
ok("INGETRAZO panorama 360" in logp, "Blender says it made the camera panoramic (360)")
d = pano360["studio"]["output"]
ok(d["projection"] == "360" and pano360.get("engine") == "cycles", f"a panorama is rendered with Cycles ({pano360.get('engine')})")
img = QImage(pano360["output"])
ok(not img.isNull() and (img.width(), img.height()) == (400, 200), f"the 360° picture is 2:1 ({img.width()} × {img.height()})")
if not img.isNull():
    mid, edge = img.pixelColor(200, 100).lightness(), img.pixelColor(2, 100).lightness()
    sky_top, ground_bottom = img.pixelColor(200, 5).lightness(), img.pixelColor(200, 195).lightness()
    right = img.pixelColor(397, 100).lightness()
    ok(abs(edge - right) < 12, f"…the picture wraps all round: its two edges meet ({edge} / {right})")
    ok(abs(mid - img.pixelColor(160, 100).lightness()) > 10 or abs(img.pixelColor(200, 100).lightness() - img.pixelColor(240, 100).lightness()) > 10,
       "…the box is in the middle")
    ok(sky_top != ground_bottom, f"…the sky above and the ground below differ ({sky_top} / {ground_bottom})")
flat, logf, _e = render("panoflat", O.clean({"projection": "flat", "angle": 90}), 600, 200)
ok("INGETRAZO panorama flat" in logf, "…and the flat one")
img = QImage(flat["output"])
ok(not img.isNull() and (img.width(), img.height()) == (600, 200), "the flat panorama has the size asked for")
if not img.isNull():
    ok(img.pixelColor(300, 100).lightness() > img.pixelColor(10, 100).lightness() + 25 or abs(img.pixelColor(300, 100).lightness() - img.pixelColor(10, 100).lightness()) > 25,
       "…the box in the middle of 90° of horizon")

chk = QImage(64, 64, QImage.Format_RGB32)
for x in range(64):
    for y in range(64):
        chk.setPixelColor(x, y, QColor(220, 30, 30) if (x // 32 + y // 32) % 2 else QColor(30, 30, 220))
chk_path = str(out / "checker.png"); chk.save(chk_path)
# ---- a material on the ground reaches the job, also with a 360° background, under the export's name ------------------
from core.materials import Material
scene.materials["Paving stone"] = Material("Paving stone", texture={"path": chk_path, "sw": 1.0, "sh": 1.0})
_pf = scene.mesh.add_face([QVector3D(8, 8, 0.01), QVector3D(9, 8, 0.01), QVector3D(9, 9, 0.01)]); _pf.attrs["mat"] = "Paving stone"
_pf.attrs["texture"] = {"path": chk_path, "sw": 1.0, "sh": 1.0}
scene.version += 1
for label, hdri in (("a plain sky", None), ("a 360° background", {"path": str(out / "x.hdr"), "rotation": 0, "strength": 1.0, "light": True})):
    job, _s = P.write_studio_job(scene, cam, out / "gmat", "clear", {}, engine="eevee", quality=0, width=200, height=100,
                                 hdri=hdri, ground_material={"name": "Paving stone", "tile": 2.0},
                                 ground_look={"type": "custom", "color": [0.1, 0.2, 0.3], "roughness": 0.2, "haze": 2.0, "offset": 0.1})
    st = json.loads(job.read_text(encoding="utf-8"))["studio"]
    ok(st.get("ground_material", {}).get("name") == "Paving_stone" and st["ground_material"]["tile"] == [2.0, 2.0],
       f"with {label}: the job names the ground's material as Blender has it ({st.get('ground_material')})")
    ok(st.get("ground_color") == [0.1, 0.2, 0.3] and st.get("ground_roughness") == 0.2 and st.get("haze_scale") == 2.0 and st.get("ground_offset") == 0.1,
       f"with {label}: and the ground's look")

# ---- the ground's material in a real render: a red/blue checker picture on a ground that was grey ------------------
scene.materials["Paving stone"] = Material("Paving stone", texture={"path": chk_path, "sw": 1.0, "sh": 1.0})
patch = scene.mesh.add_face([QVector3D(5, 5, 0.01), QVector3D(6, 5, 0.01), QVector3D(6, 6, 0.01), QVector3D(5, 6, 0.01)])
patch.attrs["mat"] = "Paving stone"; patch.attrs["texture"] = {"path": chk_path, "sw": 1.0, "sh": 1.0}
scene.version += 1
def ground_render(name, gm):
    job, script = P.write_studio_job(scene, cam, out / name, "clear", {}, engine="eevee", quality=0, width=400, height=300,
                                     ground_material=gm, output=O.clean({}))
    data = json.loads(job.read_text(encoding="utf-8"))
    argv = ([sys.executable, str(script), "--", str(job)] if BLENDER == "bpy"
            else [BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)])
    r = subprocess.run(argv, capture_output=True, text=True, timeout=900)
    return QImage(data["output"]), r.stdout + r.stderr
plain, _l = ground_render("g_plain", None)
paved, logg = ground_render("g_paved", {"name": "Paving stone", "tile": 0.5})
def strength(img):
    reds = blues = 0
    for y in range(190, 300, 2):
        for x in range(0, 400, 2):
            c = img.pixelColor(x, y)
            reds += c.red() > c.blue() + 40
            blues += c.blue() > c.red() + 40
    return reds, blues
rp, bp = strength(plain); rg, bg_ = strength(paved)
ok(not paved.isNull() and rg + bg_ > 150 and rg + bg_ > 5 * (rp + bp + 1), f"the ground wears the checker in the render (red/blue pixels {rg}/{bg_} against {rp}/{bp} plain)")
if rg + bg_ <= 150:
    print([l for l in logg.splitlines() if "ground" in l.lower()][-6:])

# ---- a material edited in Blender is rendered exactly as it was left: a glowing magenta made there ---------------------------
from render_studio import blender_edit as BE
pk = out / "pkg"; pk.mkdir(exist_ok=True)
EDIT = os.path.join(REPO, "render_studio", "blender", "edit_scene.py")
BE.dump(pk / "in.json", [{"name": "Paint", "color": [0.2, 0.2, 0.2], "roughness": 0.5, "metallic": 0.0, "glow": 0.0, "texture": None, "grass": None, "package": None}])
bl = [BLENDER, "-b", "--factory-startup"] if BLENDER != "bpy" else None
if bl:
    subprocess.run([*bl, "--python", EDIT, "--", "make", "materials", str(pk / "in.json"), str(pk / "s.blend")], capture_output=True, timeout=300)
    (pk / "mod.py").write_text("""
import bpy
m = bpy.data.materials["Paint"]
b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
b.inputs["Emission Color"].default_value = (1.0, 0.0, 1.0, 1.0)
b.inputs["Emission Strength"].default_value = 8.0
noise = m.node_tree.nodes.new("ShaderNodeTexNoise")
bpy.ops.wm.save_mainfile()
""")
    subprocess.run([*bl, str(pk / "s.blend"), "--python", str(pk / "mod.py")], capture_output=True, timeout=300)
    subprocess.run([*bl, str(pk / "s.blend"), "--python", EDIT, "--", "read", "materials", str(pk / "r.json")], capture_output=True, timeout=300)
    pkg = json.loads((pk / "r.json").read_text())[0].get("package")
    ok(pkg is not None, "the edited material comes back as a package")
    scene.materials["Paint"] = Material("Paint", color=(0.2, 0.2, 0.2))
    side = scene.mesh.add_face([QVector3D(-1, -1, 0.0), QVector3D(1, -1, 0.0), QVector3D(1, 1, 0.0), QVector3D(-1, 1, 0.0)])
    top = scene.mesh.add_face([QVector3D(-1, -1, 2.01), QVector3D(1, -1, 2.01), QVector3D(1, 1, 2.01), QVector3D(-1, 1, 2.01)])
    top.attrs["mat"] = "Paint"; top.attrs["color"] = (0.2, 0.2, 0.2, 1.0)
    def paint_render(name, specs):
        job, script = P.write_studio_job(scene, cam, out / name, "clear", {}, engine="eevee", quality=0, width=400, height=300,
                                         materials=specs, output=O.clean({}))
        data = json.loads(job.read_text(encoding="utf-8"))
        subprocess.run([*bl, "--python", str(script), "--", str(job)], capture_output=True, text=True, timeout=900)
        return QImage(data["output"])
    def magenta(img):
        return sum(1 for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
                   if img.pixelColor(x, y).red() > img.pixelColor(x, y).green() + 60 and img.pixelColor(x, y).blue() > img.pixelColor(x, y).green() + 60)
    plain_img = paint_render("paint_plain", {"Paint": {"type": "generic", "roughness": 0.5, "metallic": 0.0, "bump": 0.0, "glow": 0.0}})
    made_img = paint_render("paint_blender", {"Paint": {"type": "generic", "roughness": 0.5, "metallic": 0.0, "bump": 0.0, "glow": 0.0, "blender": pkg}})
    mp, mb = magenta(plain_img), magenta(made_img)
    ok(mb > 10 and mb > 5 * (mp + 1), f"the render shows the material as it was left in Blender (magenta pixels {mb} against {mp} without it)")

# the grass circle is centred on the centroid of the drawing's objects: the job carries it
scene.materials["Lawn"] = Material("Lawn", color=(0.2, 0.5, 0.1))
_lf = scene.mesh.add_face([QVector3D(30, 30, 0.0), QVector3D(31, 30, 0.0), QVector3D(31, 31, 0.0)]); _lf.attrs["mat"] = "Lawn"
scene.version += 1
job, _s = P.write_studio_job(scene, cam, out / "gcentre", "clear", {}, engine="eevee", quality=0, width=200, height=100,
                             materials={"Lawn": {"type": "grass", "grass_height": 0.05}}, ground_material={"name": "Lawn", "tile": 2.0})
st = json.loads(job.read_text(encoding="utf-8"))["studio"]
ok(isinstance(st.get("ground_grass_centre"), list) and len(st["ground_grass_centre"]) == 2, f"the job carries where the grass circle is centred ({st.get('ground_grass_centre')})")

# ---- a sun that has set is a night: the night sky, stars and moonlight (sliders), no sun ------------------------------------------
from render_studio import presets as PR
scene.shadows.month, scene.shadows.day, scene.shadows.hour = 6, 21, 23
def night_job(name, sliders, look="clear"):
    job, script = P.write_studio_job(scene, cam, out / name, look, sliders, engine="eevee", quality=0, width=160, height=100)
    data = json.loads(job.read_text(encoding="utf-8"))
    data["blend"] = str(out / name / "s.blend"); job.write_text(json.dumps(data))
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)], capture_output=True, text=True, timeout=900)
    probe = out / name / "probe.py"
    probe.write_text("import bpy\nm = bpy.data.objects.get('IngeTrazo moon')\nprint('MOON', None if m is None else round(m.data.energy, 4), [o.name for o in bpy.data.objects if o.type == 'LIGHT'])\n")
    p2 = subprocess.run([BLENDER, "-b", str(out / name / "s.blend"), "--python", str(probe)], capture_output=True, text=True, timeout=300)
    line = next((l for l in p2.stdout.splitlines() if l.startswith("MOON")), "")
    return data, r.stdout + r.stderr, line
if BLENDER != "bpy":
    d1, log1, moon1 = night_job("night1", {"moon": 1.0, "stars": 1.0})
    ok(d1["ambience"] == "night" and d1.get("sun") is None and "night sky" in log1.lower(), f"at 23:00 in June a day look is a night: no sun, the night sky ({d1['ambience']})")
    d2, log2, moon2 = night_job("night2", {"moon": 2.0, "stars": 0.0})
    e1 = float(moon1.split()[1]); e2 = float(moon2.split()[1])
    ok(e1 > 0 and abs(e2 - 2 * e1) < 1e-3, f"the Moonlight slider scales the moon's light ({e1} → {e2})")
    ok("stars 0" in log2.lower() or "stars, 0" in log2.lower() or "stars 0.0" in log2.lower(), "…and the Stars slider the stars")
    # no moon and no stars: black. The meter cannot lift what is not there.
    def mean_of(d):
        im = QImage(d["output"]); n = tot = 0
        for y in range(0, im.height(), 2):
            for x in range(0, im.width(), 2):
                c = im.pixelColor(x, y); tot += c.red() + c.green() + c.blue(); n += 3
        return tot / max(1, n)
    d0, _l0, _m0 = night_job("night_black", {"moon": 0.0, "stars": 0.0})
    d1b, _l1b, _m1b = night_job("night_moon", {"moon": 1.0, "stars": 0.0})
    d2b, _l2b, _m2b = night_job("night_moon2", {"moon": 2.0, "stars": 0.0})
    b0, b1, b2 = mean_of(d0), mean_of(d1b), mean_of(d2b)
    ok(b0 < 3.0, f"moonlight 0 and no stars: a black night (mean {b0:.1f} of 255)")
    dc0, _x, _y = night_job("night_clear", {"moon": 1.0, "stars": 1.0, "clouds": 0.0})
    dc1, _x, _y = night_job("night_cloudy", {"moon": 1.0, "stars": 1.0, "clouds": 1.0})
    dc2, _x, _y = night_job("night_cloudy_nomoon", {"moon": 0.0, "stars": 1.0, "clouds": 1.0})
    c0, c1, c2 = mean_of(dc0), mean_of(dc1), mean_of(dc2)
    ok(abs(c1 - c0) > 1.0, f"the clouds change a night sky (moonlit clouds: {c0:.1f} clear, {c1:.1f} cloudy)")
    ok(c2 < 5.0, f"…and with no moon the clouds are not lit: the sky stays dark ({c2:.1f})")
    ok(b1 > b0 + 3 and b2 >= b1, f"…and the moonlight brings the sky up ({b0:.1f} → {b1:.1f} → {b2:.1f})")
    scene.shadows.hour = 12
    d3, log3, _m = night_job("day", {})
    ok(d3["ambience"] == "day" and d3.get("sun") is not None, "at noon the same look is a day with its sun")
    # the golden hour look and the overcast one follow the clock too; interior and white model do not
    scene.shadows.hour = 23
    ok(night_job("night_golden", {}, "golden_hour")[0]["ambience"] == "night", "the Golden hour look at night is a night")
    ok(night_job("night_interior", {}, "interior")[0]["ambience"] != "night", "the Interior look is left as it is")
    scene.shadows.hour = 10

# ---- the skyline: the job carries it, and in a real render it fills the horizon -----------------------------------------------------------
sk_job, _s = P.write_studio_job(scene, cam, out / "sk", "clear", {}, engine="eevee", quality=0, width=200, height=100,
                                skyline={"type": "mountains", "height": 6.0, "seed": 3})
ok(json.loads(sk_job.read_text(encoding="utf-8"))["studio"].get("skyline", {}).get("type") == "mountains", "the job carries the skyline")
ok("skyline" not in json.loads(P.write_studio_job(scene, cam, out / "sk0", "clear", {}, engine="eevee", quality=0, width=200, height=100)[0].read_text(encoding="utf-8"))["studio"], "…and nothing when there is none")
if BLENDER != "bpy":
    low = OrbitCamera(); low.target = QVector3D(0, 0, 1.5); low.distance = 12; low.yaw = math.radians(30); low.pitch = math.radians(1)
    def horizon_render(name, skyline):
        job, script = P.write_studio_job(scene, low, out / name, "clear", {}, engine="eevee", quality=0, width=320, height=180,
                                         ground_look={"ground_radius": 600.0}, skyline=skyline)
        data = json.loads(job.read_text(encoding="utf-8"))
        r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)], capture_output=True, text=True, timeout=900)
        return QImage(data["output"]), r.stdout + r.stderr
    flat_img, _l = horizon_render("hz0", None)
    hill_img, logh = horizon_render("hz1", {"type": "mountains", "height": 8.0, "seed": 5})
    ok("INGETRAZO skyline mountains" in logh, "Blender says it made the mountains")
    def changed(a, b):                                # how many pixels near the horizon the skyline changes
        y0 = a.height() // 2 - 40
        return sum(1 for y in range(y0, y0 + 40) for x in range(0, a.width())
                   if abs(a.pixelColor(x, y).lightness() - b.pixelColor(x, y).lightness()) > 12)
    n_changed = changed(flat_img, hill_img)
    ok(n_changed > 400, f"the mountains fill the horizon: {n_changed} pixels near it differ from the flat one")

# ---- styles: outlines, white, model, light (lux), sketch, watercolour ------------------------------------------------------------------------
if BLENDER != "bpy":
    scene.shadows.hour = 11
    sty_cam = OrbitCamera(); sty_cam.target = QVector3D(2, 2, 0.8); sty_cam.distance = 11; sty_cam.yaw = math.radians(-35); sty_cam.pitch = math.radians(35)
    def styled(name, style, look="clear", camera=None):
        from render_studio import outlines, settings_store
        class _VP:                                         # the outlines are drawn by the app, from the scene's geometry
            def __init__(self): self.scene = scene
        lines = outlines.write_layer(_VP(), camera or sty_cam, 480, 270, settings_store.style(style), out / name / "lines.png")
        job, script = P.write_studio_job(scene, camera or sty_cam, out / name, look, {}, engine="eevee", quality=0, width=480, height=270, style=style, lines=lines)
        data = json.loads(job.read_text(encoding="utf-8"))
        r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)], capture_output=True, text=True, timeout=900)
        return QImage(data["output"]), r.stdout + r.stderr
    def sat_region(img):                              # the checker patch's rows: how coloured they are
        tot = n = 0
        for y in range(0, img.height(), 2):
            for x in range(0, img.width(), 2):
                c = img.pixelColor(x, y); tot += max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue()); n += 1
        return tot / max(1, n)
    def dark(img, thr=45):
        return sum(1 for y in range(0, img.height()) for x in range(0, img.width(), 2) if img.pixelColor(x, y).lightness() < thr)
    plain_i, _lg = styled("st_plain", {"mode": "none", "width": 0})
    line_i, lg = styled("st_lines", {"mode": "none", "width": 3.0, "color": [0.0, 0.0, 0.0]})
    ok("INGETRAZO outlines" in lg and dark(line_i) > dark(plain_i) + 150, f"None with outlines: lines are drawn ({dark(plain_i)} dark pixels, {dark(line_i)} with outlines)")
    thick_i, _lg = styled("st_thick", {"mode": "none", "width": 7.0, "color": [0.0, 0.0, 0.0]})
    ok(dark(thick_i) > dark(line_i) * 1.3, f"…a thicker line has more dark pixels ({dark(line_i)} → {dark(thick_i)})")
    red_i, _lg = styled("st_redlines", {"mode": "none", "width": 4.0, "color": [1.0, 0.0, 0.0]})
    ok(sum(1 for y in range(0, red_i.height()) for x in range(0, red_i.width(), 2) if red_i.pixelColor(x, y).red() > red_i.pixelColor(x, y).green() + 60 and red_i.pixelColor(x, y).red() > red_i.pixelColor(x, y).blue() + 60) > 100, "…in the colour chosen")
    white_i, lgw = styled("st_white", {"mode": "white", "width": 1.5, "color": [0.1, 0.1, 0.1]})
    ok(sat_region(white_i) < sat_region(plain_i) * 0.6, f"White: the colours go ({sat_region(plain_i):.1f} → {sat_region(white_i):.1f})")
    model_i, lgm = styled("st_model", {"mode": "model", "width": 1.0, "color": [0, 0, 0], "model_color": [0.1, 0.3, 0.9]})
    bl = sum(1 for y in range(0, model_i.height(), 2) for x in range(0, model_i.width(), 2) if model_i.pixelColor(x, y).blue() > model_i.pixelColor(x, y).red() + 40)
    ok("INGETRAZO model" in lgm and bl > 1500, f"Model: everything wears the one colour ({bl} bluish pixels)")
    light_i, lgl = styled("st_light", {"mode": "light", "width": 0.0})
    ok("INGETRAZO lux scale" in lgl, f"Light: a lux scale is worked out ({[l for l in lgl.splitlines() if 'lux scale' in l][-1:]})")
    # the scale at the right: a white panel with the colour bar; the picture itself in false colour (many hues, not the grey model)
    panel_px = light_i.pixelColor(light_i.width() - 12, light_i.height() // 2)
    hues = {light_i.pixelColor(x, y).hue() // 20 for y in range(0, light_i.height(), 6) for x in range(0, light_i.width() - 80, 6) if light_i.pixelColor(x, y).saturation() > 90}
    ok(len(hues) >= 3, f"…in false colour (hues: {len(hues)})")
    bar = [light_i.pixelColor(x, y) for y in range(int(light_i.height() * 0.25), int(light_i.height() * 0.75), 4) for x in range(light_i.width() - 100, light_i.width() - 5)]
    ok(any(c.lightness() > 240 for c in bar) and any(c.saturation() > 150 for c in bar), "…with its scale drawn at the right (a white panel, a colour bar)")
    light_fixed, lgf = styled("st_light2", {"mode": "light", "lux_max": 50000.0})
    ok("lux scale 0 to 50000" in lgf, "…and the top of the scale can be fixed (50 000 lx)")
    sketch_i, lgs = styled("st_sketch", {"mode": "sketch", "width": 1.5, "color": [0.1, 0.1, 0.1], "noise": 0.7, "extend": 0.5}, camera=low)
    paper = sketch_i.pixelColor(sketch_i.width() // 2, 4)
    ok(paper.red() > 235 and paper.green() > 230 and paper.blue() > 220, f"Sketch: the sky is paper ({paper.red()}, {paper.green()}, {paper.blue()})")
    ok(dark(sketch_i, 90) > 200 and sat_region(sketch_i) < 12, "…lines on it, in pencil (no colour)")
    smooth_i, lgq = styled("st_sketch0", {"mode": "sketch", "width": 1.5, "color": [0.1, 0.1, 0.1], "noise": 0.0, "extend": 0.0}, camera=low)
    differ = sum(1 for y in range(0, sketch_i.height(), 2) for x in range(0, sketch_i.width(), 2)
                 if abs(sketch_i.pixelColor(x, y).lightness() - smooth_i.pixelColor(x, y).lightness()) > 60)
    ok("INGETRAZO outlines" in lgs and differ > 15, f"…an irregular stroke when asked, a clean one when not ({differ} pixels differ)")
    water_i, lgq2 = styled("st_water", {"mode": "watercolour", "width": 0.0, "wetness": 0.7, "paper": 0.6, "edges": 0.5})
    def rough(img):                                   # the fine detail: the mean change from a pixel to its neighbour
        tot = n = 0
        for y in range(0, img.height() - 1, 2):
            for x in range(0, img.width() - 1, 2):
                a, b = img.pixelColor(x, y), img.pixelColor(x + 1, y)
                tot += abs(a.lightness() - b.lightness()); n += 1
        return tot / max(1, n)
    ok("INGETRAZO style picture watercolour" in lgq2.replace("watercolour", "watercolour"), "Watercolour: the picture is painted")
    ok(abs(rough(water_i) - rough(plain_i)) > 0.2 or sat_region(water_i) != sat_region(plain_i), f"…it is not the plain render (detail {rough(plain_i):.2f} → {rough(water_i):.2f})")
    scene.shadows.hour = 10
# ---- fog: thickness and where it starts -------------------------------------------------------------------------------------------------------
if BLENDER != "bpy":
    def fogged(name, sliders):
        job, script = P.write_studio_job(scene, sty_cam, out / name, "clear", sliders, engine="eevee", quality=0, width=480, height=270)
        data = json.loads(job.read_text(encoding="utf-8"))
        r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)], capture_output=True, text=True, timeout=900)
        return QImage(data["output"]), r.stdout + r.stderr
    def away(a, b):                                   # the mean difference between two pictures, over the whole frame
        tot = n = 0
        for y in range(0, a.height(), 3):
            for x in range(0, a.width(), 3):
                ca, cb = a.pixelColor(x, y), b.pixelColor(x, y)
                tot += abs(ca.red() - cb.red()) + abs(ca.green() - cb.green()) + abs(ca.blue() - cb.blue()); n += 3
        return tot / max(1, n)
    f0, _l = fogged("fog0", {"fog": 0.0})
    f1, l1 = fogged("fog1", {"fog": 1.0, "fog_start": 0.0})
    f2, l2 = fogged("fog2", {"fog": 1.0, "fog_start": 400.0})
    f3, l3 = fogged("fog3", {"fog": 0.3, "fog_start": 0.0})
    ok("fog 1 from 0 m" in l1, "Blender says it made the fog")
    d1, d2, d3 = away(f0, f1), away(f0, f2), away(f0, f3)
    ok(d1 > 8.0, f"a thick fog from the camera changes the picture ({d1:.1f})")
    ok(d2 < d1 * 0.6, f"…one that starts far away changes it much less ({d2:.1f} against {d1:.1f})")
    ok(d3 < d1 * 0.9, f"…and a thinner fog less than a thick one ({d3:.1f} against {d1:.1f})")
    a1, la1 = fogged("ao1", {"ao": 1.0, "ao_distance": 2.0})
    ok("occlusion 1 reach 2 m" in la1 and "no AO pass" not in la1, "Blender says it made the occlusion")
    da = away(f0, a1)
    ok(da > 1.5, f"ambient occlusion darkens the picture where things meet ({da:.1f})")
    a0, _la0 = fogged("ao0", {"ao": 0.0, "ao_distance": 2.0})
    ok(away(f0, a0) < 0.5, "…and at 0 it changes nothing")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
