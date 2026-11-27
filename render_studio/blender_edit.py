# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit the lights or the materials in Blender, and take them back.

«Edit in Blender…» opens a Blender window with the lights (or one sphere per material) of the
drawing, over a floor and a one-metre cube. The person works there the way Blender does — moves,
turns and resizes lights, adds and deletes them; changes a material's roughness, metal or glow
— and saves (Ctrl+S). Each save is read back, in a Blender that has no window, and put in the
drawing as one undo step.

What comes back is what Render Studio itself knows: for a light its kind, place, aim, power,
colour, size, beam and shadows; for a material its roughness, metal and glow. Blender's node trees
(a procedural wood, say) have nowhere to go in the drawing and stay in the .blend file.

The conversions here are plain Python (no Qt, no Blender), to be tested on their own.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from . import lights as L

SCRIPT = Path(__file__).parent / "blender" / "edit_scene.py"
#: A change smaller than this (relative) is the rounding of the trip, not the person's edit.
EPS = 2e-3


def _near(a, b, eps=EPS) -> bool:
    return abs(float(a) - float(b)) <= eps * max(1.0, abs(float(b)))


# ---- lights -----------------------------------------------------------------------------------

def lights_to_blender(free: list) -> list:
    """The free lights as the Blender script wants them: the render's own format (``energy``, ``basis``)."""
    out = []
    for lt in free:
        d = dict(lt)
        d["energy"] = L.blender_watts(lt)
        d["basis"] = [list(a) for a in L.light_basis(lt["dir"], lt["spin"])]
        d["package"] = lt.get("blender")                    # a proxy: the Blender light it was edited into
        out.append(d)
    return out


def lights_from_blender(old: list, read: list, whole_scene: bool = False) -> list:
    """The free lights after the Blender session: ``old`` are the ones sent, ``read`` what the .blend now
    holds. A light whose id is still there keeps everything Blender knows nothing about (its IES file, its
    unit, the kelvin of its colour); a light with no id is new; one that is gone is deleted."""
    by_id = {lt["id"]: lt for lt in old}
    order = {lt["id"]: i for i, lt in enumerate(old)}
    out = []
    kept = []
    if whole_scene:
        # In the render's scene the lights switched off, or with no power, are not made (the render has none of them):
        # they are not «deleted», they stay as they are.
        seen = {r.get("id") for r in read}
        kept = [lt for lt in old if lt["id"] not in seen and (not lt.get("on", True) or float(lt.get("power", 0)) <= 0.0)]
    # the list keeps its order; what Blender added goes last
    for r in sorted(read, key=lambda r: order.get(r.get("id", ""), len(order))):
        base = by_id.get(r.get("id", ""))
        kind = r["type"] if r.get("type") in L.TYPES else "point"
        raw = dict(base) if base else dict(L.DEFAULTS[kind], type=kind)
        raw["type"] = kind
        raw["name"] = "" if r["name"].startswith(("Point ", "Spot ", "Area ", "Sun ", "Light")) and base is None \
            else r["name"]
        raw["on"] = bool(r.get("on", True))
        pos = [round(float(c), 4) for c in r["pos"]]
        if base is None or not all(abs(a - b) < 2e-4 for a, b in zip(pos, base["pos"])):
            raw["pos"] = pos
        z = [float(c) for c in r["z"]]
        new_dir = [round(-c, 6) + 0.0 for c in z]
        if base is None or not all(abs(a - b) < 2e-5 for a, b in zip(new_dir, base["dir"])):
            raw["dir"] = new_dir
        # the spin: how far x has turned from the axes a light with no spin gets
        bx, by, _bz = L.light_basis(raw["dir"], 0.0)
        x = [float(c) for c in r["x"]]
        spin = round(math.degrees(math.atan2(sum(a * b for a, b in zip(x, by)),
                                             sum(a * b for a, b in zip(x, bx)))), 2) if kind == "area" else 0.0
        if base is None or abs(((spin - base["spin"] + 180.0) % 360.0) - 180.0) > 0.02:
            raw["spin"] = spin
        # power: as it was unless Blender's value moved
        was = L.blender_watts(base) if base else None
        if was is None or not _near(r["energy"], was):
            tmp = dict(raw, unit="W", power=float(r["energy"]))
            if base and base.get("unit") == "lm" and kind != "sun":
                tmp = L.convert_unit(tmp, "lm")
            raw["unit"], raw["power"] = tmp["unit"], tmp["power"]
        # colour: the temperature stays unless the colour moved
        col = [float(c) for c in r["color"]][:3]
        if base is None or not all(_near(a, b) for a, b in zip(col, base["color"])):
            raw["kelvin"], raw["color"] = None, col
        raw["shadow"] = bool(r.get("shadow", True))
        for key in ("radius", "spot_angle", "spot_blend", "size", "size_y", "spread", "sun_angle"):
            if key in r and not (base and _near(r[key], base.get(key, 1e9), 1e-4)):
                raw[key] = round(float(r[key]), 5)
        if "shape" in r and r["shape"] in L.SHAPES:
            raw["shape"] = r["shape"]
        raw["id"] = base["id"] if base else L.new_id()
        if r.get("package") and r["package"].get("blend"):
            raw["blender"] = r["package"]                   # edited beyond Render Studio's light: a proxy, kept whole
        c = L.clean_light(raw)
        if c is not None:
            out.append(c)
    out.extend(dict(lt) for lt in kept)
    out.sort(key=lambda lt: order.get(lt.get("id"), len(order)))      # the list keeps its order
    return L.clean_lights(out)


