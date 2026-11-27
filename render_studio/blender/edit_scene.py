# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender side of «Edit in Blender» (lights and materials).

Run by Blender with ``-- make <lights|materials> <in.json> <scene.blend>`` (a window opens with
the lights, or one sphere per material, ready to edit; the file is saved first so Ctrl+S works)
or ``-b scene.blend --python edit_scene.py -- read <lights|materials> <out.json>`` (the scene as
the person left it, as JSON for Render Studio to take back).
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

BLENDER_LIGHT = {"point": "POINT", "spot": "SPOT", "area": "AREA", "sun": "SUN"}
KIND_OF = {v: k for k, v in BLENDER_LIGHT.items()}


def _clear():
    """An empty scene in the Blender that is open. No ``read_factory_settings``: in a Blender with a window it
    resets the interface under the running script, and the operators that follow fail (the window then shows
    Blender's own start scene). The data is removed instead."""
    scene = bpy.context.scene
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.lights, bpy.data.cameras, bpy.data.materials, bpy.data.worlds,
                 bpy.data.images):
        for item in list(coll):
            coll.remove(item)
    return scene


def _principled(mat):
    """The material's Principled BSDF, made (with its output) when the Blender has not made the default
    nodes itself, as happens in a Blender with a window."""
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None:
        out = nt.nodes.new("ShaderNodeOutputMaterial")
    if not out.inputs["Surface"].is_linked:
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return bsdf


def _mesh_object(scene, name, verts, faces, location=(0.0, 0.0, 0.0), material=None, smooth=False):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    if smooth:
        me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    if material is not None:
        me.materials.append(material)
    ob = bpy.data.objects.new(name, me)
    ob.location = location
    scene.collection.objects.link(ob)
    return ob


def _box(size):
    h = size / 2.0
    v = [(x, y, z) for x in (-h, h) for y in (-h, h) for z in (-h, h)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return v, f


def _sphere(radius, seg=24, rings=12):
    v = [(0.0, 0.0, radius)]
    for r in range(1, rings):
        th = math.pi * r / rings
        for s_ in range(seg):
            ph = 2 * math.pi * s_ / seg
            v.append((radius * math.sin(th) * math.cos(ph), radius * math.sin(th) * math.sin(ph), radius * math.cos(th)))
    v.append((0.0, 0.0, -radius))
    f = [(0, 1 + (s_ + 1) % seg, 1 + s_) for s_ in range(seg)]
    for r in range(rings - 2):
        a = 1 + r * seg
        for s_ in range(seg):
            f.append((a + s_, a + (s_ + 1) % seg, a + seg + (s_ + 1) % seg, a + seg + s_))
    last, b = len(v) - 1, 1 + (rings - 2) * seg
    f += [(last, b + s_, b + (s_ + 1) % seg) for s_ in range(seg)]
    return v, [face[::-1] for face in f]      # facing outwards: bumps stand out and grass grows out, not in


def _stage(scene, size=14.0, cube=True):
    """A floor, a dim world, a camera and (``cube``, for the lights) a one-metre cube to see the light on."""
    mat = bpy.data.materials.new("Reference grey")
    _principled(mat).inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1.0)
    h = size / 2.0
    _mesh_object(scene, "Floor (reference, not saved)", [(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)],
                 [(0, 1, 2, 3)], material=mat)
    if cube:
        v, f = _box(1.0)
        _mesh_object(scene, "Cube 1 m (reference, not saved)", v, f, (0, 0, 0.5), mat)
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg is None:
        bg = world.node_tree.nodes.new("ShaderNodeBackground")
        wout = next((n for n in world.node_tree.nodes if n.type == "OUTPUT_WORLD"), None) or             world.node_tree.nodes.new("ShaderNodeOutputWorld")
        world.node_tree.links.new(bg.outputs["Background"], wout.inputs["Surface"])
    bg.inputs["Color"].default_value = (0.05, 0.055, 0.065, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    scene.world = world
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    scene.collection.objects.link(cam)
    cam.location = (6.0, -7.0, 4.0)
    cam.rotation_euler = (Vector((-6.0, 7.0, -3.5))).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in \
            bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys() else "BLENDER_EEVEE"
    except Exception:  # noqa: BLE001
        pass


def _look_through_the_camera():
    """Every 3D view in rendered shading (live), seen through the camera: of every screen, since the
    workspace just chosen is not on the window yet."""
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            try:
                space = area.spaces[0]
                space.shading.type = "RENDERED"                    # the scene's own lights, not a studio HDRI
                if space.region_3d is not None:
                    space.region_3d.view_perspective = "CAMERA"
            except Exception:  # noqa: BLE001 - the window is there anyway
                pass



_LSKIP = {"name", "name_full", "rna_type", "type", "energy", "color", "shadow_soft_size", "spot_size", "spot_blend",
          "shape", "size", "size_y", "spread", "angle", "use_shadow", "users", "session_uid", "is_evaluated",
          "original", "tag", "is_runtime_data", "use_fake_user", "library", "id_type", "is_embedded_data",
          "is_missing", "override_library", "preview", "asset_data", "use_extra_user", "library_weak_reference",
          "is_library_indirect", "node_tree", "animation_data", "use_nodes"}


def _light_props(data, skip):
    d = {}
    for p in data.bl_rna.properties:
        if p.identifier in skip or p.is_readonly or p.type not in ("BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"):
            continue
        try:
            d[p.identifier] = _plain(getattr(data, p.identifier))
        except Exception:  # noqa: BLE001
            continue
    nt = getattr(data, "node_tree", None)
    if getattr(data, "use_nodes", False) and nt is not None:
        d["nodes"] = _tree_sig(nt)
    return d


def _special_sig(obj):
    """What a light has that Render Studio's light format does not (its nodes, its other settings)."""
    return json.dumps(_light_props(obj.data, _LSKIP), sort_keys=True, default=str)


def _full_sig(obj):
    """Everything of the light: its settings, its nodes and where it is."""
    d = _light_props(obj.data, {"name", "name_full", "rna_type", "users", "session_uid", "is_evaluated", "original", "tag",
                                "is_runtime_data", "use_fake_user", "library", "id_type", "is_embedded_data", "is_missing",
                                "override_library", "preview", "asset_data", "use_extra_user", "library_weak_reference",
                                "is_library_indirect", "animation_data"})
    d.update(energy=round(obj.data.energy, 4), color=_plain(obj.data.color), shadow=bool(obj.data.use_shadow),
             m=[[round(c, 4) for c in row] for row in obj.matrix_world])
    return json.dumps(d, sort_keys=True, default=str)


def _load_light_package(pkg):
    import base64
    import tempfile
    path = os.path.join(tempfile.mkdtemp(prefix="rs-light-"), "light.blend")
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(pkg["blend"]))
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n == pkg["object"]]
    return dst.objects[0] if dst.objects else None


