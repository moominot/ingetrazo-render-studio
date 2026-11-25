"""The register of settings and the new model: every setting of format 1 is in it, and a document or preset read into the new model
and written back makes the SAME render job and the same outlines.
argv: <ingetrazo-src> <render-studio repo>"""
import itertools, json, os, random, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC, REPO = [os.path.abspath(a) for a in sys.argv[1:3]]
sys.path[:0] = [SRC, REPO, os.path.join(REPO, "tests")]
from pathlib import Path
from PySide6.QtWidgets import QApplication
qa = QApplication.instance() or QApplication([])
import reference_cases as R
from render_studio import look_model as M, outlines, params as P, presets, settings_store as S, user_presets

fails = []
def ok(c, w):
    print(("PASS " if c else "FAIL ") + w, flush=True)
    if not c: fails.append(w)

# -- the register is sound
ok(len(P.BY_KEY) == len(P.PARAMS), f"every key once ({len(P.PARAMS)} settings)")
ok(all(p.tab in P.TABS and p.group in P.TABS[p.tab][1] and p.group in P.GROUPS and p.kind in P.KINDS for p in P.PARAMS),
   "every setting has a known tab, group and kind")
ok(all(P.clean_value(p, P.defaults()[p.key]) == P.defaults()[p.key] for p in P.PARAMS), "every default is a valid value")
ok(all((p.kind not in ("number", "int")) or (p.lo is not None and p.hi is not None and p.lo < p.hi) for p in P.PARAMS), "numbers have limits")
ok(all(p.when == () or (p.when[0] in P.BY_KEY and all(v in P.BY_KEY[p.when[0]].choices or isinstance(v, bool) for v in p.when[1])) for p in P.PARAMS),
   "every condition names a setting and values it can have")
ok(set(P.SLIDER_KEYS.values()) == set(presets.SLIDERS), "every slider of the panel is in it")
ok(P.clean({"outline.width": 99, "surface.kind": "weird", "nothing": 1})["outline.width"] == 4.0
   and P.clean({"surface.kind": "weird"})["surface.kind"] == "real" and "nothing" not in P.clean({"nothing": 1}), "values are clamped, unknown ones dropped")
v = P.defaults()
ok(not P.applies(P.BY_KEY["surface.colour"], v) and P.applies(P.BY_KEY["surface.colour"], dict(v, **{"surface.kind": "mono"}))
   and not P.applies(P.BY_KEY["shadows.spacing"], dict(v, **{"shadows.draw": "colour"})), "a setting says when it applies")
ok(10 < len(P.simple_layout()) < len(P.PARAMS), f"the simple view is a part of it ({len(P.simple_layout())} of {len(P.PARAMS)})")

# -- the limits are the document's own
for key, name, section in (("outline.width", "width", "style"), ("shadows.spacing", "spacing", "shadows"), ("skyline.height", "height", "skyline"),
                           ("ground.offset", "offset", "ground_look"), ("fog.ground_haze", "haze", "ground_look")):
    p = P.BY_KEY[key]
    hi = S.clean({"look": "clear", section: {name: 1e9}})[section][name]
    lo = S.clean({"look": "clear", section: {name: -1e9}})[section][name]
    ok((lo, hi) == (p.lo, p.hi), f"{key}: the same limits as the document's ({lo}, {hi})")

# -- the panel's settings are all carried
panel = R.panel()
full = panel.settings_dict()
seen = M.to_v1(M.from_v1(full), full)
ok(set(S.clean(full)) == set(seen), f"the same parts as the panel saves (missing {set(S.clean(full)) - set(seen)})")
# (The values a style does not use are not part of the model; the panel today starts the sketch's and the watercolour's sliders at 0
# instead of their defaults, which the rebuilt panel is to take from the register.)
unused = ("noise", "extend", "wetness", "paper", "edges")
trim = lambda d: dict(d, style={k: v for k, v in d["style"].items() if k not in unused})
ok(trim(S.clean(full)) == trim(seen), "a fresh panel's settings come back unchanged (all that its style uses)")

