"""Editing a material's picture in another program: the picture is copied and opened there, the copy is
watched, and each save (Overwrite, or Export As with another name or format) is taken into the material, in
the model, as one undo step. The original file is never touched. Offscreen; the other program is a stand-in.
argv: <ingetrazo-src> <render-studio repo>"""
import json, os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
tmp = Path(tempfile.mkdtemp())
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp / "settings"))
qa.setOrganizationName("RenderStudioTest"); qa.setApplicationName("extedit")
from core.history import History
from core.materials import Material
from core.scene import Scene
from PySide6.QtGui import QVector3D
from render_studio import external_edit as EE, material_editor as ME

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)
def wait(cond, secs=8.0):
    t0 = time.time()
    while not cond() and time.time() - t0 < secs:
        qa.processEvents(); time.sleep(0.02)
    return cond()
def picture(path, rgb, w=8, h=4):
    img = QImage(w, h, QImage.Format_RGB32); img.fill(QColor(*rgb)); img.save(str(path)); return str(path)

class VP:
    def __init__(self, scene): self.scene = scene; self.history = History(scene)
    def notify_scene_changed(self): pass
    def update(self): pass
class App:
    def __init__(self):
        self.scene = Scene(); self.viewport = VP(self.scene); self.key = "render_studio"; self.window = None
    def document_data(self, default=None): return default
    def on_document_changed(self, fn): pass

app = App()
orig = picture(tmp / "wall.png", (200, 60, 40))
app.scene.materials["Wall"] = Material("Wall", texture={"path": orig, "sw": 2.0, "sh": 1.0})
f = app.scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
f.attrs.update({"mat": "Wall", "texture": {"path": orig, "sw": 2.0, "sh": 1.0}})
app.scene.materials["Flat"] = Material("Flat", color=(0.5, 0.5, 0.5))
before_bytes = Path(orig).read_bytes()

opened = []
real_open = EE.open_in_program
EE.open_in_program = lambda program, path: (opened.append((program, str(path))) or True)

sess = EE.PictureEdit(app, "Wall", root=tmp / "work", debounce_ms=100)
said = []; bad = []
sess.changed.connect(said.append); sess.failed.connect(bad.append)
ok(sess.start("C:/fake/gimp.exe"), "the picture is opened for editing")
ok(opened and opened[0][0] == "C:/fake/gimp.exe" and Path(opened[0][1]).is_file() and str(tmp / "work") in opened[0][1],
   "...a COPY of it, in a working folder")
ok(Path(orig).read_bytes() == before_bytes, "the original file is not touched")
ok(Path(opened[0][1]).read_bytes() == before_bytes, "the copy starts as the original")

mat_path = lambda: app.scene.materials["Wall"].texture["path"]
first_path = mat_path()
copy = Path(opened[0][1])
picture(copy, (20, 120, 220), 16, 8)                      # File > Overwrite
ok(wait(lambda: sess.swaps == 1), "saving the copy replaces the material's picture")
new1 = mat_path()
img = QImage(new1)
ok(new1 != first_path and not img.isNull() and QColor(img.pixel(1, 1)).blue() > 150, "...with the new picture (its blue is there)")
ok(f.attrs["texture"]["path"] == new1, "...on the faces that wear it")
ok(Path(orig).read_bytes() == before_bytes, "...and the original is still not touched")
ok(said and "wall.png" in said[-1].lower(), f"...and it says so ({said[-1] if said else ''})")
app.viewport.history.undo()
ok(mat_path() == first_path and f.attrs["texture"]["path"] == first_path, "each save is one undo step")
app.viewport.history.redo()

picture(copy.with_name("export.jpg"), (30, 200, 30), 8, 4)    # Export As, another name and format
ok(wait(lambda: sess.swaps == 2), "an image saved with another name or format is taken too")
ok(mat_path() != new1 and QColor(QImage(mat_path()).pixel(1, 1)).green() > 150, "...the newest one")

(copy.with_name("half.png")).write_bytes(b"\x89PNG\r\n")        # still being written
time.sleep(0.5); qa.processEvents()
ok(sess.swaps == 2, "a file that cannot be read yet is left for the next change")
sess.stop()

flat = EE.PictureEdit(app, "Flat", root=tmp / "work")
got = []; flat.failed.connect(got.append)
ok(flat.start("x") is False and got, "a material with no picture cannot be edited")

# ---- the program ------------------------------------------------------------------------------
ok(EE.find_editor() in ("", ) or Path(EE.find_editor()).is_file(), "the program is found or left to the system")
fake = tmp / "paint.exe"; fake.write_text("x")
EE.remember_editor(str(fake))
ok(EE.find_editor() == str(fake), "a program chosen is remembered")
EE.remember_editor(str(tmp / "gone.exe"))
ok(EE.find_editor() != str(tmp / "gone.exe"), "a program that is not there any more is not used")

# ---- the editor's buttons ----------------------------------------------------------------------
EE.remember_editor(str(fake))
opened.clear()
ed = ME.MaterialEditor(app, "en")
ed.refresh(force=True); ed.select("Wall")
ok(ed.edit_btn.isEnabled() and not ed.edit_btn.icon().isNull() and not ed.edit_btn.text() and not hasattr(ed, "editor_btn")
   and ed.choose_editor_act in ed.edit_btn.actions(), "Edit picture is one pencil button; its right click chooses the program")
ed.edit_btn.click()
ok(opened and opened[-1][0] == str(fake) and "Wall" in ed.hint.text() or "wall" in ed.hint.text().lower(), f"Edit picture opens it ({ed.hint.text()[:60]})")
paths_before = app.scene.materials["Wall"].texture["path"]
picture(Path(opened[-1][1]), (240, 240, 20), 8, 4)
ok(wait(lambda: app.scene.materials["Wall"].texture["path"] != paths_before, 10), "a save in the program changes the material")
ok(wait(lambda: "took" in ed.hint.text() or "wall" in ed.hint.text().lower()), f"the editor says so ({ed.hint.text()[:70]})")
# no program at all opens it: one is asked for, and used
for s_ in list(ed._edits.values()):
    s_.stop()
asked, tried = [], []
before_open = EE.open_in_program
EE.open_in_program = lambda program, path: (tried.append(program), program == "chosen.exe")[1]
EE.find_editor = (lambda real=EE.find_editor: lambda: "")()
ed.choose_editor = lambda: (asked.append(True), "chosen.exe")[1]
ed.edit_picture()
ok(asked and tried == ["", "chosen.exe"] and ed._edits, f"no program opens it: one is asked for and used ({tried})")
ed.choose_editor = lambda: ""
tried.clear()
ed.edit_picture()
ok(tried == [""] and not ed._edits, "…and with none given, nothing is left being watched")
EE.open_in_program = before_open
ed.close()
ok(all(not s._timer.isActive() for s in ed._edits.values()) and not ed._edits, "closing the editor stops watching")

EE.open_in_program = real_open
print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
