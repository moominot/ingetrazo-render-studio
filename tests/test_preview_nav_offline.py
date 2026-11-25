"""The preview window as a place to work in, offscreen with the stand-in Blender: the mouse moves the camera (the 3D view's,
or the one the preview keeps), the picture on screen is saved and copied, High follows the window's size, and «Automatic»
takes Cycles when there is a graphics card.
argv: <ingetrazo-src> <render-studio repo> [screenshot.png]"""
import json, os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
SHOT = sys.argv[3] if len(sys.argv) > 3 else None
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QImage, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
qa.setOrganizationName("RenderStudioTest"); qa.setApplicationName("previewnav")
from core.camera import OrbitCamera
from core.scene import Scene
from render_studio import engine_probe, panel as P
from render_studio.live import LiveSession

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

def wait(cond, secs=15):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        qa.processEvents(QEventLoop.AllEvents, 50)
        if cond(): return True
        time.sleep(0.01)
    return False

log = os.path.join(tempfile.mkdtemp(), "blender.log")
os.environ["FAKE_BLENDER_LOG"] = log
lines = lambda: open(log).read().splitlines() if os.path.exists(log) else []
renders = lambda: [l for l in lines() if l.startswith("render")]

class VP:
    def __init__(self): self.camera = OrbitCamera(); self.updates = 0; self.camera.set_aspect(1600, 900)
    def width(self): return 1600
    def height(self): return 900
    def update(self): self.updates += 1
class App:
    api_version = 2
    def __init__(self): self.scene = Scene(); self.viewport = VP(); self.data = {}
    def document_data(self, d=None): return json.loads(json.dumps(self.data)) if self.data else d
    def set_document_data(self, v): self.data = json.loads(json.dumps(v))
    def on_document_changed(self, fn): pass

app = App()
panel = P.StudioPanel(app)
panel.blender = lambda: object()
fake = os.path.join(REPO, "tests", "fake_blender.py")
live = LiveSession(panel, argv_factory=lambda job, script: [sys.executable, fake, str(job)], poll_ms=20, rest_ms=60)
panel._live = live
live.image.connect(panel._live_image); live.state.connect(panel._set_status)
win = panel.open_preview()
win.resize(1200, 760)
ok(wait(lambda: any("samples=8" in l for l in renders())), "the live view is up")
view = win.view
ok(view.navigating(), "while the live view shows, the mouse moves the camera")

def send(kind, pos, button=Qt.LeftButton, buttons=Qt.LeftButton, mods=Qt.NoModifier):
    ev = QMouseEvent(kind, QPointF(pos), QPointF(view.viewport().mapToGlobal(pos)), button, buttons, mods)
    {QEvent.MouseButtonPress: view.mousePressEvent, QEvent.MouseMove: view.mouseMoveEvent,
     QEvent.MouseButtonRelease: view.mouseReleaseEvent}[kind](ev)

def drag(button=Qt.LeftButton, mods=Qt.NoModifier, by=(60, 30)):
    a = view.viewport().rect().center()
    b = a + QPoint(*by)
    send(QEvent.MouseButtonPress, a, button, button, mods)
    send(QEvent.MouseMove, b, Qt.NoButton, button, mods)
    send(QEvent.MouseButtonRelease, b, button, Qt.NoButton, mods)

def wheel(notches=1, mods=Qt.NoModifier):
    at = view.viewport().rect().center()
    view.wheelEvent(QWheelEvent(QPointF(at), QPointF(view.viewport().mapToGlobal(at)), QPoint(), QPoint(0, 120 * notches),
                                Qt.NoButton, mods, Qt.NoScrollPhase, False))

