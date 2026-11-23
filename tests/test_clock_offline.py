"""The render's stopwatch: a clock icon drawn like the extension's others and the elapsed time, beside the progress, no emoji.
Offscreen, no Blender. argv: <ingetrazo-src> <render-studio repo> [<icon.png>]"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtCore import QCoreApplication, QSettings
QSettings.setDefaultFormat(QSettings.IniFormat); QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
QCoreApplication.setOrganizationName("rs-test"); QCoreApplication.setApplicationName("rs-test")
from render_studio import icons, panel as P, preview, widgets

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

ic = icons.icon("clock")
pm = ic.pixmap(48, 48)
img = pm.toImage()
ink = sum(1 for y in range(48) for x in range(48) if img.pixelColor(x, y).alpha() > 40)
ok(not ic.isNull() and 150 < ink < 1200, f"the clock icon is drawn like the others ({ink} pixels of ink in 48×48)")
if len(sys.argv) > 3:
    big = ic.pixmap(192, 192); big.save(sys.argv[3])
c = widgets.ClockLabel()
ok(not c.isVisibleTo(None) and c.isHidden(), "no render: no clock")
c.set_text("1:05")
ok(not c.isHidden() and c.time_label.text() == "1:05" and not c.icon_label.pixmap().isNull(), "the time and the icon show")
c.set_text(None)
ok(c.isHidden(), "…and it hides again")
ok(P.StudioPanel._fmt_elapsed(65) == "1:05" and P.StudioPanel._fmt_elapsed(3725) == "1:02:05" and P.StudioPanel._fmt_elapsed(-3) == "0:00", "elapsed time reads m:ss, h:mm:ss")
win = preview.ImageWindow(panel=None)
win.set_clock("0:42")
ok(win.clock.time_label.text() == "0:42" and not win.clock.isHidden(), "the render window shows it beside the progress")
win.set_clock(None)
ok(win.clock.isHidden(), "…and hides it")
src = open(os.path.join(REPO, "render_studio", "panel.py"), encoding="utf-8").read()
ok("\u23f1" not in src and "\u23f1" not in open(os.path.join(REPO, "render_studio", "preview.py"), encoding="utf-8").read(), "no emoji in the code")
print("FAILED: %s" % fails if fails else "ALL PASS")
sys.exit(1 if fails else 0)
