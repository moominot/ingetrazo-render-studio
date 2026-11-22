# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs INSIDE Blender: IngeTrazo's own render script with looks on top.

``blender -b --factory-startup --python studio_scene.py -- job.json``

IngeTrazo's ``render_scene.py`` sits next to this file (the extension copies
it there from IngeTrazo): its functions build the scene exactly as the
Render panel does — model, finishes, camera, figures, sun, sky, lights,
ground, engine. This script adds what the job's ``"studio"`` block asks for:

* a sky with clouds (a procedural layer over the physical sky), a sun moved
  to the golden hour, an overcast or a night with stars;
* or a 360° image (HDRI) as the world: lighting the scene, or only seen
  behind it;
* a white model (every material white and matte, glass kept);
* automatic exposure: a small, quick pre-pass measured in scene-linear
  light, then the exposure that puts it at a pleasant grey;
* the photographic finish: AgX look (contrast), white balance, saturation,
  bloom and vignette.

Every Blender name it touches was checked on Blender 5.3; anything a
version lacks is skipped, not fatal.
"""
import json
import math
import os
import sys
import time

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_core():
    """IngeTrazo's render_scene.py as a module, without running its main()."""
    path = os.path.join(HERE, "render_scene.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    # Its last line runs the render; keep everything above it.
    cut = src.rstrip().rsplit("\nmain()", 1)
    code = compile(cut[0] + "\n", path, "exec")
    ns = {"__name__": "ingetrazo_render_scene", "__file__": path}
    exec(code, ns)
    return ns


core = _load_core()
say = core["say"]


# ---- the sky -----------------------------------------------------------------------

def _world_nodes(scene):
    world = scene.world
    return world.node_tree.nodes, world.node_tree.links


def add_clouds(scene, coverage, scale=1.0, brightness=1.0, seed=0.0, tint=(1.0, 1.0, 1.03)):
    """A cloud layer over whatever the world's Background shows: noise on a
    flat ceiling seen from below, thresholded by ``coverage`` (0 clear … 1
    overcast), faded at the horizon. Bright white-grey, a little darker
    underneath where they are thick. Seen in the sky and in reflections; the
    light it gives is the sky's."""
    if coverage <= 0.0 or scene.world is None:
        return
    nodes, links = _world_nodes(scene)
    bg = next((n for n in nodes if n.type == "BACKGROUND"), None)
    if bg is None:
        return
    sky_link = next(iter(bg.inputs["Color"].links), None)
    sky_out = sky_link.from_socket if sky_link else None
    sky_strength = bg.inputs["Strength"].default_value

    coord = nodes.new("ShaderNodeTexCoord")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coord.outputs["Generated"], sep.inputs["Vector"])
    # z clamped above the horizon, then (x, y) / z: a ceiling seen from below.
    zc = nodes.new("ShaderNodeMath"); zc.operation = "MAXIMUM"
    zc.inputs[1].default_value = 0.03
    links.new(sep.outputs["Z"], zc.inputs[0])
    ux = nodes.new("ShaderNodeMath"); ux.operation = "DIVIDE"
    uy = nodes.new("ShaderNodeMath"); uy.operation = "DIVIDE"
    links.new(sep.outputs["X"], ux.inputs[0]); links.new(zc.outputs[0], ux.inputs[1])
    links.new(sep.outputs["Y"], uy.inputs[0]); links.new(zc.outputs[0], uy.inputs[1])
    comb = nodes.new("ShaderNodeCombineXYZ")
    links.new(ux.outputs[0], comb.inputs["X"]); links.new(uy.outputs[0], comb.inputs["Y"])
    comb.inputs["Z"].default_value = seed
    noise = nodes.new("ShaderNodeTexNoise")
    links.new(comb.outputs["Vector"], noise.inputs["Vector"])
    noise.inputs["Scale"].default_value = 0.55 * scale
    for name, value in (("Detail", 12.0), ("Roughness", 0.58), ("Lacunarity", 2.1)):
        if name in noise.inputs:
            noise.inputs[name].default_value = value
    ramp = nodes.new("ShaderNodeValToRGB")
    lo = 0.62 - 0.36 * coverage
    ramp.color_ramp.elements[0].position = max(0.0, lo)
    ramp.color_ramp.elements[1].position = min(1.0, lo + 0.16 + 0.18 * coverage)
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    # Thin near the horizon (far clouds blur into the haze) and none below.
    fade = nodes.new("ShaderNodeMapRange")
    fade.inputs["From Min"].default_value = 0.0
    fade.inputs["From Max"].default_value = 0.18
    links.new(sep.outputs["Z"], fade.inputs["Value"])
    mask = nodes.new("ShaderNodeMath"); mask.operation = "MULTIPLY"
    links.new(ramp.outputs["Color"], mask.inputs[0])
    links.new(fade.outputs["Result"], mask.inputs[1])
    # Cloud colour: white, greyer where denser (the noise's high values).
    shade = nodes.new("ShaderNodeMapRange")
    shade.inputs["From Min"].default_value = 0.5
    shade.inputs["From Max"].default_value = 0.9
    shade.inputs["To Min"].default_value = 1.0
    shade.inputs["To Max"].default_value = 0.55
    links.new(noise.outputs["Fac"], shade.inputs["Value"])
    # In the sky's units: the physical sky is bright with a small Strength.
    level = nodes.new("ShaderNodeMath"); level.operation = "MULTIPLY"
    level.inputs[1].default_value = brightness * (40.0 if sky_strength < 0.5 else 1.1)
    links.new(shade.outputs["Result"], level.inputs[0])
    cloud_col = nodes.new("ShaderNodeCombineColor")
    for ch, k in zip(("Red", "Green", "Blue"), tint):
        m = nodes.new("ShaderNodeMath"); m.operation = "MULTIPLY"; m.inputs[1].default_value = k
        links.new(level.outputs[0], m.inputs[0]); links.new(m.outputs[0], cloud_col.inputs[ch])
    mix = nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"
    links.new(mask.outputs[0], mix.inputs["Factor"])
    if sky_out is not None:
        links.new(sky_out, mix.inputs["A"])
    else:
        mix.inputs["A"].default_value = bg.inputs["Color"].default_value
    links.new(cloud_col.outputs["Color"], mix.inputs["B"])
    links.new(mix.outputs["Result"], bg.inputs["Color"])
    say("clouds", round(coverage, 2))


