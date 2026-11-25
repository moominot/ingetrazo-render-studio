"""The wheel over a field that has not been picked scrolls the page and changes nothing: the panel's pages, the Expert page's
copies, the preview window and the fields made later. A picked field answers the wheel as always.
argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["RENDER_STUDIO_HOME"] = tempfile.mkdtemp()
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QComboBox, QFormLayout, QSlider, QSpinBox, QWidget
qa = QApplication.instance() or QApplication([])
import reference_cases as R
from render_studio import wheel_guard

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

def pump():
    for _ in range(8):
        qa.processEvents()

panel = R.panel()
panel.setAttribute(Qt.WA_DontShowOnScreen, True); panel.need_box.setVisible(False)
panel.set_expert_mode(True)
panel.resize(320, 420); panel.show(); panel.activateWindow(); pump()

def wheel(widget, notches=-1):
    at = QPointF(widget.width() / 2, widget.height() / 2)
    ev = QWheelEvent(at, widget.mapToGlobal(at), QPoint(0, 0), QPoint(0, 120 * notches), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev); pump()

def value(w):
    if isinstance(w, QComboBox):
        return w.currentIndex()
    return w.value() if hasattr(w, "value") else w.text()           # (a date or a time box: what it reads)

fields = [w for w in panel.findChildren(QWidget) if isinstance(w, wheel_guard.FIELDS)]
ok(len(fields) > 60 and all(w.focusPolicy() != Qt.WheelFocus for w in fields), f"no field of the panel takes the focus from the wheel ({len(fields)})")
changed = []
for w in fields:
    if not w.isEnabled() or w.hasFocus():
        continue
    before = value(w); wheel(w, -1); wheel(w, 1); wheel(w, -3)
    if value(w) != before:
        changed.append((type(w).__name__, w.objectName(), before, value(w)))
ok(not changed, f"the wheel over a field nobody picked changes nothing ({changed[:3]})")

# it is handed on, not swallowed: left «not accepted», which is what makes Qt give it to the page behind. (A wheel sent by a
# test is not carried up by Qt, not even from a label; a person's is.)
def sent(widget):
    at = QPointF(5, 5)
    ev = QWheelEvent(at, widget.mapToGlobal(at), QPoint(0, 0), QPoint(0, -360), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    guard = wheel_guard._guard
    return guard.eventFilter(widget, ev), ev.isAccepted()
panel.tabs.setCurrentIndex(2); pump()
for name, widget in (("a drop-down", panel.bg_mode), ("a slider", panel.sliders["clouds"])):
    ok(sent(widget) == (True, False), f"over {name} nobody picked the wheel is handed on ({sent(widget)})")
bar = panel.tabs.currentWidget().verticalScrollBar()
ok(sent(bar)[0] is False and not isinstance(bar, wheel_guard.FIELDS), "a scroll bar keeps its wheel")

# a field that was picked answers it, one made later included
spin = QSpinBox(); spin.setRange(0, 100); spin.setValue(50)
panel.tabs.widget(2).widget().layout().insertWidget(0, spin); pump()
ok(spin.focusPolicy() == Qt.StrongFocus, "a field added later is guarded too")
wheel(spin, 1)
ok(spin.value() == 50, f"…and does not change while not picked ({spin.value()})")
spin.hasFocus = lambda: True              # (a window off the screen cannot hold the focus: say it has it)
wheel(spin, 1)
ok(spin.value() == 51, f"picked, it answers the wheel ({spin.value()})")

# the Expert page's copies
panel.tabs.setCurrentIndex(panel.tabs.count() - 1); pump()
row = panel.expert.rows["surface.kind"]
mirror = row.mirror.widget
before = mirror.currentIndex(); wheel(mirror, -2)
ok(mirror.currentIndex() == before, "the copies in Expert are guarded")

# the preview window
from render_studio.preview import ImageWindow
window = ImageWindow(panel=panel)
loose = [w for w in window.findChildren(QWidget) if isinstance(w, wheel_guard.FIELDS) and w.focusPolicy() == Qt.WheelFocus]
ok(not loose, f"the preview window's fields are guarded ({[type(w).__name__ for w in loose][:3]})")
ok(not [w for w in panel.lights_window.findChildren(QWidget) if isinstance(w, wheel_guard.FIELDS) and w.focusPolicy() == Qt.WheelFocus],
   "…and the lights window's")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
