# Render Studio for IngeTrazo

Photographic renders from IngeTrazo: pick a look, watch it in a live preview you can zoom and
move, press **Render**, then fine-tune the picture without rendering again.

It drives the same Blender that IngeTrazo's own Render tab uses (Blender
4.2+; tested with 5.3), with IngeTrazo's scene script plus
`blender/studio_scene.py` for the look.

When IngeTrazo finds no Blender, the panel says so at the top: a path box with **Browse…** (a
macOS `Blender.app` is fine), a link to blender.org's download page and, on Linux packages
(Flatpak, Snap), the exact install command. The chosen program is asked for its version (4.2 or
newer) and saved under IngeTrazo's own key (`render/blender_path`), so the Render tab uses it too.
**Open preview…** stays off until there is one.

![Looks](docs/looks.png)

## Looks

| Look | What it does |
|---|---|
| Clear day | Physical sky, sun coloured by its height, a few clouds |
| Partly cloudy | More cloud, softer sun |
| Golden hour | Low warm sun (7°), long shadows, punchier contrast |
| Overcast | Soft sun through full cloud cover, low contrast |
| White model | Every material white (study model), neutral finish |
| Interior | Exposed for the room, window allowed to burn out; switches to **Cycles** (EEVEE can't fill a window-lit room) |
| Night | Moonlight kept dark, stars and moonlit clouds; the document's lamps glow (light bloom) |

Every look shares:
- **Automatic exposure.** A quarter-size pre-render is metered, with a
  centre-weighted average and highlights protected.
- **AgX** tone mapping with white balance.
- **Distance haze.** The ground fades into the horizon sky.
- **Albedo capped at 80 %.** Paper-white surfaces don't glow under a path tracer.
- **Finish.** A light saturation and vignette pass in Blender's compositor.
- **EEVEE gets a ground below the horizon in its world.** Its reflections
  and the light bounced off the ground then match Cycles.

## Materials

**Materials…**, on the panel or in the menu, opens a simple material
editor. The list shows the materials used in the model.
**From the selection** jumps to the material of the selected face or group.

For each material you can:
- start from a preset: matte plaster, satin paint, gloss lacquer, polished
  stone, concrete, brick, varnished or raw wood, fabric, brushed metal,
  chrome, clear or frosted glass, water, or a light panel;
- set its **type**: generic, glass, water or glowing;
- adjust **Roughness**, **Metal**, **Relief** and **Glow**, each with an optional map.

Relief comes from the material's picture when it has one (mortar joints,
wood grain), otherwise from a fine grain. With the picture, the **Relief** slider is the height of the relief, up to 3 cm from black to
white, at full strength. The picture is first turned into a smooth height map (reduced to at most
1024 px, blurred, stretched to use the whole range, inverted and given contrast if asked): used
raw, its grain became noise and a joint a pixel or two wide gave only a thin outline (0.5.x to
0.7.0 did that; 0.7.1 only made it stronger). It shows where the picture changes clearly; for
gentle changes (wood grain) raise the map's contrast or use a height map. A glowing material lights what
is around it, and the exposure meter ignores it, so it doesn't darken the
picture.

### Transparency

