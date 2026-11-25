# SPDX-License-Identifier: GPL-3.0-or-later
"""The settings' new model, and its translation from and to the format documents and presets keep today (format 1).

The new model is flat: ``{key: value}`` with the keys of params.py. It keeps apart the surface, the outline, the shadows and the
finish, which format 1 mixed in its styles. ``from_v1`` reads any document or preset; ``to_v1`` writes it back for what still
speaks format 1 (the panel and the render job), and gives the same picture. A combination no old style can say (``not_in_v1``
names it) is written with the style's ``parts`` beside the nearest old mode. The Section and Output tabs are not part of it and pass through untouched. Pure Python: no Qt.
"""
from __future__ import annotations

from . import params, presets, settings_store

#: Parts of format 1 the new model does not hold: carried as they are.
PASS_THROUGH = ("section", "output")
_GROUND_LOOK = {"ground.type": "type", "ground.colour": "color", "ground.roughness": "roughness", "ground.offset": "offset",
                "ground.radius": "ground_radius", "ground.grass_radius": "grass_radius", "fog.ground_haze": "haze"}
_SKYLINE = {"skyline.type": "type", "skyline.height": "height", "skyline.distance": "distance", "skyline.seed": "seed",
            "skyline.colour": "color"}
_SHADOWS = {"shadows.draw": "draw", "shadows.colour": "color", "shadows.opacity": "opacity", "shadows.spacing": "spacing",
            "shadows.angle": "angle"}


def from_v1(settings) -> dict:
    """The new model of a document's (or preset's) format 1 ``settings``. Anything missing or wrong takes its default."""
    v1 = settings_store.clean(settings) or settings_store.clean({"look": "clear"})
    out = params.defaults()
    out["ambient.look"] = v1["look"]
    out["quality.level"], out["quality.engine"], out["quality.width"] = v1["quality"], v1["engine"], v1["width"]
    for key, name in params.SLIDER_KEYS.items():
        out[key] = v1["sliders"].get(name)
    _style_from_v1(v1["style"], out)
    for key, name in _SHADOWS.items():
        out[key] = v1["shadows"][name]
    out["shadows.floor"] = v1["ground_shadow"]
    out["ground.on"] = v1["ground"]
    for key, name in _GROUND_LOOK.items():
        out[key] = v1["ground_look"][name]
    material = v1["ground_material"]
    out["ground.material"] = material["name"] if material else None
    out["ground.material_tile"] = material["tile"] if material else 0.0
    for key, name in _SKYLINE.items():
        out[key] = v1["skyline"][name]
    kind = "sky"
    if v1["hdri"]:
        kind = "pano"
        h = v1["hdri"]
        out.update({"pano.path": h["path"], "pano.rotation": h["rotation"], "pano.brightness": h["brightness"],
                    "pano.height": h["height"], "pano.light": h["light"]})
    elif v1["backdrop"]:
        kind = "picture"
        b = v1["backdrop"]
        out.update({"picture.path": b["path"], "picture.fit": b["fit"], "picture.brightness": b["brightness"]})
    if v1["flat"]:
        kind = "flat"
        out["flat.colour"] = list(v1["flat"]["color"])
    out["background.kind"] = kind
    return out


def _style_from_v1(style: dict, out: dict) -> None:
    mode = style["mode"]
    sketch = mode == "sketch"
    if mode == "white" or (sketch and style["base"]):
        out["surface.kind"], out["surface.colour"], out["surface.keep_glass"] = "mono", list(params.WHITE), True
    elif mode == "model":
        out["surface.kind"], out["surface.keep_glass"] = "mono", False
        out["surface.material"], out["surface.colour"] = style["material"], list(style["model_color"])
    elif sketch:
        out["surface.kind"] = "paper"
    elif mode == "light":
        out["surface.kind"], out["surface.lux_max"] = "lux", style["lux_max"]
    out["background.paper_sky"] = sketch
    out["outline.on"] = sketch or style["width"] > 0.0          # a sketch is lines, whatever its width says
    out["outline.width"] = style["width"]
    out["outline.colour"] = list(style["color"])
    if sketch:                                                  # (the other styles drew their lines with a ruler)
        out["outline.hand"], out["outline.extend"] = style["noise"], style["extend"]
    if mode == "watercolour":
        out["finish.kind"] = "watercolour"
        out["finish.wetness"], out["finish.edges"], out["finish.paper"] = style["wetness"], style["edges"], style["paper"]
    parts = style.get("parts")
    if parts:                                                   # the whole of the style is said there
        out["surface.kind"], out["surface.keep_glass"] = parts["surface"], parts["keep_glass"]
        out["surface.material"], out["surface.colour"] = style["material"], list(style["model_color"])
        out["surface.lux_max"] = style["lux_max"]
        out["background.paper_sky"] = parts["paper_sky"]
        out["outline.on"] = parts["outline"]
        out["outline.hand"], out["outline.extend"] = style["noise"], style["extend"]
        out["finish.kind"] = parts["finish"]
        out["finish.wetness"], out["finish.edges"], out["finish.paper"] = style["wetness"], style["edges"], style["paper"]


def _white(values) -> bool:
    return all(abs(a - b) < 1e-4 for a, b in zip(values["surface.colour"], params.WHITE))


