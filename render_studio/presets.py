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
}


#: How each panel slider's value reads, and what it does (a gray line under it). They change the
#: SCENE that the preview and Render draw; the retouch sliders of the preview window (post.py)
#: change the finished picture instead.
SLIDER_FORMATS = {
    "exposure_bias": "{:+.1f} EV", "clouds": "{:.0%}", "sun_scale": "×{:.2f}",
    "warmth": "{:+.2f}", "saturation": "×{:.2f}", "vignette": "{:.2f}",
}
SLIDER_HINTS = {
    "exposure_bias": "Brighter or darker, in stops (on top of the auto exposure)",
    "clouds": "How cloudy the sky is (off with a 360° background)",
    "sun_scale": "Strength of the sun and its shadows (×1 = the look's)",
    "warmth": "Colour of the light: cooler, bluish ← → warmer, yellowish",
    "saturation": "How vivid the colours are in the render",
    "vignette": "Darkens the corners of the render",
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
    return out