def night_sky(scene, stars=1.0, density=0.14, seed=0.0,
              zenith=(0.004, 0.007, 0.020), horizon=(0.020, 0.026, 0.045)):
    """A night sky in the world's Background: deep blue overhead, a little
    paler at the horizon (the glow of towns and the air), and stars: points
    on a sphere of Voronoi cells, ``density`` of the cells lit, each with
    its own brightness and a hint of colour, faded out near the horizon.
    Clouds added afterwards (:func:`add_clouds`) hide them."""
    nodes, links = _world_nodes(scene)
    bg = next((n for n in nodes if n.type == "BACKGROUND"), None)
    if bg is None:
        return
    coord = nodes.new("ShaderNodeTexCoord")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coord.outputs["Generated"], sep.inputs["Vector"])
    # The gradient: horizon colour at z = 0, zenith colour from z ≈ 0.5.
    grad = nodes.new("ShaderNodeMapRange")
    grad.inputs["From Min"].default_value = 0.0
    grad.inputs["From Max"].default_value = 0.5
    links.new(sep.outputs["Z"], grad.inputs["Value"])
    sky = nodes.new("ShaderNodeMix"); sky.data_type = "RGBA"
    links.new(grad.outputs["Result"], sky.inputs["Factor"])
    sky.inputs["A"].default_value = (*horizon, 1.0)
    sky.inputs["B"].default_value = (*zenith, 1.0)
    out = sky.outputs["Result"]
    if stars > 0.0:
        # Stars: the distance to the nearest Voronoi point, a sharp falloff
        # makes each lit cell one small dot (about a pixel at 1920 px).
        vor = nodes.new("ShaderNodeTexVoronoi")
        vor.feature = "F1"
        vor.voronoi_dimensions = "4D" if seed else "3D"
        links.new(coord.outputs["Generated"], vor.inputs["Vector"])
        vor.inputs["Scale"].default_value = 160.0
        if seed and "W" in vor.inputs:
            vor.inputs["W"].default_value = seed
        dot = nodes.new("ShaderNodeMapRange")
        dot.inputs["From Min"].default_value = 0.0
        dot.inputs["From Max"].default_value = 0.14
        dot.inputs["To Min"].default_value = 1.0
        dot.inputs["To Max"].default_value = 0.0
        links.new(vor.outputs["Distance"], dot.inputs["Value"])
        # Which cells shine, and how much: the cell's random colour.
        rnd = nodes.new("ShaderNodeSeparateColor")
        links.new(vor.outputs["Color"], rnd.inputs["Color"])
        lit = nodes.new("ShaderNodeMapRange")       # top ``density`` of cells
        lit.inputs["From Min"].default_value = 1.0 - density
        lit.inputs["From Max"].default_value = 1.0
        links.new(rnd.outputs["Red"], lit.inputs["Value"])
        bright = nodes.new("ShaderNodeMath"); bright.operation = "POWER"
        bright.inputs[1].default_value = 3.0           # many faint, few bright
        links.new(lit.outputs["Result"], bright.inputs[0])
        star = nodes.new("ShaderNodeMath"); star.operation = "MULTIPLY"
        links.new(dot.outputs["Result"], star.inputs[0])
        links.new(bright.outputs[0], star.inputs[1])
        # None near the horizon (thick air), full from about 12°.
        high = nodes.new("ShaderNodeMapRange")
        high.inputs["From Min"].default_value = 0.03
        high.inputs["From Max"].default_value = 0.2
        links.new(sep.outputs["Z"], high.inputs["Value"])
        star2 = nodes.new("ShaderNodeMath"); star2.operation = "MULTIPLY"
        links.new(star.outputs[0], star2.inputs[0])
        links.new(high.outputs["Result"], star2.inputs[1])
        level = nodes.new("ShaderNodeMath"); level.operation = "MULTIPLY"
        level.inputs[1].default_value = 6.0 * stars
        links.new(star2.outputs[0], level.inputs[0])
        # Colour: from orange-white to blue-white, by another random channel.
        hue = nodes.new("ShaderNodeValToRGB")
        hue.color_ramp.elements[0].color = (1.0, 0.82, 0.62, 1.0)
        hue.color_ramp.elements[1].color = (0.75, 0.85, 1.0, 1.0)
        mid = hue.color_ramp.elements.new(0.5)
        mid.color = (1.0, 1.0, 1.0, 1.0)
        links.new(rnd.outputs["Green"], hue.inputs["Fac"])
        tinted = nodes.new("ShaderNodeMix"); tinted.data_type = "RGBA"
        tinted.blend_type = "MULTIPLY"
        tinted.inputs["Factor"].default_value = 1.0
        links.new(hue.outputs["Color"], tinted.inputs["A"])
        links.new(level.outputs[0], tinted.inputs["B"])
        add = nodes.new("ShaderNodeMix"); add.data_type = "RGBA"
        add.blend_type = "ADD"
        add.inputs["Factor"].default_value = 1.0
        links.new(out, add.inputs["A"])
        links.new(tinted.outputs["Result"], add.inputs["B"])
        out = add.outputs["Result"]
    links.new(out, bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 1.0
    say("night sky, stars", round(stars, 2))


def set_hdri(scene, path, rotation_deg=0.0, strength=1.0, light=True):
    """A 360° image (equirectangular HDRI/EXR, or a JPEG/PNG panorama) as the
    world. ``light``: it lights the scene too (the look's sun and sky go);
    otherwise the look still lights everything and the image is only what
    the camera sees behind the model. ``rotation_deg`` turns it about the
    vertical. Returns the image, or None when it could not be read."""
    try:
        image = bpy.data.images.load(str(path), check_existing=True)
    except (RuntimeError, OSError) as exc:
        say("hdri unreadable", path, exc)
        return None
    if scene.world is None:
        core["set_plain_world"](scene, (0.05, 0.05, 0.05), 1.0, "hdri")
    nodes, links = _world_nodes(scene)
    out = next((n for n in nodes if n.type == "OUTPUT_WORLD"), None)
    if out is None:
        out = nodes.new("ShaderNodeOutputWorld")
    look_link = next(iter(out.inputs["Surface"].links), None)
    look_shader = look_link.from_socket if look_link else None
    coord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.name = "hdri_mapping"
    mapping.inputs["Rotation"].default_value[2] = math.radians(rotation_deg)
    links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    env = nodes.new("ShaderNodeTexEnvironment")
    env.name = "hdri"
    env.image = image
    links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    bg = nodes.new("ShaderNodeBackground")
    bg.name = "hdri_background"
    bg.inputs["Strength"].default_value = strength
    links.new(env.outputs["Color"], bg.inputs["Color"])
    if light or look_shader is None:
        links.new(bg.outputs["Background"], out.inputs["Surface"])
        for ob in list(scene.objects):            # its own sun is in the image
            if ob.type == "LIGHT" and ob.data.type == "SUN":
                bpy.data.objects.remove(ob, do_unlink=True)
    else:
        path_node = nodes.new("ShaderNodeLightPath")
        mix = nodes.new("ShaderNodeMixShader")
        links.new(path_node.outputs["Is Camera Ray"], mix.inputs["Fac"])
        links.new(look_shader, mix.inputs[1])
        links.new(bg.outputs["Background"], mix.inputs[2])
        links.new(mix.outputs["Shader"], out.inputs["Surface"])
    w, h = image.size[:2] if image.size else (0, 0)
    say("hdri", os.path.basename(str(path)), f"{w}x{h}", "lights the scene" if light else "background only",
        f"rotation {rotation_deg:.0f}°")
    return image


_DOF = {"amount": 0.0}          # the job's depth of field, kept for the live view's cameras


def set_dof(scene, cam_cfg, amount):
    """Depth of field: ``amount`` 0..1 (0 = off) from a wide f/32 down to a shallow f/1.4, focused on the
    middle of the view (the distance from the eye to the camera's target)."""
    cam = scene.camera
    if cam is None or cam.type != "CAMERA":
        return
    d = cam.data.dof
    amount = max(0.0, min(1.0, float(amount or 0.0)))
    d.use_dof = amount > 0.01 and bool(cam_cfg.get("perspective", True))
    if d.use_dof:
        eye, target = Vector(cam_cfg["eye"]), Vector(cam_cfg["target"])
        d.focus_distance = max(0.05, (target - eye).length)
        d.aperture_fstop = 32.0 * (1.4 / 32.0) ** amount


def set_backdrop(scene, path, fit="fill", strength=1.0, aspect=1.5):
    """A fixed picture behind the model (not a 360° one): the camera sees it as a flat backdrop that does
    not move when the view turns; the look keeps lighting everything. ``fit``: «fill» covers the whole
    frame (crops what overflows), «fit» shows the whole picture (the look's sky around it), «stretch» fills
    the frame out of proportion. ``aspect``: the frame's width / height. Returns the image, or None."""
    try:
        image = bpy.data.images.load(str(path), check_existing=True)
    except (RuntimeError, OSError) as exc:
        say("backdrop unreadable", path, exc)
        return None
    if scene.world is None:
        core["set_plain_world"](scene, (0.05, 0.05, 0.05), 1.0, "backdrop")
    nodes, links = _world_nodes(scene)
    out = next((n for n in nodes if n.type == "OUTPUT_WORLD"), None)
    if out is None:
        out = nodes.new("ShaderNodeOutputWorld")
    look_link = next(iter(out.inputs["Surface"].links), None)
    ia = (image.size[0] / float(image.size[1])) if image.size[0] and image.size[1] else aspect
    sx = sy = 1.0
    if fit == "fill":                          # the picture covers the frame
        if ia > aspect:
            sx = aspect / ia
        else:
            sy = ia / aspect
    elif fit == "fit":                         # the whole picture inside the frame
        if ia > aspect:
            sy = ia / aspect
        else:
            sx = aspect / ia
    coord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.name = "backdrop_mapping"
    mapping.inputs["Scale"].default_value = (sx, sy, 1.0)
    mapping.inputs["Location"].default_value = (0.5 - 0.5 * sx, 0.5 - 0.5 * sy, 0.0)
    links.new(coord.outputs["Window"], mapping.inputs["Vector"])
    tex = nodes.new("ShaderNodeTexImage")
    tex.name = "backdrop"
    tex.image = image
    tex.extension = "CLIP" if fit == "fit" else "EXTEND"
    tex.interpolation = "Cubic"
    links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
    bg = nodes.new("ShaderNodeBackground")
    bg.name = "backdrop_background"
    bg.inputs["Strength"].default_value = strength
    links.new(tex.outputs["Color"], bg.inputs["Color"])
    if look_link is None:
        links.new(bg.outputs["Background"], out.inputs["Surface"])
    else:
        look_shader = look_link.from_socket
        path_node = nodes.new("ShaderNodeLightPath")
        cam = nodes.new("ShaderNodeMath"); cam.operation = "MULTIPLY"
        links.new(path_node.outputs["Is Camera Ray"], cam.inputs[0])
        if fit == "fit":                       # outside the picture: the look's sky
            links.new(tex.outputs["Alpha"], cam.inputs[1])
        else:
            cam.inputs[1].default_value = 1.0
        mix = nodes.new("ShaderNodeMixShader")
        links.new(cam.outputs["Value"], mix.inputs["Fac"])
        links.new(look_shader, mix.inputs[1])
        links.new(bg.outputs["Background"], mix.inputs[2])
        links.new(mix.outputs["Shader"], out.inputs["Surface"])
    say("backdrop", os.path.basename(str(path)), f"{image.size[0]}x{image.size[1]}", fit)
    return image


def find_sun(image, small=(512, 256)):
    """Where a 360° image has its sun: ``(direction, rgb, peak)``, or None when it has none.
    ``direction`` is the unit vector, in the image's own frame (before any rotation), TOWARD the
    brightest spot. The spot is found on a small blurred copy, so one hot pixel is not a sun, and
    only counts as one when it stands well out of the sky around it. ``peak`` is the brightest
    value (a radiance file, EXR/HDR, reports a huge one: its real sun carries its own light; a
    JPEG/PNG panorama clips it to white, and that is what needs a lamp)."""
    import numpy as np
    w, h = image.size[:2]
    if w < 8 or h < 4:
        return None
    work = image.copy()
    try:
        work.scale(*small)
        sw, sh = work.size[:2]
        px = np.empty(sw * sh * 4, np.float32)
        work.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(work)
    px = px.reshape(sh, sw, 4)[..., :3]              # row 0 is the BOTTOM of the picture
    lum = px @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    peak = float(lum.max())
    blur = _box_blur(_box_blur(lum, max(1, sw // 128), 1), max(1, sw // 128), 0)
    y, x = np.unravel_index(int(np.argmax(blur)), blur.shape)
    median = float(np.median(blur))
    if blur[y, x] < 0.5 or blur[y, x] < 2.0 * max(median, 1e-3):
        return None                                  # an even sky: no sun to speak of
    # The sun's centre: the bright pixels around the peak, turned to the middle so the seam of the
    # picture does not cut it. Their average colour is the lamp's.
    r = max(4, sw // 40)
    ys = np.clip(np.arange(y - r, y + r + 1), 0, sh - 1)
    xs = np.arange(x - r, x + r + 1) % sw
    win = lum[np.ix_(ys, xs)]
    mask = win >= 0.85 * float(win.max())
    if not mask.any():
        return None
    wy, wx = np.nonzero(mask)
    cy = float(ys[wy].mean())
    cx = float((x - r) + wx.mean())
    rgb = px[np.ix_(ys, xs)][mask].mean(axis=0)
    u, v = ((cx + 0.5) / sw) % 1.0, (cy + 0.5) / sh
    phi, theta = (u - 0.5) * 2.0 * math.pi, (v - 0.5) * math.pi
    # Blender's equirectangular lookup: u = 0.5 - atan2(y, x) / 2π, v = 0.5 + elevation / π.
    d = (math.cos(phi) * math.cos(theta), -math.sin(phi) * math.cos(theta), math.sin(theta))
    if image.is_float and image.file_format in ("HDR", "OPEN_EXR", "OPEN_EXR_MULTILAYER"):
        peak = max(peak, 1000.0)                     # a radiance file: its sun is in it already
    return d, tuple(float(c) for c in rgb), peak


def _box_blur(a, r, axis):
    """A box average of half-width ``r`` along ``axis`` (wrapping round)."""
    import numpy as np
    n = a.shape[axis]
    acc = np.zeros_like(a)
    for s in range(-r, r + 1):
        acc += np.roll(a, s, axis=axis)
    return acc / (2 * r + 1)


def hdri_sun(scene, image, rotation_deg, strength, job_strength, angle=None):
    """The sun a JPEG/PNG panorama only paints. The world lights with the whole picture, so a blue
    sky floods the scene with blue and nothing casts a shadow: a lamp goes where the picture is
    brightest, with that spot's colour. A real HDR already carries its sun (the renderer samples
    it), so one is added only when the brightest pixel is not far above white. Returns the lamp."""
    found = find_sun(image)
    if found is None:
        return None
    d, rgb, peak = found
    if peak > 4.0:
        return None
    a = math.radians(-float(rotation_deg))          # the mapping turns the lookup, not the picture
    ca, sa = math.cos(a), math.sin(a)
    world = Vector((d[0] * ca - d[1] * sa, d[0] * sa + d[1] * ca, d[2]))
    if world.z < 0.02:
        return None                                  # a sun under the horizon lights nothing
    top = max(rgb) or 1.0
    colour = tuple(0.5 + 0.5 * c / top for c in rgb)       # a warm or cool cast, kept gentle
    light = bpy.data.lights.new("IngeTrazo hdri sun", type="SUN")
    light.energy = float(job_strength) * float(strength)
    light.angle = math.radians(float(angle) if angle else 1.0)
    light.color = colour
    sun = bpy.data.objects.new("IngeTrazo hdri sun", light)
    scene.collection.objects.link(sun)
    sun.rotation_euler = world.normalized().to_track_quat("Z", "Y").to_euler()
    say("hdri sun", f"elev {math.degrees(math.asin(world.normalized().z)):.0f}°",
        f"azim {math.degrees(math.atan2(world.y, world.x)):.0f}°", f"colour {tuple(round(c, 2) for c in colour)}")
    return sun


_SKY_ATTRS = ("sky_type", "sun_elevation", "sun_rotation", "sun_direction", "altitude",
              "air_density", "aerosol_density", "ozone_density", "sun_size",
              "sun_intensity", "turbidity", "ground_albedo")


def _sky_copy(nodes, wsky):
    """A second Sky Texture with the world's settings and no sun disc."""
    sky = nodes.new("ShaderNodeTexSky")
    for attr in _SKY_ATTRS:
        if hasattr(wsky, attr):
            try:
                setattr(sky, attr, getattr(wsky, attr))
            except (TypeError, ValueError, AttributeError):
                pass
    if hasattr(sky, "sun_disc"):
        sky.sun_disc = False
    return sky


def world_ground(scene, albedo, level=2.0):
    """Below the horizon the physical sky is black. Cycles never sees it (the
    ground plane is in the way), but EEVEE does wherever its screen-space
    rays miss: a mirror reflecting the ground behind the camera came out
    black, and the light bounced up from the ground was missing. So the
    world gets a ground: the horizon sky's colour times the ground's
    albedo (and ``level``, for the sun on it)."""
    if scene.world is None:
        return
    nodes, links = _world_nodes(scene)
    wsky = next((n for n in nodes if n.type == "TEX_SKY"), None)
    bg = next((n for n in nodes if n.type == "BACKGROUND" and n.name != "hdri_background"), None)
    if wsky is None or bg is None:
        return
    src = next(iter(bg.inputs["Color"].links), None)
    if src is None:
        return
    coord = nodes.new("ShaderNodeTexCoord")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coord.outputs["Generated"], sep.inputs["Vector"])
    comb = nodes.new("ShaderNodeCombineXYZ")
    links.new(sep.outputs["X"], comb.inputs["X"]); links.new(sep.outputs["Y"], comb.inputs["Y"])
    comb.inputs["Z"].default_value = 0.02
    sky = _sky_copy(nodes, wsky)
    links.new(comb.outputs["Vector"], sky.inputs["Vector"])
    tint = nodes.new("ShaderNodeMix"); tint.data_type = "RGBA"; tint.blend_type = "MULTIPLY"
    tint.inputs["Factor"].default_value = 1.0
    links.new(sky.outputs["Color"], tint.inputs["A"])
    tint.inputs["B"].default_value = (*(min(1.0, c * level) for c in albedo[:3]), 1.0)
    below = nodes.new("ShaderNodeMapRange")          # 1 below the horizon
    below.inputs["From Min"].default_value = 0.0
    below.inputs["From Max"].default_value = -0.02
    links.new(sep.outputs["Z"], below.inputs["Value"])
    mix = nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"
    links.new(below.outputs["Result"], mix.inputs["Factor"])
    links.new(src.from_socket, mix.inputs["A"])
    links.new(tint.outputs["Result"], mix.inputs["B"])
    links.new(mix.outputs["Result"], bg.inputs["Color"])
    say("world ground", [round(c, 2) for c in albedo[:3]], "x", level)


def kelvin_rgb(kelvin):
    """Blackbody colour of ``kelvin`` (Tanner Helland's fit), 0..1, scaled
    so its brightest channel is 1."""
    t = max(1000.0, min(40000.0, kelvin)) / 100.0
    r = 255.0 if t <= 66 else 329.698727446 * ((t - 60) ** -0.1332047592)
    g = (99.4708025861 * math.log(t) - 161.1195681661) if t <= 66         else 288.1221695283 * ((t - 60) ** -0.0755148492)
    b = 255.0 if t >= 66 else (0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    rgb = [max(0.0, min(255.0, c)) / 255.0 for c in (r, g, b)]
    m = max(rgb) or 1.0
    return tuple(c / m for c in rgb)


def sun_kelvin(sun_dir):
    """The sun's colour temperature for its height: about 2500 K on the
    horizon, 5800 K once it is 35 degrees up (less air to cross)."""
    if sun_dir is None:
        return 5800.0
    el = math.degrees(math.asin(max(-1.0, min(1.0, sun_dir[2] / (Vector(sun_dir).length or 1.0)))))
    f = max(0.0, min(1.0, el / 35.0))
    f = f * f * (3 - 2 * f)
    return 2500.0 + (5800.0 - 2500.0) * f


def golden_sun(sun_dir, elevation_deg):
    """The same azimuth (or the west, at night), the sun low."""
    if sun_dir is not None and math.hypot(sun_dir[0], sun_dir[1]) > 1e-6:
        az = math.atan2(sun_dir[1], sun_dir[0])
    else:
        az = math.radians(200.0)
    el = math.radians(elevation_deg)
    return [math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)]


def fix_normals():
    """Drop the custom normals the glTF brings and let Blender take each
    face's own: IngeTrazo's export can carry vertex normals pointing the
    other way on some faces, which Cycles shades as lit from the sky (a
    stair's underside rendered white). Smooth faces stay smooth through
    Blender's own smoothing by angle."""
    n = 0
    for obj in bpy.data.objects:
        me = obj.data if obj.type == "MESH" else None
        if me is None or not getattr(me, "has_custom_normals", False):
            continue
        try:
            with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
                bpy.ops.mesh.customdata_custom_splitnormals_clear()
            n += 1
        except Exception:  # noqa: BLE001 - keep the mesh as it came
            continue
    say("normals", f"custom normals cleared on {n} meshes")


def cap_albedo(cap=0.8, only=None):
    """No material reflects more than ``cap`` of the light: IngeTrazo's
    default «paper white» is 0.96, whiter than paper, and under a path tracer
    a white wall that bright glows like the sky (real white paint is about
    0.8). Colours are scaled down whole, so their hue stays."""
    n = 0
    for mat in _live_materials(only):
        if not mat.node_tree or mat.name.startswith("IngeTrazo ground"):
            continue
        bsdf = next((x for x in mat.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        sock = bsdf.inputs.get("Base Color")
        if sock is None or sock.links:
            continue                       # a texture: left as painted
        r, g, b, a = sock.default_value
        m = max(r, g, b)
        if m > cap:
            k = cap / m
            sock.default_value = (r * k, g * k, b * k, a)
            n += 1
    if n:
        say("albedo", f"{n} materials capped at {cap}")


def _model_centre(ground):
    """The middle (x, y) of the model's boxes, in the world (the ground is left out)."""
    lo = [1e18, 1e18]
    hi = [-1e18, -1e18]
    for ob in bpy.data.objects:
        if ob is ground or ob.type != "MESH" or ob.name.startswith("IngeTrazo"):
            continue
        for corner in ob.bound_box:
            p = ob.matrix_world @ Vector(corner)
            lo[0], lo[1] = min(lo[0], p.x), min(lo[1], p.y)
            hi[0], hi[1] = max(hi[0], p.x), max(hi[1], p.y)
    if lo[0] > hi[0]:
        return 0.0, 0.0
    return (lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0


def _unshadowed_light(scene, z, where):
    """How lit a bare floor is where nothing shades it (a small probe floor far from the model, rendered
    once): the value the shadow is measured against, in EEVEE."""
    import numpy as np
    r = scene.render
    keep = (r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath, r.image_settings.file_format,
            scene.camera, scene.view_settings.exposure, getattr(r, "use_compositing", None))
    tmp = os.path.join(os.path.dirname(r.filepath) or HERE, "_floor.exr")
    mat = bpy.data.materials.new("IngeTrazo floor probe")
    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    diff = nodes.new("ShaderNodeBsdfDiffuse")
    diff.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    rgb = nodes.new("ShaderNodeShaderToRGB")
    emit = nodes.new("ShaderNodeEmission")
    out = nodes.new("ShaderNodeOutputMaterial")
    links.new(diff.outputs["BSDF"], rgb.inputs["Shader"])
    links.new(rgb.outputs["Color"], emit.inputs["Color"])
    links.new(emit.outputs["Emission"], out.inputs["Surface"])
    bpy.ops.mesh.primitive_plane_add(size=4.0, location=(where, where, z))
    probe = bpy.context.active_object
    probe.name = "IngeTrazo floor probe"
    probe.data.materials.append(mat)
    cam = bpy.data.objects.new("IngeTrazo floor probe cam", bpy.data.cameras.new("IngeTrazo floor probe cam"))
    scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 1.0
    cam.location = (where, where, z + 5.0)
    value = 1.0
    try:
        scene.camera = cam
        r.resolution_x = r.resolution_y = 4
        r.resolution_percentage = 100
        r.image_settings.file_format = "OPEN_EXR"
        r.filepath = tmp
        scene.view_settings.exposure = 0.0
        if keep[7] is not None:
            r.use_compositing = False
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(tmp)
        px = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(-1, 4)[:, :3]
        value = float(px.mean(axis=0) @ np.array([0.2126, 0.7152, 0.0722]))
        bpy.data.images.remove(img)
    finally:
        r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath, r.image_settings.file_format = keep[:5]
        scene.camera = keep[5]
        scene.view_settings.exposure = keep[6]
        if keep[7] is not None:
            r.use_compositing = keep[7]
        for ob, store in ((probe, bpy.data.meshes), (cam, bpy.data.cameras)):
            data = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if data is not None and data.users == 0:
                store.remove(data)
        bpy.data.materials.remove(mat)
    return max(value, 1e-4)


def add_shadow_floor(scene, z, size):
    """No ground is made, but the model's shadow still falls on the floor: an invisible plane that only
    shows shadows, so the sky or the 360° image shows through everywhere else. Cycles has a shadow catcher;
    EEVEE does not honour it, so there the floor is a black film whose opacity is how much darker the light
    is than on a bare floor (measured once, far from the model)."""
    bpy.ops.mesh.primitive_plane_add(size=float(size), location=(0.0, 0.0, float(z)))
    floor = bpy.context.active_object
    floor.name = "IngeTrazo shadow floor"
    floor.is_shadow_catcher = True
    if scene.render.engine == "CYCLES":
        say("shadow floor", f"z {z:.2f}", "catcher")
        return floor
    lit = _unshadowed_light(scene, float(z), float(size) * 0.05)
    mat = bpy.data.materials.new("IngeTrazo shadow floor")
    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    diff = nodes.new("ShaderNodeBsdfDiffuse")
    diff.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    rgb = nodes.new("ShaderNodeShaderToRGB")
    bw = nodes.new("ShaderNodeRGBToBW")
    ratio = nodes.new("ShaderNodeMath"); ratio.operation = "DIVIDE"
    ratio.inputs[1].default_value = lit
    dark = nodes.new("ShaderNodeMath"); dark.operation = "SUBTRACT"; dark.use_clamp = True
    dark.inputs[0].default_value = 1.0
    clear = nodes.new("ShaderNodeBsdfTransparent")
    black = nodes.new("ShaderNodeEmission")
    black.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    mix = nodes.new("ShaderNodeMixShader")
    out = nodes.new("ShaderNodeOutputMaterial")
    links.new(diff.outputs["BSDF"], rgb.inputs["Shader"])
    links.new(rgb.outputs["Color"], bw.inputs["Color"])
    links.new(bw.outputs["Val"], ratio.inputs[0])
    links.new(ratio.outputs["Value"], dark.inputs[1])
    links.new(dark.outputs["Value"], mix.inputs["Fac"])
    links.new(clear.outputs["BSDF"], mix.inputs[1])
    links.new(black.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    elif hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    floor.data.materials.append(mat)
    if hasattr(floor, "visible_shadow"):
        floor.visible_shadow = False              # it is a film: it casts nothing of its own
    say("shadow floor", f"z {z:.2f}", f"film (bare floor reads {lit:.3f})")
    return floor

def haze_ground(scene, near=120.0, far=1200.0, eye_height=None):
    """The ground melts into the sky's own horizon colour with distance, so
    the far edge of the ground plane is no hard line against the sky (the
    atmosphere Enscape shows). The horizon colour is the world's sky looked
    up level with the horizon: the same Sky Texture, fed the view direction
    flattened onto the horizon. With a 360° image and ``eye_height`` (metres) the ground shows the
    image's own ground, projected as a dome would: each point is looked up in the direction from an
    eye ``eye_height`` above the ground, in the middle of the model, to that point. Without it every
    row of the ground would be the image's horizon row, stretched (vertical stripes)."""
    ground = bpy.data.objects.get("IngeTrazo ground")
    if ground is None or not ground.data.materials or scene.world is None:
        return
    mat = ground.data.materials[0]
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if out is None or bsdf is None:
        return
    wnodes = scene.world.node_tree.nodes
    wsky = next((n for n in wnodes if n.type == "TEX_SKY"), None)
    whdri = wnodes.get("hdri")
    bg = wnodes.get("hdri_background") or next((n for n in wnodes if n.type == "BACKGROUND"), None)
    strength = bg.inputs["Strength"].default_value if bg else 1.0
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = strength
    if whdri is not None:
        # The 360° image looked up level with the horizon, turned as the
        # world is: the ground melts into what the image shows there.
        env = nodes.new("ShaderNodeTexEnvironment")
        env.image = whdri.image
        mapping = nodes.new("ShaderNodeMapping")
        wmap = wnodes.get("hdri_mapping")
        if wmap is not None:
            mapping.inputs["Rotation"].default_value = wmap.inputs["Rotation"].default_value
        geo = nodes.new("ShaderNodeNewGeometry")
        if eye_height:
            ex, ey = _model_centre(ground)
            sub = nodes.new("ShaderNodeVectorMath"); sub.operation = "SUBTRACT"
            sub.inputs[1].default_value = (ex, ey, ground.location.z + float(eye_height))
            links.new(geo.outputs["Position"], sub.inputs[0])
            links.new(sub.outputs["Vector"], mapping.inputs["Vector"])
        else:
            neg = nodes.new("ShaderNodeVectorMath"); neg.operation = "SCALE"
            neg.inputs["Scale"].default_value = -1.0
            links.new(geo.outputs["Incoming"], neg.inputs[0])
            sep = nodes.new("ShaderNodeSeparateXYZ")
            links.new(neg.outputs["Vector"], sep.inputs["Vector"])
            comb = nodes.new("ShaderNodeCombineXYZ")
            links.new(sep.outputs["X"], comb.inputs["X"]); links.new(sep.outputs["Y"], comb.inputs["Y"])
            comb.inputs["Z"].default_value = 0.02
            links.new(comb.outputs["Vector"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], env.inputs["Vector"])
        links.new(env.outputs["Color"], emit.inputs["Color"])
    elif wsky is not None:
        sky = nodes.new("ShaderNodeTexSky")
        for attr in ("sky_type", "sun_elevation", "sun_rotation", "sun_direction", "altitude",
                     "air_density", "aerosol_density", "ozone_density", "sun_size",
                     "sun_intensity", "turbidity", "ground_albedo"):
            if hasattr(wsky, attr):
                try:
                    setattr(sky, attr, getattr(wsky, attr))
                except (TypeError, ValueError, AttributeError):
                    pass
        if hasattr(sky, "sun_disc"):
            sky.sun_disc = False
        geo = nodes.new("ShaderNodeNewGeometry")
        neg = nodes.new("ShaderNodeVectorMath"); neg.operation = "SCALE"
        neg.inputs["Scale"].default_value = -1.0
        links.new(geo.outputs["Incoming"], neg.inputs[0])
        sep = nodes.new("ShaderNodeSeparateXYZ")
        links.new(neg.outputs["Vector"], sep.inputs["Vector"])
        comb = nodes.new("ShaderNodeCombineXYZ")
        links.new(sep.outputs["X"], comb.inputs["X"]); links.new(sep.outputs["Y"], comb.inputs["Y"])
        comb.inputs["Z"].default_value = 0.015
        links.new(comb.outputs["Vector"], sky.inputs["Vector"])
        links.new(sky.outputs["Color"], emit.inputs["Color"])
    elif bg is not None:
        emit.inputs["Color"].default_value = bg.inputs["Color"].default_value
    cam = nodes.new("ShaderNodeCameraData")
    rng = nodes.new("ShaderNodeMapRange")
    rng.interpolation_type = "SMOOTHSTEP"
    rng.inputs["From Min"].default_value = near
    rng.inputs["From Max"].default_value = far
    links.new(cam.outputs["View Distance"], rng.inputs["Value"])
    mix = nodes.new("ShaderNodeMixShader")
    links.new(rng.outputs["Result"], mix.inputs["Fac"])
    links.new(bsdf.outputs["BSDF"], mix.inputs[1])
    links.new(emit.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    say("haze", f"ground melts into the horizon from {near:.0f} to {far:.0f} m")


# ---- the material editor's settings ------------------------------------------------------

def _spec_for(mat, specs):
    """The editor's spec for a Blender material: matched on the export name,
    with Blender's «.001» and the export's «_2» collision suffixes allowed."""
    import re
    name = mat.name
    if name in specs:
        return specs[name]
    base = re.sub(r"\.\d{3}$", "", name)
    if base in specs:
        return specs[base]
    base2 = re.sub(r"_\d+$", "", base)
    return specs.get(base2)


def mark_material_types(specs, only=None):
    """Before IngeTrazo's finishes run: glass and water become those
    finishes (its full Blender recipes); generic and glow drop a guessed
    glass/water finish."""
    for mat in _live_materials(only):
        spec = _spec_for(mat, specs)
        if not spec:
            continue
        kind = spec.get("type", "generic")
        if kind in ("glass", "water"):
            mat["ingetrazo_finish"] = kind
        elif mat.get("ingetrazo_finish") in ("glass", "water"):
            mat["ingetrazo_finish"] = "satin"


def _colour_source(nodes, bsdf):
    """What feeds the Base Color: (socket, image node) — the picture when
    there is one, for bump and glow."""
    link = next(iter(bsdf.inputs["Base Color"].links), None)
    if link is None:
        return None, None
    seen, todo = set(), [link.from_node]
    while todo:
        node = todo.pop()
        if node.name in seen:
            continue
        seen.add(node.name)
        if node.type == "TEX_IMAGE" and node.image is not None and not node.label.startswith(PBR_LABEL):
            return link.from_socket, node                  # (not a texture set's AO map)
        for inp in node.inputs:
            todo += [l.from_node for l in inp.links]
    return link.from_socket, None


def _image_node(mat, bsdf, m):
    """The image a map reads: the material's own picture («picture»), or a
    file («file», «normal») read with the picture's own coordinates (its
    UVs and tiling) — or, on a material without a picture, projected on the
    object's sides in tiles of ``size`` metres. None when there is none."""
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    _sock, pic = _colour_source(nodes, bsdf)
    src = m.get("source")
    if src == "picture":
        return pic
    if src not in ("file", "normal") or not m.get("path"):
        return None
    try:
        img = bpy.data.images.load(str(m["path"]), check_existing=True)
    except (RuntimeError, OSError) as exc:
        say("map unreadable", m["path"], exc)
        return None
    try:
        img.colorspace_settings.name = "Non-Color"     # data, not a colour
    except (TypeError, ValueError):
        pass
    node = nodes.new("ShaderNodeTexImage")
    node.image = img
    if pic is not None:
        vec = next(iter(pic.inputs["Vector"].links), None)
        if vec is not None:
            links.new(vec.from_socket, node.inputs["Vector"])
    else:
        node.projection = "BOX"
        node.projection_blend = 0.2
        coord = nodes.new("ShaderNodeTexCoord")
        mapping = nodes.new("ShaderNodeMapping")
        k = 1.0 / max(0.01, float(m.get("size", 1.0)))
        mapping.inputs["Scale"].default_value = (k, k, k)
        links.new(coord.outputs["Object"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], node.inputs["Vector"])
    return node


def _map_value(mat, bsdf, m):
    """A map as a 0..1 value: the image in black and white, inverted if
    asked, with more contrast (0 as it is … 1 pure black or white)."""
    node = _image_node(mat, bsdf, m)
    if node is None:
        return None
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bw = nodes.new("ShaderNodeRGBToBW")
    links.new(node.outputs["Color"], bw.inputs["Color"])
    out = bw.outputs["Val"]
    if m.get("invert"):
        inv = nodes.new("ShaderNodeMath"); inv.operation = "SUBTRACT"
        inv.inputs[0].default_value = 1.0
        links.new(out, inv.inputs[1])
        out = inv.outputs[0]
    c = max(0.0, min(1.0, float(m.get("contrast", 0.0))))
    if c > 0.0:
        rng = nodes.new("ShaderNodeMapRange")
        rng.clamp = True
        rng.inputs["From Min"].default_value = 0.49 * c
        rng.inputs["From Max"].default_value = 1.0 - 0.49 * c
        links.new(out, rng.inputs["Value"])
        out = rng.outputs["Result"]
    return out


def _apply_opacity_map(mat, bsdf, alpha):
    """Put a 0..1 value (white opaque, black transparent) on the material's Alpha, times what
    it already has (the picture's own cut-out, or the opacity the model gave the material), and
    let the renderer blend it: a cut-out is dithered, so it casts a shadow through its holes."""
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    socket = bsdf.inputs["Alpha"]
    old = next(iter(socket.links), None)
    mul = nodes.new("ShaderNodeMath"); mul.operation = "MULTIPLY"
    if old is not None:
        links.new(old.from_socket, mul.inputs[0])
    else:
        mul.inputs[0].default_value = float(socket.default_value)
    links.new(alpha, mul.inputs[1])
    links.new(mul.outputs[0], socket)
    for attr, val in (("surface_render_method", "DITHERED"), ("blend_method", "HASHED")):
        if hasattr(mat, attr):
            try:
                setattr(mat, attr, val)
            except (TypeError, ValueError):
                pass


def _scaled(mat, socket, factor):
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    mul = nodes.new("ShaderNodeMath"); mul.operation = "MULTIPLY"
    links.new(socket, mul.inputs[0])
    mul.inputs[1].default_value = float(factor)
    return mul.outputs[0]


#: The tallest relief taken from a picture (metres from black to white), at the
#: slider's maximum, and how soft its edges are (a fraction of the picture).
RELIEF_MAX_DISTANCE = 0.03
RELIEF_SOFTNESS = 1.0 / 256.0
RELIEF_MAX_SIDE = 1024


def _box_blur(a, r, axis):
    """A box average of half-width ``r`` along ``axis`` that wraps round, as a
    tiling texture does (cumulative sums: cost independent of ``r``)."""
    import numpy as np
    if r < 1:
        return a
    n = a.shape[axis]
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    padded = np.pad(a, pad, mode="wrap")
    cs = np.cumsum(padded, axis=axis, dtype=np.float64)
    zero_shape = list(cs.shape)
    zero_shape[axis] = 1
    cs = np.concatenate([np.zeros(zero_shape, np.float64), cs], axis=axis)
    hi = [slice(None)] * a.ndim
    lo = [slice(None)] * a.ndim
    hi[axis] = slice(2 * r + 1, 2 * r + 1 + n)
    lo[axis] = slice(0, n)
    return ((cs[tuple(hi)] - cs[tuple(lo)]) / (2 * r + 1)).astype(np.float32)


def relief_height(img, invert=False, contrast=0.0, softness=None):
    """A picture's light and dark as a SMOOTH height map, 0..1 (numpy array,
    rows top to bottom), ready to feed a bump.

    A picture's own pixels are a poor height: its speckle and film grain turn
    into noise, and a joint that is a pixel or two wide is a spike narrower than
    a render pixel, so the relief vanishes or only outlines. Here the picture
    is brought to at most ``RELIEF_MAX_SIDE`` pixels, blurred (so a joint
    becomes a groove with slopes that catch the light), stretched to use the
    whole range, inverted if asked, and given more contrast (0 as it is …
    1 pure black or white)."""
    import numpy as np
    w, h = img.size
    raw = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(raw)
    rgba = raw.reshape(h, w, 4)[::-1]                      # top row first
    lum = (0.2126 * rgba[..., 0] + 0.7152 * rgba[..., 1] + 0.0722 * rgba[..., 2]).astype(np.float32)
    f = int(np.ceil(max(w, h) / float(RELIEF_MAX_SIDE)))
    if f > 1:                                               # block average: no aliasing
        lum = lum[: (h // f) * f, : (w // f) * f]
        lum = lum.reshape(lum.shape[0] // f, f, lum.shape[1] // f, f).mean(axis=(1, 3))
    soft = RELIEF_SOFTNESS if softness is None else float(softness)
    r = max(1, int(round(max(lum.shape) * soft)))
    for _ in range(3):                                      # three boxes ≈ a gaussian
        lum = _box_blur(_box_blur(lum, r, 0), r, 1)
    lo, hi = np.percentile(lum, 2.0), np.percentile(lum, 98.0)
    if hi - lo < 1e-6:
        return np.full(lum.shape, 0.5, np.float32)
    v = np.clip((lum - lo) / (hi - lo), 0.0, 1.0)
    if invert:
        v = 1.0 - v
    c = max(0.0, min(1.0, float(contrast)))
    if c > 0.0:
        v = np.clip((v - 0.49 * c) / (1.0 - 0.98 * c), 0.0, 1.0)
    return v.astype(np.float32)


def _height_node(mat, node, m):
    """An image-texture node that carries the smooth height of ``node``'s picture,
    placed exactly as the picture is (same coordinates, same tiling)."""
    import numpy as np
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    v = relief_height(node.image, bool(m.get("invert")), float(m.get("contrast", 0.0)))
    h, w = v.shape
    himg = bpy.data.images.new("studio relief " + mat.name, w, h, alpha=False, float_buffer=True)
    try:                                   # BEFORE the pixels: setting it wipes a generated image
        himg.colorspace_settings.name = "Non-Color"
    except (TypeError, ValueError):
        pass
    px = np.empty((h, w, 4), np.float32)
    px[..., 0] = px[..., 1] = px[..., 2] = v[::-1]
    px[..., 3] = 1.0
    himg.pixels.foreach_set(px.ravel())
    himg.update()
    try:
        himg.pack()                                         # kept if the blend is saved
    except RuntimeError:
        pass
    new = nodes.new("ShaderNodeTexImage")
    new.image = himg
    new.interpolation = "Linear"
    for attr in ("extension", "projection", "projection_blend"):
        if hasattr(node, attr):
            setattr(new, attr, getattr(node, attr))
    link = next(iter(node.inputs["Vector"].links), None)
    if link is not None:
        links.new(link.from_socket, new.inputs["Vector"])
    return new


def _add_bump(mat, bsdf, amount, m=None):
    """Relief. ``m["source"]``: «picture» (its light and dark: mortar
    joints, wood grain), «file» (a height map), «normal» (a normal map),
    «grain» (a fine noise: plaster, concrete); none = the picture when
    there is one, else the grain."""
    m = m or {}
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    src = m.get("source") or "auto"
    old = next(iter(bsdf.inputs["Normal"].links), None)
    if src == "normal":
        node = _image_node(mat, bsdf, m)
        if node is None:
            return
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.inputs["Strength"].default_value = 2.0 * amount
        links.new(node.outputs["Color"], nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
        return
    _sock, pic = _colour_source(nodes, bsdf)
    height = None
    smooth = False
    if src == "picture" or (src == "auto" and pic is not None):
        node = pic
        if node is not None:
            try:
                height = _height_node(mat, node, m if src == "picture" else {}).outputs["Color"]
                smooth = True
            except Exception as exc:  # noqa: BLE001 - fall back to the plain picture
                say("relief fallback", exc)
                height = _map_value(mat, bsdf, {**m, "source": "picture"})
    elif src == "file":
        height = _map_value(mat, bsdf, m)
    bump = nodes.new("ShaderNodeBump")
    amount = max(0.0, float(amount))
    if height is not None:
        links.new(height, bump.inputs["Height"])
        if src == "file":
            # A height map means it: 1 cm from black to white.
            bump.inputs["Strength"].default_value = min(1.0, amount)
            bump.inputs["Distance"].default_value = 0.01
        else:
            # The picture's own light and dark. The slider is the HEIGHT of
            # the relief (up to RELIEF_MAX_DISTANCE from black to white), at full strength:
            # a fixed 4 mm scaled by a strength below 1 was too faint to see in
            # a render, whatever the slider said.
            bump.inputs["Strength"].default_value = 1.0
            bump.inputs["Distance"].default_value = RELIEF_MAX_DISTANCE * min(1.0, amount)
    else:
        bump.inputs["Strength"].default_value = min(1.0, amount)
        coord = nodes.new("ShaderNodeTexCoord")
        noise = nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 28.0      # grains of a few cm
        for k, v in (("Detail", 10.0), ("Roughness", 0.65)):
            if k in noise.inputs:
                noise.inputs[k].default_value = v
        links.new(coord.outputs["Object"], noise.inputs["Vector"])
        links.new(noise.outputs["Fac"], bump.inputs["Height"])
        bump.inputs["Distance"].default_value = 0.004
    if old is not None:                    # a normal map: bump on top of it
        links.new(old.from_socket, bump.inputs["Normal"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


#: Water ripples: the «easiest water in Blender» recipe — a 3-D noise (detail 16,
#: roughness 0.442) turned into a bump on a glossy surface — with its size
#: and height as controls. ``WATER_FINE``/``WATER_COARSE`` are the noise scale
#: (waves per metre) at the editor's «Ripple size» 0 and 1; ``WATER_MAX_DISTANCE``
#: is the recipe's bump distance at the Relief slider's maximum.
WATER_FINE = 108.6
WATER_COARSE = 4.0
WATER_MAX_DISTANCE = 0.1


def water_scale(size):
    """Noise scale (per metre) for a ripple size 0 (fine) … 1 (coarse), log-spaced."""
    size = max(0.0, min(1.0, float(size)))
    return WATER_FINE * (WATER_COARSE / WATER_FINE) ** size


def _water_ripples(mat, bsdf, relief, size):
    """Replace IngeTrazo's own ripples with the recipe above, driven by the
    editor: ``relief`` 0..1 is the height of the waves, ``size`` 0..1 their size."""
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    old = next(iter(bsdf.inputs["Normal"].links), None)
    if old is not None and old.from_node.type == "BUMP":        # the finish's own ripples
        bump_old = old.from_node
        feeders = [l.from_node for l in bump_old.inputs["Height"].links]
        nodes.remove(bump_old)
        for n in feeders:
            if n.type == "TEX_NOISE" and not any(o.links for o in n.outputs):
                nodes.remove(n)
    relief = max(0.0, min(1.0, float(relief)))
    if relief <= 0.0:
        return                                                    # flat, mirror-like water
    pos = nodes.new("ShaderNodeNewGeometry")                      # world position: ripples of a true size
    noise = nodes.new("ShaderNodeTexNoise")
    if hasattr(noise, "noise_dimensions"):
        noise.noise_dimensions = "3D"
    noise.inputs["Scale"].default_value = water_scale(size)
    for k, v in (("Detail", 16.0), ("Roughness", 0.442), ("Distortion", 0.0)):
        if k in noise.inputs:
            noise.inputs[k].default_value = v
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 1.0
    bump.inputs["Distance"].default_value = WATER_MAX_DISTANCE * relief
    links.new(pos.outputs["Position"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _image_adjust(mat, bsdf, adj):
    """The editor's picture adjustments, in the render and the preview only (the 3D view keeps the
    original picture). ``adj``: ``hue`` (degrees), ``saturation`` (1 = as it is), ``brightness`` and
    ``contrast`` (−1..1), ``rotation`` (degrees, of the picture on the surface), ``tint`` (a colour)
    with ``tint_strength`` (0..1), ``flat`` (a colour that replaces the picture).

    The picture's colour goes through hue/saturation, brightness/contrast and the tint, in that
    order, on its way to the Base Color. A material without a picture goes through the same nodes
    with its colour (hue, brightness, tint work on it too)."""
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    base = bsdf.inputs["Base Color"]
    flat = adj.get("flat")
    if flat:
        for link in list(base.links):
            links.remove(link)
        base.default_value = (float(flat[0]), float(flat[1]), float(flat[2]), 1.0)
    rot = float(adj.get("rotation") or 0.0)
    if rot and not flat:
        _sock, pic = _colour_source(nodes, bsdf)
        if pic is not None:
            vec = next(iter(pic.inputs["Vector"].links), None)
            if vec is not None:
                src = vec.from_socket
            else:
                src = nodes.new("ShaderNodeTexCoord").outputs["UV"]
            mp = nodes.new("ShaderNodeMapping")
            mp.vector_type = "POINT"
            th = math.radians(rot)
            c, s = math.cos(th), math.sin(th)
            mp.inputs["Rotation"].default_value = (0.0, 0.0, th)
            # about the middle of the picture: location = centre − R·centre
            mp.inputs["Location"].default_value = (0.5 - 0.5 * c + 0.5 * s, 0.5 - 0.5 * s - 0.5 * c, 0.0)
            links.new(src, mp.inputs["Vector"])
            links.new(mp.outputs["Vector"], pic.inputs["Vector"])
    hue = float(adj.get("hue") or 0.0)
    sat = float(adj.get("saturation", 1.0))
    bright = float(adj.get("brightness") or 0.0)
    contrast = float(adj.get("contrast") or 0.0)
    tint = adj.get("tint")
    strength = max(0.0, min(1.0, float(adj.get("tint_strength", 0.5 if tint else 0.0))))
    steps = []
    if hue or abs(sat - 1.0) > 1e-6:
        steps.append("hsv")
    if bright or contrast:
        steps.append("bc")
    if tint and strength > 0.0:
        steps.append("tint")
    if not steps:
        return False
    link = next(iter(base.links), None)
    carried = link.from_socket if link is not None else None
    color0 = tuple(base.default_value)
    for kind in steps:
        if kind == "hsv":
            node = nodes.new("ShaderNodeHueSaturation")
            node.inputs["Hue"].default_value = 0.5 + hue / 360.0
            node.inputs["Saturation"].default_value = max(0.0, sat)
            inp, out = node.inputs["Color"], node.outputs["Color"]
        elif kind == "bc":
            node = nodes.new("ShaderNodeBrightContrast")
            node.inputs["Bright"].default_value = bright
            node.inputs["Contrast"].default_value = contrast
            inp, out = node.inputs["Color"], node.outputs["Color"]
        else:
            node = nodes.new("ShaderNodeMix")
            node.data_type = "RGBA"
            node.blend_type = "MULTIPLY"
            node.clamp_result = True
            _socket(node, "Factor_Float", 0).default_value = strength
            _socket(node, "B_Color", 7).default_value = (float(tint[0]), float(tint[1]), float(tint[2]), 1.0)
            inp = _socket(node, "A_Color", 6)
            out = next(s for s in node.outputs if s.identifier == "Result_Color")
        if carried is not None:
            links.new(carried, inp)
        else:
            inp.default_value = color0
        carried = out
    links.new(carried, base)
    return True


def apply_material_specs(specs, with_sets=(), only=None):
    """After IngeTrazo's finishes: the editor's numbers — and maps — on each
    material. With a map, the setting's slider scales it. ``with_sets``: the
    materials whose picture has a texture set (:func:`apply_texture_sets`):
    their own normal and displacement maps replace the AUTOMATIC relief (a
    relief source chosen in the editor still applies, on top)."""
    done = 0
    for mat in _live_materials(only):
        spec = _spec_for(mat, specs)
        if not spec or not mat.node_tree:
            continue
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        kind = spec.get("type", "generic")
        maps = spec.get("maps") or {}
        if spec.get("image") and kind != "grass":
            _image_adjust(mat, bsdf, spec["image"])      # first: the maps below follow the picture's coordinates
        for key, names in (("roughness", ("Roughness",)), ("metallic", ("Metallic",))):
            if key not in spec or (key == "metallic" and kind != "generic"):
                continue
            core["_set"](bsdf, names, float(spec[key]))
            m = maps.get(key) or {}
            if m.get("source"):
                val = _map_value(mat, bsdf, m)
                if val is not None:
                    mat.node_tree.links.new(_scaled(mat, val, spec[key]), bsdf.inputs[names[0]])
        m = maps.get("opacity") or {}
        if m.get("source") and kind != "grass":
            val = _map_value(mat, bsdf, m)          # where it is see-through: black is transparent
            if val is not None:
                _apply_opacity_map(mat, bsdf, val)
                mat["studio_opacity_map"] = True
        if kind in ("generic", "glow", "grass"):
            core["_set"](bsdf, ("Transmission Weight", "Transmission"), 0.0)
        elif kind == "glass" and "transparency" in spec:
            # Glass refracts instead of blending: the slider is how much it lets through.
            core["_set"](bsdf, ("Transmission Weight", "Transmission"),
                         max(0.0, min(1.0, float(spec["transparency"]))))
        if spec.get("coat"):
            core["_set"](bsdf, ("Coat Weight", "Clearcoat"), float(spec["coat"]))
            core["_set"](bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.05)
        if spec.get("sheen"):
            core["_set"](bsdf, ("Sheen Weight", "Sheen"), float(spec["sheen"]))
        if kind == "water" and "ripple_size" in spec:
            _water_ripples(mat, bsdf, float(spec.get("bump", 0.0)), float(spec["ripple_size"]))
        elif float(spec.get("bump", 0.0)) > 0.0:
            m = maps.get("bump") or {}
            if mat.name in with_sets and not m.get("source"):
                say("relief", mat.name, "from its texture set, not guessed from the picture")
            else:
                _add_bump(mat, bsdf, float(spec["bump"]), m)
        if kind == "glow" and float(spec.get("glow", 0.0)) > 0.0:
            sock, _img = _colour_source(mat.node_tree.nodes, bsdf)
            if sock is not None and "Emission Color" in bsdf.inputs:
                mat.node_tree.links.new(sock, bsdf.inputs["Emission Color"])
            elif "Emission Color" in bsdf.inputs:
                bsdf.inputs["Emission Color"].default_value = bsdf.inputs["Base Color"].default_value
            core["_set"](bsdf, ("Emission Strength",), float(spec["glow"]))
            m = maps.get("glow") or {}
            if m.get("source"):
                val = _map_value(mat, bsdf, m)      # where it glows: a mask
                if val is not None:
                    level = _scaled(mat, val, spec["glow"])
                    level.node.name = "studio_glow_level"      # the meter dims it
                    mat.node_tree.links.new(level, bsdf.inputs["Emission Strength"])
            mat["studio_glow"] = True
        done += 1
    if done:
        say("materials", done, "set in the material editor")


# ---- grass ------------------------------------------------------------------------------
#
# A material of type «grass» grows blades on every face that wears it, in the render
# only: tufts of a few bent blades scattered over the faces (geometry nodes, instanced,
# so a lawn costs little memory), standing up whatever the face's slope, as tall as the
# editor's «Grass height». Their colour is the material's own: its picture read where
# each tuft stands (a lawn picture gives a lawn's patches), else its colour, darker at
# the root and a little lighter at the tip, each tuft a little different. The face
# under them keeps its own look and fills the gaps.

#: Tufts per square metre for short grass (each of GRASS_BLADES blades); taller grass
#: is sparser (fewer, bigger tufts) down to GRASS_DENSITY_MIN.
GRASS_DENSITY = 260.0
GRASS_DENSITY_MIN = 60.0
GRASS_BLADES = 9
#: The most tufts in one render: past it the whole lawn gets sparser (memory and time).
GRASS_MAX_TUFTS = 600_000
GRASS_TUFT_RADIUS = 0.35            # × the height
GRASS_BLADE_WIDTH = 0.045           # × the height, at the root


def grass_density(height):
    """Tufts per m² for grass ``height`` metres tall."""
    h = max(0.005, float(height))
    return max(GRASS_DENSITY_MIN, min(GRASS_DENSITY, GRASS_DENSITY * 0.10 / h))


def _grass_tuft_mesh(name, seed=0):
    """One tuft, 1 m tall (scaled per instance): GRASS_BLADES tapered, bent blades
    around the origin, with ``grass_h`` (0 root … 1 tip) on its points."""
    import random
    rng = random.Random(seed)
    verts, faces, hs = [], [], []
    segs = 4
    for _b in range(GRASS_BLADES):
        a = rng.uniform(0, 2 * math.pi)
        r = GRASS_TUFT_RADIUS * math.sqrt(rng.random())
        ox, oy = r * math.cos(a), r * math.sin(a)
        yaw = rng.uniform(0, 2 * math.pi)
        tall = rng.uniform(0.65, 1.0)
        bend = rng.uniform(0.15, 0.45) * tall
        dx, dy = math.cos(yaw), math.sin(yaw)                 # the way it bends
        wx, wy = -dy, dx                                      # across the blade
        w0 = GRASS_BLADE_WIDTH * rng.uniform(0.7, 1.2)
        base = len(verts)
        for i in range(segs + 1):
            t = i / segs
            z = tall * (t - 0.25 * bend * t * t)
            off = bend * t * t
            w = w0 * (1.0 - t) ** 0.8 * 0.5
            cx, cy = ox + dx * off, oy + dy * off
            if i < segs:
                verts += [(cx - wx * w, cy - wy * w, z), (cx + wx * w, cy + wy * w, z)]
                hs += [t, t]
            else:
                verts.append((cx, cy, z))
                hs.append(1.0)
        for i in range(segs - 1):
            k = base + 2 * i
            faces.append((k, k + 1, k + 3, k + 2))
        k = base + 2 * (segs - 1)
        faces.append((k, k + 1, k + 2))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    attr = me.attributes.new("grass_h", "FLOAT", "POINT")
    attr.data.foreach_set("value", hs)
    for poly in me.polygons:
        poly.use_smooth = True
    me.update()
    return me


def _grass_material(mat, uv_name):
    """The blades' material: ``mat``'s picture read at each tuft's place (the UVs
    the tuft carries from the face), else its colour; root to tip, tuft to tuft."""
    nodes_src = mat.node_tree.nodes
    bsdf_src = next((n for n in nodes_src if n.type == "BSDF_PRINCIPLED"), None)
    _sock, pic = _colour_source(nodes_src, bsdf_src) if bsdf_src is not None else (None, None)
    gm = bpy.data.materials.new("studio grass " + mat.name)
    if gm.node_tree is None:                     # Blender before 5: nodes are switched on
        gm.use_nodes = True
    nt = gm.node_tree
    nodes, links = nt.nodes, nt.links
    out = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    if pic is not None:
        uv = nodes.new("ShaderNodeAttribute")
        uv.attribute_type = "INSTANCER"
        uv.attribute_name = uv_name
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = pic.image
        tex.extension = getattr(pic, "extension", "REPEAT")
        links.new(uv.outputs["Vector"], tex.inputs["Vector"])
        colour = tex.outputs["Color"]
    else:
        rgb = nodes.new("ShaderNodeRGB")
        rgb.outputs[0].default_value = tuple(bsdf_src.inputs["Base Color"].default_value) if bsdf_src else (0.2, 0.4, 0.1, 1)
        colour = rgb.outputs[0]
    # each tuft a little lighter or darker; the root in shade, the tip in the light
    info = nodes.new("ShaderNodeObjectInfo")
    vary = nodes.new("ShaderNodeMapRange")
    vary.inputs["To Min"].default_value, vary.inputs["To Max"].default_value = 0.75, 1.15
    links.new(info.outputs["Random"], vary.inputs["Value"])
    h = nodes.new("ShaderNodeAttribute")
    h.attribute_type = "GEOMETRY"
    h.attribute_name = "grass_h"
    root = nodes.new("ShaderNodeMapRange")
    root.inputs["To Min"].default_value, root.inputs["To Max"].default_value = 0.45, 1.05
    links.new(h.outputs["Fac"], root.inputs["Value"])
    k = nodes.new("ShaderNodeMath"); k.operation = "MULTIPLY"
    links.new(vary.outputs["Result"], k.inputs[0]); links.new(root.outputs["Result"], k.inputs[1])
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.clamp_result = True
    _socket(mix, "Factor_Float", 0).default_value = 1.0
    links.new(colour, _socket(mix, "A_Color", 6))
    links.new(k.outputs[0], _socket(mix, "B_Color", 7))
    tint = next(s for s in mix.outputs if s.identifier == "Result_Color")
    links.new(tint, bsdf.inputs["Base Color"])
    core["_set"](bsdf, ("Roughness",), 0.55)
    core["_set"](bsdf, ("Specular IOR Level", "Specular"), 0.35)
    # light through the blades
    trans = nodes.new("ShaderNodeBsdfTranslucent")
    links.new(tint, trans.inputs["Color"])
    both = nodes.new("ShaderNodeMixShader")
    both.inputs["Fac"].default_value = 0.3
    links.new(bsdf.outputs["BSDF"], both.inputs[1])
    links.new(trans.outputs["BSDF"], both.inputs[2])
    links.new(both.outputs["Shader"], out.inputs["Surface"])
    return gm


def _grass_area(obj, mat_indices):
    """World-space area of ``obj``'s faces wearing those material slots (m²)."""
    mw = obj.matrix_world
    area = 0.0
    me = obj.data
    for poly in me.polygons:
        if poly.material_index in mat_indices:
            pts = [mw @ me.vertices[i].co for i in poly.vertices]
            for i in range(1, len(pts) - 1):
                area += 0.5 * (pts[i] - pts[0]).cross(pts[i + 1] - pts[0]).length
    return area


def _grass_node_group(name, branches):
    """Geometry nodes: the mesh, plus for each (material, tuft object, density,
    height, seed) tufts scattered on the faces wearing it, upright, turned and sized
    at random."""
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")
    join = nodes.new("GeometryNodeJoinGeometry")
    links.new(gin.outputs[0], join.inputs[0])
    for mat, tuft, density, height, seed in branches:
        sel = nodes.new("GeometryNodeMaterialSelection")
        sel.inputs["Material"].default_value = mat
        dist = nodes.new("GeometryNodeDistributePointsOnFaces")
        dist.distribute_method = "RANDOM"
        links.new(gin.outputs[0], dist.inputs["Mesh"])
        links.new(sel.outputs["Selection"], dist.inputs["Selection"])
        dist.inputs["Density"].default_value = float(density)
        dist.inputs["Seed"].default_value = int(seed)
        src = nodes.new("GeometryNodeObjectInfo")
        src.inputs["Object"].default_value = tuft
        inst = nodes.new("GeometryNodeInstanceOnPoints")
        links.new(dist.outputs["Points"], inst.inputs["Points"])
        links.new(src.outputs["Geometry"], inst.inputs["Instance"])
        turn = nodes.new("FunctionNodeRandomValue")
        turn.data_type = "FLOAT"
        turn.inputs["Min"].default_value = 0.0
        turn.inputs["Max"].default_value = 2 * math.pi
        turn.inputs["Seed"].default_value = int(seed) + 1
        rot = nodes.new("ShaderNodeCombineXYZ")
        links.new(turn.outputs["Value"], rot.inputs["Z"])
        links.new(rot.outputs["Vector"], inst.inputs["Rotation"])
        size = nodes.new("FunctionNodeRandomValue")
        size.data_type = "FLOAT"
        size.inputs["Min"].default_value = 0.75 * float(height)
        size.inputs["Max"].default_value = 1.15 * float(height)
        size.inputs["Seed"].default_value = int(seed) + 2
        links.new(size.outputs["Value"], inst.inputs["Scale"])
        links.new(inst.outputs["Instances"], join.inputs[0])
    links.new(join.outputs[0], gout.inputs[0])
    return ng


def build_grass(specs, factor=1.0):
    """Grow the grass of every material of type «grass» (see above), at its own
    ``grass_density`` (tufts per m²; the height's automatic one when it has none),
    ``factor`` times as dense. Returns the number of tufts asked for."""
    kinds, dens = {}, {}
    for mat in _live_materials():
        spec = _spec_for(mat, specs)
        if spec and spec.get("type") == "grass" and mat.node_tree:
            kinds[mat.name] = float(spec.get("grass_height", 0.08))
            if spec.get("grass_density"):
                dens[mat.name] = max(1.0, float(spec["grass_density"]))
    if not kinds:
        return 0
    hidden = bpy.data.collections.new("studio grass tufts")
    bpy.context.scene.collection.children.link(hidden)
    hidden.hide_render = True
    hidden.hide_viewport = True
    plan, total = [], 0.0
    for obj in [o for o in bpy.context.scene.objects if o.type == "MESH"]:
        slots = {i: s.material for i, s in enumerate(obj.material_slots)
                 if s.material is not None and s.material.name in kinds}
        if not slots:
            continue
        for i, mat in slots.items():
            area = _grass_area(obj, {i})
            if area <= 0.0:
                continue
            d = dens.get(mat.name) or grass_density(kinds[mat.name])
            d *= max(0.01, float(factor))
            plan.append((obj, mat, d, area))
            total += d * area
    if not plan:
        return 0
    thin = min(1.0, GRASS_MAX_TUFTS / max(total, 1.0))
    tufts = {}
    per_obj = {}
    for n, (obj, mat, d, area) in enumerate(plan):
        if mat.name not in tufts:
            uv = obj.data.uv_layers.active.name if obj.data.uv_layers.active else "UVMap"
            me = _grass_tuft_mesh("studio grass " + mat.name, seed=len(tufts))
            me.materials.append(_grass_material(mat, uv))
            tob = bpy.data.objects.new("studio grass " + mat.name, me)
            hidden.objects.link(tob)
            tufts[mat.name] = tob
        per_obj.setdefault(obj.name, (obj, []))[1].append(
            (mat, tufts[mat.name], d * thin, kinds[mat.name], 17 * n + 3))
    for obj, branches in per_obj.values():
        mod = obj.modifiers.new("Studio grass", "NODES")
        mod.node_group = _grass_node_group("studio grass " + obj.name, branches)
    count = int(total * thin)
    say("grass", ", ".join(f"{m} {h * 100:.0f} cm {dens.get(m) or grass_density(h):.0f}/m2"
                           for m, h in kinds.items()),
        f"- {count} tufts" + (f" (thinned to {thin:.0%})" if thin < 1.0 else ""))
    return count


# ---- full texture sets ------------------------------------------------------------------
#
# The job's ``"pbr"`` block (render_studio/pbr.py): for each colour picture of the
# model, by file name, its companion maps as absolute paths. They are read with
# the picture's own coordinates (its UVs, so its tile size and rotation).

#: The label of every node a texture set adds (the picture finder skips them).
PBR_LABEL = "Texture set: "
#: How much the ambient occlusion map darkens the colour (0 none … 1 fully): the
#: render's own light bounce already shades the model's real corners.
PBR_AO_STRENGTH = 0.75
#: A displacement map as relief (when the set has no normal map): metres from black to white.
PBR_DISPLACEMENT_DISTANCE = 0.01
#: The editor's Roughness that leaves a roughness map as it is; above or below it scales the map.
PBR_ROUGHNESS_NEUTRAL = 0.5


def _texture_set_for(img, sets):
    """The texture set of a picture (a Blender image) by its file name: the
    importer may add «.001», drop the extension or cut a long name."""
    import re
    if img is None or not sets:
        return None
    names = [img.name, re.sub(r"\.\d{3}$", "", img.name)]
    try:
        names.append(os.path.basename(bpy.path.abspath(img.filepath or "")))
    except Exception:  # noqa: BLE001 - a packed image may have no path at all
        pass
    stems = {os.path.splitext(k)[0].lower(): v for k, v in sets.items()}
    lower = {k.lower(): v for k, v in sets.items()}
    for n in names:
        if not n:
            continue
        hit = sets.get(n) or lower.get(n.lower()) or stems.get(n.lower()) \
            or stems.get(os.path.splitext(n)[0].lower())
        if hit:
            return hit
    for n in names[:2]:                  # Blender's 63-byte names
        if len(n.encode("utf-8")) >= 63:
            for k, v in lower.items():
                if k.startswith(n.lower()):
                    return v
    return None


def match_texture_sets(sets):
    """{material name: its texture set} for the model's materials whose
    picture has one."""
    out = {}
    if not sets:
        return out
    for mat in _live_materials():
        if not mat.node_tree:
            continue
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        _sock, pic = _colour_source(mat.node_tree.nodes, bsdf)
        hit = _texture_set_for(pic.image if pic is not None else None, sets)
        if hit:
            out[mat.name] = hit
    return out


def _set_image(mat, pic, path, what):
    """An image node reading the map at ``path`` exactly where the picture
    ``pic`` is read (same coordinates, tiling, interpolation), as data."""
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    try:
        img = bpy.data.images.load(str(path), check_existing=True)
    except (RuntimeError, OSError) as exc:
        say("texture set map unreadable", path, exc)
        return None
    try:
        img.colorspace_settings.name = "Non-Color"
    except (TypeError, ValueError):
        pass
    node = nodes.new("ShaderNodeTexImage")
    node.image = img
    node.label = PBR_LABEL + what
    for attr in ("interpolation", "extension", "projection", "projection_blend"):
        if hasattr(pic, attr):
            try:
                setattr(node, attr, getattr(pic, attr))
            except (TypeError, ValueError):
                pass
    node.location = (pic.location.x - 300, pic.location.y - 300)
    vec = next(iter(pic.inputs["Vector"].links), None)
    if vec is not None:
        links.new(vec.from_socket, node.inputs["Vector"])
    return node


def _socket(node, identifier, fallback):
    return next((s for s in node.inputs if s.identifier == identifier), None) or node.inputs[fallback]


def _channels(mat, colour_socket):
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    sep = nodes.new("ShaderNodeSeparateColor")
    links.new(colour_socket, sep.inputs["Color"])
    return sep.outputs["Red"], sep.outputs["Green"], sep.outputs["Blue"]


def _normal_chain_end(bsdf):
    """Where a texture set's normal goes: the BSDF's Normal, or the Normal of
    the last relief (bump) already on it, so that relief sits on top. None
    when a normal map chosen in the editor is already there (it wins)."""
    link = next(iter(bsdf.inputs["Normal"].links), None)
    if link is None:
        return bsdf.inputs["Normal"]
    node = link.from_node
    while node.type == "BUMP":
        nxt = next(iter(node.inputs["Normal"].links), None)
        if nxt is None:
            return node.inputs["Normal"]
        node = nxt.from_node
    return None


def _uv_map_of(pic):
    vec = next(iter(pic.inputs["Vector"].links), None)
    node = vec.from_node if vec is not None else None
    while node is not None and node.type != "UVMAP":
        nxt = next((l for s in node.inputs for l in s.links), None)
        node = nxt.from_node if nxt is not None else None
    return getattr(node, "uv_map", "") if node is not None else ""


def apply_texture_sets(matched, specs):
    """Each material's texture set on its Principled BSDF, after the editor's
    settings: normal (OpenGL; a DirectX one with its green flipped),
    roughness, metalness, ambient occlusion (darkening the colour), opacity,
    and displacement as relief when there is no normal map. The editor's
    explicit choices stay: a roughness or metal map picked there wins, its
    Roughness slider scales the set's roughness (0.5 leaves it as it is), its
    Metal slider is a floor under the set's metalness; glass and water take
    only the normal map."""
    done = []
    for mat in _live_materials():
        ts = matched.get(mat.name)
        if not ts or not mat.node_tree:
            continue
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        colour, pic = _colour_source(nodes, bsdf)
        if pic is None:
            continue
        spec = _spec_for(mat, specs) or {}
        kind = spec.get("type") or ("glass" if mat.get("ingetrazo_finish") == "glass"
                                    else "water" if mat.get("ingetrazo_finish") == "water" else "generic")
        chosen = spec.get("maps") or {}
        used = []
        # normal map (or displacement as relief)
        end = _normal_chain_end(bsdf)
        if ts.get("normal") and end is not None:
            node = _set_image(mat, pic, ts["normal"], "normal")
            if node is not None:
                col = node.outputs["Color"]
                if ts.get("normal_flip_green"):
                    r, g, b = _channels(mat, col)
                    inv = nodes.new("ShaderNodeMath"); inv.operation = "SUBTRACT"
                    inv.inputs[0].default_value = 1.0
                    links.new(g, inv.inputs[1])
                    comb = nodes.new("ShaderNodeCombineColor")
                    links.new(r, comb.inputs["Red"]); links.new(inv.outputs[0], comb.inputs["Green"])
                    links.new(b, comb.inputs["Blue"])
                    col = comb.outputs["Color"]
                nmap = nodes.new("ShaderNodeNormalMap")
                nmap.space = "TANGENT"
                uv = _uv_map_of(pic)
                if uv:
                    nmap.uv_map = uv
                nmap.inputs["Strength"].default_value = 1.0
                links.new(col, nmap.inputs["Color"])
                links.new(nmap.outputs["Normal"], end)
                used.append("normal (green flipped)" if ts.get("normal_flip_green") else "normal")
        elif ts.get("displacement") and end is not None and kind not in ("glass", "water"):
            node = _set_image(mat, pic, ts["displacement"], "displacement")
            if node is not None:
                bump = nodes.new("ShaderNodeBump")
                bump.inputs["Strength"].default_value = 1.0
                bump.inputs["Distance"].default_value = PBR_DISPLACEMENT_DISTANCE
                links.new(node.outputs["Color"], bump.inputs["Height"])
                links.new(bump.outputs["Normal"], end)
                used.append("displacement as relief")
        if kind in ("glass", "water"):
            if used:
                done.append(f"{mat.name}: {', '.join(used)}")
            continue
        # the packed AO / roughness / metal, for what has no map of its own
        arm = None
        if ts.get("arm") and not all(ts.get(k) for k in ("ao", "roughness", "metalness")):
            node = _set_image(mat, pic, ts["arm"], "AO/roughness/metal")
            if node is not None:
                arm = _channels(mat, node.outputs["Color"])

        def value(key, channel, what):
            if ts.get(key):
                node = _set_image(mat, pic, ts[key], what)
                if node is not None:
                    return node.outputs["Color"]
            return arm[channel] if arm is not None else None

        if not (chosen.get("roughness") or {}).get("source"):
            rough = value("roughness", 1, "roughness")
            if rough is not None:
                k = float(spec.get("roughness", PBR_ROUGHNESS_NEUTRAL)) / PBR_ROUGHNESS_NEUTRAL
                if abs(k - 1.0) > 1e-6:
                    mul = nodes.new("ShaderNodeMath"); mul.operation = "MULTIPLY"; mul.use_clamp = True
                    links.new(rough, mul.inputs[0]); mul.inputs[1].default_value = k
                    rough = mul.outputs[0]
                links.new(rough, bsdf.inputs["Roughness"])
                used.append("roughness")
        if not (chosen.get("metallic") or {}).get("source"):
            metal = value("metalness", 2, "metalness")
            if metal is not None:
                floor = float(spec.get("metallic", 0.0)) if kind == "generic" else 0.0
                if floor > 0.0:
                    mx = nodes.new("ShaderNodeMath"); mx.operation = "MAXIMUM"
                    links.new(metal, mx.inputs[0]); mx.inputs[1].default_value = floor
                    metal = mx.outputs[0]
                links.new(metal, bsdf.inputs["Metallic"])
                used.append("metalness")
        ao = value("ao", 0, "ambient occlusion")
        if ao is not None and colour is not None:
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.clamp_result = True
            _socket(mix, "Factor_Float", 0).default_value = PBR_AO_STRENGTH
            links.new(colour, _socket(mix, "A_Color", 6))
            links.new(ao, _socket(mix, "B_Color", 7))
            out = next(s for s in mix.outputs if s.identifier == "Result_Color")
            links.new(out, bsdf.inputs["Base Color"])
            used.append("ambient occlusion")
        if ts.get("opacity"):
            node = _set_image(mat, pic, ts["opacity"], "opacity")
            if node is not None:
                alpha = node.outputs["Color"]
                old = next(iter(bsdf.inputs["Alpha"].links), None)
                if old is not None:                      # the picture's own cut-out too
                    mul = nodes.new("ShaderNodeMath"); mul.operation = "MULTIPLY"
                    links.new(old.from_socket, mul.inputs[0]); links.new(alpha, mul.inputs[1])
                    alpha = mul.outputs[0]
                links.new(alpha, bsdf.inputs["Alpha"])
                for attr, val in (("surface_render_method", "DITHERED"), ("blend_method", "HASHED")):
                    if hasattr(mat, attr):
                        try:
                            setattr(mat, attr, val)
                        except (TypeError, ValueError):
                            pass
                used.append("opacity")
        if used:
            mat["studio_texture_set"] = ", ".join(used)
            done.append(f"{mat.name}: {', '.join(used)}")
    for line in done:
        say("texture set", line)
    return done


# ---- the white model -----------------------------------------------------------------

def white_model(skip_ground=True):
    """Every material white and matte; glass and water stay see-through
    (Enscape's white mode)."""
    n = 0
    for mat in _live_materials():
        if skip_ground and mat.name.startswith("IngeTrazo ground"):
            continue
        if not mat.node_tree:
            continue
        bsdf = next((x for x in mat.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        if mat.get("ingetrazo_finish") in ("glass", "water") or mat.get("rs_section_cap"):
            continue
        core["_set"](bsdf, ("Base Color",), (0.82, 0.82, 0.80, 1.0))
        core["_set"](bsdf, ("Roughness",), 0.75)
        core["_set"](bsdf, ("Metallic",), 0.0)
        core["_set"](bsdf, ("Specular IOR Level", "Specular"), 0.3)
        core["_set"](bsdf, ("Coat Weight", "Clearcoat"), 0.0)
        n += 1
    say("white model", n, "materials")


# ---- the finish: colour management and compositor ------------------------------------

def set_look(scene, look_names, white_balance=None, tint=None):
    view = scene.view_settings
    try:
        view.view_transform = "AgX"
    except TypeError:
        pass
    for look in look_names:
        try:
            view.look = look
            say("look", look)
            break
        except TypeError:
            continue
    if white_balance and hasattr(view, "use_white_balance"):
        view.use_white_balance = True
        view.white_balance_temperature = float(white_balance)
        if tint is not None:
            view.white_balance_tint = float(tint)


def build_compositor(scene, saturation=1.0, bloom=0.0, vignette=0.0, exposure=0.0):
    """Render layers → saturation → bloom → vignette → output, in Blender 5's
    compositor (a node group set as the scene's compositing group)."""
    if saturation == 1.0 and bloom <= 0.0 and vignette <= 0.0:
        return
    if not hasattr(scene, "compositing_node_group"):
        say("compositor", "unavailable")
        return
    ng = bpy.data.node_groups.new("IngeTrazo studio", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    nodes, links = ng.nodes, ng.links
    rl = nodes.new("CompositorNodeRLayers")
    out = nodes.new("NodeGroupOutput")
    cur = rl.outputs["Image"]
    if saturation != 1.0:
        hs = nodes.new("CompositorNodeHueSat")
        sat = hs.inputs.get("Saturation")
        if sat is not None:
            sat.default_value = float(saturation)
        links.new(cur, hs.inputs["Image"])
        cur = hs.outputs["Image"]
    if bloom > 0.0:
        gl = nodes.new("CompositorNodeGlare")
        # The compositor sees the light BEFORE the view's exposure: the
        # threshold follows it, so only what will look brighter than white
        # (the sun on glass, lamps, glints) blooms — not a bright sky.
        threshold = 1.6 * (2.0 ** (-float(exposure)))
        for name, value in (("Type", "Bloom"), ("Quality", "High"), ("Threshold", threshold),
                            ("Smoothness", 0.25), ("Strength", float(bloom)), ("Size", 0.55)):
            sock = gl.inputs.get(name)
            if sock is not None:
                try:
                    sock.default_value = value
                except (TypeError, ValueError):
                    pass
        links.new(cur, gl.inputs["Image"])
        cur = gl.outputs["Image"]
    if vignette > 0.0:
        el = nodes.new("CompositorNodeEllipseMask")
        for name, value in (("Size", (1.35, 1.35)), ("Width", 1.35), ("Height", 1.35)):
            sock = el.inputs.get(name)
            if sock is not None:
                try:
                    sock.default_value = value
                except (TypeError, ValueError):
                    pass
        bl = nodes.new("CompositorNodeBlur")
        for name, value in (("Size", (300.0, 300.0)), ("Size X", 300), ("Size Y", 300)):
            sock = bl.inputs.get(name)
            if sock is not None:
                try:
                    sock.default_value = value
                except (TypeError, ValueError):
                    pass
        links.new(el.outputs[0], bl.inputs["Image"])
        # Image × blurred ellipse, by ``vignette``: darker towards the corners.
        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = float(vignette)
        links.new(cur, mix.inputs["A"])
        links.new(bl.outputs["Image"], mix.inputs["B"])
        cur = mix.outputs["Result"]
    links.new(cur, out.inputs[0])
    scene.compositing_node_group = ng
    if hasattr(scene.render, "use_compositing"):
        scene.render.use_compositing = True
    say("compositor", f"saturation {saturation} bloom {bloom} vignette {vignette}")


# ---- automatic exposure ----------------------------------------------------------------

def measure_exposure(scene, target=0.2, bias=0.0, fraction=25, samples=8, white=1.6, max_ev=8.0):
    """Render a small, quick image in scene-linear light (no exposure, no
    compositor), meter it — centre-weighted log average, the brightest
    2 % (sun, glints) left out — and return the exposure that brings it
    to ``target`` (+ ``bias`` stops)."""
    import numpy as np
    r = scene.render
    keep = (r.resolution_percentage, r.filepath, r.image_settings.file_format,
            scene.view_settings.exposure, getattr(r, "use_compositing", None))
    tmp = os.path.join(os.path.dirname(r.filepath) or HERE, "_meter.exr")
    # Glowing materials (light panels, screens) are metered as off: they
    # are meant to shine, not to darken the whole picture.
    glows = []
    for mat in _live_materials():
        if mat.get("studio_glow") and mat.node_tree:
            bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            lvl = mat.node_tree.nodes.get("studio_glow_level")
            sock = lvl.inputs[1] if lvl is not None else (
                bsdf.inputs.get("Emission Strength") if bsdf else None)
            if sock is not None:
                glows.append((sock, sock.default_value))
                sock.default_value = 0.0
    try:
        r.resolution_percentage = fraction
        r.image_settings.file_format = "OPEN_EXR"
        r.filepath = tmp
        scene.view_settings.exposure = 0.0
        if keep[4] is not None:
            r.use_compositing = False
        core["set_samples"](scene, samples)
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(tmp)
        w, h = img.size
        px = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(h, w, 4)
        lum = 0.2126 * px[..., 0] + 0.7152 * px[..., 1] + 0.0722 * px[..., 2]
        lum = np.clip(lum, 1e-5, None)
        yy, xx = np.mgrid[0:h, 0:w]
        cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
        weight = np.exp(-(((xx - cx) / (0.55 * w)) ** 2 + ((yy - cy) / (0.55 * h)) ** 2))
        cut = np.quantile(lum, 0.98)
        keep_px = lum <= cut
        logavg = float(np.exp(np.sum(np.log(lum[keep_px]) * weight[keep_px]) / np.sum(weight[keep_px])))
        ev_avg = math.log2(target / logavg)
        # Highlights kept: the bright end (the 97th percentile, glints left
        # out) lands near ``white`` — where AgX's shoulder still shows detail
        # — so sunlit white walls don't burn out; whichever is darker wins.
        p97 = float(np.quantile(lum, 0.97))
        ev_high = math.log2(white / max(p97, 1e-5))
        ev = min(ev_avg, ev_high, max_ev) + bias
        ev = max(-8.0, min(8.0, ev))
        bpy.data.images.remove(img)
        say("meter", f"log-average {logavg:.4f} (EV {ev_avg:+.2f}), highlights {p97:.3f} "
                     f"(EV {ev_high:+.2f}) -> exposure {ev:+.2f}")
        return ev
    finally:
        for sock, value in glows:
            sock.default_value = value
        r.resolution_percentage, r.filepath, r.image_settings.file_format = keep[0], keep[1], keep[2]
        scene.view_settings.exposure = keep[3]
        if keep[4] is not None:
            r.use_compositing = keep[4]
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---- lights --------------------------------------------------------------------------------

BLENDER_LIGHT = {"point": "POINT", "spot": "SPOT", "area": "AREA", "sun": "SUN"}


def _ies_nodes(data, path, scale=1.0):
    """An IES profile on a light (Cycles reads it; EEVEE ignores light nodes):
    the profile's shape drives the light's emission strength."""
    data.use_nodes = True
    nt = data.node_tree
    emit = next((n for n in nt.nodes if n.type == "EMISSION"), None)
    if emit is None:
        emit = nt.nodes.new("ShaderNodeEmission")
        out = next((n for n in nt.nodes if n.type == "OUTPUT_LIGHT"), None) or nt.nodes.new("ShaderNodeOutputLight")
        nt.links.new(emit.outputs[0], out.inputs[0])
    ies = nt.nodes.new("ShaderNodeTexIES")
    ies.mode = "EXTERNAL"
    ies.filepath = path
    ies.inputs["Strength"].default_value = float(scale)
    nt.links.new(ies.outputs[0], emit.inputs["Strength"])
    return ies


def add_studio_lights(scene, lights):
    """Render Studio's lights (``render_studio/lights.py``): point, spot, area
    and sun, in the world, with Blender's own power (``energy``) already
    worked out. Returns the objects made."""
    made = []
    col = bpy.data.collections.new("Render Studio lights")
    scene.collection.children.link(col)
    for i, lt in enumerate(lights):
        kind = BLENDER_LIGHT.get(lt.get("type"), "POINT")
        name = lt.get("name") or f"Studio {lt.get('type', 'point')} {i + 1}"
        data = bpy.data.lights.new(name, type=kind)
        data.energy = float(lt.get("energy", 0.0))
        data.color = tuple(float(c) for c in (lt.get("color") or (1.0, 1.0, 1.0))[:3])
        if hasattr(data, "use_shadow"):
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
            if hasattr(data, "spread"):
                data.spread = math.radians(float(lt.get("spread", 180.0)))
        elif kind == "SUN":
            data.angle = math.radians(float(lt.get("sun_angle", 0.53)))
        if lt.get("ies") and kind != "SUN":
            try:
                _ies_nodes(data, lt["ies"], lt.get("ies_scale", 1.0))
            except Exception as exc:  # noqa: BLE001 - the light stays, without its profile
                say("ies failed", os.path.basename(lt["ies"]), exc)
        obj = bpy.data.objects.new(name, data)
        col.objects.link(obj)
        obj.location = Vector(lt.get("pos") or (0.0, 0.0, 0.0))
        if lt.get("basis"):
            # The light's own axes, worked out by the extension (lights.light_basis):
            # its -Z is where it shines, X and Y lay out an area's sides — the same
            # axes the viewport draws it with.
            from mathutils import Matrix
            x, y, z = (Vector(a) for a in lt["basis"])
            obj.matrix_world = Matrix((
                (x[0], y[0], z[0], obj.location[0]),
                (x[1], y[1], z[1], obj.location[1]),
                (x[2], y[2], z[2], obj.location[2]),
                (0.0, 0.0, 0.0, 1.0)))
        elif kind != "POINT":
            d = Vector(lt.get("dir") or (0.0, 0.0, -1.0))
            if d.length < 1e-9:
                d = Vector((0.0, 0.0, -1.0))
            obj.rotation_euler = d.normalized().to_track_quat("-Z", "Y").to_euler()
        made.append(obj)
    if lights:
        kinds = {}
        for lt in lights:
            kinds[lt.get("type", "point")] = kinds.get(lt.get("type", "point"), 0) + 1
        say("studio lights", len(lights), ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    return made


# ---- the render ------------------------------------------------------------------------

#: The live view: the grass as dense as in the render (what you see is what you get);
#: EEVEE without its costliest effects, or Cycles (the Interior look) kept between images.
LIVE_GRASS = 1.0
LIVE_EEVEE = (("use_raytracing", False), ("use_fast_gi", False), ("shadow_resolution_scale", 0.5),
              ("use_shadow_jitter_viewport", False), ("shadow_ray_count", 1), ("shadow_step_count", 4),
              ("use_volumetric_shadows", False))


# ---- proxies -------------------------------------------------------------------------------

def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _cap_material(section):
    """The material of the section's cap: the model's own Blender material of that name
    (so it has its picture, finish and the material editor's settings), else a matte
    one of the material's colour (``rs_section_cap``: White model leaves it alone)."""
    name = section.get("material")
    if name:
        mat = bpy.data.materials.get(name)
        if mat is None:
            mat = next((m for m in _live_materials() if m.name.startswith(name + ".")), None)
        if mat is not None:
            return mat
        say("section material not in the model", name, "- its colour only")
    color = (section.get("color") or (0.35, 0.37, 0.41))[:3]
    rgb = [_srgb_to_linear(float(c)) for c in color]
    mat = bpy.data.materials.new(name or "Render Studio section cap")
    mat.use_nodes = True
    mat["rs_section_cap"] = True
    bsdf = next((x for x in mat.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.9
    mat.diffuse_color = (*rgb, 1.0)
    return mat


def _plane_uv(co, no, texture_size):
    """A function point → (u, v): the plane's own two axes, in metres divided by the
    picture's tile size, so a texture on the cap repeats at its real size."""
    ref = Vector((0.0, 0.0, 1.0)) if abs(no.z) < 0.9 else Vector((1.0, 0.0, 0.0))
    ax = no.cross(ref).normalized()
    ay = no.cross(ax).normalized()
    sw, sh = (texture_size or (1.0, 1.0))
    sw, sh = (float(sw) or 1.0), (float(sh) or 1.0)
    return lambda p: (((p - co).dot(ax)) / sw, ((p - co).dot(ay)) / sh)


def clip_section(section):
    """Cut every mesh with IngeTrazo's active section plane (``point``, ``normal``,
    Z up, metres): what lies on the normal's side goes, as in the viewer. Done in
    world space on each object's own mesh (a mesh shared by several objects is
    copied first).

    ``cap`` (default on): the cut is closed with a flat face of ``material``, filled from
    the edges the cut leaves in the plane (holes stay open, as a wall's section does).
    ``light`` "blocked": a copy of each cut mesh stays whole but invisible to the
    camera, so it still casts shadow and bounces light as in the real building;
    "open" (default): what is cut is gone and the light enters.
    Returns how many meshes were cut."""
    import bmesh
    co = Vector(section["point"])
    no = Vector(section["normal"])
    if no.length < 1e-9:
        return 0
    no.normalize()
    want_cap = bool(section.get("cap", True))
    blocked = section.get("light") == "blocked"
    capmat = _cap_material(section) if want_cap else None
    uv_of = _plane_uv(co, no, section.get("texture_size"))
    n = capped = ghosts = 0
    for obj in list(bpy.data.objects):
        if obj.type != "MESH" or obj.data is None or not obj.data.vertices:
            continue
        if obj.users_collection and all(c.name.startswith("proxy ") for c in obj.users_collection):
            continue                      # a proxy's original: only its copies are in the picture
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        mw = obj.matrix_world.copy()
        if not any((mw @ v.co - co).dot(no) > 1e-6 for v in obj.data.vertices):
            continue                      # nothing on the removed side
        if blocked:
            ghost = obj.copy()
            ghost.data = obj.data.copy()
            ghost.name = obj.name + " (section, blocks light)"
            for c in obj.users_collection:
                c.objects.link(ghost)
            ghost.visible_camera = False
            ghosts += 1
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.transform(bm, matrix=mw, verts=bm.verts)
        geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=co, plane_no=no,
                               clear_outer=True, clear_inner=False, dist=1e-6)
        new_faces = []
        if want_cap:
            # A model from glTF has its vertices split per face (normals, UVs): the cut's
            # vertices are welded so its edges close into loops the fill can follow.
            on_plane = [v for v in bm.verts if abs((v.co - co).dot(no)) < 1e-4]
            if on_plane:
                bmesh.ops.remove_doubles(bm, verts=on_plane, dist=1e-4)
            edges = [e for e in bm.edges if e.is_boundary
                     and all(abs((v.co - co).dot(no)) < 1e-4 for v in e.verts)]
            if edges:
                try:
                    res = bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False,
                                                  edges=edges, normal=no)
                    new_faces = [g for g in res.get("geom", []) if isinstance(g, bmesh.types.BMFace)]
                except Exception as exc:  # noqa: BLE001 - the cut stays open
                    say("section cap failed", obj.name, exc)
        uv_layer = bm.loops.layers.uv.verify() if new_faces else None
        for f in new_faces:
            if f.normal.dot(no) < 0:
                f.normal_flip()
            for loop in f.loops:
                loop[uv_layer].uv = uv_of(loop.vert.co)
        slot = None
        if new_faces:
            if not len(obj.data.materials):
                obj.data.materials.append(None)       # the faces it has keep «no material»
            obj.data.materials.append(capmat)
            slot = len(obj.data.materials) - 1
            for f in new_faces:
                f.material_index = slot
            capped += 1
        bmesh.ops.transform(bm, matrix=mw.inverted_safe(), verts=bm.verts)
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
        n += 1
    say("section", f"{n} meshes cut, {capped} capped, {ghosts} keep blocking light; at "
        f"{[round(c, 3) for c in co]}, normal {[round(c, 3) for c in no]}")
    return n


def place_proxies(scene, entries, section=None):
    """The full models of the drawing's proxies (render_studio/proxies.py): each
    original's .glb imported ONCE into a collection kept out of the scene, then
    placed with a collection instance per placement (``matrices``: 4×4 rows, Z up,
    metres). Its materials are in bpy.data like the model's, so the finishes,
    material settings and texture sets reach them too. Returns how many instances."""
    from mathutils import Matrix
    if not entries:
        return 0
    holder = bpy.data.collections.new("Render Studio proxies")
    scene.collection.children.link(holder)
    placed = 0
    for i, e in enumerate(entries):
        name = str(e.get("name") or f"proxy {i + 1}")
        before = set(bpy.data.objects)
        try:
            bpy.ops.import_scene.gltf(filepath=e["glb"])
        except Exception as exc:  # noqa: BLE001 - the others still come
            say("proxy import failed", name, exc)
            continue
        col = bpy.data.collections.new("proxy " + name)    # not linked: only instanced
        for obj in [o for o in bpy.data.objects if o not in before]:
            for c in list(obj.users_collection):
                c.objects.unlink(obj)
            col.objects.link(obj)
        for k, rows in enumerate(e.get("matrices") or []):
            if section:
                # A cut model needs real copies (a clipped instance would clip them all).
                for src in col.objects:
                    cp = src.copy()
                    if src.data is not None:
                        cp.data = src.data.copy()
                    cp.parent = None
                    cp.matrix_world = Matrix(rows) @ src.matrix_world
                    holder.objects.link(cp)
                placed += 1
                continue
            inst = bpy.data.objects.new(f"{name} {k + 1}", None)
            inst.instance_type = "COLLECTION"
            inst.instance_collection = col
            inst.matrix_world = Matrix(rows)
            holder.objects.link(inst)
            placed += 1
    say("proxies", len(entries), "models,", placed, "placements")
    return placed


# ---- changing materials without a new scene ------------------------------------------------------
#
# The live view asks for a new scene whenever anything changes, and building one again costs the
# model's import (3.9 s on a model of 588 000 faces) and the exposure meter (2 s): about 9 s for a
# slider of the material editor. A change that only touches some materials is made in place: those
# materials go back to what the importer made (a copy kept when the scene was built) and the steps
# that set them run again for them alone. Anything else (the look, the sky, the lights, a
# section, grass, a change that moves the light) builds the scene again, as before.

PRISTINE_KEY = "studio_pristine"
_STATE = {"pristine": {}, "sig": None, "specs": None, "pbr": None, "figures": None, "lights": None}


def _live_materials(only=None):
    """The scene's materials, not the kept copies; ``only``: just those names."""
    return [m for m in bpy.data.materials
            if not m.get(PRISTINE_KEY) and (only is None or m.name in only)]


def keep_pristine():
    """A copy of every material as the importer made it. The copy carries none of the material's
    custom properties (IngeTrazo's finish among them: its steps would work on the copy), they
    wait in one text."""
    _STATE["pristine"] = {}
    for mat in list(_live_materials()):
        pc = mat.copy()
        props = {}
        for k in list(pc.keys()):
            v = pc[k]
            if hasattr(v, "to_dict"):
                v = v.to_dict()
            elif hasattr(v, "to_list"):
                v = v.to_list()
            try:
                json.dumps(v)
            except TypeError:
                continue
            props[k] = v
            del pc[k]
        pc[PRISTINE_KEY] = True
        pc["studio_props"] = json.dumps(props)
        pc.use_fake_user = True
        _STATE["pristine"][mat.name] = pc


def restore_material(name):
    """The material ``name`` as the importer made it, in place of what the steps made of it (every
    object that wears it follows). Returns it, or None when no copy is kept."""
    pc = _STATE["pristine"].get(name)
    cur = bpy.data.materials.get(name)
    if pc is None or cur is None:
        return None
    new = pc.copy()
    for k in list(new.keys()):
        del new[k]
    new.use_fake_user = False
    for k, v in json.loads(pc.get("studio_props", "{}")).items():
        new[k] = v
    cur.user_remap(new)
    bpy.data.materials.remove(cur)
    new.name = name
    for img in [i for i in bpy.data.images if i.name.startswith("studio relief " + name)]:
        bpy.data.images.remove(img)                    # the relief the last pass baked from its picture
    return new


def _note_glass_alpha(only=None):
    """Before IngeTrazo's finishes: a glass material's alpha as the importer made it (the opacity the
    model gave it), which the glass finish overwrites with 1."""
    for mat in _live_materials(only):
        if mat.get("ingetrazo_finish") != "glass" or not mat.node_tree:
            continue
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is not None and "Alpha" in bsdf.inputs:
            mat["studio_alpha0"] = float(bsdf.inputs["Alpha"].default_value)


def glass_see_through(specs, only=None):
    """Glass in EEVEE (the preview and the draft render): IngeTrazo's glass finish refracts (Transmission),
    but EEVEE can only refract the sky there, not the scene behind the pane, so the glass came out as a mirror
    that showed no wall, no interior. The glass is made see-through by alpha instead, keeping its reflections:
    how much is the editor's Transparency, else the opacity the model gave the material, else 85 %. Cycles
    (the Interior look) refracts for real and is left alone."""
    n = 0
    for mat in _live_materials(only):
        if mat.get("ingetrazo_finish") != "glass" or not mat.node_tree:
            continue
        bsdf = next((x for x in mat.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None or "Alpha" not in bsdf.inputs or bsdf.inputs["Alpha"].links:
            continue                                   # a picture's own cut-out stays as it is
        spec = _spec_for(mat, specs) or {}
        transparency = spec.get("transparency")
        if transparency is None:
            a0 = float(mat.get("studio_alpha0", 1.0))
            transparency = (1.0 - a0) if a0 < 0.999 else 0.85
        alpha = max(0.02, min(1.0, 1.0 - float(transparency)))
        for names in (("Transmission Weight", "Transmission"),):
            for key in names:
                if key in bsdf.inputs:
                    bsdf.inputs[key].default_value = 0.0
                    break
        bsdf.inputs["Alpha"].default_value = alpha
        for attr, val in (("surface_render_method", "DITHERED"), ("blend_method", "HASHED"),
                          ("use_transparent_shadow", True)):
            if hasattr(mat, attr):
                try:
                    setattr(mat, attr, val)
                except (TypeError, ValueError):
                    pass
        mat["studio_glass_alpha"] = alpha
        n += 1
    if n:
        say("glass", f"{n} materials see-through by alpha")


def finishes_for(only):
    """IngeTrazo's finishes (its function works on every material) for ``only`` alone: the others
    hold their finish out of sight while it runs."""
    _note_glass_alpha(only)
    held = {}
    for m in _live_materials():
        if m.name not in only and "ingetrazo_finish" in m.keys():
            held[m.name] = m["ingetrazo_finish"]
            del m["ingetrazo_finish"]
    try:
        core["apply_finishes"]()
    finally:
        for n, v in held.items():
            m = bpy.data.materials.get(n)
            if m is not None:
                m["ingetrazo_finish"] = v


def _rest_signature(job):
    """What a scene depends on besides its materials, the camera and the picture's size."""
    j = {k: v for k, v in job.items() if k not in ("camera", "output", "width", "height", "samples", "studio")}
    st = job.get("studio") or {}
    # Render Studio's lights (a list) are changed in place by :func:`update`; the Render tab's are not.
    skip = ("materials", "pbr") + (("lights",) if isinstance(st.get("lights"), list) else ())
    s = {k: v for k, v in st.items() if k not in skip}
    return json.dumps([j, s], sort_keys=True, default=str)


def _same(a, b):
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _light_affecting(a, b, engine="eevee"):
    """Whether a change of one material's settings moves the light of the scene (it glows, lets light
    through, or stops doing either): the exposure is measured again, which needs a scene built anew.
    The Transparency of a glass in EEVEE is an alpha (see :func:`glass_see_through`): no more light moves
    than a material's roughness moves, so the exposure is kept."""
    a, b = a or {}, b or {}
    kinds = ("glow", "glass", "water")
    ka, kb = a.get("type", "generic"), b.get("type", "generic")
    if ka != kb and (ka in kinds or kb in kinds):
        return True
    if kb == "glow" and (a.get("glow") != b.get("glow")
                         or not _same((a.get("maps") or {}).get("glow"), (b.get("maps") or {}).get("glow"))):
        return True
    if kb == "glass" and engine != "cycles":
        return False
    return kb in ("glass", "water") and a.get("transparency") != b.get("transparency")


def _patch_names(job):
    """The names of the materials to change in place for ``job``, or None when the scene has to be
    built again: the scene was not built with copies to restore, something besides the materials
    changed, a section or a white model is on, a grass material is involved, or the change moves
    the light."""
    st = job.get("studio") or {}
    if _STATE["sig"] is None or not _STATE["pristine"] or st.get("section") or st.get("white_model"):
        return None
    if _STATE["sig"] != _rest_signature(job):
        return None
    old_s, new_s = _STATE["specs"] or {}, st.get("materials") or {}
    old_p, new_p = _STATE["pbr"] or {}, st.get("pbr") or {}
    names = set()
    for m in _live_materials():
        a, b = _spec_for(m, old_s), _spec_for(m, new_s)
        if _same(a, b) and _same(_spec_for(m, old_p), _spec_for(m, new_p)):
            continue
        if m.name not in _STATE["pristine"]:
            return None
        if (a or {}).get("type") == "grass" or (b or {}).get("type") == "grass" or _light_affecting(a, b, job.get("engine", "eevee")):
            return None
        names.add(m.name)
    return names


def _expose(scene, job):
    """The scene's exposure (measured on what it shows now, or the job's) and the compositor made from it.
    Again after a change of the lights: what a light adds moves the exposure."""
    st = job.get("studio") or {}
    if st.get("auto_exposure", True):
        scene.view_settings.exposure = measure_exposure(
            scene, target=float(st.get("exposure_target", 0.2)),
            bias=float(st.get("exposure_bias", 0.0)),
            samples=16 if job.get("engine") == "cycles" else 8,
            white=float(st.get("exposure_white", 1.6)),
            max_ev=float(st.get("exposure_max", 8.0)))
        core["set_samples"](scene, int(job.get("samples", 64)))
    else:
        scene.view_settings.exposure = float(job.get("exposure", -0.6)) + float(st.get("exposure_bias", 0.0))
    if hasattr(scene, "compositing_node_group"):          # the one made before goes (build_compositor makes it anew)
        scene.compositing_node_group = None
    for g in [g for g in bpy.data.node_groups if g.name.startswith("IngeTrazo studio")]:
        bpy.data.node_groups.remove(g)
    build_compositor(scene, float(st.get("saturation", 1.0)), float(st.get("bloom", 0.0)),
                     float(st.get("vignette", 0.0)), scene.view_settings.exposure)
    say("exposure", round(scene.view_settings.exposure, 2))


def replace_studio_lights(scene, lights):
    """Render Studio's lights changed in place: the old ones (and their data) go, the new ones are made."""
    col = bpy.data.collections.get("Render Studio lights")
    if col is not None:
        for obj in list(col.objects):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.lights.remove(data)
        bpy.data.collections.remove(col)
    return add_studio_lights(scene, lights)


def update(job):
    """The scene of ``job`` from the one that is built: when only some materials changed, those are
    made again in place (a slider costs a few hundred milliseconds, not the whole scene); otherwise
    the scene is built from scratch. Returns (scene, figures) as :func:`build` does."""
    names = _patch_names(job)
    if names is None:
        return build(job)
    t0 = time.perf_counter()
    st = job.get("studio") or {}
    for name in names:
        restore_material(name)
    specs = st.get("materials") or {}
    if specs:
        mark_material_types(specs, names)
    finishes_for(names)
    sets = match_texture_sets(st.get("pbr") or {})
    if specs:
        apply_material_specs(specs, sets, names)
    mine = {k: v for k, v in sets.items() if k in names}
    if mine:
        apply_texture_sets(mine, specs)
    if job.get("engine") != "cycles":
        glass_see_through(specs, names)
    if st.get("albedo_cap", 0.8):
        cap_albedo(float(st.get("albedo_cap", 0.8)), names)
    _STATE["specs"] = json.loads(json.dumps(specs))
    _STATE["pbr"] = json.loads(json.dumps(st.get("pbr") or {}))
    lights = st.get("lights")
    if isinstance(lights, list) and not _same(_STATE.get("lights") or [], lights):
        replace_studio_lights(bpy.context.scene, lights)     # the lights, in place: the model stays
        _STATE["lights"] = json.loads(json.dumps(lights))
        _expose(bpy.context.scene, job)                      # what they add moves the exposure
        say("patch", f"{len(lights)} lights in place")
    say("patch", f"{len(names)} materials in place, {time.perf_counter() - t0:.2f} s")
    return bpy.context.scene, _STATE["figures"]


def build(job):
    """The whole scene of ``job`` from scratch: model, materials, sky, lights,
    engine, look and exposure. Returns (scene, figures). Called again, in the
    same Blender, when the live view sends a new job (no restart)."""
    st = job.get("studio") or {}
    _STATE.update(pristine={}, sig=None, specs=None, pbr=None, figures=None, lights=None)
    if job.get("expert") and not bpy.app.background:
        # A Blender with a window: reading the factory settings would leave it without the window's
        # context (no active object); the scene it started with is emptied instead.
        for coll in (bpy.data.objects, bpy.data.collections, bpy.data.meshes, bpy.data.materials,
                     bpy.data.images, bpy.data.lights, bpy.data.cameras, bpy.data.worlds,
                     bpy.data.node_groups, bpy.data.curves):
            for item in list(coll):
                try:
                    coll.remove(item)
                except Exception:  # noqa: BLE001 - what cannot go stays
                    pass
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    core["import_model"](job["glb"])
    place_proxies(scene, st.get("proxies") or [], st.get("section"))
    if not st.get("section") and not st.get("white_model"):
        keep_pristine()                  # to change a material later without building the scene again
    if st.get("section"):
        clip_section(st["section"])
    if st.get("fix_normals", False):
        fix_normals()
    specs = st.get("materials") or {}
    if specs:
        mark_material_types(specs)
    _note_glass_alpha()
    core["apply_finishes"]()
    sets = match_texture_sets(st.get("pbr") or {})
    if specs:
        apply_material_specs(specs, sets)
    if sets and not st.get("white_model"):
        apply_texture_sets(sets, specs)
    if job.get("engine") != "cycles" and not st.get("white_model"):
        glass_see_through(specs)
    if specs and st.get("grass", True):
        build_grass(specs, LIVE_GRASS if st.get("live") else 1.0)
    if st.get("albedo_cap", 0.8):
        cap_albedo(float(st.get("albedo_cap", 0.8)))
    if st.get("white_model"):
        white_model()
    figures = core["find_figures"]()
    w, h = int(job["width"]), int(job["height"])
    core["set_camera"](scene, job["camera"], w, h)
    _DOF["amount"] = st.get("dof", 0.0)
    set_dof(scene, job["camera"], _DOF["amount"])
    core["face_figures"](figures, job["camera"])
    ambience = job.get("ambience", "day")
    sun_dir = job.get("sun") if ambience == "day" else None
    if st.get("sun_elevation") is not None and ambience == "day":
        sun_dir = golden_sun(sun_dir, float(st["sun_elevation"]))
    if ambience == "night":
        core["set_plain_world"](scene, (0.010, 0.016, 0.035), 1.0, "night")
        core["add_moon"](scene)
        night_sky(scene, stars=float(st.get("stars", 1.0)), seed=float(st.get("cloud_seed", 0.0)))
        if st.get("clouds", 0.0) > 0.0:
            # Moonlit: a blue-grey a little brighter than the sky, darker
            # where thick; they hide the stars behind them.
            add_clouds(scene, float(st["clouds"]), scale=st.get("cloud_scale", 1.0),
                       brightness=0.05 * float(st.get("cloud_brightness", 1.0)),
                       seed=st.get("cloud_seed", 0.0), tint=(0.80, 0.90, 1.25))
    elif ambience == "overcast":
        core["set_world"](scene, golden_sun(job.get("sun"), 35.0))
        bg = next(n for n in scene.world.node_tree.nodes if n.type == "BACKGROUND")
        bg.inputs["Strength"].default_value *= 1.0
        add_clouds(scene, 1.0, scale=st.get("cloud_scale", 1.0), brightness=0.75)
        sun = core["add_sun"](scene, golden_sun(job.get("sun"), 40.0),
                              float(job.get("sun_strength", 4.0)) * 0.12)
        sun.data.angle = math.radians(25.0)        # a sky-wide soft source
    else:
        if sun_dir is not None:
            strength = float(job.get("sun_strength", 4.0)) * float(st.get("sun_scale", 1.0))
            sun = core["add_sun"](scene, sun_dir, strength)
            if st.get("sun_angle"):
                sun.data.angle = math.radians(float(st["sun_angle"]))
            kelvin = float(st.get("sun_kelvin") or sun_kelvin(sun_dir))
            sun.data.color = kelvin_rgb(kelvin)
            say("sun", f"{kelvin:.0f} K")
        core["set_world"](scene, sun_dir)
        if st.get("clouds", 0.0) > 0.0:
            # Clouds take the sun's colour: white at noon, peach at sunset.
            warm = kelvin_rgb(float(st.get("sun_kelvin") or sun_kelvin(sun_dir)))
            tint = tuple(0.55 + 0.45 * c for c in warm)
            add_clouds(scene, float(st["clouds"]), scale=st.get("cloud_scale", 1.0),
                       brightness=st.get("cloud_brightness", 1.0), seed=st.get("cloud_seed", 0.0),
                       tint=tint)
    if st.get("sky_type") and scene.world is not None:            # for tuning
        for n in scene.world.node_tree.nodes:
            if n.type == "TEX_SKY":
                n.sky_type = st["sky_type"]
                say("sky type", n.sky_type)
    if st.get("hdri"):
        pano = set_hdri(scene, st["hdri"], float(st.get("hdri_rotation", 0.0)),
                        float(st.get("hdri_strength", 1.0)), bool(st.get("hdri_light", True)))
        if pano is not None and st.get("hdri_light", True) and st.get("hdri_sun", True):
            try:                                   # a panorama only paints its sun: give it a lamp
                hdri_sun(scene, pano, float(st.get("hdri_rotation", 0.0)), float(st.get("hdri_strength", 1.0)),
                         float(job.get("sun_strength", 4.0)) * float(st.get("sun_scale", 1.0)),
                         st.get("sun_angle"))
            except Exception as exc:               # never lose the render over it
                say("hdri sun failed", exc)
    elif st.get("backdrop"):
        try:
            set_backdrop(scene, st["backdrop"], st.get("backdrop_fit", "fill"), float(st.get("backdrop_strength", 1.0)),
                         float(job["width"]) / max(1.0, float(job["height"])))
        except Exception as exc:                   # never lose the render over it
            say("backdrop failed", exc)
    ground = job.get("ground")
    if ground and not (st.get("hdri") and st.get("hdri_light", True)):
        world_ground(scene, st.get("ground_color") or ground["color"],
                     float(st.get("world_ground_level", 2.0)))
    if isinstance(st.get("lights"), list):
        add_studio_lights(scene, st["lights"])     # Render Studio's (the Render tab's are among them)
    else:
        core["add_lights"](scene, job.get("lights") or [])
    if ground:
        color = st.get("ground_color") or ground["color"]
        core["add_ground"](scene, ground["z"], ground["size"], color)
        if st.get("haze", True):
            # A photo's horizon is near (trees, buildings): melt sooner.
            near, far = (30.0, 300.0) if st.get("hdri") else (120.0, 1200.0)
            haze_ground(scene, float(st.get("haze_near", near)), float(st.get("haze_far", far)),
                        eye_height=(float(st.get("hdri_height", 2.5)) if st.get("hdri") else None))
    core["set_engine"](scene, job.get("engine", "eevee"), int(job.get("samples", 64)))
    if job.get("engine") != "cycles" and st.get("hdri") and scene.world is not None:
        wld = scene.world
        for attr, value in (("use_sun_shadow", True), ("sun_threshold", float(st.get("hdri_sun_threshold", 10.0)))):
            if hasattr(wld, attr):
                setattr(wld, attr, value)
        say("world sun", {a: getattr(wld, a) for a in ("sun_threshold", "sun_angle", "use_sun_shadow") if hasattr(wld, a)})
    if job.get("engine") != "cycles":
        ev = scene.eevee
        for attr, value in (("use_fast_gi", True), ("fast_gi_method", "GLOBAL_ILLUMINATION"),
                            ("fast_gi_resolution", "2"), ("fast_gi_distance", 1.5),
                            ("shadow_resolution_scale", 1.0), ("use_shadow_jitter_viewport", True)):
            if hasattr(ev, attr):
                try:
                    setattr(ev, attr, value)
                except (TypeError, ValueError):
                    pass
    if st.get("live") and job.get("engine") != "cycles":
        ev = scene.eevee
        for attr, value in LIVE_EEVEE:                 # a quick draft, not the final picture
            if hasattr(ev, attr):
                try:
                    setattr(ev, attr, value)
                except (TypeError, ValueError):
                    pass
    if st.get("live") and job.get("engine") == "cycles":
        # The Interior look's live view: Cycles, its scene kept between images (only the
        # camera changes), denoised so a few samples read as a picture.
        scene.render.use_persistent_data = True
        cy = scene.cycles
        for attr, value in (("use_denoising", True), ("denoising_use_gpu", True),
                            ("denoising_prefilter", "FAST"), ("use_adaptive_sampling", False)):
            if hasattr(cy, attr):
                try:
                    setattr(cy, attr, value)
                except (TypeError, ValueError):
                    pass
        say("live", "cycles")
    for attr, value in (st.get("eevee_overrides") or {}).items():   # for tuning
        target = scene.eevee
        for part in attr.split(".")[:-1]:
            target = getattr(target, part)
        setattr(target, attr.split(".")[-1], value)
        say("eevee", attr, "=", value)
    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
    r.image_settings.file_format = "PNG"
    r.filepath = job["output"]
    r.film_transparent = False
    set_look(scene, st.get("looks") or ["AgX - Medium High Contrast", "Medium High Contrast"],
             st.get("white_balance"), st.get("tint"))
    _expose(scene, job)
    if st.get("shadow_catcher") and not ground:          # after the exposure: the floor is no part of what is metered
        add_shadow_floor(scene, float(st["shadow_catcher"]["z"]), float(st["shadow_catcher"]["size"]))
    last = {"text": None}

    def _stats(text, *_a):
        text = str(text)
        if text != last["text"]:
            last["text"] = text
            say("stats", text.replace("\n", " "))

    if hasattr(bpy.app.handlers, "render_stats"):        # (a new file clears it: added each build)
        bpy.app.handlers.render_stats.append(_stats)
    _STATE.update(sig=_rest_signature(job), specs=json.loads(json.dumps(st.get("materials") or {})),
                  pbr=json.loads(json.dumps(st.get("pbr") or {})), figures=figures,
                  lights=json.loads(json.dumps(st["lights"])) if isinstance(st.get("lights"), list) else None)
    return scene, figures


def serve(scene, figures):
    """IngeTrazo's «sync with the view» protocol, and more: each JSON line is a
    camera to render (``camera``, ``output``, ``width``, ``height``, ``samples``),
    ``{"reload": "<job.json>"}`` builds that job's scene in THIS Blender (no new
    start: a changed setting costs only the scene's build), ``{"update": "<job.json>"}``
    the same but changing only the materials that changed when that is all that did (see
    :func:`update`), ``{"quit": true}`` ends. «ready» after each build, «done <file>» after each image."""
    say("ready")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            say("error", "bad request")
            continue
        if req.get("quit"):
            break
        if req.get("reload"):
            try:
                with open(req["reload"], encoding="utf-8") as fh:
                    job = json.load(fh)
                scene, figures = build(job)
            except Exception as exc:  # noqa: BLE001 - say it; the app starts a new Blender
                say("error", "reload failed", exc)
                raise
            say("ready")
            continue
        if req.get("update"):
            try:
                with open(req["update"], encoding="utf-8") as fh:
                    job = json.load(fh)
                scene, figures = update(job)
            except Exception as exc:  # noqa: BLE001 - say it; the app starts a new Blender
                say("error", "update failed", exc)
                raise
            say("ready")
            continue
        w, h = int(req["width"]), int(req["height"])
        r = scene.render
        core["set_camera"](scene, req["camera"], w, h)
        set_dof(scene, req["camera"], _DOF["amount"])
        core["face_figures"](figures, req["camera"])
        core["set_samples"](scene, int(req.get("samples", 16)))
        r.resolution_x, r.resolution_y = w, h
        r.filepath = req["output"]
        say("rendering", w, "x", h)
        bpy.ops.render.render(write_still=True)
        say("done", req["output"])


def save_final(scene, out):
    """The final picture again in the Output tab's format (16-bit PNG or TIFF, OpenEXR),
    beside the PNG the preview window reads. EXR keeps the scene's linear light."""
    st = scene.render.image_settings
    for key, value in (out.get("image_settings") or {}).items():
        try:
            setattr(st, key, value)
        except (AttributeError, TypeError, ValueError) as exc:
            say("output setting skipped", key, value, exc)
    result = bpy.data.images.get("Render Result")
    if result is None:
        say("error", "no render result to save")
        return
    result.save_render(filepath=out["path"], scene=scene)
    say("saved", out["path"])


def expert_open(scene, job):
    """Expert mode: the scene is built and left open for the person to work in (Blender runs with its window):
    the model, materials, sky, lights, camera and engine of the final render, no picture made. Its pictures are
    packed in the file, which is saved first (job «blend») so it can be opened again."""
    try:
        bpy.ops.file.pack_all()
    except Exception as exc:  # noqa: BLE001 - a picture that cannot be packed stays a link
        say("warning", "pictures not packed:", exc)
    if job.get("blend"):
        bpy.ops.wm.save_as_mainfile(filepath=job["blend"])
        say("blend", job["blend"])

    tries = {"n": 0}

    def look_through_camera():
        """Once the window is there: every 3D view looks through the scene's camera, in Material Preview.
        Tried again every half second (the window may not be ready yet) and said, so a failure shows."""
        tries["n"] += 1
        found = looking = 0
        try:
            wm = bpy.context.window_manager
            for win in wm.windows if wm else ():
                for area in win.screen.areas:
                    if area.type != "VIEW_3D":
                        continue
                    space = next((s for s in area.spaces if s.type == "VIEW_3D"), None)
                    region = next((r for r in area.regions if r.type == "WINDOW"), None)
                    if space is None or region is None:
                        continue
                    found += 1
                    if scene.camera is not None and bpy.context.scene.camera is None:
                        bpy.context.window.scene.camera = scene.camera
                    space.shading.type = "MATERIAL"
                    space.region_3d.view_perspective = "CAMERA"
                    if space.region_3d.view_perspective != "CAMERA":
                        with bpy.context.temp_override(window=win, area=area, region=region):
                            bpy.ops.view3d.view_camera()
                    looking += space.region_3d.view_perspective == "CAMERA"
        except Exception as exc:  # noqa: BLE001 - said, tried again
            say("warning", "3D view not set:", exc)
        if found and looking == found:
            say("expert", "looking through the camera")
            if job.get("expert_probe"):                 # tests: say it in a file and leave
                with open(job["expert_probe"], "w", encoding="utf-8") as fh:
                    fh.write(f"looking {looking}\n")
                bpy.ops.wm.quit_blender()
            return None
        if tries["n"] >= 40:
            say("warning", "no 3D view found to look through the camera")
            if job.get("expert_probe"):
                with open(job["expert_probe"], "w", encoding="utf-8") as fh:
                    fh.write(f"no view: found {found}\n")
                bpy.ops.wm.quit_blender()
            return None
        return 0.5
    if not bpy.app.background:
        bpy.app.timers.register(look_through_camera, first_interval=0.5, persistent=True)
    say("expert", "ready")


def main():
    job = core["load_job"]()
    if job.get("expert") and not bpy.app.background:
        # With a window the script runs before Blender's main loop, where the context is cut down
        # (no active object: the ground and others fail): the scene is built once the loop runs.
        def build_open():
            try:
                scene, _figures = build(job)
                expert_open(scene, job)
            except Exception as exc:  # noqa: BLE001 - said, the window stays
                import traceback
                say("error", exc)
                traceback.print_exc()
                if job.get("expert_probe"):
                    with open(job["expert_probe"], "w", encoding="utf-8") as fh:
                        fh.write(f"error {exc}\n")
                    bpy.ops.wm.quit_blender()
            return None
        bpy.app.timers.register(build_open, first_interval=1.0, persistent=True)
        return
    scene, figures = build(job)
    if job.get("expert"):
        expert_open(scene, job)
        return
    if job.get("serve"):
        serve(scene, figures)
        return
    w, h = int(job["width"]), int(job["height"])
    out = (job.get("studio") or {}).get("output") or {}
    if out.get("transparent"):
        # The sky left transparent — only now: the exposure was measured with it.
        scene.render.film_transparent = True
        scene.render.image_settings.color_mode = "RGBA"
    say("rendering", w, "x", h)
    bpy.ops.render.render(write_still=True)
    if out.get("path"):
        save_final(scene, out)
    if job.get("blend"):
        bpy.ops.wm.save_as_mainfile(filepath=job["blend"])
        say("blend", job["blend"])
    say("done", job["output"])


main()
