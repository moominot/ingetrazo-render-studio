"""Offline (IngeTrazo's source, offscreen Qt): write a studio job with the
panel's own function, render it with Blender, show it in the image window,
adjust and save. argv: <ingetrazo-src> <render-studio repo> <skp_dc_import repo> <skp> <out dir> [preset]"""
import json, math, os, subprocess, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO, DCREPO, SKP, OUT = [os.path.abspath(a) for a in sys.argv[1:6]]
preset = sys.argv[6] if len(sys.argv) > 6 else "golden_hour"
sys.path[:0] = [SRC, REPO, DCREPO]
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from PySide6.QtGui import QVector3D
from pathlib import Path
from core.scene import Scene
from core.camera import OrbitCamera
from skp_dc_import import builder, reader
from render_studio import panel as P, post
scene = Scene(); builder.build(scene, reader.parse(SKP), SKP)
lo, hi = scene.bounds(); c = (lo + hi) * 0.5
size = max(hi.x() - lo.x(), hi.y() - lo.y(), hi.z() - lo.z())
cam = OrbitCamera(); cam.target = QVector3D(c.x(), c.y(), c.z() * 0.8); cam.distance = size
cam.yaw = math.radians(-35); cam.pitch = math.radians(4)
work = Path(OUT) / f"job_{preset}"
job, script = P.write_studio_job(scene, cam, work, preset, {"exposure_bias": 0.0, "sun_scale": 1.0},
                                 engine="eevee", quality=1, width=960, height=540)
data = json.loads(job.read_text(encoding="utf-8"))
print("job studio keys:", sorted(data["studio"])[:6], "... ambience", data["ambience"])
B = r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe"
t0 = time.time()
r = subprocess.run([B, "-b", "--factory-startup", "--python", str(script), "--", str(job)], capture_output=True, text=True, errors="replace")
print("blender rc", r.returncode, f"{time.time()-t0:.1f}s", [l for l in r.stdout.splitlines() if "meter" in l or "done" in l][-2:])
w = P.ImageWindow(); w.set_image(Path(data["output"]))
adj = {"exposure": 0.4, "contrast": 1.15, "saturation": 1.2, "warmth": 0.3, "vignette": 0.3}
for k, v in adj.items():
    s = w.adj[k]; lo_, hi_ = float(s.property("lo")), float(s.property("hi"))
    s.setValue(int(round((v - lo_) / (hi_ - lo_) * s.maximum())))
print("window adjustments", {k: round(v, 2) for k, v in w.adjustments().items()})
print("saved adjusted:", w.save_to(str(Path(OUT) / f"{preset}_adjusted.png")))
w.resize(1000, 700); w.show(); app.processEvents(); w.grab().save(str(Path(OUT) / "window.png"))
