"""The panel's groups: folded when a drawing opens (the presets open), one at a time as an accordion, and the
Expert page's search fixed above its groups. Offscreen, no Blender. argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["RENDER_STUDIO_HOME"] = tempfile.mkdtemp()
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
QCoreApplication.setOrganizationName("rs-test")
QCoreApplication.setApplicationName(f"panel-groups-{os.getpid()}")
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
import reference_cases as R
from render_studio import widgets

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

QSettings().setValue("render_studio/tab", 2)         # the panel was left on another page
panel = R.panel()
ok(panel.tabs.currentIndex() == 0, "a drawing just opened: the Main page is in view, whatever was left")
cards = panel._page_cards()
open_ones = lambda: [c.title() for c in cards if c.is_open()]
ok(len(cards) > 10 and open_ones() == [panel.gallery.title()], f"a drawing just opened: every group folded but the presets ({open_ones()})")
ok(panel.expert.config in cards and not panel.expert.config.is_open(), "…the panel's configuration group too")

ok(panel.expert.accordion.isChecked(), "the accordion is on by default")
main = [c for c in panel.tabs.widget(0).findChildren(widgets.Card)]
others = [c for c in main if c is not panel.gallery]
others[0].set_open(True)
ok(others[0].is_open() and not panel.gallery.is_open(), "accordion: opening a group folds the others of its page")
elsewhere = panel.tabs.widget(2).findChildren(widgets.Card)[0]
elsewhere.set_open(True)
ok(others[0].is_open() and elsewhere.is_open(), "…not those of another page")
panel.expert.accordion.setChecked(False)
others[1].set_open(True)
ok(others[0].is_open() and others[1].is_open(), "off: each group on its own")
ok(str(QSettings().value("render_studio/accordion")) == "false", "…and it is remembered")

# the same drawing, changed: nothing folds
panel.tabs.setCurrentIndex(2)
panel.document_changed()
ok(panel.tabs.currentIndex() == 2, "…and the page in view stays")
ok(others[0].is_open() and others[1].is_open(), "a change of the drawing folds nothing")

# the same drawing saved under a name: it has things to undo, it was not just opened
class History:
    undo_stack = ["a step"]
panel.app.viewport = type("V", (), {"history": History(), "scene": panel.app.scene})() if panel.app.viewport is None else panel.app.viewport
viewport = panel.app.viewport
had = getattr(viewport, "history", None)
viewport.history = History()
panel.doc_path = lambda: "C:/work/house.igz"
panel.document_changed()
ok(others[0].is_open() and others[1].is_open(), "saved under a name: nothing folds")

ok(panel.tabs.currentIndex() == 2, "…saved under a name too")

# another drawing opened (nothing to undo yet)
viewport.history = type("H", (), {"undo_stack": []})()
panel.doc_path = lambda: "C:/work/other.igz"
panel.document_changed()
ok(open_ones() == [panel.gallery.title()], f"another drawing opened: folded again ({open_ones()})")
ok(panel.tabs.currentIndex() == 0, "…at the Main page")
others[0].set_open(True)
panel.tabs.setCurrentIndex(1)
panel.doc_path = lambda: "C:/work/house.igz"
panel.document_changed()
ok(panel.tabs.currentIndex() == 1, "back to a drawing already seen: the page in view stays")
ok(others[0].is_open(), "back to a drawing already seen: nothing folds")

e = panel.expert
ok(e.search.parentWidget() is panel.expert_page and not panel.expert_scroll.isAncestorOf(e.search),
   "the Expert page's search is above the scrolling part")
ok(panel.expert_scroll.isAncestorOf(e.config) and e.config.isAncestorOf(e.layout_box) and e.config.isAncestorOf(e.accordion),
   "the panel's configuration (the saved configurations and the accordion) is a group that scrolls with the others")
ok(e.layout_box.itemText(0).startswith("Default configuration"), "…and speaks of configuration, not layout")
print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
