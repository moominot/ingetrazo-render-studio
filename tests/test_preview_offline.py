"""The preview window and the panel's controls, offscreen, no Blender: zoom and pan, the three states
(preview / rendering / final) and what each shows, the retouch sliders, the panel's value labels and hints.
argv: <ingetrazo-src> <render-studio repo>"""
import json, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QApplication, QGraphicsView
qa = QApplication.instance() or QApplication([])
from PySide6.QtCore import QCoreApplication, QSettings        # settings in a throwaway file, not the user's
_prev = (QCoreApplication.organizationName(), QCoreApplication.applicationName(), QSettings.defaultFormat())
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
qa.setOrganizationName("RenderStudioTest"); qa.setApplicationName("preview")
def _restore_settings():
    QSettings.setDefaultFormat(_prev[2]); qa.setOrganizationName(_prev[0]); qa.setApplicationName(_prev[1])
from core.camera import OrbitCamera
from core.scene import Scene
from render_studio import panel as P, post, presets
from render_studio.widgets import ZoomView

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

class QTest:                      # (this IngeTrazo has no QtTest: send the events by hand)
    @staticmethod
    def _mouse(view, kind, pos, button, buttons):
        ev = QMouseEvent(kind, QPointF(pos), QPointF(view.mapToGlobal(pos)), button, buttons, Qt.NoModifier)
        QApplication.sendEvent(view, ev); qa.processEvents()
    @staticmethod
    def mousePress(view, button, mod, pos): QTest._mouse(view, QEvent.MouseButtonPress, pos, button, button)
    @staticmethod
    def mouseMove(view, pos): QTest._mouse(view, QEvent.MouseMove, pos, Qt.NoButton, Qt.LeftButton)
    @staticmethod
    def mouseRelease(view, button, mod, pos): QTest._mouse(view, QEvent.MouseButtonRelease, pos, button, Qt.NoButton)
    @staticmethod
    def mouseDClick(view, button, mod, pos): QTest._mouse(view, QEvent.MouseButtonDblClick, pos, button, button)
    @staticmethod
    def keyClick(view, key):
        QApplication.sendEvent(view, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)); qa.processEvents()
tmp = Path(tempfile.mkdtemp())
def picture(name, w, h):
    img = QImage(w, h, QImage.Format_RGB32); img.fill(QColor(120, 160, 200))
    p = QPainter(img); p.fillRect(0, h * 2 // 3, w, h - h * 2 // 3, QColor(70, 130, 60)); p.fillRect(w * 2 // 5, h // 3, w // 5, h // 3, QColor(220, 210, 190)); p.end()
    img.save(str(tmp / name)); return tmp / name
big, small = picture("draft960.png", 960, 540), picture("quick480.png", 480, 270)

# ---- zoom and pan ---------------------------------------------------------------------------------
v = ZoomView(); v.resize(800, 500); v.show(); qa.processEvents()
from PySide6.QtGui import QPixmap
v.set_pixmap(QPixmap(str(big))); qa.processEvents()
ok(v.is_fitted() and v.percent() < 100, f"a new picture fits the window ({v.percent():.0f} %)")
ok(v.dragMode() == QGraphicsView.ScrollHandDrag, "a drag moves the picture")
fit_scale = v.transform().m11()
def wheel(view, dy, at=QPoint(400, 250)):
    ev = QWheelEvent(QPointF(at), QPointF(view.viewport().mapToGlobal(at)), QPoint(0, 0), QPoint(0, dy), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(view.viewport(), ev); qa.processEvents()
wheel(v, 240)
ok(not v.is_fitted() and v.transform().m11() > fit_scale * 1.3, f"the wheel zooms in ({v.percent():.0f} %)")
z = v.transform().m11()
wheel(v, -240)
ok(v.transform().m11() < z, "…and out")
for _ in range(60): wheel(v, 240)
ok(v.percent() <= 16 * 100 + 1, f"it stops at 16 screen pixels per picture pixel ({v.percent():.0f} %)")
for _ in range(120): wheel(v, -240)
ok(v.transform().m11() >= fit_scale * 0.5 - 1e-6, "…and does not shrink the picture away")
v.fit(); qa.processEvents()
ok(v.is_fitted() and abs(v.transform().m11() - fit_scale) < 1e-6, "Fit goes back")
v.actual_size(); qa.processEvents()
ok(abs(v.percent() - 100.0) < 0.5 and not v.is_fitted(), f"100 % is one picture pixel per screen pixel ({v.percent():.1f} %)")
ok(v.horizontalScrollBar().maximum() > 0 or v.verticalScrollBar().maximum() > 0, "…with scroll room to move around")
c0 = v.mapToScene(v.viewport().rect().center())
QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(400, 250))
QTest.mouseMove(v.viewport(), QPoint(340, 220)); QTest.mouseMove(v.viewport(), QPoint(300, 200))
QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(300, 200)); qa.processEvents()
c1 = v.mapToScene(v.viewport().rect().center())
ok(abs(c1.x() - c0.x()) > 1 or abs(c1.y() - c0.y()) > 1, f"dragging moves the picture (centre {c0.x():.0f},{c0.y():.0f} → {c1.x():.0f},{c1.y():.0f})")
t = v.transform().m11()
v.set_pixmap(QPixmap(str(small))); qa.processEvents()
ok(abs(v.transform().m11() - t) < 1e-9 and not v.is_fitted(), "a live frame of another size keeps the zoom and place")
ok(v.picture_size() == (480, 270), "…and shows the new frame")
v.fit()
QTest.mouseDClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(400, 250)); qa.processEvents()
ok(abs(v.percent() - 100.0) < 0.5, "a double click goes to 100 %")
QTest.mouseDClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(400, 250)); qa.processEvents()
ok(v.is_fitted(), "…and again, back to fit")
QTest.keyClick(v, Qt.Key_Plus); ok(not v.is_fitted() and v.percent() > 0, "+ zooms in")
QTest.keyClick(v, Qt.Key_0); ok(v.is_fitted(), "0 fits")
QTest.keyClick(v, Qt.Key_1); ok(abs(v.percent() - 100.0) < 0.5, "1 is 100 %")
v.close()

