# SPDX-License-Identifier: GPL-3.0-or-later
"""The looks Render Studio offers, as the ``studio`` block of a render job
(what ``blender/studio_scene.py`` reads) plus the IngeTrazo ambience each
one renders in.

Tuned on real renders (Blender 5.3, EEVEE and Cycles): every value here was
looked at, not guessed. The user's sliders scale or replace a few of them
(see :func:`apply_sliders`).
"""
from __future__ import annotations

import copy

#: Shared by every look: AgX, 80 % albedo cap (paper-white 0.96 glows
#: under a path tracer), metered exposure with highlights kept, no bloom
#: (Blender 5.3's Glare spreads a bright sky over the model in Cycles).
_BASE = {
    "auto_exposure": True,
    "exposure_target": 0.3,
    "exposure_white": 1.6,
    "exposure_bias": 0.0,
    "albedo_cap": 0.8,
    "looks": ["AgX - Medium High Contrast", "Medium High Contrast"],
    "white_balance": 7000,
    "saturation": 1.06,
    "bloom": 0.0,
    "vignette": 0.16,
    "sun_scale": 4.0,
    "clouds": 0.0,
    "cloud_brightness": 1.0,
    "cloud_scale": 1.0,
    "ground_color": [0.30, 0.29, 0.27],
}

#: key → (labels by language, ambience, overrides of _BASE)
PRESETS = {
    "clear": ({"en": "Clear day", "ca": "Dia clar", "es": "Día despejado"}, "day",
              {"clouds": 0.25}),
    "partly_cloudy": ({"en": "Partly cloudy", "ca": "Parcialment ennuvolat",
                       "es": "Parcialmente nublado"}, "day",
                      {"clouds": 0.5, "sun_scale": 3.2, "saturation": 1.03}),
    "golden_hour": ({"en": "Golden hour", "ca": "Hora daurada", "es": "Hora dorada"}, "day",
                    {"sun_elevation": 7.0, "sun_angle": 1.0, "clouds": 0.3,
                     "white_balance": 5600, "exposure_target": 0.28, "saturation": 1.1,
                     "vignette": 0.22, "looks": ["AgX - Punchy", "AgX - Medium High Contrast"]}),
    "overcast": ({"en": "Overcast", "ca": "Cobert", "es": "Nublado"}, "overcast",
                 {"white_balance": 6800, "exposure_target": 0.32, "saturation": 0.98,
                  "vignette": 0.12, "looks": ["AgX - Medium Contrast", "AgX - Base Contrast"]}),
    "white_model": ({"en": "White model", "ca": "Maqueta blanca", "es": "Maqueta blanca"}, "day",
                    {"white_model": True, "clouds": 0.2, "white_balance": 7500,
                     "exposure_target": 0.32, "saturation": 0.85, "vignette": 0.15,
                     "ground_color": [0.62, 0.62, 0.60]}),
    "interior": ({"en": "Interior", "ca": "Interior", "es": "Interior"}, "day",
                 # Exposed for the room, the window allowed to burn out (as a
                 # photographer would); the sky's blue light neutralised.
                 {"clouds": 0.25, "exposure_target": 0.36, "exposure_white": 6.0,
                  "white_balance": 7600, "saturation": 1.04, "vignette": 0.14,
                  "engine_hint": "cycles"}),
    "night": ({"en": "Night", "ca": "Nit", "es": "Noche"}, "night",
              # Metered low and capped: without lamps a night stays dark (the
              # meter would otherwise lift the moonlight to a flat blue day).
              {"clouds": 0.35, "stars": 1.0, "white_balance": 8500, "exposure_target": 0.07, "exposure_white": 3.0,
               "exposure_max": 2.5, "saturation": 0.95, "bloom": 0.2, "vignette": 0.25}),
}

ORDER = ("clear", "partly_cloudy", "golden_hour", "overcast", "white_model", "interior", "night")


def label(key: str, lang: str = "en") -> str:
    names = PRESETS[key][0]
    return names.get(lang) or names["en"]


def studio(key: str) -> tuple:
    """(studio block, ambience) for preset ``key``."""
    _names, ambience, over = PRESETS[key]
    block = copy.deepcopy(_BASE)
    block.update(copy.deepcopy(over))
    return block, ambience