def _write_light_package(obj):
    import base64
    import tempfile
    path = os.path.join(tempfile.mkdtemp(prefix="rs-light-"), "light.blend")
    bpy.data.libraries.write(path, {obj}, path_remap="ABSOLUTE", compress=True)
    with open(path, "rb") as fh:
        return {"v": 1, "object": obj.name, "blend": base64.b64encode(fh.read()).decode("ascii")}


def make_lights(lights):
    scene = _clear()
    _stage(scene)
    for i, lt in enumerate(lights):
        if (lt.get("package") or {}).get("blend"):         # edited in Blender before: it opens as it was left
            try:
                obj = _load_light_package(lt["package"])
            except Exception:  # noqa: BLE001 - Render Studio's own settings then
                import traceback
                print(traceback.format_exc())
                obj = None
            if obj is not None:
                obj.name = lt.get("name") or obj.name
                scene.collection.objects.link(obj)
                obj["rs_id"] = lt.get("id", "")
                obj["rs_proxy"] = True
                obj.hide_render = not lt.get("on", True)
                obj.location = Vector(lt.get("pos") or obj.location)
                bpy.context.view_layer.update()                     # its matrix is current before it is measured
                obj.data["rs_lsig"] = _special_sig(obj)
                obj["rs_lfull"] = _full_sig(obj)
                continue
        kind = BLENDER_LIGHT.get(lt.get("type"), "POINT")
        name = lt.get("name") or f"{lt.get('type', 'point').capitalize()} {i + 1}"
        data = bpy.data.lights.new(name, type=kind)
        data.energy = float(lt.get("energy", 0.0))
        data.color = tuple(float(c) for c in (lt.get("color") or (1.0, 1.0, 1.0))[:3])
        data.use_shadow = bool(lt.get("shadow", True))
        if kind in ("POINT", "SPOT"):
            data.shadow_soft_size = float(lt.get("radius", 0.05))
        if kind == "SPOT":
            data.spot_size = math.radians(float(lt.get("spot_angle", 60.0)))
            data.spot_blend = float(lt.get("spot_blend", 0.25))
        elif kind == "AREA":
            shape = str(lt.get("shape", "square")).upper()
            data.shape = shape if shape in ("SQUARE", "RECTANGLE", "DISK", "ELLIPSE") else "SQUARE"
            data.size = float(lt.get("size", 0.6))
            if data.shape in ("RECTANGLE", "ELLIPSE"):
                data.size_y = float(lt.get("size_y", data.size))
            data.spread = math.radians(float(lt.get("spread", 180.0)))
        elif kind == "SUN":
            data.angle = math.radians(float(lt.get("sun_angle", 0.53)))
        obj = bpy.data.objects.new(name, data)
        scene.collection.objects.link(obj)
        obj["rs_id"] = lt.get("id", "")
        obj.hide_render = not lt.get("on", True)
        x, y, z = (Vector(a) for a in lt["basis"])
        p = lt.get("pos") or (0.0, 0.0, 0.0)
        obj.matrix_world = Matrix(((x[0], y[0], z[0], p[0]), (x[1], y[1], z[1], p[1]),
                                   (x[2], y[2], z[2], p[2]), (0.0, 0.0, 0.0, 1.0)))
        obj.data["rs_lsig"] = _special_sig(obj)             # what it is now: a change from it is the person's


