"""Renders the thumbnails of the presets that come with Render Studio (render_studio/preset_thumbs/), on the small reference
scene, through the real panel and a real Blender. Run it again when a built-in preset changes.
argv: <ingetrazo-src> <render-studio repo> <blender.exe>"""
import json, os, subprocess, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
BLENDER = sys.argv[3]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
os.environ["RENDER_STUDIO_HOME"] = tempfile.mkdtemp()
from pathlib import Path
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
import reference_cases as R
from render_studio import preset_files as F, preset_gallery as G, outlines, settings_store

panel = R.panel()
panel.app.viewport.camera.distance = 13.0              # closer: the thumbnail is small

# The faces in view must be the lit ones: a northern place (the sun in the south) and a late April afternoon, for a long shadow;
# the camera on the corner, so that three faces show: one wall full in the light, the other raked by it, and the roof.
from types import SimpleNamespace
import math
from render_studio import sun_site
panel.app.scene.georef = SimpleNamespace(lat=40.0, lon=0.0, alt=0.0, north=0.0)
shadows = panel.app.scene.shadows
shadows.month, shadows.day, shadows.hour, shadows.minute, shadows.utc_offset = 4, 15, 16, 35, 0
sun = sun_site.info(sun_site.site(panel.app.scene))
azimuth = math.radians(sun["azimuth"])                  # clockwise from north (+Y)
panel.app.viewport.camera.yaw = math.radians(-135)       # on the corner: two walls and the roof, both walls in the sun
panel.app.viewport.camera.pitch = math.radians(30)
# the small block in front, where it is seen and its shadow with it
from PySide6.QtGui import QVector3D
block = next(g for g in panel.app.scene.groups if g.name == "block")
for vertex in list(block.mesh.vertices):
    block.mesh.move_vertex(vertex, QVector3D(-1.9, -2.9, 0.0))
panel.app.scene.version += 1
panel.app.viewport.camera.target = QVector3D(2.9, 1.1, 1.2)
print(f"sun: {sun['elevation']:.0f} degrees high, from {sun['azimuth']:.0f}; camera yaw {math.degrees(panel.app.viewport.camera.yaw):.0f}")
out_dir = Path(REPO) / "render_studio" / "preset_thumbs"
out_dir.mkdir(exist_ok=True)
work = Path(tempfile.mkdtemp())
W, H = G.THUMB
for key, name, settings in F.builtins():
    panel.apply_settings({"look": "clear"})
    panel.apply_preset(settings)
    job, script = panel.live_job(work / key, W * 2, H * 2)
    data = json.loads(job.read_text(encoding="utf-8"))
    data.pop("serve", None)
    data["output"] = str(work / f"{key}.png")
    # the outlines are the app's own: a layer drawn here, as for a render (thicker, as the thumbnail is small)
    style = settings_store.style(panel.style_settings())
    if outlines.wanted(style) and data["studio"].get("style") is not None:
        thick = dict(style, width=(float(style.get("width") or 0.0) or 1.5) * 1.6)
        layer = outlines.write_layer(panel.app.viewport, panel.app.viewport.camera, W * 2, H * 2, thick, work / f"{key}_lines.png",
                                     geom=outlines.scene_geometry(panel.app.scene))
        if layer:
            data["studio"]["style"]["lines"] = str(layer)
    job.write_text(json.dumps(data), encoding="utf-8")
    subprocess.run([BLENDER, "-b", "--factory-startup", "--python", str(script), "--", str(job)], capture_output=True, text=True, timeout=900)
    image = QImage(data["output"])
    if image.isNull():
        print("NOT rendered", key)
        continue
    (out_dir / f"{key}.png").write_bytes(G.thumbnail_of(image))
    print("made", key, flush=True)
