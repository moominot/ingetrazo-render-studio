# SPDX-License-Identifier: GPL-3.0-or-later
"""Render materials: how each of the document's named materials looks in a
render, beyond its colour or picture — Enscape's material editor, simple.

A material's render settings live in the document (the extension's
document data, ``{"materials": {name: spec}}``), so they are saved with the
``.igz`` and undone like any edit. A spec::

    {"type": "generic" | "glass" | "water" | "glow",
     "roughness": 0..1, "metallic": 0..1, "bump": 0..1,
     "glow": nits-ish 0..50, "coat": 0..1, "sheen": 0..1}

Missing keys keep what IngeTrazo's own finish gives. In the render job they
are keyed by the material's EXPORT name (what the GLB, and so Blender,
calls it), which :func:`export_name` computes as IngeTrazo does.
"""
from __future__ import annotations

TYPES = ("generic", "glass", "water", "glow")
TYPE_LABELS = {"generic": "Generic", "glass": "Glass", "water": "Water", "glow": "Glowing"}

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
              {"type": "glass", "roughness": 0.0, "metallic": 0.0, "bump": 0.0}),
    "glass_frosted": ({"en": "Frosted glass", "ca": "Vidre glaçat", "es": "Vidrio esmerilado"},
                      {"type": "glass", "roughness": 0.35, "metallic": 0.0, "bump": 0.0}),
    "water": ({"en": "Water", "ca": "Aigua", "es": "Agua"},
              {"type": "water", "roughness": 0.02, "metallic": 0.0, "bump": 0.0}),
    "light": ({"en": "Light panel (glows)", "ca": "Panell de llum (brilla)", "es": "Panel de luz (brilla)"},
              {"type": "glow", "roughness": 0.5, "metallic": 0.0, "bump": 0.0, "glow": 12.0}),
}

#: What an untouched material shows in the editor (IngeTrazo's finish rules).
DEFAULT = {"type": "generic", "roughness": 0.5, "metallic": 0.0, "bump": 0.0, "glow": 0.0}


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


def used_materials(scene) -> dict:
    """name → number of places painted with it: faces over the whole model
    (loose geometry, groups and components, nested) and groups or components
    painted whole. Every material of the document's registry is listed too,
    with 0 when nothing wears it yet, so the list is never empty while the
    model has named materials."""
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
