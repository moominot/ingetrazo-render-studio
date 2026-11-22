"""The Section tab follows the model only while it matters: the preview window is open and a
section plane is active (or the tab is on screen). Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from render_studio import materials as M
from render_studio.section_panel import SectionTab

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

class Plane:
    point = normal = None

class Scene:
    def __init__(self):
        self.plane = None
        self.materials = {"Brick": object()}
        self.groups = []
    def active_section(self):
        return self.plane

class App:
    def __init__(self):
        self.scene = Scene()

calls = []
real = M.used_materials
M.used_materials = lambda scene: (calls.append(1), {"Brick": 3})[1]
try:
    app, state = App(), {"open": False}
    tab = SectionTab(app, live=lambda: state["open"])
    ok(len(calls) == 1 and tab.material.count() == 2, "built once at the start, with the model's materials")
    calls.clear()

    tab.document_changed()
    ok(not calls and tab._stale, "preview closed and no section: an edit does not read the model")

    state["open"] = True
    tab.document_changed()
    ok(not calls, "preview open but no section plane: still nothing")

    state["open"] = False
    app.scene.plane = Plane()
    tab.document_changed()
    ok(not calls, "a section plane but the preview closed: still nothing")

    state["open"] = True
    tab.document_changed()
    ok(len(calls) == 1 and not tab._stale, "preview open and a section active: it follows the edit")
    calls.clear()

    state["open"] = False
    tab.document_changed()
    ok(not calls and tab._stale, "preview closed again: it stops")
    tab.show(); qa.processEvents()
    ok(len(calls) == 1 and not tab._stale, "shown while out of date: it catches up")
    calls.clear()
    tab.document_changed()
    ok(len(calls) == 1, "…and follows the edits while it is on screen")
    tab.hide(); calls.clear()

    app.scene.plane = None
    tab.apply({"cap": True, "material": "Zed", "light": "open"})
    calls.clear()
    tab.document_changed()
    ok(tab._stale and tab.settings()["material"] == "Zed",
       "the chosen cap material is kept for the render even when the list is out of date")
    ok(tab.settings()["cap"] is True and tab.settings()["light"] == "open", "the other options are read as before")

    tab2 = SectionTab(app)
    calls.clear()
    tab2.document_changed()
    ok(len(calls) == 1, "without a preview probe (older callers) it follows every edit, as before")
finally:
    M.used_materials = real


# ---- the cap's style: material / flat colour / hatch, and no shadows ----------------------------------
from render_studio import section as S
tab = SectionTab(App(), live=lambda: False); tab.show()
ok(tab.settings()["style"] == "material" and tab.settings()["shadows"] is True, "the cap starts as before: the material, with shadows")
ok(tab.material.isVisibleTo(tab) and not tab.colour.isVisibleTo(tab) and not tab.pattern.isVisibleTo(tab), "material style: only the material list")
tab.style.setCurrentIndex(tab.style.findData("flat"))
ok(tab.colour.isVisibleTo(tab) and not tab.material.isVisibleTo(tab) and not tab.pattern.isVisibleTo(tab), "flat style: a colour, no material, no pattern")
tab.style.setCurrentIndex(tab.style.findData("hatch"))
ok(all(w.isVisibleTo(tab) for w in (tab.colour, tab.pattern, tab.line, tab.spacing)), "hatch style: colour, pattern, lines and spacing")
tab.colour.set_rgb((1, 1, 1)); tab.pattern.setCurrentIndex(tab.pattern.findData("cross")); tab.spacing.setValue(25); tab.shadows.setChecked(True)
st = tab.settings()
ok(st["style"] == "hatch" and st["pattern"] == "cross" and abs(st["spacing"] - 0.25) < 1e-6 and st["shadows"] is False and st["color"] == [1.0, 1.0, 1.0],
   f"the settings carry it ({st['style']}, {st['pattern']}, {st['spacing']}, shadows {st['shadows']})")
tab2 = SectionTab(App(), live=lambda: False); tab2.apply(st)
ok(tab2.settings() == st, "and apply puts them back")
ok(S.clean({"style": "x", "pattern": "y", "spacing": -4, "color": "red", "shadows": 0})["style"] == "material"
   and S.clean({"spacing": -4})["spacing"] == 0.005 and S.clean({"color": "red"})["color"] == S.DEFAULT["color"], "junk is cleaned")
class Sc2(Scene):
    def __init__(self):
        super().__init__()
        from PySide6.QtGui import QVector3D
        pl = Plane(); pl.point = QVector3D(0, 0, 0); pl.normal = QVector3D(1, 0, 0); self.plane = pl
blk = S.job_block(Sc2(), st)
ok(blk["style"] == "hatch" and blk["pattern"] == "cross" and blk["texture_size"] == [1.0, 1.0] and blk["shadows"] is False and blk["color"] == [1.0, 1.0, 1.0],
   "the job carries the hatch, laid out in metres")
ok(S.job_block(Sc2(), {"style": "material"})["shadows"] is True, "the default job keeps the shadows")
print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