# -- the same render job and the same outlines, through the real panel
work = Path(tempfile.mkdtemp())
(work / "pano.hdr").write_bytes(b"x"); (work / "sky.png").write_bytes(b"x")
cases = dict(R.CASES)
cases["pano"] = {"look": "clear", "hdri": {"path": str(work / "pano.hdr"), "rotation": 90, "brightness": 0.5, "height": 4, "light": False}}
cases["picture"] = {"look": "interior", "backdrop": {"path": str(work / "sky.png"), "fit": "stretch", "brightness": -1}}
cases["old_hatched_sketch"] = {"look": "clear", "style": {"mode": "sketch", "hatch": "cross", "hatch_spacing": 12, "color": [0.1, 0, 0]}}
cases["ground_material"] = {"look": "partly_cloudy", "ground_material": {"name": "Fusta", "tile": 1.5}, "engine": "cycles", "quality": 2}
cases["white_model_look"] = {"look": "white_model", "style": R._style()}
rng = random.Random(7)
for n in range(40):                       # and forty mixtures of every style with every kind of the rest
    cases[f"mix{n}"] = {
        "look": rng.choice(presets.ORDER), "ground": rng.random() < 0.7, "ground_shadow": rng.random() < 0.5,
        "style": R._style(mode=rng.choice(list(presets.STYLES)), width=rng.choice([0.0, 0.7, 2.0]), base=rng.random() < 0.5,
                          noise=rng.choice([0.0, 0.4, 1.0]), extend=rng.choice([0.0, 0.5]), material=rng.choice(["", "Fusta"]),
                          lux_max=rng.choice([0.0, 20000.0]), color=[rng.random() for _ in range(3)]),
        "shadows": {"draw": rng.choice(list(presets.SHADOW_DRAWS)), "spacing": rng.randint(4, 20), "angle": 30, "opacity": 0.6},
        "flat": {"color": [1, 1, 1]} if rng.random() < 0.3 else None,
        "sliders": {k: round(rng.uniform(lo, hi), 3) for k, (_l, lo, hi, _d, _u) in presets.SLIDERS.items() if rng.random() < 0.3},
    }
different = []
for name, settings in cases.items():
    direct = R.job_of(panel, settings, work / "a")[2]
    direct_lines = repr(outlines.line_style(panel.style_settings(), 270)), outlines.wanted(panel.style_settings())
    model = M.from_v1(settings)
    back = M.to_v1(model, S.clean(settings))
    again = R.job_of(panel, back, work / "a")[2]
    again_lines = repr(outlines.line_style(panel.style_settings(), 270)), outlines.wanted(panel.style_settings())
    if direct != again or direct_lines != again_lines or M.not_in_v1(model):
        different.append((name, M.not_in_v1(model), [k for k in set(direct.get("studio", {})) | set(again.get("studio", {}))
                                                      if direct.get("studio", {}).get(k) != again.get("studio", {}).get(k)]))
ok(not different, f"{len(cases)} documents: the same render job and outlines through the new model ({different[:4]})")
ok(all(M.from_v1(M.to_v1(M.from_v1(s))) == M.from_v1(s) for s in cases.values()), "…and reading it back gives the same model")

# -- what only the new model can say is named
base = P.defaults()
ok(M.not_in_v1(base) == [], "the defaults can be said in format 1")
for changes in ({"surface.kind": "mono", "finish.kind": "watercolour"}, {"outline.on": True, "outline.width": 1.0, "outline.hand": 0.5},
                {"surface.kind": "paper"}, {"surface.kind": "mono", "surface.colour": [0.2, 0.3, 0.4], "surface.keep_glass": True}):
    ok(M.not_in_v1(dict(base, **changes)) != [], f"named as beyond format 1: {changes}")

# -- every combination of the new model comes back from the document as it was
def used(m):
    """The values the picture depends on."""
    keys = [p.key for p in P.PARAMS if p.key.split(".")[0] in ("surface", "outline", "finish") or p.key == "background.paper_sky"]
    out = {k: m[k] for k in keys if P.applies(P.BY_KEY[k], m)}
    if m["surface.kind"] != "mono":
        out.pop("surface.keep_glass", None)
    if m["surface.kind"] == "lux":
        out = {k: v for k, v in out.items() if not k.startswith("finish.")}
    return out
lost = []
for surface, finish, on, hand, width, paper, glass, material, white in itertools.product(
        ("real", "mono", "paper", "lux"), ("none", "watercolour"), (False, True), (0.0, 0.7), (0.0, 1.2), (False, True), (True, False),
        ("", "Fusta"), (True, False)):
    if surface == "paper" and not paper:
        continue                                  # (the panel always puts paper behind a paper surface)
    m = dict(P.defaults(), **{"surface.kind": surface, "finish.kind": finish, "outline.on": on, "outline.hand": hand,
                              "outline.width": width, "background.paper_sky": paper, "surface.keep_glass": glass,
                              "surface.material": material, "surface.colour": list(P.WHITE) if white else [0.2, 0.3, 0.4]})
    back = M.from_v1(S.clean(M.to_v1(m)))
    a, b = used(m), used(back)
    if surface == "mono" and material:
        a.pop("surface.colour", None); b.pop("surface.colour", None)
    if a != b:
        lost.append(({k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)}, surface, finish, on, hand, width, paper, glass, material, white))
ok(not lost, f"every combination of surface, outline, paper and finish comes back as it was ({len(lost)} lost: {lost[:2]})")

# -- presets saved today are read
text = user_presets.to_file("Meu", panel.settings_dict() | {"style": R._style(mode="sketch", width=1.0)})
name, preset = user_presets.from_file(text)
ok(M.from_v1(preset)["background.paper_sky"] and M.from_v1(preset)["surface.kind"] == "mono", "a preset file of today is read into the new model")
ok(M.from_v1(None) == M.from_v1({"look": "clear"}) and M.from_v1({"look": "zzz", "style": 5})["ambient.look"] == "clear", "rubbish gives the defaults")
print("FAILED" if fails else "ALL OK"); sys.exit(1 if fails else 0)