def _reference_special_sig(kind):
    """The special signature of a fresh Blender light of ``kind``: what a light that has had nothing done to it has."""
    cache = _reference_special_sig.__dict__.setdefault("cache", {})
    if kind not in cache:
        data = bpy.data.lights.new("rs-reference", type=kind)
        tmp = bpy.data.objects.new("rs-reference", data)
        cache[kind] = _special_sig(tmp)
        bpy.data.objects.remove(tmp)
        bpy.data.lights.remove(data)
    return cache[kind]


def _baseline_full_sigs(baseline):
    """{light id: full signature} of the proxies of ``baseline`` (the lights Render Studio sent) as their packages hold
    them, placed where the list says: what a proxy that nobody touched looks like."""
    out = {}
    for lt in baseline or ():
        pkg = lt.get("package")
        if not (pkg or {}).get("blend"):
            continue
        try:
            obj = _load_light_package(pkg)
            if obj is None:
                continue
            bpy.context.scene.collection.objects.link(obj)
            obj.location = Vector(lt.get("pos") or obj.location)
            bpy.context.view_layer.update()
            out[lt.get("id", "")] = _full_sig(obj)
            bpy.data.objects.remove(obj)
        except Exception:  # noqa: BLE001 - that proxy is then taken as changed only if it has a package of its own
            continue
    return out


def read_lights(baseline=None):
    """The lights of the scene as the person left it. ``baseline``: the lights Render Studio sent (their payload), to
    tell what the person changed. In a scene that is the whole render (the model, the sky, the ground) only Render
    Studio's free lights, and lights the person added, are read."""
    out = []
    proxy_sigs = None
    for obj in bpy.data.objects:
        if obj.type != "LIGHT":
            continue
        if obj.get("rs_source") in ("object", "tab", "ingetrazo"):
            continue                                   # not Render Studio's free lights: they are not edited here
        if obj.name.startswith("IngeTrazo "):
            continue                                   # the look's own sun, moon…
        d = obj.data
        kind = KIND_OF.get(d.type)
        if kind is None:
            continue
        m = obj.matrix_world
        x, y, z = (m.col[i].to_3d().normalized() for i in range(3))
        item = {"id": str(obj.get("rs_id", "")), "name": obj.name, "type": kind,
                "on": not obj.hide_render, "pos": list(m.translation),
                "x": list(x), "y": list(y), "z": list(z),
                "energy": d.energy, "color": list(d.color), "shadow": bool(d.use_shadow)}
        if d.type in ("POINT", "SPOT"):
            item["radius"] = d.shadow_soft_size
        if d.type == "SPOT":
            item["spot_angle"] = math.degrees(d.spot_size)
            item["spot_blend"] = d.spot_blend
        if d.type == "AREA":
            item["shape"] = d.shape.lower()
            item["size"] = d.size
            item["size_y"] = d.size_y
            item["spread"] = math.degrees(d.spread)
        if d.type == "SUN":
            item["sun_angle"] = math.degrees(d.angle)
        # A light with something Render Studio's format has no place for (nodes, other settings), or one that was
        # already a Blender light and has been changed, comes back whole, as a proxy.
        was_proxy = bool(obj.get("rs_proxy"))
        if d.get("rs_lsig") is not None:                # opened from a scene of this tool: its own baseline
            special = d.get("rs_lsig") != _special_sig(obj)
            changed_proxy = was_proxy and obj.get("rs_lfull") != _full_sig(obj)
        else:                                          # the render's scene: compared with an untouched light, and the packages
            special = _special_sig(obj) != _reference_special_sig(d.type) and not was_proxy
            if was_proxy:
                if proxy_sigs is None:
                    proxy_sigs = _baseline_full_sigs(baseline)
                want = proxy_sigs.get(str(obj.get("rs_id", "")))
                changed_proxy = want is None or want != _full_sig(obj)
            else:
                changed_proxy = False
        if special or changed_proxy:
            try:
                item["package"] = _write_light_package(obj)
            except Exception:  # noqa: BLE001 - the numbers still come back
                import traceback
                print(traceback.format_exc())
        out.append(item)
    return out


