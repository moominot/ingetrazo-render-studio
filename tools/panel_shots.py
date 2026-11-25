"""Grabs pages of the panel (offscreen, nothing shown). argv: <ingetrazo-src> <repo> <out.png> <python file>
The file defines shots(panel, grab) and calls grab() for each picture."""
import os, runpy, sys, tempfile
from pathlib import Path
os.environ["RENDER_STUDIO_HOME"] = tempfile.mkdtemp()
SRC, REPO, OUT, SCRIPT = [os.path.abspath(a) for a in sys.argv[1:5]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
qa = QApplication([])
qa.setStyle("Fusion")


def load_fonts() -> None:
    """With the «offscreen» platform Qt may find no font, and every letter is drawn as a box: take one from the system."""
    from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
    if QGuiApplication.platformName() != "offscreen":
        return
    wanted = (("segoeui.ttf", "segoeuib.ttf"), ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
              ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"))
    folders = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path("/System/Library/Fonts")]
    for names in wanted:
        found = [hit for name in names for folder in folders if folder.is_dir() for hit in list(folder.rglob(name))[:1]]
        families = [f for hit in found for f in QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(hit)))]
        if families:
            font = QFont(families[0])
            font.setPointSizeF(9.0)
            qa.setFont(font)
            return
    print("no font found: the letters will be boxes (install fonts-dejavu-core)")


load_fonts()
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
