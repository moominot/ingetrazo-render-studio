"""The combinations the old styles could not say, through the real panel and a REAL Blender.
argv: <ingetrazo-src> <render-studio repo> <out dir> <blender.exe>"""
import json, os, subprocess, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, OUT = [os.path.abspath(a) for a in sys.argv[1:4]]
BLENDER = sys.argv[4]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QImage
import reference_cases as R
from render_studio import look_model as M, params as P

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

panel = R.panel()
Path(OUT).mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp())

def render(name, **changes):
    model = dict(P.defaults(), **{k.replace("__", "."): v for k, v in changes.items()})
    job, script, data = R.job_of(panel, M.to_v1(model), work / name)
    raw = json.loads(job.read_text(encoding="utf-8"))
    raw.pop("serve", None)
    raw["output"] = str(Path(OUT) / f"{name}.png")
    job.write_text(json.dumps(raw), encoding="utf-8")
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)], capture_output=True, text=True, timeout=900)
    img = QImage(raw["output"])
    if img.isNull() or "Traceback" in r.stdout + r.stderr or "style failed" in r.stdout:
        print((r.stdout + r.stderr)[-2500:])
    return img, data.get("studio", {}).get("style") or {}

def share(img, test):
    n = hit = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y); n += 1; hit += bool(test(c.red(), c.green(), c.blue()))
    return hit / max(1, n)

bluish = lambda r, g, b: b > r + 35 and b > g + 10
orange = lambda r, g, b: r > g + 20 and r > b + 35          # the brown-orange walls
paperish = lambda r, g, b: r > 238 and g > 236 and b > 228

real, _ = render("real")
ok(not real.isNull() and share(real, orange) > 0.05, f"to compare: the real materials, orange walls ({share(real, orange):.1%})")
img, st = render("blue_keeps_glass", surface__kind="mono", surface__colour=[0.05, 0.12, 0.6], surface__keep_glass=True)
ok(not img.isNull() and st.get("parts") and share(img, bluish) > 0.05 and share(img, orange) < 0.005, f"one colour that keeps the glass: blue, no orange ({share(img, bluish):.1%})")
img, st = render("water_white", surface__kind="mono", finish__kind="watercolour")
ok(not img.isNull() and st.get("parts") and share(img, orange) < 0.005 and img != real, f"a watercolour of the white model (orange {share(img, orange):.2%})")
img, st = render("water_on_paper", surface__kind="real", finish__kind="watercolour", background__paper_sky=True, ground__on=False)
warm = share(img, lambda r, g, b: r > g + 8 and r > b + 14)          # (the washes are pale)
ok(not img.isNull() and share(img, paperish) > 0.2 and warm > 0.01, f"a watercolour with its own colours, on paper (paper {share(img, paperish):.0%}, warm walls {warm:.1%})")
img, st = render("paper_only", surface__kind="paper", background__paper_sky=True, outline__on=True, shadows__draw="lines")
ok(not img.isNull() and share(img, paperish) > 0.85, f"no surface: paper, with the shadows' hatching ({share(img, paperish):.0%})")
img, st = render("material_no_glass", surface__kind="mono", surface__material="Fusta", surface__keep_glass=False)
ok(not img.isNull() and st.get("mode") == "model" and "parts" not in st, "one material over everything: still said as before")
img, _ = render("hatch_no_ground", surface__kind="paper", background__paper_sky=True, ground__on=False, outline__on=True, shadows__draw="lines")
corner = [img.pixelColor(x, y) for x in range(2, 120) for y in range(2, 60)]
ok(not img.isNull() and max(c.lightness() for c in corner) - min(c.lightness() for c in corner) <= 2,
   "with no ground the shadows' hatching stays on the shadows: the paper's corner is clean")
ok(share(img, paperish) > 0.85 and share(img, lambda r, g, b: r < 200) > 0.002, "…and there is hatching where the shadows fall")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
