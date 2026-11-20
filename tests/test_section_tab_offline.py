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

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