#: The sliders the panel shows: key → (label, minimum, maximum, default, unit)
SLIDERS = {
    "exposure_bias": ("Exposure", -3.0, 3.0, 0.0, "EV"),
    "clouds": ("Clouds", 0.0, 1.0, None, "%"),
    "sun_scale": ("Sun", 0.0, 2.0, 1.0, "×"),
    "warmth": ("Warmth", -1.0, 1.0, 0.0, ""),
    "saturation": ("Saturation", 0.0, 1.6, None, "×"),
    "vignette": ("Vignette", 0.0, 0.6, None, ""),
    "dof": ("Depth of field", 0.0, 1.0, 0.0, "%"),
    "focus": ("Focal point", 0.0, 100.0, 0.0, "m"),
    "ao": ("Ambient occlusion", 0.0, 1.0, 0.0, "%"),
    "ao_distance": ("Occlusion reach", 0.1, 5.0, 1.0, "m"),
    "fog": ("Fog", 0.0, 1.0, 0.0, "%"),
    "fog_start": ("Fog starts at", 0.0, 500.0, 30.0, "m"),
    "stars": ("Stars", 0.0, 2.0, 1.0, "×"),
    "moon": ("Moon", 0.0, 2.0, 1.0, "×"),
}

#: The sliders of the night sky: shown only when the render is a night (the Night look, or a sun below the horizon).
NIGHT_SLIDERS = ("stars", "moon")
#: The looks that become a night when the sun is below the horizon at the site's place, date and hour.
NIGHT_WHEN_SUN_SET = ("clear", "partly_cloudy", "overcast", "golden_hour")


#: The sliders always in view; the others are folded under «More adjustments».
#: The ground types: key → (label, colour, roughness). The colour is the ground's base colour as
#: the render uses it (the look's own is [0.30, 0.29, 0.27] to [0.62, 0.62, 0.60]).
GROUND_TYPES = {
    "grass": ("Grass", [0.16, 0.27, 0.09], 0.95),
    "asphalt": ("Asphalt", [0.09, 0.09, 0.10], 0.85),
    "concrete": ("Concrete", [0.46, 0.46, 0.44], 0.85),
    "sand": ("Sand", [0.62, 0.50, 0.33], 0.95),
    "snow": ("Snow", [0.86, 0.88, 0.92], 0.70),
    "wet": ("Wet pavement", [0.06, 0.06, 0.07], 0.12),
}
#: The styles of the render: key → label. Every style can have outlines; each adds its own settings.
STYLES = {"none": "None", "white": "White", "model": "Model", "light": "Light", "sketch": "Sketch", "watercolour": "Watercolour"}
STYLE_DEFAULT = {"mode": "none", "width": 0.0, "color": [0.05, 0.05, 0.05], "material": "", "model_color": [0.85, 0.80, 0.70],
                 "lux_max": 0.0, "noise": 0.5, "extend": 0.4, "wetness": 0.5, "paper": 0.5, "edges": 0.4,
                 # the sketch: whether the render shows under its lines
                 "base": True}
#: How the sun's shadows are drawn, for every style: key → label. "render": as Blender makes them, nothing drawn over them.
SHADOW_DRAWS = {"render": "From the render", "colour": "Colour", "lines": "Lines", "cross": "Cross-hatch", "dots": "Dots"}
#: ``color`` as the screen shows it; ``spacing`` in pixels and ``angle`` in degrees (the hatchings).
SHADOW_DEFAULT = {"draw": "render", "color": [0.1, 0.12, 0.18], "opacity": 0.5, "spacing": 8.0, "angle": 45.0}

#: The distant skyline that hides the line between ground and sky: key → label.
SKYLINE_TYPES = {"mountains": "Mountains", "hills": "Hills", "forest": "Distant forest", "city": "City skyline"}
#: The colour each skyline type has when none is chosen (the same as studio_scene.py's own; linear light).
SKYLINE_COLOURS = {"mountains": [0.13, 0.17, 0.26], "hills": [0.12, 0.19, 0.12], "forest": [0.03, 0.06, 0.03], "city": [0.17, 0.19, 0.24]}
SKYLINE_DEFAULT = {"type": "", "height": 4.0, "distance": 0.0, "seed": 1, "color": None}

GROUND_DEFAULT = {"type": "", "color": None, "roughness": 0.9, "haze": 1.0, "offset": 0.0, "grass_radius": 0.0, "ground_radius": 0.0}

