"""The toolbar: its commands in order in a real main window, and the Library button with and without the Library extension.
argv: <ingetrazo-src> <render-studio repo>"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from PySide6.QtWidgets import QApplication, QDockWidget, QLineEdit, QMainWindow, QTabWidget, QToolBar, QWidget
qa = QApplication.instance() or QApplication([])
import reference_cases as R
from render_studio import toolbar as T

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

panel = R.panel()
c = panel.commands
ok(c.build(panel.app) is None, "with no window there is no toolbar, and nothing breaks")
asked = []

class Manager(QWidget):
    """As IngeTrazo's: pages with their search boxes, built when the dialog is."""
    def __init__(self):
        super().__init__()
        self._tabs = QTabWidget(self)
        for name in ("browse", "installed"):
            self._tabs.addTab(QWidget(), name)
        self._tabs.setCurrentIndex(1)
        self._pages = {"browse": {"search": QLineEdit(self)}}

class Window(QMainWindow):
    _extension_manager_dialog = None
    def _on_manage_extensions(self):
        asked.append("manager")
        self._extension_manager_dialog = Manager()
        for _ in range(20):                       # the dialog's own event loop
            qa.processEvents()

win = Window(); panel.app.window = win
shown = []
panel.app.show_panel = shown.append
bar = c.build(panel.app)
names = ["|" if a.isSeparator() else a.text() for a in bar.actions()]
ok(names == ["Render Studio", "Open preview", "Sync changes", "Update preview", "Sync camera", "|", "Materials", "Lights", "Library"], f"the toolbar, in order ({names})")
ok(bar.objectName() == "render_studio_toolbar" and bar in win.findChildren(QToolBar), "it is in the window, under a stable name")
ok(all(not a.icon().isNull() and a.toolTip() for a in bar.actions() if not a.isSeparator()), "every button has an icon and says what it does")
pix = [a.icon().pixmap(32, 32).toImage() for a in bar.actions() if not a.isSeparator()]
ok(all(any(img.pixelColor(x, y).alpha() > 0 for x in range(32) for y in range(32)) for img in pix), "…and every icon draws something")

# the switches are remembered and told to the panel
told = []
panel._follow_toggled = lambda k, on: told.append((k, on))
c.follow_camera.setChecked(False); c.follow_camera.setChecked(True)
ok(told == [("live_follow_camera", False), ("live_follow_camera", True)], "Sync camera tells the panel")
c.need_blender(False)
ok(not c.preview.isEnabled() and not c.update.isEnabled() and c.materials.isEnabled() and c.library.isEnabled(), "without Blender only what needs it is greyed")
opened = []
panel.open_preview = lambda: opened.append("preview"); panel.open_materials = lambda: opened.append("materials"); panel.open_lights = lambda: opened.append("lights")
c.need_blender(True); c.preview.trigger(); c.materials.trigger(); c.lights.trigger()
ok(opened == ["preview", "materials", "lights"], f"each button does its job ({opened})")

# the panel's own button
home = QDockWidget(win); home.setWidget(panel)
c.studio.trigger()
ok(shown == [home], "the first button shows the Render Studio panel's tab")
shown.clear()
c.need_blender(False)
ok(c.studio.isEnabled(), "…also without Blender")
c.need_blender(True)

# the Library: not installed, then installed
answers = []
T.ask_install = lambda p, can: (answers.append(can), True)[1]
c.library.trigger()
ok(answers == [True] and asked == ["manager"] and not shown, "without the Library: it says so and opens the extension manager when asked")
manager = win._extension_manager_dialog
ok(manager._pages["browse"]["search"].text() == "asset_manager" and manager._tabs.currentIndex() == 0,
   "…already searching for the Library, on the Browse page")
T.ask_install = lambda p, can: False
c.library.trigger()
ok(asked == ["manager"], "…and not when the person closes the message")
AssetPanel = type("AssetPanel", (QWidget,), {"__module__": "asset_manager.panel"})
dock = QDockWidget(win); dock.setWidget(AssetPanel())
c.library.trigger()
ok(shown == [dock] and asked == ["manager"], "with the Library: its tab is shown")
# torn off the window, it keeps the size of its buttons
from PySide6.QtCore import Qt
win2 = QMainWindow(); panel.app.window = win2
try:                                              # IngeTrazo's own title strip on a floating bar, where this version has it
    from views.floating_toolbar import watch_toolbars
    watch_toolbars(win2)
except ImportError:
    pass
def pump():
    for _ in range(20):
        qa.processEvents()
c.follow_changes.setChecked(True)
win2.resize(900, 600); win2.show()
bar2 = c.build(panel.app); pump()
bar2.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint); bar2.move(100, 100); bar2.show(); pump()
def cut():
    return [a.text() for a in bar2.actions() if a.isVisible() and not a.isSeparator()
            and not (bar2.widgetForAction(a).isVisible() and bar2.rect().contains(bar2.widgetForAction(a).geometry()))]
ok(bar2.isFloating() and not cut(), f"floating, every button is whole ({cut()})")
narrow = bar2.width()
c.follow_changes.setChecked(False); pump()
ok(not cut() and bar2.width() > narrow, f"…also when «Update preview» appears: the bar widens ({cut()})")
c.follow_changes.setChecked(True); pump()
ok(not cut() and bar2.width() == narrow, "…and narrows again when it goes")
bar2.resize(narrow - 60, bar2.height()); pump()
ok(not cut() and bar2.width() == narrow, f"a size too small, as an old saved layout may give, is put right ({cut()})")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
