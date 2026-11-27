"""Labels above their controls: the value is shown at the right of the name as a COPY, and the control's own
value label is never moved (moving it ended the program at times: an access violation much later, while a list
was cleared). Offscreen, no Blender. argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["RENDER_STUDIO_HOME"] = tempfile.mkdtemp()
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from pathlib import Path
from PySide6.QtWidgets import QApplication, QFormLayout, QHBoxLayout, QLabel, QSlider, QWidget
qa = QApplication.instance() or QApplication([])
from PySide6.QtCore import Qt
import reference_cases as R
from render_studio import labels_above, widgets

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

code = "".join(p.read_text(encoding="utf-8") for p in Path(REPO, "render_studio").glob("*.py"))
ok(".setParent(" not in code.replace('Do not setParent', ''), "no widget of the extension is moved to another parent")

# a form with a slider row of each kind
host = QWidget()
form = QFormLayout(host)
row = widgets.SliderRow(widgets.slider(0, 1, 0.25), "{:.2f}")
form.addRow("Amount", row)
bare = QHBoxLayout()
s, v = QSlider(Qt.Horizontal), QLabel("10 %")
bare.addWidget(s, 1)
bare.addWidget(v)
form.addRow("Waves", bare)
owner_of_value, owner_of_bare = row.value_label.parentWidget(), v.parentWidget()
labels_above.apply(host)
host.resize(320, 200)
host.show()
for _ in range(5):
    qa.processEvents()
ok(row.value_label.parentWidget() is owner_of_value and v.parentWidget() is owner_of_bare and bare.indexOf(v) == 1,
   "the control's own value labels stay where they were made")
ok(not row.value_label.isVisibleTo(host), "…the slider row's one hidden there")
ok(v.isVisibleTo(host), "(a bare slider with its value in a layout of its own is left as it is)")
copies = lambda: sorted(w.text() for w in host.findChildren(QLabel)
                        if w.isVisibleTo(host) and w.text() not in ("Amount", "Waves"))
ok(copies() == sorted(["0.25", "10 %"]), f"…and a copy of each is shown by its name ({copies()})")
widgets.set_value(row.slider if hasattr(row, "slider") else row.findChild(QSlider), 0.75)
row.update_value()
v.setText("40 %")
qa.processEvents()
ok(copies() == sorted(["0.75", "40 %"]), f"the copies say what the controls say now ({copies()})")
name = next(w for w in host.findChildren(QLabel) if w.text() == "Amount")
copy = next(w for w in host.findChildren(QLabel) if w.text() == "0.75" and w.isVisibleTo(host))
ok(abs(copy.y() - name.y()) <= 2 and copy.x() > name.x() + 40, "the copy is on the name's line, at the right")
form.setRowVisible(row, False)
qa.processEvents()
ok(not copy.isVisibleTo(host), "a hidden row takes its copy with it")

panel = R.panel()
e = panel.expert
rows = [r for r in e.rows.values() if r.value is not None]
ok(rows and all(r.value.parentWidget() is r for r in rows), f"the Expert page's values are copies of its own ({len(rows)})")
r = rows[0]
slider = r.mirror.widget.findChild(QSlider)
before = r.value.text()
slider.setValue(slider.maximum() if slider.value() != slider.maximum() else slider.minimum())
qa.processEvents()
ok(r.value.text() != before, f"…and follow their control ({before} → {r.value.text()})")
print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