The **Transparency** slider (0 = opaque, up to 95 %) sets how much light the material lets
through, **in the IngeTrazo model itself**: the opacity of the registry material, of every face
that wears it (nested components included) and of every object painted whole, as one undo step.
The 3D view shows it and so does the render, because the render reads the same value (a see-through
water shows the floor below, tinted by the material's colour or picture). For **Glass** the slider
is also how much the refracting glass transmits. Choosing the Water or Glass type, or their presets,
gives a transparency to start with. (Before 0.9.0 the Water type only changed the finish, and a sea
texture painted opaque stayed opaque.) With «Change picture…» these are the only controls that edit
IngeTrazo's own material; every other setting only affects the render.

### Water

For the **Water** type, **Relief** is the height of the ripples and **Ripple size** their size,
from fine to broad waves. They follow the «easiest water in Blender» recipe: a 3-D noise (detail
16, roughness 0.442, scale 108.6 at the finest) turned into a bump (distance 0.1 at the maximum
relief) on the glossy surface, laid out in world metres so a ripple has the same size everywhere.
Fine ripples read as grain from far away; the default (0.8, about 7 waves a metre) reads as water
and makes the sun glint. Relief 0 gives a flat, mirror-like water. Materials saved before 0.8.0
keep IngeTrazo's own ripples until their settings are changed here.

### Cube preview

The material editor shows the material on a **one-metre cube**, drawn on the CPU, so it follows
the sliders instantly and needs no Blender. It uses the picture and its tile size, the colour,
the type (glass and water see-through, glowing ones with a halo) and the Roughness, Metal,
Relief and Glow sliders. It is an approximation: the maps and Blender's lighting only show in
the render.

### Change the picture, in the model

**Change picture…** in the material editor replaces the picture of the material **in the
IngeTrazo model itself**, not only in the render: every face, component and object that wears
the material changes, in the viewport too, as one undo step. Each face keeps where its texture
was placed, and a colour tint is kept over the new image. **Keep proportions** makes the tile
height follow the new image's shape. The new image is copied into IngeTrazo's texture cache and
travels with the document. It needs a material that already has a picture. This is the one
control of Render Studio that edits IngeTrazo's own material; every other setting only affects
the render.

### Maps

Each setting can vary over the surface by following a map. The setting's
slider then scales the map. A map can come from:
- **Picture (B/W)**: the material's own texture in black and white. For
  example, a wood texture's grain for its roughness and relief.
- **Image file**: a roughness, metal or height map, or a mask for where it
  glows. Relief also takes a **normal map**.

Every map can be **inverted** and given more **contrast**, and a small
preview shows what the render will read. Map files follow the picture's
own size and placement. On a material without a picture, they tile at the
**Map image size**.

![Maps](docs/maps.png)

The settings are saved in the document, one undo step per change. **Back
to automatic** returns the material to IngeTrazo's own finish. Map files
are linked by their path, not embedded in the document.

### Grass

A material of type **Grass** grows blades of grass on every face that wears it, **in the render only**
(the model stays flat). **Grass height** sets how tall they are (1–60 cm); the **Lawn** (6 cm) and
**Tall grass** (30 cm) presets start from there. In Blender they are tufts of a few bent blades
scattered by geometry nodes over the faces of that material (instanced: a lawn costs little memory),
upright, turned and sized at random; their colour is the material's picture read at each tuft's UVs,
else its colour, darker at the root. Short grass gets 260 tufts per m², taller grass fewer and bigger;
past 250 000 tufts in one render the whole lawn is thinned (the log says by how much). The job carries
it in the material's settings: `{"type": "grass", "grass_height": 0.08, "grass_density": 260}`.

**Grass density** (0.11.0) is the tufts per m², 20–800 (Lawn preset 260, Tall grass 90). The live
view grows the same grass as the render (before 0.11.0 it had a third of it). A material saved
without a density gets the old automatic one for its height. Past 600 000 tufts in one render the
whole lawn is thinned, and Blender's log says by how much.

### Recognised by the name

A material with no settings of its own whose name, or its picture's file name, says what it is gets
that preset, in the editor and in the render job (`materials.detect_preset` / `with_detected`):
**Water** (aigua, agua, água, water, wasser, eau, piscina, pool, mar, llac, lago, estany…),
**Clear glass** (vidre, vidrio, glass, glas, cristal, verre…), **Tall grass** (herba alta, hierba
alta, tall grass, prat, prado, meadow…), **Lawn** (gespa, césped, grass, herba, lawn, rasen,
pelouse…) and **Light panel** (llum, luz, LED, neon, làmpada, lámpara, emissive…). Whole words or
word starts, camel case split («WaterBlue»), short words must end there (Mar ≠ Marbre, Glas ≠
Glasur, Led ≠ Ledge). The list marks such materials ◦; the editor shows the preset with a note and
writes nothing until a setting changes (then ●). The model's transparency is left alone.

### Only what matters is shown

The editor hides the controls that do nothing for the material as it is set
(`materials.shown_controls`, which follows what `studio_scene.py` does): Metal only for Generic;
Glow for Glowing; Ripple size for Water (whose Relief is the waves' height, with no relief map);
grass height and density for Grass (no Transparency there); the Relief slider while a texture set
gives the relief and no relief map is chosen; **Map image size** only for a map file on a material
without a picture; **Change picture…** only with a picture; Invert and contrast only for a
black-and-white map; «Picture (B/W)» can't be chosen without a picture. For Glass and Water the
texture set offers only its normal map, the only one the render uses on them. The map of a hidden
setting is not saved.

### Full texture sets (normal, roughness, AO, displacement, metalness, opacity)

IngeTrazo gives a face only its colour picture. When that picture has companion maps beside it,
the render builds the full material from them by itself (Principled BSDF), read with the picture's
own UVs (same tile size and rotation). They are found, in this order:

1. A manifest next to the picture, `<picture stem>.pbr.json` (the asset panel writes it for its
   Poly Haven and ambientCG downloads):

   ```
   {"version": 1, "color": "wood_floor_diff_1k.jpg",
    "normal_gl": "...", "normal_dx": "...", "roughness": "...", "ao": "...",
    "displacement": "...", "metalness": "...", "opacity": "...",
    "arm": "...",                 # AO / roughness / metalness packed in R / G / B
    "size_m": [w, h], "source": "polyhaven|ambientcg", "id": "<asset id>"}
   ```

   Every key but `version` and `color` is optional. Files are relative to the manifest's folder
   and must stay inside it: an absolute path, a `..` or a missing file is dropped (the rest of the
   manifest still counts). Another `version`, no `color` or bad JSON: the manifest is ignored.
2. No manifest: the libraries' own file names, in the picture's folder (any of .png/.jpg/.exr/.tif):
   **Poly Haven** `<id>_diff_<res>` → `<id>_nor_gl_<res>`, `_nor_dx_`, `_rough_`, `_ao_`,
   `_disp_`, `_metal_`, `_arm_`; **ambientCG** `<id>_<res>-JPG_Color` (or `-PNG_`) → `_NormalGL`,
   `_NormalDX`, `_Roughness`, `_AmbientOcclusion`, `_Displacement`, `_Metalness`, `_Opacity`.
3. Nothing found: the picture alone, exactly as before.

A tinted picture looks for the maps of its original. The material editor shows the set: a line lists the
maps found, and the first choice of Roughness, Metal and Relief becomes «Texture set: …» with a preview
of that map; choosing another one there replaces it. In the render:
- **Normal**: the OpenGL map; else the DirectX one with its green flipped. It replaces the
  *automatic* relief guessed from the picture; a relief source chosen in the editor stays, on top.
  Without a normal map the **displacement** map is the relief (a bump, 1 cm black to white).
  True displacement is not used: it would need the model subdivided.
- **Roughness**: the map × (the editor's Roughness / 0.5); a roughness map chosen in the editor wins.
- **Metalness**: the map, with the editor's Metal as its floor; a metal map chosen in the editor wins.
- **Ambient occlusion** multiplies the colour (75 %); **opacity** drives the alpha.
- `arm` fills in whichever of AO / roughness / metalness has no map of its own.
- Glass and water take only the normal map; the white model ignores the sets.

The job carries them as `studio.pbr = {picture file name: {"normal": abs path, "normal_flip_green":
bool, "roughness": …}}` (`render_studio/pbr.py`, no Qt, no Blender); `studio_scene.py` matches
them to the imported materials by the picture's name.

![Material editor](docs/material_editor.png)

![Materials](docs/materials.png)

## 360° background (HDRI)

Any equirectangular image (.hdr, .exr, .jpg) as the world:
- **Lights the scene** (on): the image lights the model, and its sun casts
  the shadows. The look's sky and sun are replaced; its exposure and
  finish stay.
- **Lights the scene** (off): the look lights the model, and the image is
  only what the camera sees behind it.
- **Rotation** turns the image, and **Brightness** sets it in stops.
- The ground melts into the image's horizon.

Blender's own eight HDRIs (CC0, Poly Haven) are offered in the list. They
are 1K: good light, but soft behind the model. For a sharp background,
choose a 4K or larger file, for example a free one from polyhaven.com.

![HDRI](docs/hdri.png)

![Night with the document's lamps](docs/night.png)

![Interior and live adjustments](docs/interior.png)

## Panel

`Render Studio…` in the extensions menu opens the panel, in three groups:
- **Look and light** (the scene: the preview and Render both draw it): the look, and sliders for exposure
  (EV), clouds, sun, warmth, saturation and vignette, each with its value and a line saying what it does;
- **360° background** (HDRI), with rotation, brightness and "Lights the scene";
- **Final render** (only Render uses it): the engine, EEVEE (fast, about 3 s) or Cycles (best, about 5 s
  on an RTX GPU), the quality and the width.

There is no Render button in the panel: **Open preview…** opens the preview window.

![Panel](docs/panel.png)

## Preview window

One window to look at the scene and to make the picture, in three states:

- **Preview**: the live view (below), which you can zoom and move. **Render** makes the final picture with
  the panel's engine, quality and width (shown beside the buttons); **Render and save…** asks for a PNG or
  JPEG file first, renders, saves the picture exactly as rendered (no retouching) and returns to the preview.
- **Rendering**: the progress bar and **Cancel**. The live Blender is closed meanwhile. Closing the window
  does not stop the render: the picture opens when it is ready.
- **Final picture**: the render with the retouch sliders (exposure in EV, contrast, saturation, warmth,
  vignette: they change the picture instantly, nothing is rendered again), **Reset**, **Save image…**
  (what you see, PNG or JPEG) and **Back to preview**.

The panel's sliders and the retouch sliders share some names but not their effect: the panel's change
the **scene** (a new preview or render), the retouch ones only the **finished picture**; each shows its
value and what it does. Zoom: the mouse wheel zooms where the cursor is, dragging moves, a double click
goes between Fit and 100 %, keys `+` `-` `0` `1`; the zoom and place stay while live frames of other sizes
arrive (`widgets.ZoomView`). The code is in `preview.py` (window), `widgets.py` (zoom view, slider rows) and
`panel.py`.
## Live view

The **live view** (the preview window's first state) keeps one Blender open with the scene and the look loaded, and
an image follows your work. Two switches in the window, remembered between sessions:

- **Follow the camera**: while the 3D view moves, small frames (320 px, 1 sample) come one after
  another as fast as Blender renders them, each showing the camera as it is when Blender is free;
  250 ms after it stops a quick image (480 px, 1 sample) comes, then the draft (960 px, 8 samples).
  Off: the live image keeps its camera.
- **Follow changes**: an edit of the model, its textures or the materials' render settings rebuilds
  the scene in the same Blender (`{"reload": job}` on its input); the model is exported again only
  when it changed. A change that comes while the previous one is still being built waits for it.
  Off: the live scene keeps the model and materials it has; the look and sliders still apply.

The live Blender (it starts when the window opens and stops when it closes) uses EEVEE with its costliest effects off (ray tracing, fast GI, fine
shadows): the panel's **Engine** and **Quality** are for **Render**. The **Interior** look is the
exception (0.11.0): EEVEE can't fill a room lit through a window, so its live view is **Cycles**
(persistent data, GPU denoiser; 2 samples while moving, 4 for the quick image, 32 for the draft),
and the preview looks like the render. The grass is as dense as in the render. Measured on a test machine (Blender 5.3): first start about 3 s, a camera stop to the
quick image about 0.3 s, a change of look, material or model about 0.7–1 s, and 3–4 frames a second
while the camera moves. That last figure is EEVEE's fixed cost per image (about a quarter of a second
whatever its size; saving it and the compositor barely count): a smoother motion would need an
interactive viewport, which a Blender running in the background does not have. It speaks the protocol
of IngeTrazo's own «Sync with the view» (Blender in `serve` mode), extended with `reload`. **Render**
closes the live Blender first and leaves the live view off, so the draft does not cover the final image; **Back to preview** brings it back.

## Settings in the document

The panel's settings are saved in the IngeTrazo document (a moment after each change, one undo
step per pause, and only when something changed): `scene.plugin_data["render_studio"]`, saved in
the `.igz`. Tabs and reopened files show their own; undo and redo move them. The format is
meant to be read by other tools, such as IngeTrazo's own Blender render (its Render tab does not
apply them yet: that needs a change in IngeTrazo):

```
plugin_data["render_studio"] = {
  "materials": { "<material name>": { …render settings of that material… } },
  "settings": {
    "version": 1,
    "look": "clear",            # clear partly_cloudy golden_hour overcast white_model interior night
    "engine": "eevee",          # or "cycles"
    "quality": 1,               # 0 draft, 1 medium, 2 high
    "width": 1920,              # pixels; the height follows the 3D view
    "sliders": { "exposure_bias": 0.0, "clouds": 0.25, "sun_scale": 1.0,
                 "warmth": 0.0, "saturation": 1.06, "vignette": 0.16 },
    "hdri": null                # or {"path": "...", "rotation": 0..360, "brightness": stops, "light": true}
  } }
```

`render_studio/settings_store.py` reads and cleans it (unknown looks fall back, numbers are
clamped) and has no Qt dependency.

## Help

A **?** button in the panel, in the image window and in the material editor opens a help
window (with search) at the right section: how Render Studio works, every control, the looks,
the 360° background, the image adjustments, the material editor with its maps and starting
points, and a few tips.

## Releases

The packaged extension of each version is in `releases/` and tagged (`v0.9.1` → `releases/render_studio-0.9.1.zip`),
so the catalog can pin the exact file by tag and SHA-256. Unpack it in IngeTrazo's plugins folder, or install it from
**Extensions ▸ Manage extensions…**.

## Install

Copy the `render_studio` folder into IngeTrazo's plugins folder
(`%APPDATA%\IngeTrazo\plugins` on Windows), then restart IngeTrazo. It
requires Extension API 2 and a Blender that IngeTrazo can find (set in the
Render tab).

## Tests

- `tests/test_opacity_offline.py` checks the transparency in the model (reach, undo, the editor); `tests/test_opacity_e2e.py` goes IngeTrazo → GLB → real Blender and checks the floor shows through (needs `BPY_PYTHON`).
- `tests/test_water_editor_offline.py` checks the water controls of the editor.
- `tests/test_relief_bpy.py` renders a brick wall and a pool with a REAL Blender (the `bpy` module, `pip install bpy`) with and without relief and checks the height map and the difference; skipped when `bpy` is missing.
- `tests/test_cube_preview_offline.py` checks the cube preview (picture, tile, colour, polish, metal, relief, glass, glow) and its wiring in the editor.
- `tests/test_live_blender_offline.py` runs the live view with a real Blender (house on a lawn) and times the
  quick image, the draft, frames while orbiting, a material edit, edits in a row, a change of look (same Blender,
  model kept) and of the model.
- `tests/test_live_offline.py` runs the live view against a stand-in for Blender (`tests/fake_blender.py`, same protocol): first draft, camera moves, model/look changes, a final render, switching off.
- `tests/test_doc_settings_offline.py` checks the settings kept in the document.
- `tests/test_materials_list_offline.py` checks the material list (faces, groups painted whole, nested, registry).
- `tests/test_texture_swap_offline.py` changes a material's picture on loose faces, nested
  components and painted objects, and checks placement, proportions, tint, undo and save/reopen.
- `tests/test_help_offline.py` checks the help against the code.
- `tests/test_grass_sets_editor_offline.py` checks the Grass type in the editor (height and density sliders,
  presets, cube preview) and how the editor shows a picture's texture set.
- `tests/test_preview_offline.py` checks the preview window without Blender: zoom and pan (wheel, drag, double click, keys,
  kept across frames of other sizes), its three states and what each shows, the retouch sliders, and the panel's value
  labels and hints.
- `tests/test_workflow_blender_offline.py` runs the workflow with a REAL Blender: preview, Render, retouch and save, Back to
  preview, Render and save… (PNG, JPEG, cancelled dialog), Cancel, and closing the window during a render.
- `tests/test_detect_offline.py` checks the names recognised (and the look-alikes that are not), the editor's
  ◦ mark and note, and the render job.
- `tests/test_shown_controls_offline.py` checks which controls the editor shows for each type, picture and
  texture set, and the panel's check of a Blender chosen by hand.
- `tests/test_grass_blender.py` renders a lawn with a real Blender (EEVEE and Cycles): the blades grow on the lawn
  only, take its picture's colour where they stand, follow the height slider and leave the model's mesh alone.
- `tests/test_pbr_offline.py` (plain Python) finds texture sets by manifest and by the two libraries' names,
  refuses manifest entries that leave the picture's folder, and collects the model's pictures.
- `tests/test_pbr_job_offline.py` writes a job with the panel's own code and IngeTrazo's own GLB (a set on a
  loose face and one on a tinted, painted group); given `blender.exe` it renders it and checks Blender found both.
- `tests/test_pbr_blender.py` runs in Blender (`blender -b --factory-startup --python tests/test_pbr_blender.py --
  <repo> <render_scene.py> <out dir>`): two small sets (Poly Haven and ambientCG style) rendered with and without
  them in EEVEE and Cycles, the nodes checked, and a DirectX normal map shown to render like the OpenGL one.
- `tests/test_offline.py` writes a job with the panel's own code and
  renders it with Blender. It then adjusts and saves the image in the image
  window, without IngeTrazo running.
- `selftest.py` runs inside a real, separate IngeTrazo. Start it with
  `RENDER_STUDIO_SELFTEST=<config.json> ingetrazo --new-window`. It
  renders every look through the Render button code, saves the pictures
  and quits without saving.

## Licence

GPL-3.0-or-later, like IngeTrazo.