# ---- the window's three states ------------------------------------------------------------------------
class VP:
    def __init__(self): self.camera = OrbitCamera()
    def width(self): return 1600
    def height(self): return 900
    def update(self): pass
class App:
    api_version = 2
    def __init__(self): self.scene = Scene(); self.viewport = VP(); self.data = {}
    def document_data(self, d=None): return json.loads(json.dumps(self.data)) if self.data else d
    def set_document_data(self, v): self.data = json.loads(json.dumps(v))
    def on_document_changed(self, fn): pass
app = App(); panel = P.StudioPanel(app); panel.blender = lambda: object(); panel.check_blender()
w = panel.preview(); w.resize(1000, 700); w.show(); qa.processEvents()
see = lambda x: x.isVisibleTo(w)
ok(w.mode == "preview" and see(w.bar_preview) and not see(w.bar_final), "the window opens as a preview: Render buttons, no retouch tools")
ok(see(w.render_btn) and w.render_btn.isEnabled() and "Render and save" in w.render_save_btn.text() and w.render_btn.menu() is not None
   and w.render_save_btn in w.render_btn.menu().actions(), "…with Render, and Render and save… under its arrow")
ok(see(w.scene_btn), "…and «New scene from this view…» always in view")
ok(not any(see(s) for s in w.adj.values()), "…and the retouch sliders are hidden")
ok(not any(hasattr(w, n) for n in ("more_btn", "follow_camera_box", "follow_changes_box", "update_btn")),
   "…no «More» fold, and the live view's switches are not here: they are on the toolbar")
ok(w.expert_btn in w.render_btn.menu().actions(), "…and Open in Blender… is under Render's arrow")
c = panel.commands
ok(c.follow_camera.isCheckable() and c.follow_changes.isCheckable() and not c.follow_camera.icon().isNull(),
   "the two switches are commands with icons")