# ---- materials --------------------------------------------------------------------------------

def _pbr(scene) -> dict:
    """Each picture's companion maps (normal, roughness…), as the render gets them."""
    try:
        from . import pbr
        return pbr.job_block(scene)
    except Exception:  # noqa: BLE001 - the pictures alone
        return {}


def _finish(name: str, mat) -> dict:
    """IngeTrazo's finish for a material, as its export to Blender gives it (the one chosen, or guessed from
    the name and the picture), with the finish's numbers. Empty when it cannot be told."""
    try:
        from core.finish import PBR, resolve
    except Exception:  # noqa: BLE001 - an IngeTrazo without finishes
        return {}
    tex = getattr(mat, "texture", None) or {}
    picture = str(tex.get("path") or "").replace("\\", "/").rsplit("/", 1)[-1] or None
    opacity = getattr(mat, "opacity", None)
    finish = resolve(getattr(mat, "finish", None), name, picture, opacity)
    if finish not in PBR:
        return {}
    return {"finish": finish, "finish_pbr": [float(v) for v in PBR[finish]],
            "opacity": None if opacity is None else float(opacity)}


def materials_to_blender(scene, specs: dict, names: list, limit: int = 64) -> list:
    """One entry per material: its colour and its render settings (the automatic ones where it has none)."""
    from . import materials as M
    try:
        full = M.with_detected(scene, specs)           # the finish the render gives them by name too
    except Exception:  # noqa: BLE001
        full = specs
    out = []
    for name in names[:limit]:
        spec = dict(M.DEFAULT)
        spec.update(full.get(name) or {})
        mat = scene.materials.get(name) if getattr(scene, "materials", None) is not None else None
        color = (getattr(mat, "color", None) or (0.8, 0.8, 0.8))[:3]
        tex = (getattr(mat, "texture", None) or {}) if mat is not None else {}
        plain = {k: v for k, v in (full.get(name) or {}).items() if k != "blender"}    # nothing: the finish alone
        grass = None
        if spec.get("type") == "grass":
            h = float(spec.get("grass_height", M.DEFAULT_GRASS_HEIGHT))
            grass = {"type": "grass", "grass_height": h,
                     "grass_density": float(spec.get("grass_density") or M.auto_grass_density(h))}
        out.append({"name": name, "grass": grass, "spec": plain, "pbr": _pbr(scene), "package": (full.get(name) or {}).get("blender"), "color": [float(c) for c in color], "roughness": float(spec.get("roughness", 0.5)),
                    "metallic": float(spec.get("metallic", 0.0)), "glow": float(spec.get("glow", 0.0)),
                    "texture": {"path": str(tex["path"]), "sw": float(tex.get("sw", 1.0) or 1.0), "sh": float(tex.get("sh", 1.0) or 1.0)} if tex.get("path") else None,
                    **_finish(name, mat)})
    return out


def materials_from_blender(specs: dict, read: list, current: dict | None = None) -> dict:
    """The material specs that changed in Blender (name → new spec), the rest of each spec kept.
    ``current``: the specs the render uses now (``specs`` plus those detected from the names)."""
    from . import materials as M
    changed = {}
    for r in read:
        name = r["name"]
        old = dict((current or specs).get(name) or specs.get(name) or {})
        base = dict(M.DEFAULT)
        base.update(old)
        new = dict(base)
        opened = r.get("opened") or {}                     # the numbers the material was opened with
        for key, hi in (("roughness", 1.0), ("metallic", 1.0), ("glow", 50.0)):
            v = max(0.0, min(hi, float(r[key])))
            if not _near(v, float(opened.get(key, base.get(key, 0.0))), 5e-3):
                new[key] = round(v, 3)
        if r.get("package") and r["package"].get("blend"):
            new["blender"] = r["package"]                  # the whole material as it was left: the render uses it as it is
        if new != base:
            if not old and r.get("finish") in ("glass", "water"):
                new["type"] = r["finish"]                  # (a generic one would take the glass or water away)
            new.pop("preset", None)                        # no longer the preset it started from
            changed[name] = new
    return changed


# ---- the session ------------------------------------------------------------------------------

def work_folder(kind: str) -> Path:
    import tempfile
    p = Path(tempfile.gettempdir()) / "render-studio-edit" / f"blender-{kind}-{time.strftime('%H%M%S')}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _rounded(v):
    if isinstance(v, float):
        return round(v, 5) + 0.0
    if isinstance(v, (list, tuple)):
        return [_rounded(c) for c in v]
    if isinstance(v, dict):
        return {k: _rounded(c) for k, c in v.items()}
    return v


def same(a, b) -> bool:
    """Two lists of lights alike but for the last digits (what a trip through Blender rounds)."""
    return json.dumps(_rounded(a), sort_keys=True) == json.dumps(_rounded(b), sort_keys=True)
