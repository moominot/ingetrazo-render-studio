# SPDX-License-Identifier: GPL-3.0-or-later
"""The register of Render Studio's settings: each one described ONCE.

A setting says its key, where it belongs (tab and group), its name, what kind of
value it is, its limits and default, whether the simple view shows it, and when
it applies. The panel's tabs, the expert view and its layouts, the presets and
the reset buttons are to be made from this list, so that a new setting is added
here and nowhere else.

The keys are those of the settings' new model (see look_model.py), which keeps
apart what the old styles mixed: the SURFACE of the model, its OUTLINE, the
SHADOWS and the FINISH of the picture.

A value of None means «the look's own» (a slider never touched). Not listed: the
Section and Output tabs, which keep their own settings (section.py, output.py),
and the camera, which is the 3D view's. Pure Python: no Qt.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import presets

#: Tabs and their groups, in the order they are shown.
TABS = {
    "main": ("Main", ("ambient", "camera", "quality")),
    "style": ("Style", ("surface", "outline", "finish", "image")),
    "environment": ("Environment", ("sky", "shadows", "background", "ground", "horizon", "fog")),
    "section": ("Section", ("cap", "rim", "cutlight")),
}
GROUPS = {"ambient": "Light", "camera": "Camera", "quality": "Quality", "surface": "Surface", "outline": "Outline",
          "finish": "Finish", "image": "Picture", "sky": "Sun and sky", "shadows": "Shadows", "background": "Background",
          "ground": "Ground", "horizon": "Horizon", "fog": "Fog", "cap": "Cap", "rim": "Cap outline", "cutlight": "Light"}

#: "program": a control over data that is IngeTrazo's own (the sun's place, date and hour): it has a row and an eye, and
#: no value, default or reset of Render Studio's.
KINDS = ("bool", "number", "int", "choice", "colour", "text", "path", "program")

#: The surface's own white (what the old White style painted), in the same terms as a chosen colour.
WHITE = (0.82, 0.82, 0.80)


def _cut(group, key, label, simple=True) -> "Param":
    return Param(key, "section", group, label, "program", None, simple=simple, optional=True, local=True)


def _site(key, label, simple=False) -> "Param":
    return Param(key, "environment", "sky", label, "program", None, simple=simple, optional=True, local=True)


#: What the lowest position of a finer slider says when it leaves the value to the ambient.
OWN = "Ambient's own"
#: «Tone contrast»: the choice -> the looks Blender is asked for, the first it has.
CONTRASTS = {"base": ("AgX - Base Contrast",), "medium": ("AgX - Medium Contrast",),
             "high": ("AgX - Medium High Contrast", "Medium High Contrast"), "punchy": ("AgX - Punchy",)}


#: The names of the choices of the finer settings: key -> {choice: name}.
CHOICE_NAMES = {
    "finish.texture": {"none": "None", "paper": "Fine paper", "rough": "Rough paper", "canvas": "Canvas", "image": "A picture…"},
    "image.contrast": {"": "Ambient's own", "base": "Soft", "medium": "Medium", "high": "Medium high", "punchy": "Punchy"},
}


def _fine(key, tab, group, label, kind, default=None, lo=None, hi=None, step=0.0, fmt="", **more) -> "Param":
    return Param(key, tab, group, label, kind, default, lo, hi, extra=True, step=step, fmt=fmt, **more)


@dataclass(frozen=True)
class Param:
    key: str
    tab: str
    group: str
    label: str
    kind: str
    default: object = None
    lo: float | None = None
    hi: float | None = None
    choices: tuple = ()           # of a "choice"; () for one whose list is made at run time (materials)
    simple: bool = False          # shown in the simple view (the default layout)
    when: tuple = ()              # (other key, values): applies only while that setting has one of them
    optional: bool = False        # may be None: «the look's own», «none»
    colour_space: str = ""        # of a "colour": "screen" (sRGB, as seen) or "linear" (as Blender takes it)
    hint: str = ""
    local: bool = False           # a preference of the program, not of the drawing: it has its control, its row in Expert and
                                  # its eye, but no document or preset keeps it
    extra: bool = False           # a finer setting: its control is made from the register (fine_controls.py) and the document
    step: float = 0.0             # keeps it in "fine", only when it is not at its default. Of its slider: the step,
    fmt: str = ""                 # how the value is written
    special: str = ""             # and the word its lowest position says


def _slider(name, tab, group, key, simple=False, when=()):
    label, lo, hi, _default, _unit = presets.SLIDERS[name]
    return Param(key, tab, group, label, "number", None, lo, hi, simple=simple, when=when, optional=True,
                 hint=presets.SLIDER_HINTS.get(name, ""))


def _build() -> tuple:
    sh, sk, gr = presets.SHADOW_DEFAULT, presets.SKYLINE_DEFAULT, presets.GROUND_DEFAULT
    mono = ("surface.kind", ("mono",))
    lux = ("surface.kind", ("lux",))
    lines = ("outline.on", (True,))
    water = ("finish.kind", ("watercolour",))
    hatched = ("shadows.draw", ("lines", "cross", "dots"))
    painted = ("shadows.draw", ("colour", "lines", "cross", "dots"))
    pano = ("background.kind", ("pano",))
    picture = ("background.kind", ("picture",))
    flat = ("background.kind", ("flat",))
    ground = ("ground.on", (True,))
    textured = ("finish.texture", ("paper", "rough", "canvas", "image"))
    skyline = ("skyline.type", ("mountains", "hills", "forest", "city"))
    return (
        # -- Main
        Param("ambient.look", "main", "ambient", "Look", "choice", "clear", choices=tuple(presets.ORDER), simple=True),
        _slider("dof", "main", "camera", "camera.dof", simple=True),
        _slider("focus", "main", "camera", "camera.focus", simple=True),
        Param("quality.level", "main", "quality", "Quality", "int", 1, 0, 2, simple=True),
        Param("quality.width", "main", "quality", "Width", "int", 1920, 320, 16384, simple=True),
        Param("quality.engine", "main", "quality", "Engine", "choice", "auto", choices=("auto", "eevee", "cycles")),
        Param("quality.preview_engine", "main", "quality", "Preview engine", "choice", "auto", choices=("auto", "eevee", "cycles"),
              local=True),
        Param("quality.preview_quality", "main", "quality", "Preview quality", "choice", "normal",
              choices=("fast", "normal", "high"), local=True),
        # -- Style: the surface
        Param("surface.kind", "style", "surface", "Surface", "choice", "real", choices=("real", "mono", "paper", "lux"), simple=True),
        Param("surface.material", "style", "surface", "Material", "text", "", when=mono, simple=True),
        Param("surface.colour", "style", "surface", "Colour", "colour", WHITE, when=mono, simple=True, colour_space="linear"),
        Param("surface.keep_glass", "style", "surface", "Keep glass and water", "bool", True, when=mono),
        Param("surface.lux_max", "style", "surface", "Scale up to", "number", 0.0, 0.0, 1e6, when=lux, simple=True),
        # -- Style: the outline
        Param("outline.on", "style", "outline", "Outlines", "bool", False, simple=True),
        Param("outline.width", "style", "outline", "Thickness", "number", 0.0, 0.0, 4.0, when=lines, simple=True,
              hint="In pixels of the picture; 0 = automatic"),
        Param("outline.colour", "style", "outline", "Colour", "colour", tuple(presets.STYLE_DEFAULT["color"]), when=lines,
              simple=True, colour_space="linear"),
        Param("outline.hand", "style", "outline", "Irregular stroke", "number", 0.0, 0.0, 1.0, when=lines, simple=True),
        Param("outline.extend", "style", "outline", "Line extension", "number", 0.0, 0.0, 1.0, when=lines, simple=True),
        # -- Style: the finish
        Param("finish.kind", "style", "finish", "Finish", "choice", "none", choices=("none", "watercolour"), simple=True),
        Param("finish.wetness", "style", "finish", "Wetness", "number", 0.5, 0.0, 1.0, when=water, simple=True),
        Param("finish.edges", "style", "finish", "Edges", "number", 0.4, 0.0, 1.0, when=water, simple=True),
        Param("finish.paper", "style", "finish", "Paper", "number", 0.5, 0.0, 1.0, when=water, simple=True),
        _fine("finish.texture", "style", "finish", "Texture", "choice", "none", choices=tuple(CHOICE_NAMES["finish.texture"]),
              simple=True, hint="The grain of a paper or a canvas over the whole picture, with any surface and finish"),
        _fine("finish.texture_path", "style", "finish", "Texture picture", "path", None, optional=True, simple=True,
              when=("finish.texture", ("image",)), hint="A picture of a paper or a cloth, repeated over the render: its light and dark"),
        _fine("finish.texture_strength", "style", "finish", "Texture strength", "number", 0.5, 0.0, 1.0, 0.05, "{:.0%}",
              when=textured, simple=True),
        _fine("finish.texture_scale", "style", "finish", "Texture size", "number", 1.0, 0.25, 4.0, 0.05, "{:.0%}",
              when=textured, simple=True),
        # -- Style: the picture
        _slider("exposure_bias", "style", "image", "image.exposure_bias", simple=True),
        _slider("warmth", "style", "image", "image.warmth", simple=True),
        _slider("saturation", "style", "image", "image.saturation", simple=True),
        _slider("vignette", "style", "image", "image.vignette"),
        _slider("ao", "style", "image", "image.ao"),
        _slider("ao_distance", "style", "image", "image.ao_distance"),
        _fine("surface.albedo_cap", "style", "surface", "Whitest material", "number", 0.8, 0.5, 1.0, 0.01, "{:.0%}",
              hint="No material reflects more than this: white walls keep their shades"),
        _fine("image.contrast", "style", "image", "Tone contrast", "choice", "", choices=tuple(CHOICE_NAMES["image.contrast"])),
        _fine("image.kelvin", "style", "image", "White balance", "number", 3900.0, 3900.0, 12000.0, 100.0, "{:.0f} K", special=OWN,
              hint="The light that comes out white, in kelvin: higher gives a warmer picture. «Warmth» still adds to it"),
        _fine("image.tint", "style", "image", "Green–magenta tint", "number", 0.0, -50.0, 50.0, 1.0, "{:+.0f}"),
        _fine("image.bloom", "style", "image", "Bloom", "number", -0.05, -0.05, 1.0, 0.05, "{:.0%}", special=OWN,
              hint="A glow round what shines: lamps, the sun on glass"),
        _fine("image.exposure_target", "style", "image", "Auto exposure aim", "number", 0.0, 0.0, 0.8, 0.01, "{:.2f}", special=OWN,
              hint="How bright the middle of the picture is made"),
        _fine("image.exposure_white", "style", "image", "Highlights allowed", "number", 0.0, 0.0, 10.0, 0.2, "{:.1f}", special=OWN,
              hint="How far the lightest parts may go before the exposure is held back: more lets a window burn out"),
        _fine("image.exposure_max", "style", "image", "Most it brightens", "number", 0.0, 0.0, 12.0, 0.5, "{:.1f} EV", special=OWN),
        # -- Environment: the sky
        _site("sun.date", "Date", simple=True),
        _site("sun.hour", "Hour", simple=True),
        _site("site.location", "Location", simple=True),
        _site("site.coords", "Latitude, longitude"),
        _site("site.north", "North"),
        _site("site.zone", "Time zone"),
        _site("site.shadows", "Shadows in the 3D view"),
        _site("site.info", "The sun then"),
        _slider("sun_scale", "environment", "sky", "sky.sun_scale", simple=True),
        _slider("clouds", "environment", "sky", "sky.clouds", simple=True),
        _slider("stars", "environment", "sky", "sky.stars", simple=True),           # (only at night, where the sun's slider
        _slider("moon", "environment", "sky", "sky.moon", simple=True),             # is gone: they cost the day nothing)
        _fine("sky.golden_elevation", "environment", "sky", "Golden hour sun height", "number", 0.0, 0.0, 30.0, 0.5, "{:.1f}°",
              special=OWN, when=("ambient.look", ("golden_hour",))),
        _fine("sky.cloud_scale", "environment", "sky", "Cloud size", "number", 1.0, 0.25, 4.0, 0.05, "{:.0%}"),
        _fine("sky.cloud_brightness", "environment", "sky", "Cloud brightness", "number", 1.0, 0.2, 2.0, 0.05, "{:.0%}"),
        _fine("sky.cloud_seed", "environment", "sky", "Cloud shape", "int", 0, 0, 99, 1.0, "{:.0f}",
              hint="Another number, other clouds (and other stars)"),
        # -- Environment: the shadows
        Param("shadows.draw", "environment", "shadows", "Draw", "choice", sh["draw"], choices=tuple(presets.SHADOW_DRAWS), simple=True),
        Param("shadows.colour", "environment", "shadows", "Colour", "colour", tuple(sh["color"]), when=painted, simple=True, colour_space="screen"),
        Param("shadows.opacity", "environment", "shadows", "Intensity", "number", sh["opacity"], 0.05, 1.0, when=painted, simple=True),
        Param("shadows.spacing", "environment", "shadows", "Hatch spacing", "number", sh["spacing"], 3.0, 60.0, when=hatched, simple=True),
        Param("shadows.angle", "environment", "shadows", "Hatch angle", "number", sh["angle"], 0.0, 180.0, when=hatched, simple=True),
        Param("shadows.floor", "environment", "shadows", "Shadow on the floor", "bool", True, simple=True),
        _fine("shadows.outline", "environment", "shadows", "Shadow outline", "number", 0.0, 0.0, 4.0, 0.1, "{:.1f} px",
              special="No outline", simple=True,          # (not «None»: its Catalan, «Cap», is also the section's cap)
              hint="A line round the sun's shadows, as thick as this, in the outlines' colour (Style, Outline)"),
        _fine("shadows.softness", "environment", "shadows", "Soft shadow edge", "number", 0.0, 0.0, 20.0, 0.5, "{:.1f}°",
              special=OWN, hint="The size of the sun in the sky: small, a sharp edge; large, a soft one"),
        # -- Environment: what is behind
        Param("background.kind", "environment", "background", "Show", "choice", "sky", choices=("sky", "pano", "picture", "flat", "transparent"), simple=True),
        Param("background.paper_sky", "environment", "background", "Paper instead of the sky", "bool", False,
              hint="The sky is left out and paper (or the plain colour) is put behind: what the old Sketch style did"),
        Param("pano.path", "environment", "background", "Image", "path", None, when=pano, optional=True, simple=True),
        Param("pano.rotation", "environment", "background", "Rotation", "number", 0.0, 0.0, 360.0, when=pano, simple=True),
        Param("pano.brightness", "environment", "background", "Panorama brightness", "number", 0.0, -3.0, 3.0, when=pano),
        Param("pano.height", "environment", "background", "Viewpoint height", "number", 2.5, 0.5, 30.0, when=pano),
        Param("pano.light", "environment", "background", "Lights the scene", "bool", True, when=pano, simple=True),
        Param("picture.path", "environment", "background", "Picture", "path", None, when=picture, optional=True, simple=True),
        Param("picture.fit", "environment", "background", "Fit", "choice", "fill", choices=("fill", "fit", "stretch"), when=picture),
        Param("picture.brightness", "environment", "background", "Picture brightness", "number", 0.0, -3.0, 3.0, when=picture),
        Param("flat.colour", "environment", "background", "Colour", "colour", (1.0, 1.0, 1.0), when=flat, simple=True, colour_space="screen"),
        # -- Environment: the ground
        Param("ground.on", "environment", "ground", "Generated ground", "bool", True, simple=True),
        Param("ground.type", "environment", "ground", "Type", "choice", gr["type"], choices=("",) + tuple(presets.GROUND_TYPES) + ("custom",),
              when=ground, simple=True),
        Param("ground.colour", "environment", "ground", "Colour", "colour", None, when=ground, optional=True, colour_space="linear"),
        Param("ground.roughness", "environment", "ground", "Roughness", "number", gr["roughness"], 0.0, 1.0, when=ground),
        Param("ground.offset", "environment", "ground", "Height", "number", gr["offset"], -10.0, 10.0, when=ground),
        Param("ground.radius", "environment", "ground", "Size", "number", gr["ground_radius"], 0.0, 5000.0, when=ground),
        Param("ground.grass_radius", "environment", "ground", "Grass radius", "number", gr["grass_radius"], 0.0, 500.0, when=ground),
        Param("ground.material", "environment", "ground", "Material", "text", None, when=ground, optional=True),
        Param("ground.material_tile", "environment", "ground", "Material size", "number", 0.0, 0.0, 100.0, when=ground),
        # -- Environment: the far skyline
        Param("skyline.type", "environment", "horizon", "Skyline", "choice", sk["type"], choices=("",) + tuple(presets.SKYLINE_TYPES), simple=True),
        Param("skyline.height", "environment", "horizon", "Peak height", "number", sk["height"], 0.5, 20.0, when=skyline, simple=True),
        Param("skyline.distance", "environment", "horizon", "Distance", "number", sk["distance"], 0.0, 20000.0, when=skyline),
        Param("skyline.seed", "environment", "horizon", "Shape", "int", sk["seed"], 0, 9999, when=skyline),
        Param("skyline.colour", "environment", "horizon", "Colour", "colour", None, when=skyline, optional=True, colour_space="linear"),
        # -- Environment: the air
        _slider("fog", "environment", "fog", "fog.amount", simple=True),
        _slider("fog_start", "environment", "fog", "fog.start"),
        Param("fog.ground_haze", "environment", "fog", "Ground haze", "number", gr["haze"], 0.0, 4.0, when=ground),
        # -- Section: the cap, its outline and the light in the cut (section.py keeps them in the drawing)
        _cut("cap", "section.cap", "Close the cut with a face"),
        _cut("cap", "section.style", "Type"),
        _cut("cap", "section.material", "Material"),
        _cut("cap", "section.colour", "Colour"),
        _cut("cap", "section.pattern", "Pattern"),
        _cut("cap", "section.spacing", "Spacing"),
        _cut("cap", "section.line_width", "Hatching thickness"),
        _cut("cap", "section.line_colour", "Hatching colour"),
        _cut("cap", "section.line_hand", "Hatching hand"),
        _cut("cap", "section.line_ink", "Hatching ink"),
        _cut("cap", "section.no_shadows", "No shadows on the cap", simple=False),
        _cut("rim", "rim.on", "Outline of the cap"),
        _cut("rim", "rim.width", "Thickness"),
        _cut("rim", "rim.colour", "Colour"),
        _cut("rim", "rim.hand", "Hand"),
        _cut("rim", "rim.ink", "Ink"),
        _cut("cutlight", "cutlight.mode", "Light"),
    )


PARAMS: tuple = _build()
BY_KEY: dict = {p.key: p for p in PARAMS}

#: The finer settings (see ``Param.extra``).
EXTRA_KEYS: tuple = tuple(p.key for p in PARAMS if p.extra)


def fine_clean(values) -> dict:
    """The finer settings of ``values`` that are not at their default, made safe."""
    out = {}
    if isinstance(values, dict):
        for key in EXTRA_KEYS:
            if key not in values:
                continue
            param = BY_KEY[key]
            value = clean_value(param, values[key])
            default = list(param.default) if isinstance(param.default, tuple) else param.default
            if value is None or value == default:
                continue
            out[key] = value
    return out


#: The settings that are sliders of the old format: new key -> its name there.
SLIDER_KEYS = {"camera.dof": "dof", "camera.focus": "focus", "image.exposure_bias": "exposure_bias", "image.warmth": "warmth",
               "image.saturation": "saturation", "image.vignette": "vignette", "image.ao": "ao", "image.ao_distance": "ao_distance",
               "sky.sun_scale": "sun_scale", "sky.clouds": "clouds", "sky.stars": "stars", "sky.moon": "moon",
               "fog.amount": "fog", "fog.start": "fog_start"}


def defaults() -> dict:
    """Every setting at its default, by key (colours as lists, so the result can be kept as JSON)."""
    return {p.key: list(p.default) if isinstance(p.default, tuple) else p.default for p in PARAMS}


def clean_value(param: Param, value):
    """``value`` made safe for ``param``: clamped, or its default when it is of no use."""
    default = list(param.default) if isinstance(param.default, tuple) else param.default
    if value is None:
        return None if param.optional else default
    if param.kind == "bool":
        return bool(value)
    if param.kind in ("number", "int"):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return default
        if v != v:                                    # NaN
            return default
        v = max(param.lo, min(param.hi, v))
        return int(v) if param.kind == "int" else v
    if param.kind == "choice":
        return value if value in param.choices else default
    if param.kind == "colour":
        try:
            c = [max(0.0, min(1.0, float(x))) for x in value][:3]
        except (TypeError, ValueError):
            return default
        return c if len(c) == 3 else default
    return value if isinstance(value, str) else default      # text, path


def clean(values) -> dict:
    """A full, safe set of settings from whatever ``values`` holds (unknown keys are dropped)."""
    values = values if isinstance(values, dict) else {}
    return {p.key: clean_value(p, values[p.key]) if p.key in values else defaults()[p.key] for p in PARAMS}


def applies(param: Param, values: dict) -> bool:
    """Whether ``param`` means something with these ``values`` (its condition, and those of what it depends on)."""
    if not param.when:
        return True
    key, wanted = param.when
    return values.get(key) in wanted and applies(BY_KEY[key], values)


def simple_layout() -> list:
    """The keys the default layout shows."""
    return [p.key for p in PARAMS if p.simple]