ok(c.update.isVisible() and not c.update.isEnabled(), "…«Update preview» is there but greyed while the changes are synced")
c.follow_changes.setChecked(False); qa.processEvents()
ok(c.update.isEnabled(), "…and usable when they are not")
c.follow_changes.setChecked(True); qa.processEvents()
ok(w.summary.text() == "Render: Automatic · Medium · 1920 × 1080 px · PNG, 8 bits", f"…and says what Render will use («{w.summary.text()}»)")
panel.quality.setCurrentIndex(2); panel.engine.setCurrentIndex(panel.engine.findData("cycles")); panel.width.setValue(1280)
ok(w.summary.text() == "Render: Cycles · High · 1280 × 720 px · PNG, 8 bits", f"…following the panel («{w.summary.text()}»)")
w.show_draft(small); qa.processEvents()
ok(w.has_image() and w.view.picture_size() == (480, 270) and w.original is None, "a live frame is shown (not retouched, no final picture yet)")
w.set_mode("rendering"); qa.processEvents()
ok(see(w.bar) and see(w.cancel_btn) and not w.render_btn.isEnabled() and not see(w.bar_final),
   "rendering: progress and Cancel, the Render buttons off")
w.set_progress(0.42); ok(w.bar.value() == 42, "…the bar follows")
w.set_image(big); qa.processEvents()
ok(w.mode == "final" and see(w.bar_final) and not see(w.bar_preview) and not see(w.bar), "the finished picture: the retouch tools replace the Render buttons")
ok(all(see(s) for s in w.adj.values()) and see(w.save_btn) and see(w.back_btn) and see(w.reset_btn), "…sliders, Save image…, Back to preview, Reset")
ok(w.view.is_fitted() and w.view.picture_size() == (960, 540), "…the picture fitted")
# retouch
ok(w.shown is not None and (w.shown == w.original).all(), "neutral: the picture as rendered")
ex = w.adj["exposure"]; ex.setValue(int(ex.maximum() * 0.75))
ok(not (w.shown == w.original).all() and w.adj_rows["exposure"].value_label.text() == "+1.0 EV",
   f"a slider retouches it at once, and its value reads «{w.adj_rows['exposure'].value_label.text()}»")
w.view.zoom_by(2.0); z = w.view.transform().m11()
w.adj["saturation"].setValue(10)
ok(abs(w.view.transform().m11() - z) < 1e-9, "retouching keeps the zoom")
out = tmp / "retouched.png"
ok(w.save_to(str(out)) and QImage(str(out)).size().width() == 960, "Save writes what you see")
w._reset()
ok((w.shown == w.original).all() and w.adj_rows["exposure"].value_label.text() == "+0.0 EV", "Reset: neutral again")
ok(all(r.hint.text() for r in w.adj_rows.values()), "every retouch slider says what it does")
w.set_mode("preview")
ok(see(w.bar_preview) and not see(w.bar_final) and w.render_btn.isEnabled(), "Back to the preview: the Render buttons again")

# close = the live view is not needed any more
closed = []
panel.preview_closed = lambda: closed.append(1)
w.close(); qa.processEvents()
ok(closed == [1], "closing the window tells the panel (it stops the live Blender)")

# alone, as a viewer of a finished picture
solo = P.ImageWindow(); solo.set_image(big); solo.show(); qa.processEvents()
sees = lambda x: x.isVisibleTo(solo)
ok(solo.mode == "final" and sees(solo.bar_final) and not sees(solo.bar_preview) and not sees(solo.back_btn),
   "without a panel: just the picture and its retouch tools")
solo.close()