SIMPLE_SLIDERS = ("exposure_bias", "clouds", "sun_scale", "warmth", "saturation")
#: The panel page each slider lives on (the Image tab holds the picture's, the Environment tab the sky's).
SLIDER_PAGE = {"exposure_bias": "image", "warmth": "image", "saturation": "image", "vignette": "image",
               "dof": "camera", "focus": "camera", "ao": "image", "ao_distance": "image", "fog": "env", "fog_start": "env", "clouds": "sky", "sun_scale": "sky", "stars": "sky", "moon": "sky"}


#: How each panel slider's value reads, and what it does (a gray line under it). They change the
#: SCENE that the preview and Render draw; the retouch sliders of the preview window (post.py)
#: change the finished picture instead.
SLIDER_FORMATS = {
    "exposure_bias": "{:+.1f} EV", "clouds": "{:.0%}", "sun_scale": "×{:.2f}",
    "warmth": "{:+.2f}", "saturation": "×{:.2f}", "vignette": "{:.2f}", "dof": "{:.0%}", "focus": "auto|{:.1f} m", "ao": "{:.0%}", "ao_distance": "{:.1f} m", "fog": "{:.0%}", "fog_start": "{:.0f} m",
    "stars": "×{:.2f}", "moon": "×{:.2f}",
}
SLIDER_HINTS = {
    "exposure_bias": "Brighter or darker, in stops (on top of the auto exposure)",
    "clouds": "How cloudy the sky is (off with a 360° background)",
    "sun_scale": "Strength of the sun and its shadows (×1 = the look's)",
    "warmth": "Colour of the light: cooler, bluish ← → warmer, yellowish",
    "saturation": "How vivid the colours are in the render",
    "vignette": "Darkens the corners of the render",
    "dof": "Blurs what is nearer or farther than the middle of the view (0 = everything sharp)",
    "ao": "Darkens the corners and the contact of things: where surfaces meet and the light hardly reaches (0 = off)",
    "ao_distance": "How far from a surface the occlusion reaches, in metres: small for crevices, large for broad shade",
    "fog": "How thick the fog is: it veils what is far (0 = none, 100 % = the farthest things vanish into it)",
    "fog_start": "How far from the camera the fog begins, in metres: nearer than this, everything is clear",
    "focus": "The distance, in metres, that is in focus (the focal point). Auto: the middle of the view. Only matters with depth of field",
    "stars": "How many stars the night sky has (0 = none). Shown when it is night",
    "moon": "How bright the moonlight and the night sky are (0 = a black sky; a real moon's phase and place are not worked out: this is a free setting). Shown when it is night",
}


def apply_sliders(block: dict, sliders: dict) -> dict:
    """The preset's block with the user's sliders on top: exposure in
    stops, clouds as coverage, the sun as a multiple of the preset's, warmth
    as a white-balance shift (+1 warmer: a higher neutral point in Blender's
    terms), saturation and vignette as values."""
    out = copy.deepcopy(block)
    if "exposure_bias" in sliders:
        out["exposure_bias"] = float(sliders["exposure_bias"])
    if sliders.get("clouds") is not None:
        out["clouds"] = max(0.0, min(1.0, float(sliders["clouds"])))
    if "sun_scale" in sliders:
        out["sun_scale"] = out.get("sun_scale", 4.0) * max(0.0, float(sliders["sun_scale"]))
    if "warmth" in sliders:
        out["white_balance"] = out.get("white_balance", 6500) + 1500.0 * float(sliders["warmth"])
    if sliders.get("saturation") is not None:
        out["saturation"] = float(sliders["saturation"])
    if sliders.get("vignette") is not None:
        out["vignette"] = float(sliders["vignette"])
    if sliders.get("dof") is not None:
        out["dof"] = max(0.0, min(1.0, float(sliders["dof"])))
    if sliders.get("ao") is not None:
        out["ao"] = max(0.0, min(1.0, float(sliders["ao"])))
        out["ao_distance"] = max(0.05, float(sliders.get("ao_distance", 1.0)))
    if sliders.get("fog") is not None:
        out["fog"] = max(0.0, min(1.0, float(sliders["fog"])))
        out["fog_start"] = max(0.0, float(sliders.get("fog_start", 30.0)))
    if sliders.get("focus") is not None:
        out["focus"] = max(0.0, float(sliders["focus"]))
    if sliders.get("stars") is not None:
        # clouds hide the stars: fewer and dimmer as the sky closes
        out["stars"] = out.get("stars", 1.0) * max(0.0, float(sliders["stars"])) * (1.0 - 0.85 * out.get("clouds", 0.0))
    if sliders.get("moon") is not None:
        out["moon_scale"] = max(0.0, float(sliders["moon"]))
    return out
