# SPDX-License-Identifier: GPL-3.0-or-later
"""Render materials: how each of the document's named materials looks in a
render, beyond its colour or picture — Enscape's material editor, simple.

A material's render settings live in the document (the extension's
document data, ``{"materials": {name: spec}}``), so they are saved with the
``.igz`` and undone like any edit. A spec::

    {"type": "generic" | "glass" | "water" | "glow" | "grass",
     "roughness": 0..1, "metallic": 0..1, "bump": 0..1,
     "glow": nits-ish 0..50, "coat": 0..1, "sheen": 0..1,
     "grass_height": metres, "grass_density": tufts per m² (grass only)}

Missing keys keep what IngeTrazo's own finish gives. In the render job they
are keyed by the material's EXPORT name (what the GLB, and so Blender,
calls it), which :func:`export_name` computes as IngeTrazo does.
"""
from __future__ import annotations

#: Default size of the ripples of water (0 fine … 1 coarse): about 7 waves a metre.
DEFAULT_RIPPLE_SIZE = 0.8
#: What choosing the type gives to start with (0 = opaque): see-through, not a solid slab.
DEFAULT_TRANSPARENCY = {"glass": 0.85, "water": 0.7}

#: Grass: blades grown on the faces in the render only (not in the model). Height in metres.
DEFAULT_GRASS_HEIGHT = 0.08
GRASS_HEIGHT_RANGE = (0.01, 0.60)
#: Grass density: tufts per m² (each a few blades). The same in the live view and the render.
GRASS_DENSITY_RANGE = (20.0, 800.0)
GRASS_DENSITY_SHORT = 260.0         # the automatic density of short grass…
GRASS_DENSITY_TALL = 60.0           # …down to this for tall grass (fewer, bigger tufts)


def auto_grass_density(height: float) -> float:
    """Tufts per m² a material gets when it has no density of its own
    (materials saved before 0.11.0): what the render used for that height."""
    h = max(0.005, float(height))
    return max(GRASS_DENSITY_TALL, min(GRASS_DENSITY_SHORT, GRASS_DENSITY_SHORT * 0.10 / h))

TYPES = ("generic", "glass", "water", "glow", "grass")
TYPE_LABELS = {"generic": "Generic", "glass": "Glass", "water": "Water", "glow": "Glowing", "grass": "Grass"}

