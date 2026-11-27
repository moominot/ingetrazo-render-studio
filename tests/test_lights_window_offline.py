"""The lights window: the same ways as the materials one. The finer settings are out of the Light tab until
their eye is opened, buttons with icons only do what the chosen light can, and a light edited in Blender
shows only its name and place. Offscreen, no Blender. argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["RENDER_STUDIO_HOME"] = tempfile.mkdtemp()
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
QCoreApplication.setOrganizationName("rs-test")
QCoreApplication.setApplicationName(f"lights-window-{os.getpid()}")
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())
import reference_cases as R
from render_studio import light_ops as ops, lights as L

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

panel = R.panel()
tab, win = panel.lights_tab, panel.lights_window
from core.history import History                  # (the reference panel has no undo history of its own)
panel.app.viewport.history = History(panel.app.scene)
win.show()
tab.refresh(); qa.processEvents()
seen = lambda key: tab.blocks[key].isVisibleTo(tab)
ok(not tab.buttons.isVisibleTo(tab) and not any(c.isVisibleTo(tab) for c, _k in tab.cards.values()) and not seen("name"),
   "nothing chosen: no settings and no Duplicate or Delete")
ok(all(not b.icon().isNull() for b in (*tab.add_btns.values(), tab.dup_btn, tab.del_btn, tab.move_btn, tab.aim_btn,
                                       tab.blender_btn, tab.unlock_btn, tab.expert_btn, tab.help_btn, tab.colour_btn)),
   "every button has its icon")
spot = L.new_light("spot", pos=(0, 0, 2.5), name="Spot", dir=[0.0, 0.0, -1.0])
key = ops.add_free(tab.app, spot)
tab.refresh(select=key); qa.processEvents()
ok(tab.selected_key() == key and seen("kind") and seen("power") and seen("colour") and seen("spot_angle")
   and not seen("shape") and tab.buttons.isVisibleTo(tab) and tab.del_btn.isVisibleTo(tab), "a spot: its own settings")
fine = ("spot_blend", "radius", "aim", "pos", "ies", "attach")
ok(not any(seen(k) for k in fine), "the finer ones are not in the Light tab")
tab.set_expert(True); qa.processEvents()
ok(all(seen(k) for k in fine) and not seen("shape") and tab.blocks["radius"].eye.isVisibleTo(tab),
   "Expert: all the spot has, each with its eye; none of another kind's")
tab.expert_search.setText("bulb")
ok(seen("radius") and not seen("power"), "the search finds by name")
tab.expert_search.setText("")
tab.blocks["radius"].eye.click()
tab.tabs.setCurrentIndex(0); qa.processEvents()
ok(seen("radius") and not seen("aim"), "an opened eye puts the setting in the Light tab")
tab._default_view()
ok(not seen("radius"), "Default view closes it again")
tab.set_expert(False)
win.resize(820, 700); qa.processEvents()
ok(tab.unit.isVisibleTo(tab) and tab.unit.geometry().right() <= tab.power_row.width(), "the power's unit is inside its row, in sight")
tab.kind.setCurrentIndex(tab.kind.findData("area")); tab._flush(); tab.refresh(); qa.processEvents()
ok(ops.entry(tab.app.scene, tab.selected_key())["light"]["type"] == "area" and seen("shape") and seen("size")
   and not seen("spot_angle"), "the kind's big buttons change the light")

# a light edited in Blender
e = ops.entry(tab.app.scene, tab.selected_key())
proxy = dict(e["world"], blender={"v": 1, "object": "Spot", "blend": "AAAA"})
new = ops.update(tab.app, tab.selected_key(), proxy)
tab.refresh(select=new); qa.processEvents()
ok(tab.lock_box.isVisibleTo(tab) and seen("name") and seen("pick") and not seen("kind") and not seen("power")
   and not seen("colour") and not seen("shape") and not tab.preview.isVisibleTo(tab),
   "edited in Blender: only its name and place, and Unlock in plain view")
tab.set_expert(True); qa.processEvents()
ok(not seen("power") and seen("pos"), "…in the Expert tab too")
tab.set_expert(False)
tab.unlock(); qa.processEvents()
ok(not tab.lock_box.isVisibleTo(tab) and seen("power") and seen("kind"), "unlocked: its settings are back")
print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
