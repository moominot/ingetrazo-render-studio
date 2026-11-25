"""The toolbar: its commands in order in a real main window, and the Library button with and without the Library extension.
argv: <ingetrazo-src> <render-studio repo>"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow, QToolBar, QWidget
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

class Window(QMainWindow):
    def _on_manage_extensions(self):
        asked.append("manager")

win = Window(); panel.app.window = win
shown = []
panel.app.show_panel = shown.append
bar = c.build(panel.app)
names = ["|" if a.isSeparator() else a.text() for a in bar.actions()]
ok(names == ["Open preview", "Sync changes", "Update preview", "Sync camera", "|", "Materials", "Lights", "Library"], f"the toolbar, in order ({names})")
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

# the Library: not installed, then installed
answers = []
T.ask_install = lambda p, can: (answers.append(can), True)[1]
c.library.trigger()
ok(answers == [True] and asked == ["manager"] and not shown, "without the Library: it says so and opens the extension manager when asked")
T.ask_install = lambda p, can: False
c.library.trigger()
ok(asked == ["manager"], "…and not when the person closes the message")
AssetPanel = type("AssetPanel", (QWidget,), {"__module__": "asset_manager.panel"})
dock = QDockWidget(win); dock.setWidget(AssetPanel())
c.library.trigger()
ok(shown == [dock] and asked == ["manager"], "with the Library: its tab is shown")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