#: Starting points, Enscape-like. key → (labels, spec)
PRESETS = {
    "plaster": ({"en": "Matte plaster", "ca": "Arrebossat mat", "es": "Enlucido mate"},
                {"type": "generic", "roughness": 0.9, "metallic": 0.0, "bump": 0.15}),
    "paint": ({"en": "Satin paint", "ca": "Pintura setinada", "es": "Pintura satinada"},
              {"type": "generic", "roughness": 0.45, "metallic": 0.0, "bump": 0.0}),
    "lacquer": ({"en": "Gloss lacquer", "ca": "Lacat brillant", "es": "Lacado brillante"},
                {"type": "generic", "roughness": 0.15, "metallic": 0.0, "bump": 0.0, "coat": 0.8}),
    "stone": ({"en": "Polished stone", "ca": "Pedra polida", "es": "Piedra pulida"},
              {"type": "generic", "roughness": 0.12, "metallic": 0.0, "bump": 0.05, "coat": 0.3}),
    "concrete": ({"en": "Concrete", "ca": "Formigó", "es": "Hormigón"},
                 {"type": "generic", "roughness": 0.85, "metallic": 0.0, "bump": 0.45}),
    "brick": ({"en": "Brick, rough stone", "ca": "Maó, pedra rugosa", "es": "Ladrillo, piedra rugosa"},
              {"type": "generic", "roughness": 0.8, "metallic": 0.0, "bump": 0.7}),
    "wood": ({"en": "Wood, varnished", "ca": "Fusta envernissada", "es": "Madera barnizada"},
             {"type": "generic", "roughness": 0.4, "metallic": 0.0, "bump": 0.25, "coat": 0.3}),
    "wood_raw": ({"en": "Wood, raw", "ca": "Fusta natural", "es": "Madera natural"},
                 {"type": "generic", "roughness": 0.75, "metallic": 0.0, "bump": 0.4}),
    "fabric": ({"en": "Fabric", "ca": "Teixit", "es": "Tejido"},
               {"type": "generic", "roughness": 0.95, "metallic": 0.0, "bump": 0.3, "sheen": 0.6}),
    "metal_brushed": ({"en": "Brushed metal", "ca": "Metall raspallat", "es": "Metal cepillado"},
                      {"type": "generic", "roughness": 0.35, "metallic": 1.0, "bump": 0.0}),
    "chrome": ({"en": "Chrome", "ca": "Crom", "es": "Cromo"},
               {"type": "generic", "roughness": 0.04, "metallic": 1.0, "bump": 0.0}),
    "glass": ({"en": "Clear glass", "ca": "Vidre transparent", "es": "Vidrio transparente"},
              {"type": "glass", "roughness": 0.0, "metallic": 0.0, "bump": 0.0, "transparency": 0.85}),
    "glass_frosted": ({"en": "Frosted glass", "ca": "Vidre glaçat", "es": "Vidrio esmerilado"},
                      {"type": "glass", "roughness": 0.35, "metallic": 0.0, "bump": 0.0, "transparency": 0.6}),
    "water": ({"en": "Water", "ca": "Aigua", "es": "Agua"},
              {"type": "water", "roughness": 0.02, "metallic": 0.0, "bump": 0.5, "ripple_size": 0.8, "transparency": 0.7}),
    "lawn": ({"en": "Lawn", "ca": "Gespa", "es": "Césped"},
             {"type": "grass", "roughness": 0.85, "metallic": 0.0, "bump": 0.0, "grass_height": 0.06,
              "grass_density": 260.0}),
    "meadow": ({"en": "Tall grass", "ca": "Herba alta", "es": "Hierba alta"},
               {"type": "grass", "roughness": 0.9, "metallic": 0.0, "bump": 0.0, "grass_height": 0.30,
               "grass_density": 90.0}),
    "light": ({"en": "Light panel (glows)", "ca": "Panell de llum (brilla)", "es": "Panel de luz (brilla)"},
              {"type": "glow", "roughness": 0.5, "metallic": 0.0, "bump": 0.0, "glow": 4.0}),
}

#: What an untouched material shows in the editor (IngeTrazo's finish rules).
DEFAULT = {"type": "generic", "roughness": 0.5, "metallic": 0.0, "bump": 0.0, "glow": 0.0}


def shown_controls(kind: str, *, picture: bool = False, set_relief: bool = False,
                   relief_source: str = "", file_maps: bool = False) -> set:
    """The editor's controls that change the render of a material of type ``kind``
    (the rest are hidden). ``picture``: it has a picture of its own; ``set_relief``:
    its texture set gives the relief (a normal or displacement map); ``relief_source``:
    the relief map chosen in the editor ("" = automatic); ``file_maps``: some
    setting follows an image file. What the render does with each (studio_scene):

    * Metal: generic only (other types have no metal).
    * Relief: the waves' height for water (its own ripples, no map); with a
      texture set that gives the relief and no map chosen, the slider does
      nothing (the set's map is used as it is), so only its map row shows.
    * Glow: glowing only. Ripple size: water. Grass height and density: grass.
    * Transparency and its map (white opaque, black transparent): not grass (the blades cover the
      face). Picture adjustments: the same.

    * Map image size: a map file on a material without a picture (with one,
      maps follow the picture's size). Change picture: a material with one.
    """
    shown = {"roughness", "map:roughness"}
    if kind == "generic":
        shown |= {"metallic", "map:metallic"}
    if kind == "water":
        shown |= {"bump", "ripple_size"}
    else:
        shown.add("map:bump")
        if not (set_relief and not relief_source):
            shown.add("bump")
    if kind == "glow":
        shown |= {"glow", "map:glow"}
    if kind == "grass":
        shown |= {"grass_height", "grass_density"}
    else:
        shown |= {"transparency", "map:opacity", "image"}
    if file_maps and not picture:
        shown.add("map_size")
    if picture:
        shown.add("picture")
    return shown


