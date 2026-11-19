# SPDX-License-Identifier: GPL-3.0-or-later
"""The text behind the «?» buttons of Render Studio (panel, image window and
material editor). The looks and the material presets are listed from the
same data the panel uses, and a test checks that each one has a
description, so the help cannot fall behind the code."""
from __future__ import annotations

from html import escape

from . import materials as M
from . import presets

LOOKS = {
    "clear": "Physical sky, the sun coloured by its height, a few clouds. The all-round daylight look.",
    "partly_cloudy": "More cloud and a softer sun.",
    "golden_hour": "A low, warm sun (7° above the horizon): long shadows and more contrast.",
    "overcast": "Soft light through full cloud cover: low contrast, no hard shadows.",
    "white_model": "Every material white, a neutral finish: for studying volumes and light, as a model.",
    "interior": "Exposed for the room; the window may burn out, as in a photograph. It switches to "
                "<b>Cycles</b>, because EEVEE cannot fill a room that is lit through a window.",
    "night": "Dark moonlight, stars and moonlit clouds. The document's lamps glow (light bloom).",
}

PRESET_NOTES = {
    "plaster": "very matte, a little grain", "paint": "satin finish", "lacquer": "glossy, with a clear coat",
    "stone": "polished, a faint coat", "concrete": "matte with a marked grain",
    "brick": "rough, strong relief", "wood": "varnished: a soft sheen over the grain",
    "wood_raw": "natural, matte", "fabric": "very matte with a soft edge sheen",
    "metal_brushed": "metal, half polished", "chrome": "metal, almost a mirror",
    "glass": "clear and transparent", "glass_frosted": "transparent but diffuse",
    "water": "reflective and transparent surface", "light": "a panel that shines by itself",
}


def _looks() -> str:
    rows = "".join(f"<tr><td valign='top'><b>{escape(presets.label(k))}</b></td><td>{LOOKS[k]}</td></tr>"
                   for k in presets.ORDER)
    return f"<table cellspacing='0' cellpadding='3' width='100%'>{rows}</table>"


def _material_presets() -> str:
    rows = "".join(f"<tr><td valign='top'><b>{escape(M.preset_label(k))}</b></td><td>{PRESET_NOTES[k]}</td></tr>"
                   for k in M.PRESETS)
    return f"<table cellspacing='0' cellpadding='3' width='100%'>{rows}</table>"


