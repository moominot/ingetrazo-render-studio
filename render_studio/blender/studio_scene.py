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


def cap_albedo(cap=0.8):
    """No material reflects more than ``cap`` of the light: IngeTrazo's
    default «paper white» is 0.96, whiter than paper, and under a path tracer
    a white wall that bright glows like the sky (real white paint is about
    0.8). Colours are scaled down whole, so their hue stays."""
    n = 0
    for mat in bpy.data.materials:
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


def haze_ground(scene, near=120.0, far=1200.0):
    """The ground melts into the sky's own horizon colour with distance, so
    the far edge of the ground plane is no hard line against the sky (the
    atmosphere Enscape shows). The horizon colour is the world's sky looked
    up level with the horizon: the same Sky Texture, fed the view direction
    flattened onto the horizon."""
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
        geo = nodes.new("ShaderNodeNewGeometry")
        neg = nodes.new("ShaderNodeVectorMath"); neg.operation = "SCALE"
        neg.inputs["Scale"].default_value = -1.0
        links.new(geo.outputs["Incoming"], neg.inputs[0])
        sep = nodes.new("ShaderNodeSeparateXYZ")
        links.new(neg.outputs["Vector"], sep.inputs["Vector"])
        comb = nodes.new("ShaderNodeCombineXYZ")
        links.new(sep.outputs["X"], comb.inputs["X"]); links.new(sep.outputs["Y"], comb.inputs["Y"])
        comb.inputs["Z"].default_value = 0.02
        mapping = nodes.new("ShaderNodeMapping")
        wmap = wnodes.get("hdri_mapping")
        if wmap is not None:
            mapping.inputs["Rotation"].default_value = wmap.inputs["Rotation"].default_value
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


def mark_material_types(specs):
    """Before IngeTrazo's finishes run: glass and water become those
    finishes (its full Blender recipes); generic and glow drop a guessed
    glass/water finish."""
    for mat in bpy.data.materials:
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
        if node.type == "TEX_IMAGE" and node.image is not None:
            return link.from_socket, node
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


def _scaled(mat, socket, factor):
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    mul = nodes.new("ShaderNodeMath"); mul.operation = "MULTIPLY"
    links.new(socket, mul.inputs[0])
    mul.inputs[1].default_value = float(factor)
    return mul.outputs[0]


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
    if src in ("picture", "file"):
        height = _map_value(mat, bsdf, m)
    elif src == "auto" and pic is not None:
        height = _map_value(mat, bsdf, {"source": "picture"})
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = min(1.0, amount)
    if height is not None:
        links.new(height, bump.inputs["Height"])
        # A height map means it: 1 cm from black to white. A photo's light
        # and dark only hints at relief: less.
        bump.inputs["Distance"].default_value = 0.01 if src == "file" else 0.004
    else:
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


def apply_material_specs(specs):
    """After IngeTrazo's finishes: the editor's numbers — and maps — on each
    material. With a map, the setting's slider scales it."""
    done = 0
    for mat in bpy.data.materials:
        spec = _spec_for(mat, specs)
        if not spec or not mat.node_tree:
            continue
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        kind = spec.get("type", "generic")
        maps = spec.get("maps") or {}
        for key, names in (("roughness", ("Roughness",)), ("metallic", ("Metallic",))):
            if key not in spec or (key == "metallic" and kind != "generic"):
                continue
            core["_set"](bsdf, names, float(spec[key]))
            m = maps.get(key) or {}
            if m.get("source"):
                val = _map_value(mat, bsdf, m)
                if val is not None:
                    mat.node_tree.links.new(_scaled(mat, val, spec[key]), bsdf.inputs[names[0]])
        if kind in ("generic", "glow"):
            core["_set"](bsdf, ("Transmission Weight", "Transmission"), 0.0)
        if spec.get("coat"):
            core["_set"](bsdf, ("Coat Weight", "Clearcoat"), float(spec["coat"]))
            core["_set"](bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.05)
        if spec.get("sheen"):
            core["_set"](bsdf, ("Sheen Weight", "Sheen"), float(spec["sheen"]))
        if float(spec.get("bump", 0.0)) > 0.0:
            _add_bump(mat, bsdf, float(spec["bump"]), maps.get("bump"))
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


# ---- the white model -----------------------------------------------------------------

def white_model(skip_ground=True):
    """Every material white and matte; glass and water stay see-through
    (Enscape's white mode)."""
    n = 0
    for mat in bpy.data.materials:
        if skip_ground and mat.name.startswith("IngeTrazo ground"):
            continue
        if not mat.node_tree:
            continue
        bsdf = next((x for x in mat.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        if mat.get("ingetrazo_finish") in ("glass", "water"):
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
    for mat in bpy.data.materials:
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


# ---- the render ------------------------------------------------------------------------

def main():
    job = core["load_job"]()
    st = job.get("studio") or {}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    core["import_model"](job["glb"])
    if st.get("fix_normals", False):
        fix_normals()
    specs = st.get("materials") or {}
    if specs:
        mark_material_types(specs)
    core["apply_finishes"]()
    if specs:
        apply_material_specs(specs)
    if st.get("albedo_cap", 0.8):
        cap_albedo(float(st.get("albedo_cap", 0.8)))
    if st.get("white_model"):
        white_model()
    figures = core["find_figures"]()
    w, h = int(job["width"]), int(job["height"])
    core["set_camera"](scene, job["camera"], w, h)
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
        set_hdri(scene, st["hdri"], float(st.get("hdri_rotation", 0.0)),
                 float(st.get("hdri_strength", 1.0)), bool(st.get("hdri_light", True)))
    ground = job.get("ground")
    if ground and not (st.get("hdri") and st.get("hdri_light", True)):
        world_ground(scene, st.get("ground_color") or ground["color"],
                     float(st.get("world_ground_level", 2.0)))
    core["add_lights"](scene, job.get("lights") or [])
    if ground:
        color = st.get("ground_color") or ground["color"]
        core["add_ground"](scene, ground["z"], ground["size"], color)
        if st.get("haze", True):
            # A photo's horizon is near (trees, buildings): melt sooner.
            near, far = (30.0, 300.0) if st.get("hdri") else (120.0, 1200.0)
            haze_ground(scene, float(st.get("haze_near", near)), float(st.get("haze_far", far)))
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
    build_compositor(scene, float(st.get("saturation", 1.0)), float(st.get("bloom", 0.0)),
                     float(st.get("vignette", 0.0)), scene.view_settings.exposure)
    say("exposure", round(scene.view_settings.exposure, 2))
    last = {"text": None}

    def _stats(text, *_a):
        text = str(text)
        if text != last["text"]:
            last["text"] = text
            say("stats", text.replace("\n", " "))

    if hasattr(bpy.app.handlers, "render_stats"):
        bpy.app.handlers.render_stats.append(_stats)
    if job.get("serve"):
        core["serve"](scene, figures)
        return
    say("rendering", w, "x", h)
    bpy.ops.render.render(write_still=True)
    if job.get("blend"):
        bpy.ops.wm.save_as_mainfile(filepath=job["blend"])
        say("blend", job["blend"])
    say("done", job["output"])


main()
