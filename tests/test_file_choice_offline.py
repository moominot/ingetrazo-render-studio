"""«Choose a file…» asks once: for the 360° background, the fixed picture and the texture, from their page and from Expert,
whether a file is picked or the dialog is closed. (Putting the picked file in the list used to ask a second time.)
argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["RENDER_STUDIO_HOME"] = tempfile.mkdtemp()
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QFileDialog
qa = QApplication.instance() or QApplication([])
import reference_cases as R

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

folder = Path(tempfile.mkdtemp())
def picture(name):
    path = folder / name
    img = QImage(32, 32, QImage.Format_RGB32); img.fill(QColor("#888888")); img.save(str(path))
    return str(path)

asked, answer = [], [""]
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (asked.append(a[1]) or answer[0], ""))
panel = R.panel()
panel.apply_settings({"look": "clear"})
texture = panel.fine.control("finish.texture")
texture.setCurrentIndex(texture.findData("image")); qa.processEvents()

def choose(combo, mirror=False):
    """What a person does: opens the list and picks its last line."""
    i = combo.count() - 1
    combo.setCurrentIndex(i)
    combo.activated.emit(i)
    qa.processEvents()

boxes = {"360° background": (panel.hdri, panel.hdri.currentData),
         "fixed picture": (panel.backdrop, panel.backdrop.currentData),
         "texture": (panel.fine.control("finish.texture_path"), panel.fine.control("finish.texture_path").path)}
for n, (name, (combo, value)) in enumerate(boxes.items()):
    for turn in range(2):                              # a first file, then another with one already chosen
        answer[0] = picture(f"{n}_{turn}.png"); asked.clear()
        choose(combo)
        ok(len(asked) == 1 and Path(value() or ".").name == f"{n}_{turn}.png", f"{name}: asked once, the file is chosen ({len(asked)})")
    answer[0] = ""; asked.clear()
    before = value()
    choose(combo)
    ok(len(asked) == 1 and value() == before, f"{name}: closed without a file: asked once, nothing changes ({len(asked)})")

# the same from the Expert page
for key in ("pano.path", "picture.path", "finish.texture_path"):
    row = panel.expert.rows[key]
    row.mirror.pull()
    answer[0] = picture(f"expert_{key}.png"); asked.clear()
    mirror = row.mirror.widget
    i = mirror.count() - 1
    mirror.setCurrentIndex(i); mirror.activated.emit(i); qa.processEvents()
    real = panel.expert.controls[key]
    ok(len(asked) == 1 and Path(real.currentData() or ".").name == f"expert_{key}.png", f"Expert, {key}: asked once ({len(asked)})")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