def _lay_out_nodes(mat, bsdf):
    """The nodes side by side, so the Shader editor shows them apart."""
    out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
    bsdf.location = (0.0, 0.0)
    if out is not None:
        out.location = (320.0, 0.0)


def _arrange_nodes(tree):
    """The nodes in columns, each one left of what it feeds (the render's steps add theirs on top of each other).
    The positions do not count as a change of the material."""
    out = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None:
        return
    depth = {out.name: 0}
    for _pass in range(len(tree.nodes)):                       # the longest way to the output
        moved = False
        for link in tree.links:
            a, b = link.from_node.name, link.to_node.name
            if b in depth and depth.get(a, -1) < depth[b] + 1:
                depth[a] = depth[b] + 1
                moved = True
        if not moved:
            break
    columns = {}
    for node in tree.nodes:
        columns.setdefault(depth.get(node.name, 0), []).append(node)
    for column, nodes in columns.items():                      # each column centred, so all of them are in sight
        for row, node in enumerate(nodes):
            node.location = (320.0 - 340.0 * column, 170.0 * (len(nodes) - 1) - 340.0 * row)


def _picture_node(mat, bsdf, tex):
    """The material's own picture (``tex`` = {path}) on the Base Color, as the render has it."""
    path = (tex or {}).get("path")
    if not path or not os.path.isfile(path):
        return None
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    node = nodes.new("ShaderNodeTexImage")
    node.location = (-380.0, 0.0)
    node.label = "Picture of the material"
    try:
        node.image = bpy.data.images.load(path, check_existing=True)
    except RuntimeError:
        nodes.remove(node)
        return None
    links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
    return node


def _tile(sp):
    """(width, height) in metres of one repeat of the material's picture."""
    tex = sp.get("texture") or {}
    return max(0.01, float(tex.get("sw") or 1.0)), max(0.01, float(tex.get("sh") or 1.0))


def _sphere_uvs(me, radius, tile):
    """UVs as the model's export makes them, counted in repeats of the picture (so the nodes need no Mapping
    and the material reads the same on the model): metres along the equator and from pole to pole."""
    sw, sh = tile
    layer = me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        cos = [me.vertices[me.loops[i].vertex_index].co for i in poly.loop_indices]
        phis = [math.atan2(c.y, c.x) % (2 * math.pi) if math.hypot(c.x, c.y) > 1e-6 else None for c in cos]
        known = [p for p in phis if p is not None]
        if max(known) - min(known) > math.pi:                  # a face on the seam: all on the same side of it
            phis = [None if p is None else (p + 2 * math.pi if p < math.pi else p) for p in phis]
            known = [p for p in phis if p is not None]
        middle = sum(known) / len(known)                       # (a pole has no angle of its own)
        for i, c, phi in zip(poly.loop_indices, cos, phis):
            down = math.acos(max(-1.0, min(1.0, c.z / radius)))
            layer.data[i].uv = ((middle if phi is None else phi) * radius / sw, (math.pi - down) * radius / sh)


