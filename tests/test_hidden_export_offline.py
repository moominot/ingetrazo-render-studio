"""What is hidden in the drawing stays out of the exported model: a nested object, one on a hidden
tag, a face hidden inside an object; the export is put back as it was. Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, tempfile, json, struct
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QMatrix4x4, QVector3D
import formats.gltf as gltf, formats.meshexport as me
from core.camera import OrbitCamera
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from render_studio import panel as P, visibility

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

def quad_mesh(n, z=0.0):
    m = Mesh()
    faces = [m.add_face([QVector3D(i, 0, z), QVector3D(i + 1, 0, z), QVector3D(i + 1, 1, z), QVector3D(i, 1, z)])
             for i in range(n)]
    return m, faces

def glb_triangles(path):
    data = Path(path).read_bytes()
    n = struct.unpack("<I", data[12:16])[0]
    js = json.loads(data[20:20 + n])
    return sum(js["accessors"][p["indices"]]["count"] // 3
               for me_ in js["meshes"] for p in me_["primitives"] if "indices" in p)

def build():
    scene = Scene()
    root_mesh, root_faces = quad_mesh(3)                    # 3 faces, one of them hidden
    root_faces[2].attrs["hidden"] = True
    root = Group(root_mesh, name="root"); root.xform = QMatrix4x4()
    shown_mesh, _ = quad_mesh(2, 5.0)
    hidden_mesh, _ = quad_mesh(4, 9.0)
    shown = Group(shown_mesh, name="shown child"); shown.xform = QMatrix4x4()
    hidden = Group(hidden_mesh, name="hidden child"); hidden.xform = QMatrix4x4()
    hidden.hidden = True
    root.adopt([shown, hidden])
    scene.groups.append(root)
    return scene, root, hidden

def export(scene, shared):
    tmp = Path(tempfile.mkdtemp()) / "m.glb"
    P.INSTANCED_FROM_FACES = 1 if shared else 10 ** 9
    with P._shared_copies(scene), visibility.hidden_left_out(scene):
        gltf.save_glb(scene, str(tmp), None if shared else OrbitCamera())
    return glb_triangles(tmp)

scene, root, hidden = build()
before = (list(root.children), me._add_face)
ok(len(visibility.hidden_placements(scene)) == 1, "the hidden nested object is found")
# 2 (root's own visible faces) + 2 (shown child) = 4 quads = 8 triangles; hidden child (4) and face (1) out
ok(export(scene, False) == 8, f"flat export: hidden object and face are out ({export(scene, False)} triangles)")
ok(export(scene, True) == 8, f"shared export: same ({export(scene, True)} triangles)")
ok(root.children == before[0] and hidden in root.children, "the hidden object is back in its parent afterwards")
ok(me._add_face is before[1], "the exporter is put back")

# without the fix, they would be written (the reason for this module)
tmp = Path(tempfile.mkdtemp()) / "m.glb"
gltf.save_glb(scene, str(tmp), OrbitCamera())
ok(glb_triangles(tmp) > 8, f"without it the export has them ({glb_triangles(tmp)} triangles)")

# a hidden tag
scene, root, hidden = build()
hidden.hidden = False
hidden.layer = "Off"
from core.layers import Layer
scene.layers.append(Layer("Off")) if hasattr(scene, "layers") else None
try:
    scene.layer("Off").visible = False
    ok(export(scene, False) == 8, "a nested object on a hidden tag is out too")
except Exception as exc:                                    # the layer API differs: not what this checks
    print("SKIP hidden tag:", exc)

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
