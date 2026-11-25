"""The render jobs of the reference cases stay as recorded (tests/reference/jobs.json). What goes to Blender is the whole of what
makes a picture, so an identical job is an identical render.
argv: <ingetrazo-src> <render-studio repo> [record | images <blender.exe> <out dir>]
«record» writes the reference again (only when a change of the pictures is meant); «images» also renders each case."""
import json, os, subprocess, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
MODE = sys.argv[3] if len(sys.argv) > 3 else "check"
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
import reference_cases as R

REFERENCE = Path(REPO) / "tests" / "reference" / "jobs.json"
panel = R.panel()
work = Path(tempfile.mkdtemp())
got = {}
for name, settings in R.CASES.items():
    job, script, got[name] = R.job_of(panel, settings, work / name)
    if MODE == "images":
        out = Path(sys.argv[5]); out.mkdir(parents=True, exist_ok=True)
        data = json.loads(job.read_text(encoding="utf-8"))
        data.pop("serve", None)
        data["output"] = str(out / f"{name}.png")
        job.write_text(json.dumps(data), encoding="utf-8")
        r = subprocess.run([sys.argv[4], "-b", "--factory-startup", "--python", str(script), "--", str(job)],
                           capture_output=True, text=True, timeout=900)
        print(("rendered " if (out / f"{name}.png").is_file() else "NOT rendered ") + name, flush=True)
        if not (out / f"{name}.png").is_file():
            print((r.stdout + r.stderr)[-2500:])

if MODE == "record":
    REFERENCE.parent.mkdir(exist_ok=True)
    REFERENCE.write_text(json.dumps(got, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"recorded {len(got)} cases")
    sys.exit(0)

want = json.loads(REFERENCE.read_text(encoding="utf-8"))
fails = 0
for name in R.CASES:
    same = json.loads(json.dumps(got[name], sort_keys=True)) == want.get(name)
    print(("PASS " if same else "FAIL ") + name)
    if not same:
        fails += 1
        a, b = want.get(name) or {}, got[name]
        for section in sorted(set(a) | set(b)):
            if a.get(section) != b.get(section):
                x, y = a.get(section), b.get(section)
                if isinstance(x, dict) and isinstance(y, dict):
                    for k in sorted(set(x) | set(y)):
                        if x.get(k) != y.get(k):
                            print(f"    {section}.{k}: {x.get(k)!r} -> {y.get(k)!r}"[:200])
                else:
                    print(f"    {section}: {x!r} -> {y!r}"[:200])
print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
