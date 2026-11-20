"""A big model is exported with its copies shared (not as one flat list of world triangles);
a small one keeps the export with the camera. Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from PySide6.QtGui import QMatrix4x4, QVector3D
import formats.gltf as gltf
from core.camera import OrbitCamera
from core.group import Group, copy_group
from core.mesh import Mesh
from core.scene import Scene
from render_studio import panel as P

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

def component(name, n_quads):
    m = Mesh()
    for i in range(n_quads):
        m.add_face([QVector3D(i, 0, 0), QVector3D(i + 1, 0, 0), QVector3D(i + 1, 1, 0), QVector3D(i, 1, 0)])
    g = Group(m, name=name)
    g.xform = QMatrix4x4()
    return g

scene = Scene()
base = component("chair", 8)
scene.groups.append(base)
for k in range(1, 4):
    scene.groups.append(copy_group(base, QVector3D(0, 5 * k, 0)))      # 4 placements of 8 faces
ok(P.expanded_faces(scene) == 32, f"faces counted over every copy ({P.expanded_faces(scene)})")
base_mesh_faces = len(base.mesh.faces)
ok(base_mesh_faces == 8, "…while the shared mesh has only 8")

calls = []
real = gltf.save_glb
def recorder(sc, path, face_me=None, only=None):
    calls.append(face_me)
    Path(path).write_bytes(b"glb")
gltf.save_glb = recorder
cam = OrbitCamera()
tmp = Path(tempfile.mkdtemp())
try:
    P.INSTANCED_FROM_FACES = 1000                     # a small model: as before
    P.write_studio_job(scene, cam, tmp / "small", "clear", {}, engine="eevee", quality=0, width=320, height=200)
    ok(len(calls) == 1 and calls[-1] is not None, "a small model is exported with the camera, as before")
    ok(gltf.save_glb is recorder, "…and the writer is put back")

    P.INSTANCED_FROM_FACES = 10                       # 32 faces over the line: shared copies
    P.write_studio_job(scene, cam, tmp / "big", "clear", {}, engine="eevee", quality=0, width=320, height=200)
    ok(len(calls) == 2 and calls[-1] is None, "a big model is exported with its copies shared (no camera)")
    ok(gltf.save_glb is recorder, "…and the writer is put back")

    # the live view's reload with the model kept does not export again
    (tmp / "big" / "model.glb").write_bytes(b"glb")
    n = len(calls)
    P.write_studio_job(scene, cam, tmp / "big", "clear", {}, engine="eevee", quality=0, width=320, height=200,
                       live=True, serve=True, reuse_model=True)
    ok(len(calls) == n, "a reload that keeps the model still does not export it")
finally:
    gltf.save_glb = real

print("FAILED" if fails else "ALL PASSED", len(fails))
sys.exit(1 if fails else 0)