def _mode(v: dict) -> str:
    """The format 1 style nearest to the new model's surface, paper and finish."""
    if v["background.paper_sky"]:
        return "sketch"
    if v["surface.kind"] == "lux":
        return "light"
    if v["finish.kind"] == "watercolour":
        return "watercolour"
    if v["surface.kind"] == "mono":
        return "white" if v["surface.keep_glass"] and not v["surface.material"] and _white(v) else "model"
    if v["surface.kind"] == "paper":
        return "sketch"
    return "none"


def not_in_v1(values: dict) -> list:
    """What these settings ask for that no style of format 1 can say by its mode alone: short reasons, [] if none."""
    v = params.clean(values)
    out = []
    mode = _mode(v)
    surface = v["surface.kind"]
    if mode == "sketch":
        if surface not in ("mono", "paper"):
            out.append("paper behind a surface that is not white or paper")
        elif surface == "mono" and (v["surface.material"] or not v["surface.keep_glass"] or not _white(v)):
            out.append("paper behind a colour or a material that is not the plain white")
        elif surface == "paper" and not v["background.paper_sky"]:
            out.append("a paper surface without paper behind")
        if not v["outline.on"]:
            out.append("paper with no outlines")
        if v["finish.kind"] != "none":
            out.append("a finish on paper")
    else:
        if mode in ("light", "watercolour") and surface == "mono":
            out.append("a finish or lux over one colour")
        if surface == "lux" and v["finish.kind"] != "none":
            out.append("a finish on the lux picture")
        if v["outline.on"] and (v["outline.hand"] > 0.0 or v["outline.extend"] > 0.0):
            out.append("a hand-drawn outline without paper")
        if v["outline.on"] and v["outline.width"] <= 0.0:
            out.append("an outline of automatic thickness without paper")
        if mode == "model" and v["surface.keep_glass"]:
            out.append("one colour that keeps the glass")
    return out


def style_of(values: dict) -> dict:
    """The format 1 style (with its ``parts`` when it needs them) of the surface, outline, finish and paper in ``values``."""
    return to_v1(dict(params.defaults(), **values))["style"]


def style_of(values: dict) -> dict:
    """The format 1 style (with its ``parts`` when it needs them) of the surface, outline, finish and paper in ``values``."""
    return to_v1(dict(params.defaults(), **values))["style"]


def to_v1(values: dict, pass_through: dict | None = None) -> dict:
    """The format 1 settings of the new model's ``values``; ``pass_through``: the Section and Output settings to keep."""
    v = params.clean(values)
    mode = _mode(v)
    style = dict(presets.STYLE_DEFAULT, mode=mode, color=list(v["outline.colour"]),
                 width=v["outline.width"] if v["outline.on"] else 0.0)
    if mode == "model":
        style["material"], style["model_color"] = v["surface.material"], list(v["surface.colour"])
    elif mode == "light":
        style["lux_max"] = v["surface.lux_max"]
    elif mode == "sketch":
        style["base"] = v["surface.kind"] != "paper"
        style["noise"], style["extend"] = v["outline.hand"], v["outline.extend"]
    elif mode == "watercolour":
        style["wetness"], style["edges"], style["paper"] = v["finish.wetness"], v["finish.edges"], v["finish.paper"]
    if not_in_v1(v):
        style.update(width=v["outline.width"], material=v["surface.material"], model_color=list(v["surface.colour"]),
                     lux_max=v["surface.lux_max"], base=v["surface.kind"] != "paper", noise=v["outline.hand"],
                     extend=v["outline.extend"], wetness=v["finish.wetness"], edges=v["finish.edges"], paper=v["finish.paper"])
        style["parts"] = {"surface": v["surface.kind"], "keep_glass": v["surface.keep_glass"], "plain": _white(v),
                          "paper_sky": v["background.paper_sky"], "finish": v["finish.kind"], "outline": v["outline.on"]}
    kind = v["background.kind"]
    hdri = backdrop = flat = None
    if kind == "pano" and v["pano.path"]:
        hdri = {"path": v["pano.path"], "rotation": v["pano.rotation"], "brightness": v["pano.brightness"],
                "height": v["pano.height"], "light": v["pano.light"]}
    elif kind == "picture" and v["picture.path"]:
        backdrop = {"path": v["picture.path"], "fit": v["picture.fit"], "brightness": v["picture.brightness"]}
    elif kind == "flat":
        flat = {"color": list(v["flat.colour"])}
    material = {"name": v["ground.material"], "tile": v["ground.material_tile"]} if v["ground.material"] else None
    out = {
        "version": settings_store.VERSION,
        "look": v["ambient.look"],
        "engine": v["quality.engine"],
        "quality": v["quality.level"],
        "width": v["quality.width"],
        "ground": v["ground.on"],
        "ground_shadow": v["shadows.floor"],
        "sliders": {name: v[key] for key, name in params.SLIDER_KEYS.items() if v[key] is not None},
        "ground_look": {name: v[key] for key, name in _GROUND_LOOK.items()},
        "skyline": {name: v[key] for key, name in _SKYLINE.items()},
        "style": style,
        "shadows": {name: v[key] for key, name in _SHADOWS.items()},
        "ground_material": material,
        "hdri": hdri,
        "backdrop": backdrop,
        "flat": flat,
    }
    for key in PASS_THROUGH:
        if pass_through and key in pass_through:
            out[key] = pass_through[key]
    return settings_store.clean(out)