#: Names that say what a material is, in Catalan, Spanish, English, Portuguese, French, Italian and
#: German: matched as whole words or word starts in its name and its picture's file name, as
#: IngeTrazo's own finish guess does (core/finish.py). Short words must end there («mar» is the sea,
#: «Marbre» is stone). The first kind in this order that matches wins (tall grass before lawn).
_DETECT = (
    ("water", r"aig[uü]|agua|[aá]gua|water|wasser|acqua|eau(?![a-z])|piscin|pileta|pool|"
              r"(?:mar|sea|llac|lago|lake|estany|bassa|riu|r[ií]o|river|pond)(?![a-záéíóúàèòïüñç])|"
              r"oc[eé]an|estanque"),
    ("glass", r"vidr|vidre|glass|glas(?![a-z])|cristal|crystal|verre|vetro|vitral|vitrall|mampara|window[_ ]?pane"),
    ("meadow", r"(?:herba|hierba|erba|grass|gras)[_ ]*(?:alt|tall|long|high|hoch)|"
               r"(?:tall|long|high)[_ ]*grass|prat(?![a-z])|prado|prato(?![a-z])|meadow|wiese|pasto"),
    ("lawn", r"gespa|c[eé]sped|grass|lawn|herb(?:a|es)(?![a-z])|hierbas?(?![a-z])|erba(?![a-z])|rasen|"
             r"gras(?![a-z])|gazon|pelouse|relva|grama|turf"),
    ("light", r"llum(?![a-z])|luz(?![a-z])|led(?![a-z])|ne[oó]n|l[aàá]mpad|l[aá]mpara|lamp(?![a-z])|"
              r"emissi|emisi|glow|luminari|lightbox|light[_ ]?panel"),
)
_DETECT_RX = None


def detect_preset(name: str | None, picture: str | None = None):
    """The preset a material's name (or its picture's file name) says it is — water, glass,
    lawn, tall grass, or a light — or None. «Gespa», «Césped_01», «[Water Pool]», «Vidre
    finestra», «Herba alta», «LED panel»."""
    import re
    global _DETECT_RX
    if _DETECT_RX is None:
        _DETECT_RX = [(k, re.compile(r"(?:^|[^a-záéíóúàèòïüñç])(?:" + p + ")", re.IGNORECASE))
                      for k, p in _DETECT]
    for text in (name, picture):
        if not text:
            continue
        low = str(text).replace("-", "_")
        low = re.sub(r"([a-z])([A-Z])", r"\1_\2", low)          # «WaterBlue» → «Water_Blue»
        for key, rx in _DETECT_RX:
            if rx.search(low):
                return key
    return None


def detected_spec(name: str | None, picture: str | None = None) -> dict | None:
    """The render settings a material gets from its name when it has none of its own: its
    detected preset's (without the transparency, which is the model's)."""
    key = detect_preset(name, picture)
    if key is None:
        return None
    spec = {k: v for k, v in PRESETS[key][1].items() if k != "transparency"}
    spec["preset"] = key
    spec["detected"] = True
    return spec


def with_detected(scene, specs: dict | None) -> dict:
    """``specs`` plus, for each material of the model that has no settings of its own, the
    ones its name says (detected_spec): a «Gespa» grows grass, an «Aigua» gets ripples."""
    out = dict(specs or {})
    try:
        names = list(used_materials(scene))
    except Exception:  # noqa: BLE001 - an odd scene: only the specs given
        return out
    registry = getattr(scene, "materials", None) or {}
    for name in names:
        if name in out:
            continue
        mat = registry.get(name) if hasattr(registry, "get") else None
        tex = (getattr(mat, "texture", None) or {}) if mat is not None else {}
        pic = tex.get("base") or tex.get("path") or ""
        spec = detected_spec(name, pic.replace("\\", "/").rsplit("/", 1)[-1] if pic else None)
        if spec:
            out[name] = spec
    return out


def preset_label(key: str, lang: str = "en") -> str:
    names = PRESETS[key][0]
    return names.get(lang) or names["en"]


def export_name(name: str) -> str:
    """The name IngeTrazo's GLB export gives a registry material
    (formats.meshexport.export_names, without its collision suffix)."""
    base = "".join(c if c.isalnum() or c in "._-" else "_"
                   for c in name.strip()).strip("._-")
    if base and base[0].isdigit():
        base = f"m_{base}"
    return base