pose = lambda c: (round(c.yaw, 5), round(c.pitch, 5), round(c.distance, 5), tuple(round(v, 5) for v in (c.target.x(), c.target.y(), c.target.z())))
cam = app.viewport.camera
p0, n0, u0 = pose(cam), len(renders()), app.viewport.updates
drag()
ok(pose(cam)[:2] != p0[:2] and abs(cam.distance - p0[2]) < 1e-4 and app.viewport.updates > u0, "a drag orbits the 3D view's camera, which is redrawn")
ok(wait(lambda: len(renders()) > n0), "…and the preview follows")
for button, mods, name in ((Qt.LeftButton, Qt.ShiftModifier, "Shift+drag"), (Qt.MiddleButton, Qt.ShiftModifier, "Shift+middle drag")):
    p0 = pose(cam); drag(button, mods)
    ok(pose(cam)[:2] == p0[:2] and pose(cam)[3] != p0[3], f"{name} pans")
p0 = pose(cam); drag(Qt.MiddleButton)
ok(pose(cam)[:2] != p0[:2], "the middle button orbits, as in the 3D view")
p0 = pose(cam); wheel(2)
ok(cam.distance < p0[2], "the wheel zooms in")
assert wait(lambda: not live._busy and live._done_key is not None)
_full = QImage(960, 540, QImage.Format_RGB32); _full.fill(Qt.darkGray)      # (the stand-in's frames are an eighth of the size)
from PySide6.QtGui import QPixmap
view.set_pixmap(QPixmap.fromImage(_full)); view.fit()
p0, z0 = pose(cam), view.transform().m11(); wheel(3, Qt.ControlModifier)
ok(pose(cam) == p0 and view.transform().m11() > z0, "Ctrl+wheel looks closer at the picture; the camera stays")
p0 = pose(cam); drag(mods=Qt.ControlModifier)
ok(pose(cam) == p0, "…and Ctrl+drag moves the picture, not the camera")
view.fit()

# Sync camera off: the preview's own camera moves
panel.commands.follow_camera.setChecked(False); qa.processEvents()
ok(live.frozen_camera is not None, "Sync camera off: the preview keeps a camera")
assert wait(lambda: not live._busy)
p0, k0, n0 = pose(cam), pose(live.frozen_camera), len(renders())
drag(); wheel(1)
ok(pose(cam) == p0 and pose(live.frozen_camera) != k0, "the mouse moves the kept camera; the 3D view stays where it was")
ok(app.viewport.camera is cam, "…and the 3D view's camera is its own again after picking")
ok(wait(lambda: len(renders()) > n0), "…and the preview shows the new place")
ok(panel.render_camera() is live.frozen_camera, "…which is what Render takes")
panel.commands.follow_camera.setChecked(True)

# the picture on screen, saved and copied
ok(wait(lambda: not live._busy and live._done_key is not None), "the picture is refined")
size = view.picture_size()
ok(win.snapshot_btn.isVisibleTo(win) and win.snapshot_btn.isEnabled(), "«Save this picture…» is there")
tmp = Path(tempfile.mkdtemp())
for name in ("a.png", "a.jpg"):
    img_ok = win.save_picture(str(tmp / name))
    back = QImage(str(tmp / name))
    ok(img_ok and (back.width(), back.height()) == size, f"saved as {name}, at the picture's own size {size}")
ok(win.copy_picture() and (QApplication.clipboard().image().width(), QApplication.clipboard().image().height()) == size, "…and copied")
texts = [a.text() for a in win.picture_menu().actions() if not a.isSeparator()]
ok(texts[:3] == ["Save picture…", "Copy picture", "New scene from this view…"], f"right click: {texts}")
from PySide6.QtWidgets import QFileDialog
asked = {}
def fake_dialog(parent, title, start, filters):
    asked["start"] = start
    return str(tmp / "picked"), "JPEG (*.jpg)"
real = QFileDialog.getSaveFileName
QFileDialog.getSaveFileName = fake_dialog
win.snapshot_btn.click(); qa.processEvents()
QFileDialog.getSaveFileName = real
ok((tmp / "picked.jpg").is_file() and "view-" in asked["start"] and "picked.jpg" in win.status.text(), f"the button asks for a name and saves: {win.status.text()}")

