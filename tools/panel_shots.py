"""Grabs pages of the panel (offscreen, nothing shown). argv: <ingetrazo-src> <repo> <out.png> <python file>
The file defines shots(panel, grab) and calls grab() for each picture."""
import os, runpy, sys, tempfile
os.environ["RENDER_STUDIO_HOME"] = tempfile.mkdtemp()
SRC, REPO, OUT, SCRIPT = [os.path.abspath(a) for a in sys.argv[1:5]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
qa = QApplication([])
qa.setStyle("Fusion")
from render_studio import i18n, icons
i18n.language = lambda: "ca"
icons._ink = lambda: QColor("#2b3038")
import reference_cases as R
panel = R.panel()
panel.expert_mode.setChecked(False)
panel.expert.load_layout("")
i18n.translate_tree(panel)
panel.setAttribute(Qt.WA_DontShowOnScreen, True)
panel.need_box.setVisible(False)
panel.resize(320, 900)
panel.show()
shots = []


def grab():
    for _ in range(10):
        qa.processEvents()
    shots.append(panel.grab())


runpy.run_path(SCRIPT)["shots"](panel, grab)
sheet = QPixmap(sum(s.width() for s in shots) + 10 * (len(shots) - 1), max(s.height() for s in shots))
sheet.fill(Qt.darkGray)
p = QPainter(sheet)
x = 0
for s in shots:
    p.drawPixmap(x, 0, s)
    x += s.width() + 10
p.end()
sheet.save(OUT)
