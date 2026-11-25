"""A preset saved with the preview closed gets its thumbnail from a small render made on the side, in a REAL Blender.
argv: <ingetrazo-src> <render-studio repo> <blender.exe>"""
import os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["RENDER_STUDIO_HOME"] = tempfile.mkdtemp()
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
BLENDER = sys.argv[3]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QImage
import reference_cases as R
from core import render_blender as rb
from render_studio import preset_gallery as G

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

panel = R.panel()
panel.blender = lambda: rb.BlenderFound([BLENDER], BLENDER)
path = panel.gallery.keep("From a render")
ok(path is not None and panel.gallery.folder.load(path)[2] is None, "saved at once, still without a picture")
until = time.time() + 400
while time.time() < until and panel.gallery._jobs:
    qa.processEvents(); time.sleep(0.2)
thumb = panel.gallery.folder.load(path)[2]
image = QImage()
if thumb:
    image.loadFromData(thumb)
ok((image.width(), image.height()) == G.THUMB, f"…and the render puts its picture in it ({image.width()}×{image.height()})")
ok(len({image.pixelColor(x, y).rgb() for x in range(0, image.width(), 16) for y in range(0, image.height(), 16)}) > 5, "…a picture of the model, not a blank")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