# the bar: one height, and the way back to the panel
quality = win.quality_buttons._buttons
bar = [win.panel_btn, win.help_btn, *win.sync_buttons, *quality, win.scene_btn, win.snapshot_btn, win.render_btn]
ok(all(w.isVisibleTo(win) for w in bar) and len({w.height() for w in bar}) == 1, f"the bar's controls are all {bar[0].height()} px tall")
ok(all(win.tool_bar.isAncestorOf(w) for w in bar + [win.back_btn, win.save_btn, win.fit_btn]), "…in one bar")
from PySide6.QtWidgets import QDockWidget, QMainWindow
main_window = QMainWindow(); dock = QDockWidget(); dock.setWidget(panel); main_window.addDockWidget(Qt.RightDockWidgetArea, dock)
dock.setMinimumWidth(300)
screen = qa.primaryScreen().availableGeometry()
main_window.setGeometry(screen); main_window.show(); dock.hide()
shown = []
app.show_panel = lambda d: (shown.append(d), d.show(), d.raise_())
app.window = main_window
win.setGeometry(screen.adjusted(10, 40, -10, -10)); qa.processEvents()
win.panel_btn.click(); qa.processEvents()
from PySide6.QtCore import QRect
where = QRect(panel.mapToGlobal(QPoint(0, 0)), panel.size())
ok(shown == [dock] and panel.isVisible(), "«Panel» shows Render Studio's tab, even if it was closed")
ok(win.isMinimized() or not win.frameGeometry().intersects(where), f"…and the window no longer covers it ({'minimised' if win.isMinimized() else 'beside it'})")
win.showNormal(); win.resize(1200, 760); qa.processEvents()

# the bar at the top, the messages at the bottom
top = lambda w: w.mapTo(win, QPoint(0, 0)).y()
ok(top(win.tool_bar) < top(win.view) < top(win.info_row) < top(win.status), "the bar is at the top; the data and the messages under the picture")

# the live view's switches, the toolbar's own
cam_b, changes_b, update_b = win.sync_buttons
ok(cam_b.defaultAction() is panel.commands.follow_camera and changes_b.defaultAction() is panel.commands.follow_changes
   and update_b.defaultAction() is panel.commands.update and not cam_b.icon().isNull(), "Sync camera, Sync changes and Update are in the window")
cam_b.click(); qa.processEvents()
ok(not panel.commands.follow_camera.isChecked() and not live.follow_camera and live.frozen_camera is not None, "«Sync camera» off from the window")
cam_b.click(); qa.processEvents()
ok(panel.commands.follow_camera.isChecked() and live.follow_camera, "…and on again")
ok(not update_b.isEnabled(), "Update is greyed while the changes are synced")
changes_b.click(); qa.processEvents()
ok(update_b.isEnabled() and not live.follow_changes, "…and usable with «Sync changes» off")
panel.commands.follow_changes.setChecked(True); qa.processEvents()
ok(changes_b.isChecked(), "…the toolbar's switch moves the window's too")

# narrow: the words that can go, go
win.resize(1400, 760); qa.processEvents()
ok(all(b.toolButtonStyle() == Qt.ToolButtonTextBesideIcon for b in quality) and win.scene_btn.text(), "wide: the quality and New scene say their words")
win.resize(760, 600); qa.processEvents(); qa.processEvents()
right = max(w.mapTo(win, QPoint(w.width(), 0)).x() for w in bar)
ok(win.width() == 760 and all(b.toolButtonStyle() == Qt.ToolButtonIconOnly for b in quality) and not win.scene_btn.text() and right <= 760,
   f"narrow: icons alone, and everything inside the window (right edge {right})")
win.resize(1400, 760); qa.processEvents(); qa.processEvents()
ok(win.scene_btn.text() and quality[0].toolButtonStyle() == Qt.ToolButtonTextBesideIcon, "wide again: the words are back")
win.resize(1200, 760); qa.processEvents()

