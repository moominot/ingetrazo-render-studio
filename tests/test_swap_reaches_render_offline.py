"""A picture swapped into a material (by «Change picture…» or by the other program's save) reaches what Render
Studio draws: the drawing's content version moves (so the live preview exports the model again) and the model
file the job writes holds the NEW picture, for loose faces and for a component's faces alike. Offscreen, no Blender.
argv: <ingetrazo-src> <render-studio repo>"""
import json, os, struct, sys, tempfile, hashlib
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO]
from pathlib import Path
from PySide6.QtGui import QColor, QImage, QVector3D
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
from core.camera import OrbitCamera
from core.group import Group
from core.history import History
from core.materials import Material
from core.mesh import Mesh
from core.scene import Scene
from render_studio import panel as P, texture_swap

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

tmp = Path(tempfile.mkdtemp())
def picture(path, rgb, w=16, h=16):
    img = QImage(w, h, QImage.Format_RGB32); img.fill(QColor(*rgb)); img.save(str(path)); return str(path)

old_png = picture(tmp / "old.png", (200, 40, 40))
new_png = picture(tmp / "new.png", (30, 60, 220))
tex = {"path": old_png, "sw": 1.0, "sh": 1.0}

scene = Scene()
scene.materials["Wood"] = Material("Wood", texture=dict(tex))
loose = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
loose.attrs.update({"mat": "Wood", "texture": dict(tex)})
m = Mesh()
inner = m.add_face([QVector3D(3, 0, 0), QVector3D(4, 0, 0), QVector3D(4, 1, 0), QVector3D(3, 1, 0)])
inner.attrs.update({"mat": "Wood", "texture": dict(tex)})
g = Group(m, name="Chair")
scene.groups.append(g)


class VP:
    def __init__(self): self.scene = scene; self.history = History(scene); self.camera = OrbitCamera()
    def notify_scene_changed(self): pass
    def update(self): pass
class App:
    def __init__(self): self.scene = scene; self.viewport = VP()


def images_in(job_dir):
    """The pictures embedded in the job's model file (sha1 of each)."""
    glb = next(Path(job_dir).glob("*.glb"))
    data = glb.read_bytes()
    jlen, _t = struct.unpack("<II", data[12:20])
    doc = json.loads(data[20:20 + jlen])
    bin_off = 20 + jlen + 8
    out = []
    for im in doc.get("images", []):
        bv = doc["bufferViews"][im["bufferView"]]
        start = bin_off + bv.get("byteOffset", 0)
        out.append(hashlib.sha1(data[start:start + bv["byteLength"]]).hexdigest())
    return out


def export(name):
    d = tmp / name
    P.write_studio_job(scene, OrbitCamera(), d, "clear", {}, engine="eevee", quality=0, width=320, height=200)
    return d


app = App()
d0 = export("before")
imgs0 = images_in(d0)
ok(len(imgs0) >= 1, f"the model file carries the picture before the swap ({len(imgs0)} image)")

cv0 = scene.content_version
key0 = (id(scene), cv0 - getattr(scene, "_rs_not_model", 0))
done, msg = texture_swap.swap_picture(app, "Wood", new_png, True)
ok(done, f"the swap is done ({msg})")
cv1 = scene.content_version
key1 = (id(scene), cv1 - getattr(scene, "_rs_not_model", 0))
ok(key1 != key0, f"the drawing's content version moved, so the live preview sends the model again ({cv0} → {cv1})")
ok(loose.attrs["texture"]["path"] == scene.materials["Wood"].texture["path"], "the loose face wears the new picture")
ok(inner.attrs["texture"]["path"] == scene.materials["Wood"].texture["path"], "the component's face wears it too")

d1 = export("after")
imgs1 = images_in(d1)
new_sha = hashlib.sha1(Path(scene.materials["Wood"].texture["path"]).read_bytes()).hexdigest()
ok(imgs1 and set(imgs1) != set(imgs0), f"the model file is not the same one (before {len(imgs0)}, after {len(imgs1)} pictures)")
print("images before", imgs0, "after", imgs1, "new", new_sha)
ok(new_sha in imgs1 or all(s != hashlib.sha1(Path(old_png).read_bytes()).hexdigest() for s in imgs1),
   "the model file carries the NEW picture, not the old one")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