def html() -> str:
    return f"""
<a name="panel"></a>
<h3>Render Studio: how it works</h3>
<p>Render Studio makes a realistic picture of your model with one click. You choose a <b>look</b> (the light and
the mood), press <b>Render</b>, and then fine-tune the finished image <i>without rendering again</i>. It uses
Blender in the background: IngeTrazo has to be able to find it (set its path in IngeTrazo's Render tab first).</p>

<h4>In five steps</h4>
<ol>
<li>Point the 3D view at what you want to render: the picture takes the <b>current camera</b> and its proportions.</li>
<li>Choose a <b>Look</b>, the <b>Engine</b>, the <b>Quality</b> and the <b>Width</b>.</li>
<li>Optionally move the sliders, add a 360° background or adjust the <b>Materials…</b>.</li>
<li>Press <b>Render</b>. The bar shows the progress; the image opens in its own window.</li>
<li>In that window adjust the exposure, contrast, saturation, warmth and vignette instantly, and <b>Save image…</b>.</li>
</ol>

<h4>The panel</h4>
<table cellspacing='0' cellpadding='3' width='100%'>
<tr><td valign='top'><b>Look</b></td><td>The light and mood: see the list below. Changing it puts that look's own
values into the sliders it sets.</td></tr>
<tr><td valign='top'><b>Engine</b></td><td><b>EEVEE</b> is fast (about 3 seconds). <b>Cycles</b> gives the best
quality (about 5 seconds on an RTX graphics card, slower without one), with truer light bouncing.</td></tr>
<tr><td valign='top'><b>Quality</b></td><td>Draft, Medium or High: the number of samples. EEVEE uses 16 / 64 / 128 and
Cycles 32 / 128 / 512. More samples mean less noise and a slower render. Use Draft while you adjust and High for the
final picture.</td></tr>
<tr><td valign='top'><b>Width</b></td><td>The picture's width in pixels (320 to 7680). The height follows the
proportions of the 3D view.</td></tr>
<tr><td valign='top'><b>Exposure</b></td><td>How bright the picture is, in stops (EV) from -3 to +3, on top of the
automatic exposure that every look applies. 0 is what the look meters.</td></tr>
<tr><td valign='top'><b>Clouds</b></td><td>Cloud cover, 0 to 100 %. Not available while a 360° background lights
the scene (its own sky replaces the look's).</td></tr>
<tr><td valign='top'><b>Sun</b></td><td>The sun's strength as a multiple of the look's: 0 none, 1 as the look has
it, up to 2. Not available while a 360° background lights the scene.</td></tr>
<tr><td valign='top'><b>Warmth</b></td><td>Colour of the light, from cool and bluish (-1) to warm and yellowish (+1).</td></tr>
<tr><td valign='top'><b>Saturation</b></td><td>Intensity of the colours: 0 is black and white, 1.6 is vivid.</td></tr>
<tr><td valign='top'><b>Vignette</b></td><td>Darkens the corners of the picture to draw the eye to the centre.</td></tr>
<tr><td valign='top'><b>Materials…</b></td><td>Opens the material editor (see below).</td></tr>
<tr><td valign='top'><b>Live view</b></td><td>Keeps Blender open with your scene and look loaded: a <b>draft</b> image
(small, few samples) follows the 3D view. Move the camera and stop: after a moment the image updates. Change the
model, the look, a slider, the 360° background or a material setting and the scene is loaded into Blender again
(it takes a few seconds). Press <b>Render</b> for the final image: the live Blender is closed first and the live view stays
off afterwards, so the draft does not draw over your picture; tick the box again to bring it back.</td></tr>
<tr><td valign='top'><b>Render</b></td><td>Starts the render. It is disabled while one is running. The line below the
bar says what is happening, or why it could not start (for example, Blender was not found).</td></tr>
</table>

<h4>Settings are saved in the document</h4>
<p>The look, engine, quality, width, sliders and 360° background are kept <b>inside the IngeTrazo document</b>
(next to the materials' render settings), a moment after each change, one undo step per pause. Save the drawing and
they come back with it; another tab or file shows its own. Undo and redo move them too. The format is public
(see the README), so other tools that read the document can use it.</p>

<h4>The looks</h4>
{_looks()}
<p>Every look shares: <b>automatic exposure</b> (a small pre-render is metered, highlights protected), <b>AgX</b> tone
mapping with white balance, a <b>distance haze</b> that fades the ground into the horizon, paper-white surfaces
capped at 80 % so they do not glow, and a light finish of saturation and vignette.</p>

<a name="hdri"></a>
<h4>360° background (HDRI)</h4>
<p>Any equirectangular 360° image (.hdr, .exr, .jpg) can be the world around the model. Choose <b>None</b>, one of
Blender's own eight (free, 1K), or <b>Choose a file…</b> (the last ones you used are remembered).</p>
<table cellspacing='0' cellpadding='3' width='100%'>
<tr><td valign='top'><b>Lights the scene</b></td><td><b>On</b>: the image lights the model and its sun casts the shadows;
the look's sky and sun are replaced (its exposure and finish stay). <b>Off</b>: the look lights the model and the image
is only what the camera sees behind it.</td></tr>
<tr><td valign='top'><b>Rotation</b></td><td>Turns the image about the vertical, 0 to 360°: use it to put the sun or a
view where you want it.</td></tr>
<tr><td valign='top'><b>Brightness</b></td><td>The image's brightness in stops (-3 to +3), against the lamps and the look's
light.</td></tr>
</table>
<p>Blender's own images are 1K: good light, but soft behind the model. For a sharp background pick a 4K or larger
file, for example a free one from polyhaven.com. The ground melts into the image's horizon.</p>

<a name="image"></a>
<h4>The image window</h4>
<p>The finished picture opens in its own window, fitted to its size. The sliders change the <b>picture</b>, instantly,
without rendering again, and what you see is what you save.</p>
<table cellspacing='0' cellpadding='3' width='100%'>
<tr><td valign='top'><b>Exposure (EV)</b></td><td>-2 to +2 stops; highlights soften instead of clipping.</td></tr>
<tr><td valign='top'><b>Contrast</b></td><td>0.6 flat to 1.6 punchy; 1 is as rendered.</td></tr>
<tr><td valign='top'><b>Saturation</b></td><td>0 black and white to 1.8; 1 is as rendered.</td></tr>
<tr><td valign='top'><b>Warmth</b></td><td>-1 cooler to +1 warmer.</td></tr>
<tr><td valign='top'><b>Vignette</b></td><td>0 to 0.8, darkens the corners.</td></tr>
<tr><td valign='top'><b>Reset</b></td><td>Puts every slider back to neutral.</td></tr>
<tr><td valign='top'><b>Save image…</b></td><td>Saves the adjusted picture as PNG or JPEG.</td></tr>
</table>

<a name="materials"></a>
<h3>The material editor</h3>
<p>Controls how each material of the model <b>renders</b>, as Enscape's material editor does. The list shows the
materials used in the model (hover one for its number of faces). <b>From the selection</b> jumps to the material of the
selected face or group. Changes apply to the <b>next render</b>, are saved in the document, and each one is an undo step.</p>
<table cellspacing='0' cellpadding='3' width='100%'>
<tr><td valign='top'><b>Cube preview</b></td><td>At the top, a quick preview of the material on a one-metre cube. It follows
the picture (and its tile size), the colour, the <b>type</b> (glass and water are see-through, glowing ones get a halo) and
the <b>Roughness</b>, <b>Metal</b>, <b>Relief</b> and <b>Glow</b> sliders, instantly and without Blender. It is only an idea of the
look: the <b>maps</b> and Blender's lighting show only in the render.</td></tr>
<tr><td valign='top'><b>Change picture…</b></td><td>Replaces the material's picture <b>in the model itself</b>, not only in
the render: the viewport changes too, on every face, component and object that wears the material, as <b>one undo
step</b> (this is the one control here that edits IngeTrazo's own material). Each face keeps where its texture was
placed, and a colour tint is kept over the new image. <b>Keep proportions</b> makes the tile height follow the new
image's shape (the tile width stays); off, the tile size stays and a different shape is stretched. The material needs
a picture already; paint it with a texture first if it has only a colour. The image is copied into IngeTrazo's texture
cache and travels with the document when you save.</td></tr>
<tr><td valign='top'><b>Start from</b></td><td>A ready-made starting point; then adjust it. See the list below.</td></tr>
<tr><td valign='top'><b>Type</b></td><td><b>Generic</b> (opaque), <b>Glass</b> (transparent), <b>Water</b>, or
<b>Glowing</b> (it shines by itself and lights what is around it; the exposure meter ignores it so it does not darken the
picture).</td></tr>
<tr><td valign='top'><b>Roughness</b></td><td>0 is a mirror-like polish, 1 fully matte.</td></tr>
<tr><td valign='top'><b>Metal</b></td><td>1 for metals: the reflection takes the material's colour.</td></tr>
<tr><td valign='top'><b>Relief</b></td><td>How strongly the surface looks raised. Automatic: from the light and dark of the
material's picture when it has one (mortar joints, wood grain), otherwise a fine grain. With the picture, the slider is the
<b>height</b> of the relief (0 to 2.5 cm from black to white). It shows where the picture changes sharply (joints, edges), and
barely where it changes gently: for that, raise the map's <b>Contrast</b>, or use a <b>height map file</b>.</td></tr>
<tr><td valign='top'><b>Glow</b></td><td>0 to 50: how brightly it shines (type Glowing): screens, light panels.</td></tr>
<tr><td valign='top'><b>Map image size</b></td><td>How big one image of a map file is on the model, in metres. Used when
the material has no picture of its own; with a picture, the maps follow its size and placement.</td></tr>
<tr><td valign='top'><b>Back to automatic</b></td><td>Forgets these settings: IngeTrazo's own finish for the material.</td></tr>
</table>

<h4>Maps</h4>
<p>Under each setting, a <b>map</b> makes it vary over the surface; the slider above then scales the map.</p>
<ul>
<li><b>Picture (B/W)</b>: the material's own texture in black and white (a wood's grain for its roughness and relief).</li>
<li><b>Image file…</b>: a roughness or metal map, or a mask of where it glows (png, jpg, tif, bmp, exr, hdr, tga).</li>
<li>For <b>Relief</b>: <b>Automatic</b>, <b>Fine grain</b>, <b>Picture</b>, a <b>Height map file</b> or a <b>Normal map file</b>.</li>
<li><b>Invert</b>: white becomes black, for a picture whose dark parts should be the rough, raised or glowing ones.</li>
<li><b>Contrast</b> slider: 0 the map as it is, 100 pure black or white.</li>
<li>The small <b>preview</b> shows what the render will read. A material without a picture ignores a Picture map.</li>
</ul>
<p>Map files are linked by their <b>path</b>, not embedded in the document: keep them where they are.</p>

<h4>Starting points</h4>
{_material_presets()}

<h4>Tips</h4>
<ul>
<li>Try ideas in <b>Draft</b> with EEVEE; render the final picture in <b>High</b>, with Cycles for interiors.</li>
<li>For an interior, use the <b>Interior</b> look: it switches to Cycles by itself.</li>
<li>For a night picture with lamps, make the lamp material <b>Glowing</b>.</li>
<li>If the picture is too dark or bright, change <b>Exposure</b> in the panel (it re-meters) or in the image window (instant).</li>
</ul>
"""