def _show_shader_editor(scene):
    """In a Blender with a window: the Shading workspace (3D view and Shader editor) with the first
    material's sphere active, so its nodes are in sight."""
    try:
        win = bpy.context.window
        ws = bpy.data.workspaces.get("Shading")
        sphere = next((o for o in scene.objects if o.type == "MESH" and o.data.materials and
                       o.data.materials[0] is not None and o.data.materials[0].get("rs_name")), None)
        if sphere is not None:
            bpy.context.view_layer.objects.active = sphere
            sphere.select_set(True)
        if win is not None and ws is not None:
            win.workspace = ws
            return True
        if win is not None:                           # no Shading workspace: the timeline becomes the editor
            for area in win.screen.areas:
                if area.type in ("TIMELINE", "DOPESHEET_EDITOR"):
                    area.type = "NODE_EDITOR"
                    area.spaces[0].tree_type = "ShaderNodeTree"
                    return True
    except Exception:  # noqa: BLE001 - the window is there anyway
        pass
    return False


def _studio(folder):
    """The render's own scene script (``studio_scene.py``, copied next to the data with IngeTrazo's
    ``render_scene.py``) as a module, without running its main()."""
    path = os.path.join(folder, "studio_scene.py")
    if not os.path.isfile(path) or not os.path.isfile(os.path.join(folder, "render_scene.py")):
        return None
    with open(path, encoding="utf-8") as fh:
        src = fh.read().rstrip().rsplit("\nmain()", 1)[0]
    ns = {"__name__": "studio_scene", "__file__": path}
    exec(compile(src, path, "exec"), ns)
    return ns


def _grass_patch(scene, sp, mat, at, folder):
    """A square of the material, 2 m wide, with the grass of the render grown on it (its modifier and
    tufts: the same ``build_grass`` the render uses), next to the sphere."""
    studio = _studio(folder)
    if studio is None:
        return None
    me = bpy.data.meshes.new(sp["name"] + " patch")
    me.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    me.uv_layers.new(name="UVMap")
    for loop in me.loops:
        co = me.vertices[loop.vertex_index].co
        me.uv_layers[0].data[loop.index].uv = (co.x / _tile(sp)[0], co.y / _tile(sp)[1])
    me.materials.append(mat)
    ob = bpy.data.objects.new(sp["name"] + " patch", me)
    ob.location = at
    scene.collection.objects.link(ob)
    studio["build_grass"]({mat.name: sp["grass"]}, 1.0, only=[ob])
    return ob



# ---- the Blender material as a package: what the person leaves in Blender comes back whole ------------------------
#
# A material edited in Blender is kept in the document as a small .blend (base64) holding that material (its
# whole node tree), and for grass the geometry-nodes group that grows it and its tuft. The render appends them in
# place of the material it would have made from the editor's settings (``studio_scene.apply_blender_packages``).

_SIG_SKIP = {"name", "label", "location", "width", "height", "dimensions", "select", "show_options", "show_preview",
             "show_texture", "hide", "parent", "internal_links", "inputs", "outputs", "rna_type", "type", "color",
             "use_custom_color", "bl_idname", "bl_label", "bl_description", "bl_icon", "bl_static_type",
             "bl_width_default", "bl_width_min", "bl_width_max", "bl_height_default", "bl_height_min",
             "bl_height_max", "width_hidden"}


def _plain(v):
    if isinstance(v, float):
        return round(v, 5)
    if isinstance(v, str) or v is None or isinstance(v, (bool, int)):
        return v
    if hasattr(v, "name") and hasattr(v, "bl_rna") and not hasattr(v, "__len__"):
        return "ID:" + str(v.name)                    # a material, an object, an image: by name
    try:
        return [_plain(c) for c in v]
    except TypeError:
        return str(v)


def _node_sig(n):
    d = {"t": n.bl_idname, "mute": bool(n.mute)}
    for p in n.bl_rna.properties:
        if p.identifier in _SIG_SKIP or p.is_readonly or p.type not in ("BOOLEAN", "INT", "FLOAT", "STRING", "ENUM", "POINTER"):
            continue
        try:
            d[p.identifier] = _plain(getattr(n, p.identifier))
        except Exception:  # noqa: BLE001
            continue
    d["in"] = {s.identifier: _plain(s.default_value) for s in n.inputs
               if not s.is_linked and hasattr(s, "default_value")}
    if n.bl_idname == "ShaderNodeValToRGB":
        d["ramp"] = [[round(e.position, 5), _plain(e.color)] for e in n.color_ramp.elements]
    if n.bl_idname == "ShaderNodeTexImage" and n.image is not None:
        d["img"] = [n.image.name, os.path.normcase(os.path.normpath(bpy.path.abspath(n.image.filepath)))]   # (saving makes it relative)
    return d