# the quality, three buttons, and High follows the window
ok(win.quality_buttons.isVisibleTo(win) and len(quality) == 3 and win.quality_buttons.currentIndex() == 1
   and all(not b.icon().isNull() for b in quality), "the preview's quality: three buttons with icons")
n0 = len(renders())
quality[2].click(); qa.processEvents()
ok(panel.preview_quality.currentData() == "high", "…the same choice as the panel's")
expected = min(win.picture_pixels(panel._aspect()), panel.output_tab.frame()[0])
ok(expected > 960 and wait(lambda: any(f"width={expected} " in l for l in renders()[n0:])), f"High: the draft is as wide as the window shows it ({expected} px)")
panel.preview_quality.setCurrentIndex(panel.preview_quality.findData("normal"))
ok(quality[1].isChecked(), "…both ways")

# the final picture: no camera moves, the picture's own zoom
big = tmp / "big.png"
im = QImage(1920, 1080, QImage.Format_RGB32); im.fill(Qt.darkCyan); im.save(str(big))
live.pause(); win.set_image(big); qa.processEvents()
p0 = pose(cam); drag(); wheel(2)
ok(pose(cam) == p0 and not view.navigating() and not view.is_fitted(), "on a final picture the mouse zooms and moves the picture")
ok(not win.snapshot_btn.isEnabled() and [a.text() for a in win.picture_menu().actions()] == ["Save image…", "Copy picture"], "…right click: Save image…, Copy picture")
ok(win.copy_picture() and QApplication.clipboard().image().width() == 1920, "…copied as shown")

# «Automatic»
panel.preview_engine.setCurrentIndex(panel.preview_engine.findData("auto"))
panel._gpu = ""
ok(panel.live_engine() == "eevee", "Automatic without a graphics card: EEVEE")
panel._gpu = "OPTIX"
ok(panel.live_engine() == "cycles", "Automatic with one: Cycles")
panel.preview_engine.setCurrentIndex(panel.preview_engine.findData("eevee"))
ok(panel.live_engine() == "eevee", "EEVEE chosen: EEVEE")
panel.engine.setCurrentIndex(panel.engine.findData("auto"))
panel._gpu = "OPTIX"; panel._update_summary()
ok(panel.final_engine() == "cycles" and "Cycles" in win.summary.text(), f"Render's Automatic with a card: Cycles ({win.summary.text()})")
panel._gpu = ""; panel._update_summary()
ok(panel.final_engine() == "eevee" and "EEVEE" in win.summary.text(), "…without one: EEVEE")
panel._gpu = None
ok(panel.final_engine() is None and panel._render_engine() == "eevee", "…not looked for yet: Render looks, then decides")
ok(panel.settings_dict()["engine"] == "auto", "the drawing keeps «Automatic», not what it meant on this computer")
panel.engine.setCurrentIndex(panel.engine.findData("eevee")); panel._gpu = "OPTIX"
ok(panel.final_engine() == "eevee", "EEVEE chosen: EEVEE, card or not")
asked = []
engine_probe._run = lambda command: (asked.append(command), "HIP")[1]
class Found: command = ["blender-for-the-test"]
ok(engine_probe.gpu_backend(Found()) == "HIP" and engine_probe.gpu_backend(Found()) == "HIP" and len(asked) == 1, "Blender is asked once")
engine_probe._memory.clear()
ok(engine_probe.gpu_backend(Found()) == "HIP" and len(asked) == 1, "…and the answer is remembered between sessions")
ok(engine_probe.gpu_backend(object()) == "", "no Blender command: no card")

if SHOT:
    win.back_btn.click()
    wait(lambda: win.mode == "preview" and live._done_key is not None and not live._busy, 8)
    win.grab().save(SHOT)

panel._stop_live(); win.close()
print("FAILED" if fails else "ALL PASSED")
sys.exit(1 if fails else 0)