def _paint_name(group):
    """The material a group or component is painted WHOLE with (its own
    ``material`` paint, not its faces'), or None."""
    paint = getattr(group, "material", None)
    return paint.get("mat") if isinstance(paint, dict) and paint.get("mat") else None


_USED_CACHE = {"ref": None, "version": None, "out": None}


def material_kind(scene, name) -> str:
    """The type the render gives the material ``name``: its settings', else the one its name (or its
    picture's file name) suggests, else generic."""
    from pathlib import Path
    data = (getattr(scene, "plugin_data", None) or {}).get("render_studio") or {}
    spec = (data.get("materials") or {}).get(name)
    if isinstance(spec, dict) and spec:
        return spec.get("type", "generic")
    mat = (getattr(scene, "materials", None) or {}).get(name)
    tex = (getattr(mat, "texture", None) or {}) if mat is not None else {}
    pic = tex.get("base") or tex.get("path") or ""
    found = detected_spec(name, Path(str(pic)).name if pic else None)
    return found.get("type", "generic") if found else "generic"


def model_version(scene):
    """The document's version without Render Studio's own writes (the materials' settings, the
    look, the lights: they bump it but change no face's paint, and not the model file either; see
    ``studio_data``). None where the scene has no version."""
    v = getattr(scene, "content_version", None)
    return None if v is None else v - getattr(scene, "_rs_not_model", 0)


def used_materials(scene) -> dict:
    """name → number of places painted with it: faces over the whole model
    (loose geometry, groups and components, nested) and groups or components
    painted whole. Every material of the document's registry is listed too,
    with 0 when nothing wears it yet, so the list is never empty while the
    model has named materials.

    Remembered for the model's ``content_version`` (selecting does not change
    it): it reads every face's paint, over 588 000 faces about a second and
    a half each time the panels ask (2026-11-20)."""
    import weakref
    version = model_version(scene)
    cache = _USED_CACHE
    if (version is not None and cache["out"] is not None
            and cache["version"] == version
            and cache["ref"] is not None and cache["ref"]() is scene):
        return dict(cache["out"])
    out = _used_materials(scene)
    if version is not None:
        try:
            cache.update(ref=weakref.ref(scene), version=version, out=out)
        except TypeError:
            cache.update(ref=None, version=None, out=None)
    return dict(out)


def _used_materials(scene) -> dict:
    counts: dict = {}
    seen: set = set()

    def add(name):
        if name:
            counts[name] = counts.get(name, 0) + 1

    def mesh_faces(mesh):
        for f in getattr(mesh, "faces", ()) or ():
            add((getattr(f, "attrs", None) or {}).get("mat"))

    def walk(groups):
        for g in groups or ():
            if id(g) in seen:
                continue
            seen.add(id(g))
            add(_paint_name(g))
            add((getattr(g, "attrs", None) or {}).get("mat"))
            mesh_faces(getattr(g, "mesh", None))
            walk(getattr(g, "children", None))

    mesh_faces(getattr(scene, "mesh", None))
    walk(getattr(scene, "groups", None))
    for name in (getattr(scene, "materials", None) or {}):
        counts.setdefault(name, 0)
    return counts


def selection_material(scene):
    """The material of what is selected: a face's, a group or component's own
    paint, or the first painted face inside it (nested ones included); None
    when nothing selected wears a named material."""
    def first_in(g, seen):
        if g is None or id(g) in seen:
            return None
        seen.add(id(g))
        name = _paint_name(g)
        if name:
            return name
        for f in getattr(getattr(g, "mesh", None), "faces", ()) or ():
            name = (getattr(f, "attrs", None) or {}).get("mat")
            if name:
                return name
        for c in getattr(g, "children", None) or ():
            name = first_in(c, seen)
            if name:
                return name
        return None

    for ent in list(getattr(scene, "selection", ()) or ()):
        name = (getattr(ent, "attrs", None) or {}).get("mat")
        if name:
            return name
        owner = getattr(ent, "owner", None)
        name = first_in(ent, set()) or (first_in(owner, set()) if owner is not None else None)
        if name:
            return name
    return None


def job_block(specs: dict) -> dict:
    """The document's specs keyed by export name, for the render job."""
    out = {}
    for name, spec in (specs or {}).items():
        key = export_name(name)
        if key and spec:
            out[key] = dict(spec)
    return out