def _tree_sig(tree):
    """What a node tree is, as text: the nodes (kind, settings, unlinked values) and the links. Where the nodes
    sit does not count."""
    nodes = {n.name: _node_sig(n) for n in tree.nodes}
    links = sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in tree.links)
    return json.dumps([nodes, links], sort_keys=True, default=str)


def _load_package(pkg):
    """(material, group or None, tuft object or None) appended from a package, not yet renamed or placed."""
    import base64
    import tempfile
    path = os.path.join(tempfile.mkdtemp(prefix="rs-pkg-"), "package.blend")
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(pkg["blend"]))
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.materials = [n for n in src.materials if n == pkg["material"]]
        dst.node_groups = [n for n in src.node_groups if pkg.get("group") and n == pkg["group"]]
        dst.objects = [n for n in src.objects if pkg.get("tuft") and n == pkg["tuft"]]
    mat = dst.materials[0] if dst.materials else None
    group = dst.node_groups[0] if dst.node_groups else None
    tuft = dst.objects[0] if dst.objects else None
    return mat, group, tuft


def _write_package(mat, group=None, tuft=None):
    import base64
    import tempfile
    path = os.path.join(tempfile.mkdtemp(prefix="rs-pkg-"), "package.blend")
    ids = {mat}
    if group is not None:
        ids.add(group)
    if tuft is not None:
        ids.add(tuft)
    bpy.data.libraries.write(path, ids, path_remap="ABSOLUTE", compress=True)
    with open(path, "rb") as fh:
        blend = base64.b64encode(fh.read()).decode("ascii")
    return {"v": 1, "material": mat.name, "group": group.name if group is not None else None,
            "tuft": tuft.name if tuft is not None else None, "blend": blend}


def _patch_group(patch):
    """(node group, tuft object) of the grass modifier on a patch, or (None, None)."""
    mod = next((m for m in patch.modifiers if m.type == "NODES" and m.node_group is not None), None) if patch else None
    if mod is None:
        return None, None
    tuft = None
    for n in mod.node_group.nodes:
        if n.bl_idname == "GeometryNodeObjectInfo" and n.inputs["Object"].default_value is not None:
            tuft = n.inputs["Object"].default_value
            break
    return mod.node_group, tuft


def _patch_from_group(scene, sp, mat, group, tuft, at):
    """The patch of grass with a stored group (not built again): the modifier and its tuft."""
    me = bpy.data.meshes.new(sp["name"] + " patch")
    me.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    me.uv_layers.new(name="UVMap")
    for loop in me.loops:
        co = me.vertices[loop.vertex_index].co
        me.uv_layers[0].data[loop.index].uv = (co.x / _tile(sp)[0], co.y / _tile(sp)[1])
    me.materials.append(mat)
    ob = bpy.data.objects.new(sp["name"] + " patch", me)
    ob.location = at
    scene.collection.objects.link(ob)
    hidden = bpy.data.collections.new("studio grass tufts")
    scene.collection.children.link(hidden)
    hidden.hide_render = True
    hidden.hide_viewport = True
    if tuft is not None:
        hidden.objects.link(tuft)
    mod = ob.modifiers.new("Studio grass", "NODES")
    mod.node_group = group
    return ob


def _as_exported(mat, bsdf, sp):
    """The material as the model arrives in Blender: IngeTrazo's finish (its name on the material, its numbers
    on the BSDF, as the glTF export writes them) and the model's opacity."""
    finish, values = sp.get("finish"), sp.get("finish_pbr")
    if not finish or not values:
        return
    mat["ingetrazo_finish"] = finish
    rough, metal, transmission, ior = (float(v) for v in values)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["IOR"].default_value = ior
    for name in ("Transmission Weight", "Transmission"):
        if name in bsdf.inputs:
            bsdf.inputs[name].default_value = transmission
            break
    if sp.get("opacity") is not None:
        bsdf.inputs["Alpha"].default_value = max(0.0, min(1.0, float(sp["opacity"])))


