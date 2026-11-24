"""The Section tab's list of the drawing's sections: tick the one that cuts, rename, delete. Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QInputDialog
qa = QApplication.instance() or QApplication([])
tmp = Path(tempfile.mkdtemp())
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp / "settings"))
qa.setOrganizationName("RenderStudioTest"); qa.setApplicationName("sectionlist")
from core.camera import OrbitCamera
from core.history import History
from core.scene import Scene
from core.section import SectionBox, SectionPlane
from render_studio import section as S, section_panel as SP

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

class VP:
    def __init__(self, scene): self.scene = scene; self.history = History(scene); self.camera = OrbitCamera(); self.updates = 0
    def notify_scene_changed(self): pass
    def update(self): self.updates += 1
class App:
    def __init__(self, scene=None):
        self.scene = scene or Scene(); self.viewport = VP(self.scene); self.key = "render_studio"; self.window = None
    def document_data(self, default=None): return default
    def on_document_changed(self, fn): pass

def rows(tab):
    return [(tab.sections.item(i).text(), tab.sections.item(i).checkState() == Qt.Checked) for i in range(tab.sections.count())]

def plane(symbol, x, name="", active=False):
    return SectionPlane(QVector3D(x, 0, 0), QVector3D(1, 0, 0), name=name, symbol=symbol, active=active)

# ---- a drawing with no sections --------------------------------------------------------------------------
app = App()
tab = SP.SectionTab(app, live=lambda: False)           # (no preview window: a hidden tab does not follow the drawing)
def undo():
    app.viewport.history.undo()
    tab.document_changed()                              # what IngeTrazo tells the extensions after an undo
tab.show()
ok(tab.sections_note.isVisibleTo(tab) and not tab.sections.isVisibleTo(tab) and not tab.delete_btn.isVisibleTo(tab),
   "no sections: the tab says so and shows no list")

# ---- two planes and two boxes ----------------------------------------------------------------------------
sc = app.scene
a, b = plane("A", 1.0, active=True), plane("B", 3.0)
sc.section_planes += [a, b]
b1 = SectionBox(QVector3D(0, 0, 0), QVector3D(2, 2, 2), active=True, name="Kitchen")
b2 = SectionBox(QVector3D(5, 0, 0), QVector3D(7, 2, 2), active=False)
sc.section_boxes += [b1, b2]
sc.bump_sections()
tab.document_changed()
ok(rows(tab) == [("Section A  ·  plane", True), ("Section B  ·  plane", False), ("Kitchen  ·  box", True), ("Box 2  ·  box", False)],
   f"every plane and box of the drawing is listed, ticked when it cuts ({rows(tab)})")
ok(tab.sections.isVisibleTo(tab) and not tab.sections_note.isVisibleTo(tab), "...and the list is shown")
ok(S.entries(sc)[0]["kind"] == "plane" and S.entries(sc)[2]["kind"] == "box" and len(S.entries(sc)) == 4, "(the planes first, then the boxes)")

# ---- ticking: one plane and one box cut at a time ------------------------------------------------------------
ok(len(S.job_block(sc, {})["planes"]) == 7, "the render cuts with the plane and the six faces of the box")
tab.sections.item(1).setCheckState(Qt.Checked)
ok(sc.active_section() is b and rows(tab)[0][1] is False and rows(tab)[1][1] is True, "ticking plane B makes it cut and takes the cut off A")
ok(sc.active_section_box() is b1, "...the box goes on cutting")
undo()
ok(sc.active_section() is a and rows(tab)[0][1] is True and rows(tab)[1][1] is False, "...one undo step of the drawing, and the list follows")
tab.sections.item(0).setCheckState(Qt.Unchecked)
ok(sc.active_section() is None and rows(tab)[0][1] is False, "unticking the plane that cuts: no plane cuts")
ok(len(S.job_block(sc, {})["planes"]) == 6, "...the render cuts with the box alone")
tab.sections.item(3).setCheckState(Qt.Checked)
ok(sc.active_section_box() is b2 and not b1.active and rows(tab)[2][1] is False, "ticking box 2 makes it cut and takes the cut off box 1")
undo()
ok(sc.active_section_box() is b1 and b1.active and not b2.active, "...undone")
tab.sections.item(2).setCheckState(Qt.Unchecked)
tab.sections.item(3).setCheckState(Qt.Unchecked)
ok(sc.active_section() is None and sc.active_section_box() is None and S.job_block(sc, {}) is None
   and "No active section" in tab.state.text(), "nothing ticked: the render shows the whole model and the tab says so")
undo(); undo(); undo()

# ---- renaming ---------------------------------------------------------------------------------------------
asked = {}
real = QInputDialog.getText
def fake(answer):
    def f(parent, title, label, *args, **kw):
        asked.update(title=title, label=label, text=kw.get("text"))
        return answer, True
    return staticmethod(f)
QInputDialog.getText = fake("Main section")
tab.sections.setCurrentRow(0)
tab.sections.item(0).setSelected(True)
tab._rename()
ok(a.name == "Main section" and a.symbol == "A" and asked["text"] == "", f"a plane takes the name and keeps its letter ({a.name!r}, {a.symbol!r})")
ok(rows(tab)[0][0] == "Main section (A)  ·  plane", f"...its row says both ({rows(tab)[0][0]})")
undo()
ok(a.name == "" and rows(tab)[0][0] == "Section A  ·  plane", "...one undo step")
QInputDialog.getText = fake("Bathroom")
tab.sections.clearSelection(); tab.sections.setCurrentRow(3); tab.sections.item(3).setSelected(True)
tab._rename()
ok(b2.name == "Bathroom" and rows(tab)[3][0] == "Bathroom  ·  box", f"a box takes the name ({b2.name!r})")
ok(b2.lo == QVector3D(5, 0, 0) and not b2.active, "...and nothing else of it changes")
QInputDialog.getText = fake("   ")
tab._rename()
ok(b2.name == "" and rows(tab)[3][0] == "Box 2  ·  box", "an empty name goes back to the number")
undo(); undo()
QInputDialog.getText = fake("Kitchen")
tab.sections.clearSelection(); tab.sections.setCurrentRow(2); tab.sections.item(2).setSelected(True)
before = len(app.viewport.history._undo) if hasattr(app.viewport.history, "_undo") else None
tab._rename()
ok(b1.name == "Kitchen", "the same name asks for nothing")
QInputDialog.getText = real

# ---- deleting ---------------------------------------------------------------------------------------------
tab.sections.clearSelection()
ok(not tab.rename_btn.isEnabled() and not tab.delete_btn.isEnabled(), "nothing chosen: Rename and Delete are off")
tab.sections.item(1).setSelected(True)
ok(tab.rename_btn.isEnabled() and tab.delete_btn.isEnabled(), "one chosen: both are on")
tab.sections.item(3).setSelected(True)
ok(not tab.rename_btn.isEnabled() and tab.delete_btn.isEnabled(), "two chosen: only Delete")
tab._delete()
ok(sc.section_planes == [a] and sc.section_boxes == [b1] and rows(tab) == [("Section A  ·  plane", True), ("Kitchen  ·  box", True)],
   "Delete takes the chosen plane and box out of the drawing, and out of the list")
undo()
ok(sc.section_planes == [a, b] and sc.section_boxes == [b1, b2] and len(rows(tab)) == 4, "...both come back, in their places, with one undo")
ok(b2.active is False and b1.active is True and a.active is True, "...as they were")
tab.sections.clearSelection(); tab.sections.item(0).setSelected(True)
tab._delete()
ok(sc.section_planes == [b] and sc.active_section() is None and S.job_block(sc, {}) is not None, "deleting the plane that cuts: it is gone, the box still cuts")
undo()

# ---- the list follows the drawing ----------------------------------------------------------------------------
c = plane("C", 9.0, name="Garden")
sc.section_planes.append(c); sc.bump_sections()
tab.document_changed()
ok(len(rows(tab)) == 5 and rows(tab)[2][0] == "Garden (C)  ·  plane", "a plane placed in the drawing joins the list")
tab.sections.clearSelection(); tab.sections.item(2).setSelected(True)
sc.section_planes.remove(a); sc.bump_sections()
tab.document_changed()
ok(len(rows(tab)) == 4 and [t.item(i).isSelected() for t in (tab.sections,) for i in range(4)].count(True) == 1,
   "one that goes leaves it, and the chosen row stays chosen")
tab.hide()
d = plane("D", 11.0)
sc.section_planes.append(d); sc.bump_sections()
tab.document_changed()
ok(len(rows(tab)) == 4, "while the tab is hidden and nothing needs it, the list waits...")
tab.show()
ok(len(rows(tab)) == 5, "...and is read again when the tab shows")

# ---- an IngeTrazo with no sections ------------------------------------------------------------------------------
class OldScene:
    materials = {}
    plugin_data = {}
    selection = set()
old = SP.SectionTab(App(OldScene()))
old.show()
ok(not old.sections_title.isVisibleTo(old) and not old.sections.isVisibleTo(old) and not old.sections_note.isVisibleTo(old),
   "an IngeTrazo without sections: no list, no note, no error")

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
