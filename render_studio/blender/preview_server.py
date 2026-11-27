# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender side of the material editor's rendered sample: a Blender that stays open in the background and
renders one material on a sphere each time it is asked.

Run: ``blender -b --factory-startup --python preview_server.py``. It reads one job per line from its input
(``{"id", "payload", "out", "width", "height"}``: ``payload`` is the file «Edit in Blender» sends, with one
material) and says ``RSPREVIEW {...}`` for each. The material is made by the same code as «Edit in Blender»
(``edit_scene.make_materials``), which uses the render's own steps."""
import json
import os
import sys
import time

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = 32


def _edit_scene():
    """edit_scene.py as a module, without running its main()."""
    path = os.path.join(HERE, "edit_scene.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read().rstrip().rsplit("\nmain()", 1)[0]
    ns = {"__name__": "edit_scene", "__file__": path}
    exec(compile(src, path, "exec"), ns)
    return ns


def _engine(scene):
    names = bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys()
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in names else "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = SAMPLES


def _the_sphere(scene):
    return next(o for o in scene.objects if o.type == "MESH" and o.data.materials and o.data.materials[0] is not None
                and o.data.materials[0].get("rs_name") and not o.name.endswith(" patch"))


def _outwards(group):
    """The grass's blades along the surface's own direction. The render grows them straight up, which on flat
    ground is the same; on the sample's sphere those underneath would grow into it."""
    nodes, links = group.nodes, group.links
    for inst in [n for n in nodes if n.bl_idname == "GeometryNodeInstanceOnPoints"]:
        points = next((l.from_node for l in inst.inputs["Points"].links), None)
        turn = next(iter(inst.inputs["Rotation"].links), None)
        if points is None or turn is None:
            continue
        random_turn, users = turn.from_socket, [l.to_socket for l in inst.outputs["Instances"].links]
        links.remove(turn)
        for old in list(inst.outputs["Instances"].links):                   # (the join takes many: take these off)
            links.remove(old)
        links.new(points.outputs["Rotation"], inst.inputs["Rotation"])      # stand on the surface
        spin = nodes.new("GeometryNodeRotateInstances")                     # …then turned about itself
        links.new(inst.outputs["Instances"], spin.inputs["Instances"])
        links.new(random_turn, spin.inputs["Rotation"])
        for to in users:
            links.new(spin.outputs["Instances"], to)


def _grass_on_the_sphere(scene):
    """The editor's grass grows on a flat square beside the sphere: here it moves onto the sphere itself.
    True when there was grass."""
    ball = _the_sphere(scene)
    patch = next((o for o in scene.objects if o.name.endswith(" patch")), None)
    if patch is None:
        return False
    group = next((m.node_group for m in patch.modifiers if m.type == "NODES" and m.node_group is not None), None)
    bpy.data.objects.remove(patch, do_unlink=True)
    if group is None:
        return False
    _outwards(group)
    ball.modifiers.new("Studio grass", "NODES").node_group = group
    return True


def _stage_for_the_picture(scene, width, height, grass=0.0):
    """…``grass``: the height of its blades, which the picture makes room for."""
    ball = _the_sphere(scene)
    centre = ball.location.copy()
    cam = scene.camera
    cam.data.lens = 60.0
    away = Vector((0.0, -1.0, 0.34)).normalized()
    cam.location = centre + away * (5.0 * (1.0 + 1.4 * min(0.6, grass)))   # the whole sphere (and grass), small
    cam.rotation_euler = (-away).to_track_quat("-Z", "Y").to_euler()
    world = scene.world
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = (0.42, 0.45, 0.5, 1.0)
    bg.inputs["Strength"].default_value = 0.55
    lamp = bpy.data.lights.new("preview fill", "AREA")
    lamp.energy = 9.0
    lamp.size = 1.6
    ob = bpy.data.objects.new("preview fill", lamp)
    scene.collection.objects.link(ob)
    ob.location = centre + Vector((-1.8, -1.2, 1.6))
    ob.rotation_euler = (centre - ob.location).to_track_quat("-Z", "Y").to_euler()
    for light in bpy.data.lights:
        if light.type == "SUN":
            light.energy = 2.0                   # a pale stone must keep its tone
    scene.render.resolution_x, scene.render.resolution_y = int(width), int(height)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"


def _light_room(edit, payload, width, height):
    """A corner of a dim room (a floor, a back wall, a ball and a block), lit by the one light of ``payload``
    alone: its beam, colour, brightness and shadows show."""
    edit["make_lights"](payload)                 # the light as «Edit in Blender» makes it, on its usual stage
    scene = bpy.context.scene
    for ob in list(scene.objects):               # that stage goes; the room takes its place
        if ob.type != "LIGHT":
            bpy.data.objects.remove(ob, do_unlink=True)
    mat = bpy.data.materials.new("room")
    mat.use_nodes = True
    bsdf = edit["_principled"](mat)
    bsdf.inputs["Base Color"].default_value = (0.55, 0.55, 0.55, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.75
    mesh = edit["_mesh_object"]
    mesh(scene, "floor", [(-8, -8, 0), (8, -8, 0), (8, 1.3, 0), (-8, 1.3, 0)], [(0, 1, 2, 3)], material=mat)
    mesh(scene, "wall", [(-8, 1.3, 0), (8, 1.3, 0), (8, 1.3, 6), (-8, 1.3, 6)], [(0, 1, 2, 3)], material=mat)
    v, f = edit["_sphere"](0.32)
    mesh(scene, "ball", v, f, (0.55, 0.35, 0.32), mat, True)
    v, f = edit["_box"](0.48)
    block = mesh(scene, "block", v, f, (-0.6, 0.55, 0.24), mat)
    block.rotation_euler = (0.0, 0.0, 0.5)
    world = bpy.data.worlds.new("dim")
    world.use_nodes = True
    bg = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg is None:
        bg = world.node_tree.nodes.new("ShaderNodeBackground")
        out = world.node_tree.nodes.new("ShaderNodeOutputWorld")
        world.node_tree.links.new(bg.outputs["Background"], out.inputs["Surface"])
    bg.inputs["Color"].default_value = (0.015, 0.017, 0.022, 1.0)
    scene.world = world
    cam = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    scene.collection.objects.link(cam)
    cam.data.lens = 26.0
    cam.location = (0.0, -3.0, 1.7)
    cam.rotation_euler = (Vector((0.0, 0.6, 0.8)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    scene.view_settings.exposure = 1.4           # the same for every light: a stronger one still looks stronger
    for light in scene.objects:
        if light.type == "LIGHT":
            light.hide_render = False                # a switched-off light is still shown here
    scene.render.resolution_x, scene.render.resolution_y = int(width), int(height)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"


def render(edit, job):
    with open(job["payload"], encoding="utf-8") as fh:
        payload = json.load(fh)
    if job.get("kind") == "light":
        _light_room(edit, payload, job["width"], job["height"])
        scene = bpy.context.scene
        _engine(scene)
        if hasattr(scene.eevee, "use_raytracing"):
            scene.eevee.use_raytracing = True
        scene.render.filepath = job["out"]
        bpy.ops.render.render(write_still=True)
        return
    edit["make_materials"](payload, os.path.dirname(os.path.abspath(job["payload"])))
    scene = bpy.context.scene
    _engine(scene)
    height = 0.0
    if _grass_on_the_sphere(scene):
        height = float(((payload[0].get("grass") or {}).get("grass_height")) or 0.1)
    _stage_for_the_picture(scene, job["width"], job["height"], height)
    scene.render.filepath = job["out"]
    bpy.ops.render.render(write_still=True)


def main():
    edit = _edit_scene()
    sphere = edit["_sphere"]                     # a rounder one than «Edit in Blender»'s: its edge is seen close
    edit["_sphere"] = lambda radius, seg=96, rings=48: sphere(radius, seg, rings)
    print("RSPREVIEW " + json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        answer = {}
        start = time.perf_counter()
        try:
            job = json.loads(line)
            answer = {"id": job["id"], "out": job["out"]}
            render(edit, job)
            answer["seconds"] = round(time.perf_counter() - start, 2)
        except Exception as exc:  # noqa: BLE001 - this material only; the next one is tried
            import traceback
            print(traceback.format_exc(), flush=True)
            answer["error"] = str(exc)
        print("RSPREVIEW " + json.dumps(answer), flush=True)


main()