def _as_the_render_makes_it(studio, mat, sp):
    """The material with every step of the render's own pipeline on it, so what Blender shows is what the render
    would have made from the editor's settings: the finish of its type (glass, water, glow), its roughness, metal and
    relief, the maps that drive them, the picture's adjustments and its texture set. Then the person edits THAT."""
    spec = dict(sp.get("spec") or {})       # its own (or named) render settings; none: IngeTrazo's finish alone
    spec.pop("blender", None)
    specs = {mat.name: spec} if spec else {}
    names = {mat.name}
    if specs:
        studio["mark_material_types"](specs, names)
    studio["finishes_for"](names)
    sets = studio["match_texture_sets"](sp.get("pbr") or {})
    if specs:
        studio["apply_material_specs"](specs, sets, names)
    mine = {k: v for k, v in sets.items() if k in names}
    if mine:
        studio["apply_texture_sets"](mine, specs)
    if specs:
        studio["apply_last_touches"](specs, names)
    return True


def make_materials(specs, folder=None):
    scene = _clear()
    studio = None
    _stage(scene, 40.0, cube=False)
    n = len(specs)
    cols = max(1, min(8, int(math.ceil(math.sqrt(n)))))
    shown = []                                      # what the camera frames
    for i, sp in enumerate(specs):
        loaded = None
        if (sp.get("package") or {}).get("blend"):            # edited in Blender before: it opens as it was left
            try:
                loaded = _load_package(sp["package"])
            except Exception:  # noqa: BLE001 - the editor's settings then
                import traceback
                print(traceback.format_exc())
        group = tuft = None
        if loaded and loaded[0] is not None:
            mat, group, tuft = loaded
            mat.name = sp["name"]
        else:
            mat = bpy.data.materials.new(sp["name"])
            b = _principled(mat)
            _lay_out_nodes(mat, b)
            r, g, bl = (sp.get("color") or (0.8, 0.8, 0.8))[:3]
            b.inputs["Base Color"].default_value = (r, g, bl, 1.0)
            _picture_node(mat, b, sp.get("texture"))
            b.inputs["Roughness"].default_value = float(sp.get("roughness", 0.5))
            b.inputs["Metallic"].default_value = float(sp.get("metallic", 0.0))
            glow = float(sp.get("glow", 0.0))
            b.inputs["Emission Color"].default_value = (r, g, bl, 1.0)
            b.inputs["Emission Strength"].default_value = glow
            _as_exported(mat, b, sp)
            mat.diffuse_color = (r, g, bl, 1.0)
            if studio is None and folder:
                try:
                    studio = _studio(folder) or False
                except Exception:  # noqa: BLE001 - the plain material then
                    import traceback
                    print(traceback.format_exc())
                    studio = False
            if studio:
                try:
                    _as_the_render_makes_it(studio, mat, sp)
                except Exception:  # noqa: BLE001 - the plain material then
                    import traceback
                    print(traceback.format_exc())
            _arrange_nodes(mat.node_tree)
        mat["rs_name"] = sp["name"]
        v, f = _sphere(0.5)
        ball = _mesh_object(scene, sp["name"], v, f, ((i % cols) * 1.3 - cols * 0.65, (i // cols) * -1.3, 0.5), mat, True)
        _sphere_uvs(ball.data, 0.5, _tile(sp))
        shown.append(ball)
        at = ((i % cols) * 1.3 - cols * 0.65 + 2.2, (i // cols) * -1.3, 0.0)
        patch = None
        if group is not None:
            patch = _patch_from_group(scene, sp, mat, group, tuft, at)
        elif sp.get("grass") and folder:
            try:
                patch = _grass_patch(scene, sp, mat, at, folder)
            except Exception:  # noqa: BLE001 - the sphere is there anyway
                import traceback
                print(traceback.format_exc())
        mat["rs_sig"] = _tree_sig(mat.node_tree)                # what it is now: a change from it is the person's
        mat["rs_open"] = json.dumps(_numbers(mat))              # …and its three numbers
        if patch is not None:
            shown.append(patch)
        g0, _t0 = _patch_group(patch)
        if patch is not None and g0 is not None:
            patch["rs_gsig"] = _tree_sig(g0)
    # a sun and a soft fill, so the spheres are lit
    for name, kind, e, loc in (("Sun", "SUN", 3.0, (4, -4, 6)),):
        d = bpy.data.lights.new(name, kind)
        d.energy = e
        o = bpy.data.objects.new(name, d)
        scene.collection.objects.link(o)
        o.location = loc
        o.rotation_euler = (Vector(loc) * -1).to_track_quat("-Z", "Y").to_euler()
        o["rs_reference"] = True
    _frame(scene, shown)


def _frame(scene, objects):
    """The camera on the spheres (and grass patches), all of them in the picture."""
    bpy.context.view_layer.update()
    points = [ob.matrix_world @ Vector(c) for ob in objects for c in ob.bound_box]
    if not points:
        return
    low = Vector(min(p[i] for p in points) for i in range(3))
    high = Vector(max(p[i] for p in points) for i in range(3))
    centre, radius = (low + high) / 2.0, max(0.5, (high - low).length / 2.0)
    cam = scene.camera
    cam.data.lens = 50.0
    away = Vector((0.0, -1.0, 0.5)).normalized()
    cam.location = centre + away * (radius * 3.6)
    cam.rotation_euler = (-away).to_track_quat("-Z", "Y").to_euler()


def _numbers(mat):
    """Roughness, metal and glow of a material's Principled BSDF, as Render Studio takes them."""
    b = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if b is None:
        return {"roughness": 0.5, "metallic": 0.0, "glow": 0.0}
    em = b.inputs["Emission Color"].default_value
    return {"roughness": b.inputs["Roughness"].default_value, "metallic": b.inputs["Metallic"].default_value,
            "glow": b.inputs["Emission Strength"].default_value if (em[0] + em[1] + em[2]) > 0.0 else 0.0}


def read_materials():
    out = []
    for mat in bpy.data.materials:
        name = mat.get("rs_name")
        if not name or not mat.use_nodes:
            continue
        item = dict(_numbers(mat), name=name)
        if mat.get("rs_open"):
            item["opened"] = json.loads(mat["rs_open"])         # only what differs from this is the person's
        if mat.get("ingetrazo_finish"):
            item["finish"] = str(mat["ingetrazo_finish"])
        # what is different from the nodes the material was opened with comes back whole, as a package
        patch = bpy.data.objects.get(name + " patch")
        group, tuft = _patch_group(patch)
        changed = mat.get("rs_sig") is not None and mat.get("rs_sig") != _tree_sig(mat.node_tree)
        gchanged = group is not None and patch.get("rs_gsig") is not None and patch.get("rs_gsig") != _tree_sig(group)
        if changed or gchanged:
            try:
                item["package"] = _write_package(mat, group, tuft)
                missing = [i.name for i in bpy.data.images if i.source == "GENERATED" and i.users]
                if missing:
                    item["package_warning"] = missing
            except Exception:  # noqa: BLE001 - the three numbers still come back
                import traceback
                print(traceback.format_exc())
        out.append(item)
    return out


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    mode, kind = argv[0], argv[1]
    if mode == "make":
        try:
            data = json.load(open(argv[2], encoding="utf-8"))
            if kind == "lights":
                make_lights(data)
            else:
                make_materials(data, os.path.dirname(os.path.abspath(argv[2])))
            bpy.ops.wm.save_as_mainfile(filepath=argv[3])
            if kind == "materials":
                _show_shader_editor(bpy.context.scene)      # the Shading workspace: the view and the nodes
            _look_through_the_camera()
            # again once the window has changed workspace
            bpy.app.timers.register(lambda: (_look_through_the_camera(), None)[1], first_interval=0.3)
        except Exception:  # noqa: BLE001 - say it where the person can find it
            import traceback
            text = traceback.format_exc()
            print(text)
            try:
                with open(os.path.join(os.path.dirname(argv[3]), "error.txt"), "w", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError:
                pass
            raise
        if os.environ.get("RENDER_STUDIO_EDIT_QUIT"):          # tests: open, build, save, close
            bpy.app.timers.register(lambda: (bpy.ops.wm.quit_blender(), None)[1], first_interval=1.0)
    elif mode == "read":
        baseline = None
        if kind == "lights" and len(argv) > 3 and os.path.isfile(argv[3]):
            baseline = json.load(open(argv[3], encoding="utf-8"))
        data = read_lights(baseline) if kind == "lights" else read_materials()
        json.dump(data, open(argv[2], "w", encoding="utf-8"))


main()
