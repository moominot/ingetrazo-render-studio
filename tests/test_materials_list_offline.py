"""The material list: paint on faces, on groups painted WHOLE, nested, registry-only.
argv: <ingetrazo-src> <render-studio repo>"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QVector3D, QMatrix4x4
from core.group import Group
from core.materials import Material
from core.mesh import Mesh
from core.scene import Scene
from render_studio import materials as M, material_editor as ME

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w)
    if not c: fails.append(w)

def quad(mesh, z=0.0):
    return mesh.add_face([QVector3D(0, 0, z), QVector3D(1, 0, z), QVector3D(1, 1, z), QVector3D(0, 1, z)])

# a wall painted WHOLE with a named brick material: the faces carry no name, the container does
scene = Scene()
scene.materials["Brick"] = Material("Brick", texture={"path": "x.png", "sw": 1.0, "sh": 1.0})
wall = Group(Mesh(), name="wall"); wall.xform = QMatrix4x4()
quad(wall.mesh)
wall.material = {"mat": "Brick", "texture": {"path": "x.png", "sw": 1.0, "sh": 1.0}}
scene.groups.append(wall)
used = M.used_materials(scene)
ok(used.get("Brick") == 1, f"a group painted whole counts ({used})")

# nested component painted whole
outer = Group(Mesh(), name="outer"); inner = Group(Mesh(), name="inner"); inner.xform = QMatrix4x4()
inner.material = {"mat": "Plaster"}; outer.adopt([inner]); scene.groups.append(outer)
scene.materials["Plaster"] = Material("Plaster", color=(0.9, 0.9, 0.9))
ok(M.used_materials(scene).get("Plaster") == 1, "a nested component painted whole counts")

# faces
f = quad(scene.mesh, 2.0); f.attrs["mat"] = "Glass"
ok(M.used_materials(scene).get("Glass") == 1, "a loose face counts (even without a registry entry)")

# registry only
scene.materials["Unused"] = Material("Unused", color=(1, 0, 0))
ok(M.used_materials(scene).get("Unused") == 0, "a registry material nothing wears is listed (0)")
ok(M.used_materials(Scene()) == {}, "an empty document: empty list")

# selection
scene.selection.clear(); scene.selection.add(wall)
ok(M.selection_material(scene) == "Brick", "selecting the painted group gives its material")
scene.selection.clear(); scene.selection.add(outer)
ok(M.selection_material(scene) == "Plaster", "selecting a group whose child is painted gives the child's")
scene.selection.clear(); scene.selection.add(f)
ok(M.selection_material(scene) == "Glass", "selecting a face gives its material")
scene.selection.clear()
ok(M.selection_material(scene) is None, "nothing selected: none")

class App:
    def __init__(self, s): self.scene = s; self.viewport = None
    def document_data(self, d=None): return d
    def set_document_data(self, v): pass
ed = ME.MaterialEditor(App(scene), "en")
names = [ed.list.item(i).data(0x0100) for i in range(ed.list.count())]
ok({"Brick", "Plaster", "Glass", "Unused"} <= set(names), f"the editor lists them all ({names})")
scene.selection.add(wall); ed.pick_selection()
ok(ed.current_name() == "Brick", "«From the selection» jumps to the wall's material")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