# ---- the panel ---------------------------------------------------------------------------------------------
# what is see-through shows the WINDOW's checkerboard: the same squares, in the same place, whatever the picture's size or zoom
import tempfile as _tmp
from PySide6.QtGui import QColor as _Color, QImage as _Image
from render_studio.preview import ImageWindow as _Window
_w = _Window()
_w.resize(900, 600); _w.show()
_dir = _tmp.mkdtemp()
def _frame(width):
    """A live frame ``width`` wide: nothing, but for a red block at the right."""
    img = _Image(width, width // 2, _Image.Format_ARGB32); img.fill(_Color(0, 0, 0, 0))
    for x in range(width * 3 // 4, width):
        for y in range(width // 2):
            img.setPixelColor(x, y, _Color(200, 30, 30, 255))
    path = os.path.join(_dir, f"live{width}.png"); img.save(path)
    return path
def _board():
    """What the view shows: the greys along a line across the middle of its left half, in the window's own pixels."""
    for _ in range(5):
        QApplication.processEvents()
    shot = _w.view.viewport().grab().toImage()
    y = 200                                  # (a fixed line: a scroll bar that appears makes the view a little shorter)
    return [shot.pixelColor(x, y).red() for x in range(shot.width() // 4, shot.width() // 2)]
_w.show_draft(_frame(160)); _small = _board()
_runs = [len(r) for r in "".join("L" if g > 220 else "D" for g in _small).replace("LD", "L|D").replace("DL", "D|L").split("|")]
ok(set(_small) == {236, 204} and set(_runs[1:-1]) == {12}, f"a live frame with nothing behind shows the checkerboard, 12 px squares ({sorted(set(_small))}, {_runs[1:-1][:4]})")
_w.show_draft(_frame(480)); _large = _board()
ok(_large == _small, "a frame of another size: the same squares in the same place")
_w.view.zoom_by(1.7); _zoomed = _board()
ok(_zoomed == _small, "…and zoomed in too: the board is the window's")
_w.view.fit(); _w.set_image(_frame(320))
ok(_board() == _small, "…and under the finished picture")
_solid = _Image(320, 160, _Image.Format_RGB32); _solid.fill(_Color(10, 90, 10)); _p = os.path.join(_dir, "solid.png"); _solid.save(_p)
_w.show_draft(_p)
ok(set(_board()) == {10}, "a picture with nothing see-through has no board")
_w.close(); _w.deleteLater()

ok(hasattr(panel, "render_btn") and hasattr(panel, "render_save_btn") and not hasattr(panel, "live_box"),
   "the panel has Render and Render and save…, and no Live view box (that is in the preview window)")
ok(panel.commands.preview.isEnabled() and panel.preview_btn.defaultAction() is panel.commands.preview
   and panel.materials_btn.defaultAction() is panel.commands.materials and panel.lights_btn.defaultAction() is panel.commands.lights,
   "…and its Open preview, Materials and Lights buttons are the toolbar's own commands")
ok(set(panel.slider_rows) == set(presets.SLIDERS), "every panel slider has a row with a value and a hint")
ok(all(r.hint.text() and r.value_label.text() for r in panel.slider_rows.values()), "…each says what it does and its value")
ok(panel.slider_rows["exposure_bias"].value_label.text() == "+0.0 EV" and panel.slider_rows["clouds"].value_label.text().endswith("%"),
   f"…in units (exposure «{panel.slider_rows['exposure_bias'].value_label.text()}», clouds «{panel.slider_rows['clouds'].value_label.text()}»)")
panel.sliders["exposure_bias"].setValue(panel.sliders["exposure_bias"].maximum())
ok(panel.slider_rows["exposure_bias"].value_label.text() == "+3.0 EV", "…and the value follows the slider")
panel.preset.setCurrentIndex(panel.preset.findData("night"))
ok(panel.slider_rows["clouds"].value_label.text() == f"{presets.studio('night')[0]['clouds']:.0%}", "…and a look's own values")
panel.apply_settings(panel.settings_dict() | {"sliders": {"clouds": 0.8}});
ok(panel.slider_rows["clouds"].value_label.text() == "80%", "…and settings put in from the document")
titles = [g.title() for g in panel.findChildren(P.QGroupBox) if not g.isHidden()]       # (the look's group is hidden)
ok(set(titles) == {"Projection", "Size", "File", "What to render", "Save", "Sections in the drawing", "Cap", "Cap outline",
                   "Presets", "Light", "Surface", "Outline", "Finish", "Shadows", "Camera", "Corrections", "Sun and sky", "Background", "Ground", "Horizon", "Fog", "Quality"}, f"the panel's groups ({titles})")
ok({"preview", "rendering", "final"} <= set(__import__("render_studio.preview", fromlist=["x"]).NOTES), "each state has its own note")
_restore_settings()
# ---- the preview's quality: fast, normal, high ----
from render_studio import live as LV
ok(LV.quality_numbers("normal", "draft", 8) == (1.0, 8), "normal: the draft as it was")
fw, fs = LV.quality_numbers("fast", "quick", 4); hw, hs = LV.quality_numbers("high", "quick", 4)
ok(fw < 1.0 and fs < 4 and hw > 1.0 and hs > 4, f"fast is smaller and rougher, high bigger and cleaner ({fw},{fs} / {hw},{hs})")
ok(LV.quality_numbers("fast", "motion", 1)[1] == 1, "…never fewer than one sample")
ok([panel.preview_quality.itemData(i) for i in range(3)] == ["fast", "normal", "high"], "the Quality group offers the preview's quality")
print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
