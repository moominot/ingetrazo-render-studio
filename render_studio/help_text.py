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
    "night": "Dark moonlight, stars and moonlit clouds. The lights of the Lights tab glow (light bloom).",
}

PRESET_NOTES = {
    "plaster": "very matte, a little grain", "paint": "satin finish", "lacquer": "glossy, with a clear coat",
    "stone": "polished, a faint coat", "concrete": "matte with a marked grain",
    "brick": "rough, strong relief", "wood": "varnished: a soft sheen over the grain",
    "wood_raw": "natural, matte", "fabric": "very matte with a soft edge sheen",
    "metal_brushed": "metal, half polished", "chrome": "metal, almost a mirror",
    "glass": "clear and transparent", "glass_frosted": "transparent but diffuse",
    "water": "reflective and transparent surface", "light": "a panel that shines by itself",
    "lawn": "short mown grass, 6 cm", "meadow": "long, uncut grass, 30 cm",
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
<p>Render Studio makes a realistic picture of your model. You choose a <b>look</b> (the light and
the mood), watch it in a live <b>preview</b>, press <b>Render</b>, and then fine-tune the finished image <i>without rendering again</i>. It uses
Blender (free, 4.2 or newer) in the background. When IngeTrazo can't find one, the panel says so at the top: choose
the Blender program there (type its path or <b>Browse…</b>; on a Mac the Blender app itself), or follow the link to
download it from blender.org, install it and choose it. The path is checked (it must be Blender 4.2 or newer) and kept
where IngeTrazo's Render tab keeps it, so both use the same Blender.</p>

<h4>In four steps</h4>
<ol>
<li>Choose a <b>Look</b> and move the sliders (the scene), and set the <b>Engine</b>, <b>Quality</b> and <b>Width</b> of the final render.</li>
<li>Press <b>Open preview…</b>: a window with a <b>live preview</b> of the 3D view that you can zoom and move.</li>
<li>Press <b>Render</b> for the final picture. Then the retouch sliders and <b>Save image…</b> appear. Or press
<b>Render and save…</b> to choose a file and get the picture saved straight away, with no retouching.</li>
<li>In the retouch tools, adjust the picture instantly and <b>Save image…</b>; <b>Back to preview</b> returns to the live view.</li>
</ol>

<h4>Two kinds of sliders</h4>
<p>Some names appear twice (exposure, saturation, warmth, vignette) because they do two different things:
the <b>panel's</b> sliders change the <b>scene</b> (the light, the sky), so the preview and Render both draw them, and
a change makes the preview update; the preview window's <b>retouch</b> sliders change the <b>finished picture</b> only,
instantly, without rendering again. Every slider shows its value and a line saying what it does.</p>

<h4>The panel</h4>
<p>Three groups: <b>Look and light</b> (the scene), <b>360° background</b> and <b>Final render</b> (only Render uses
the engine, quality and width; the preview is always a quick draft).</p>
<table cellspacing='0' cellpadding='3' width='100%'>
<tr><td valign='top'><b>Look</b></td><td>The light and mood: see the list below. Changing it puts that look's own
values into the sliders it sets.</td></tr>
<tr><td valign='top'><b>Exposure</b></td><td>How bright the render is, in stops (EV) from -3 to +3, on top of the
automatic exposure that every look applies. 0 is what the look meters.</td></tr>
<tr><td valign='top'><b>Clouds</b></td><td>Cloud cover, 0 to 100 %. Not available while a 360° background lights
the scene (its own sky replaces the look's).</td></tr>
<tr><td valign='top'><b>Sun</b></td><td>The sun's strength as a multiple of the look's: 0 none, 1 as the look has
it, up to 2. Not available while a 360° background lights the scene.</td></tr>
<tr><td valign='top'><b>Warmth</b></td><td>Colour of the light, from cool and bluish (-1) to warm and yellowish (+1).</td></tr>
<tr><td valign='top'><b>Saturation</b></td><td>Intensity of the colours in the render: 0 is black and white, 1.6 is vivid.</td></tr>
<tr><td valign='top'><b>Vignette</b></td><td>Darkens the corners of the render to draw the eye to the centre.</td></tr>
<tr><td valign='top'><b>Engine</b></td><td><b>EEVEE</b> is fast (about 3 seconds). <b>Cycles</b> gives the best
quality (about 5 seconds on an RTX graphics card, slower without one), with truer light bouncing.</td></tr>
<tr><td valign='top'><b>Quality</b></td><td>Draft, Medium or High: the number of samples. EEVEE uses 16 / 64 / 128 and
Cycles 32 / 128 / 512. More samples mean less noise and a slower render. Use Draft while you adjust and High for the
final picture.</td></tr>
<tr><td valign='top'><b>Width</b></td><td>The picture's width in pixels (320 to 7680). The height follows the
proportions of the 3D view.</td></tr>
<tr><td valign='top'><b>Materials…</b></td><td>Opens the material editor (see below).</td></tr>
<tr><td valign='top'><b>Open preview…</b></td><td>Opens the preview window (see below). The line under it says what is
happening, or why it could not start (for example, Blender was not found).</td></tr>
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

<a name="lights"></a>
<h4>Lights</h4>
<p>The <b>Lights</b> tab of the panel places lights for the render, of the four kinds Blender has. They are drawn in
the 3D view (a bulb, a spot's cone, an area light's outline and the way it faces, a sun's rays), in their colour,
grey when off; <b>Show in the 3D view</b> hides them. Click one with the Select tool to choose it; Supr deletes it.</p>
<table cellspacing='0' cellpadding='3' width='100%'>
<tr><td valign='top'><b>Point light</b></td><td>A bulb that lights all round. <b>Bulb size</b>: bigger, softer shadows.</td></tr>
<tr><td valign='top'><b>Spot</b></td><td>A cone of light: <b>Beam angle</b> and <b>Soft edge</b> (0 a hard edge, 1 it fades
from the centre). Its lumens go into its cone: a narrow spot is brighter in its beam.</td></tr>
<tr><td valign='top'><b>Area light</b></td><td>A glowing square, rectangle, disc or ellipse: an LED panel, a tube, a strip,
a window's light. <b>Width</b>, <b>Length</b>, <b>Turn</b> about the way it faces, <b>Spread</b> (180° all over, less like
a louvre; Cycles only).</td></tr>
<tr><td valign='top'><b>Sun</b></td><td>Parallel light from far away, in W/m²: a second sun, moonlight. <b>Disc</b>: bigger,
softer shadows. Added over the model at once (it has no place, only a direction).</td></tr>
</table>
<p><b>Adding.</b> <b>+ Point</b>, <b>+ Spot</b>, <b>+ Area</b>, or <b>Add a ready-made light…</b> (a candle, bulbs,
a downlight, a track spot, a street lamp, a floodlight, an LED panel, a fluorescent tube, an LED strip, a window fill,
a ceiling disc, moonlight), then a click in the 3D view, snapped like any tool. On a face, a bulb sits a hand away from
it, and a spot or an area light shines away from it: a downlight clicked on a ceiling hangs under it and shines down,
a panel clicked on a wall lies on it. In the air, they shine down. Esc cancels.</p>
<p><b>On an object.</b> With <b>On the object clicked</b>, the light goes on the group or component whose face you
click: moving, turning or copying the object takes its light along; every copy of a component has its own. With
<b>Every copy of the component</b> a change (power, colour, beam…) reaches the light on every copy, each where it is;
moving it inside the object moves it in every copy. <b>Put on selected object</b> and <b>Free it</b> move a light
on and off an object without moving it. A light on a hidden object, or on a hidden tag, does not light the render.</p>
<p><b>Power</b> in <b>lumens</b>, as a lamp's box says, or in Blender's own <b>W</b> (radiant power, not a bulb's
electrical watts); switching keeps the brightness. Lumens become Blender watts at 381 lm/W (Blender's manual puts an
800 lm bulb at 2.1 W): a starting point, not a photometric truth. The automatic exposure still sets the picture's
brightness, so what counts most is how the lights compare. <b>Colour</b>: a temperature, from a candle (1000 K) to a blue
sky (12 000 K), or a colour of your own (<b>…</b>). <b>Aim</b>: a heading (0° north, 90° east) and a tilt below the
horizon (90° straight down), or <b>Aim…</b> and a click on the point to look at. <b>Place</b>: X, Y, Z, or <b>Move…</b>
and a click. <b>Casts shadows</b> can be turned off for a fill light.</p>
<p><b>IES profile</b> (point lights and spots): a manufacturer's photometric file gives the light its real shape (the
scallops of a downlight on a wall). The power set here stays the total; the profile only shapes it. Only <b>Cycles</b>
reads it: EEVEE lights the same lamp evenly.</p>
<p><b>The Render tab's lights.</b> The point lights and spots placed in IngeTrazo's own Render tab are listed too,
dashed in the 3D view, and both renders use them. Here only what that tab knows can change (place, aim, power,
colour, beam); <b>Make it a Render Studio light</b> moves one here, with every setting (the Render tab then no
longer renders it).</p>
<p>The lights are saved in the document (free ones in its data, the others on their objects); each change is one undo
step. The preview follows them.</p>

<a name="sun"></a>
<h4>Sun</h4>
<p>The <b>Sun</b> tab sets where the model is and the date and hour of the sun. They are IngeTrazo's own (the
Shadows panel's date and hour, the model's location and north), so the shadows of the 3D view, the Render tab and
Render Studio always show the same sun. Each change is one undo step.</p>
<table cellspacing='0' cellpadding='3' width='100%'>
<tr><td valign='top'><b>Latitude, longitude</b></td><td>Typed, or <b>Map…</b> to choose the place on a map. It
becomes the model's location: the map and the terrain follow it too. Without one, the sun stands at IngeTrazo's
default place.</td></tr>
<tr><td valign='top'><b>North</b></td><td>Where true north lies, clockwise from the green axis. The shadows turn;
the model does not move.</td></tr>
<tr><td valign='top'><b>Date</b></td><td>Day and month; <b>Spring</b>, <b>Summer</b>, <b>Autumn</b> and <b>Winter</b> give the equinoxes and solstices as
the site lives them (summer is June in the north, December in the south).</td></tr>
<tr><td valign='top'><b>Hour</b></td><td>The slider and the box; <b>Morning</b> (an hour after sunrise), <b>Noon</b> (solar
noon) and <b>Evening</b> (an hour before sunset) jump there. Daylight shows the hours the sun is up that day.</td></tr>
<tr><td valign='top'><b>Time zone</b></td><td>The clock the hour is read on: from the longitude (solar time), or a real
zone (summer time included) to match a watch.</td></tr>
<tr><td valign='top'><b>Shadows in the 3D view</b></td><td>IngeTrazo's own sun shadows in the model, with this date
and hour.</td></tr>
</table>
<p><b>The sun then</b> says how high it is, where it comes from and how long the shadows are. Some looks change it:
<b>Golden hour</b> lowers it to 7° (same compass direction), <b>Overcast</b> and <b>Night</b> have none, and a 360°
background that lights the scene brings its own.</p>

<a name="output"></a>
<h4>Output</h4>
<p>The <b>Output</b> tab sets the final picture's size and its file. They are saved in the document.</p>
<table cellspacing='0' cellpadding='3' width='100%'>
<tr><td valign='top'><b>Size</b></td><td><b>Same shape as the 3D view</b> (a width; the height follows the view), a
ready size (HD, Full HD, QHD, 4K UHD, square, portrait 4:5, vertical 9:16, A4, A3, A2 and A1 at the print resolution)
or <b>Custom</b>. Typing a width or a height makes it Custom; <b>Keep proportions</b> changes the other with it;
<b>⇄</b> turns it between landscape and portrait. The preview frames the same picture: the view's height is kept,
its sides change.</td></tr>
<tr><td valign='top'><b>Print resolution</b></td><td>Dots per inch: the paper sizes are worked out at it, and the line
under the size says how big a print is.</td></tr>
<tr><td valign='top'><b>Format</b></td><td><b>PNG</b> and <b>JPEG</b> (with its quality) keep the preview window's
retouching. <b>PNG, 16 bits</b>, <b>TIFF, 16 bits</b> and <b>OpenEXR</b> (32-bit float, linear light, for compositing)
keep more of the light for editing elsewhere; they are saved as Blender wrote them, and Save image… offers them
beside the retouched PNG and JPEG.</td></tr>
<tr><td valign='top'><b>Transparent sky</b></td><td>The sky is left transparent (the ground and the model stay), to
put another sky behind it; the exposure is still measured with the sky. Not for JPEG. The preview window shows it over
a checkerboard.</td></tr>
<tr><td valign='top'><b>Save every render</b></td><td>Each final render is also saved in a folder of this computer,
named from {{document}}, {{look}} and {{date}}.</td></tr>
</table>

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
<h4>The preview window</h4>
<p>One window to look at the scene and to make the picture. It has three states:</p>
<table cellspacing='0' cellpadding='3' width='100%'>
<tr><td valign='top'><b>Preview</b></td><td>The live view: Blender stays open with your scene and look, and an image follows your
work. It uses EEVEE with its slowest effects off, whatever the <b>Engine</b> and <b>Quality</b> say (those are for Render),
except with the <b>Interior</b> look: EEVEE can't fill a room lit through a window, so there the preview uses <b>Cycles</b> (a
few samples, denoised; best with a graphics card) and looks like the render. The grass is as dense as in the render. The
first start takes a few seconds; after that everything happens in the same Blender. Closing the window stops it.
<br><b>Follow the camera</b>: while you orbit or walk, small rough frames keep coming (three or four a second, as fast as
Blender renders them); stop, and a <b>quick</b> image comes, then a cleaner <b>draft</b>. Off: the image keeps the camera
it had, so you can look elsewhere in the 3D view while watching one view change.
<br><b>Follow changes</b>: an edit of the model, of a texture or of a material's render settings shows by itself, in about
a second (the scene is rebuilt in the same Blender; the model is exported again only when it changed). Off: the preview
keeps the model and materials it had while you work; the look and the panel's sliders still apply. Tick it again to bring
your edits in.
<br><b>Render</b> makes the final picture with the panel's engine, quality and width (shown beside the buttons).
<b>Render and save…</b> asks for a file (PNG or JPEG) first, makes the picture, saves it exactly as rendered and goes back to
the preview.</td></tr>
<tr><td valign='top'><b>Rendering</b></td><td>The progress bar and <b>Cancel</b>. The live Blender is closed meanwhile. If you close the
window the render goes on, and the picture opens when it is ready.</td></tr>
<tr><td valign='top'><b>Final picture</b></td><td>The finished render, with the retouch sliders below it; they change the <b>picture</b>
instantly, without rendering again, and what you see is what you save. The live view stays off so it does not draw over it;
<b>Back to preview</b> brings it back.</td></tr>
</table>
<p><b>Zoom and move</b> (preview and final picture): the mouse wheel zooms where the cursor is, dragging moves the picture, a
double click goes between <b>Fit</b> and <b>100 %</b> (one picture pixel per screen pixel); the keys <b>+</b> and <b>-</b> zoom,
<b>0</b> fits and <b>1</b> is 100 %. The zoom and place stay while new preview frames arrive.</p>
<p><b>Retouch sliders</b> (final picture only):</p>
<table cellspacing='0' cellpadding='3' width='100%'>
<tr><td valign='top'><b>Exposure (EV)</b></td><td>-2 to +2 stops; highlights soften instead of clipping.</td></tr>
<tr><td valign='top'><b>Contrast</b></td><td>0.6 flat to 1.6 punchy; 1 is as rendered.</td></tr>
<tr><td valign='top'><b>Saturation</b></td><td>0 black and white to 1.8; 1 is as rendered.</td></tr>
<tr><td valign='top'><b>Warmth</b></td><td>-1 cooler to +1 warmer.</td></tr>
<tr><td valign='top'><b>Vignette</b></td><td>0 to 0.8, darkens the corners.</td></tr>
<tr><td valign='top'><b>Reset</b></td><td>Puts every slider back to neutral.</td></tr>
<tr><td valign='top'><b>Save image…</b></td><td>Saves the retouched picture as PNG or JPEG.</td></tr>
<tr><td valign='top'><b>Back to preview</b></td><td>Returns to the live view to change the scene and render again.</td></tr>
</table>
<a name="materials"></a>
<h3>The material editor</h3>
<p>Controls how each material of the model <b>renders</b>, in a few simple settings. The list shows the
materials used in the model (hover one for its number of faces). <b>From the selection</b> jumps to the material of the
selected face or group. Changes apply to the <b>next render</b>, are saved in the document, and each one is an undo step.
The editor shows only the settings that change the render of the material as it is: those of its <b>type</b> (Metal for
generic materials, Ripple size for water, Glow for glowing ones, the grass's height and density for grass), <b>Change
picture…</b> only when it has a picture, and no Relief slider while its texture set gives the relief (choose a relief map
and the slider comes back to scale it).</p>
<p><b>Recognised by the name.</b> A material without settings of its own whose name (or picture's file name) says what
it is starts as that preset, in the editor <i>and</i> in the render: water (aigua, agua, water, piscina, mar, llac…),
glass (vidre, vidrio, glass, cristal…), grass (gespa, césped, grass, herba, lawn…; «herba alta», «tall grass», prat or
prado give Tall grass) and lights (llum, luz, LED, neon, làmpada…), in several languages. The list marks them ◦ and the
editor says so; change any setting and they become the material's own (●). The model's transparency is not changed:
for see-through water or glass, move <b>Transparency</b>.</p>
<table cellspacing='0' cellpadding='3' width='100%'>
<tr><td valign='top'><b>Opacity map</b></td><td>Under <b>Transparency</b>: an image that says where the material is see-through, for a
cut-out such as leaves, a fence or a lace. <b>White is opaque, black is transparent</b>, greys in between; <b>Invert</b> swaps
them. With a picture on the material the map follows the picture's layout, so a map made for that picture lines up; without
one it is tiled at the <i>map size</i>. The render and the preview use it; the 3D view shows only the Transparency slider.</td></tr>
<tr><td valign='top'><b>Cube preview</b></td><td>At the top, a quick preview of the material on a one-metre cube. It follows
the picture (and its tile size), the colour, the <b>type</b> (glass and water are see-through, glowing ones get a halo) and
the <b>Roughness</b>, <b>Metal</b>, <b>Relief</b> and <b>Glow</b> sliders, instantly and without Blender. It is only an idea of the
look: the <b>maps</b> and Blender's lighting show only in the render.</td></tr>
<tr><td valign='top'><b>Change picture…</b></td><td>Replaces the material's picture <b>in the model itself</b>, not only in
the render: the viewport changes too, on every face, component and object that wears the material, as <b>one undo
step</b> (together with <b>Transparency</b>, the controls here that edit IngeTrazo's own material). Each face keeps where its texture was
placed, and a colour tint is kept over the new image. <b>Keep proportions</b> makes the tile height follow the new
image's shape (the tile width stays); off, the tile size stays and a different shape is stretched. The material needs
a picture already; paint it with a texture first if it has only a colour. The image is copied into IngeTrazo's texture
cache and travels with the document when you save.</td></tr>
<tr><td valign='top'><b>Start from</b></td><td>A ready-made starting point; then adjust it. See the list below.</td></tr>
<tr><td valign='top'><b>Type</b></td><td><b>Generic</b> (opaque), <b>Glass</b> (transparent), <b>Water</b> (transparent, with ripples),
<b>Glowing</b> (it shines by itself and lights what is around it; the exposure meter ignores it so it does not darken the
picture), or <b>Grass</b> (blades of grass grow on it in the render).</td></tr>
<tr><td valign='top'><b>Transparency</b></td><td>How much light the material lets through: 0 is opaque, up to 95 %. It changes IngeTrazo's own material
<b>in the model</b> (every face and object that wears it, one undo step, so the 3D view shows it too) and so the render sees it: water and
other materials become see-through (the floor shows below), tinted by the material's colour or picture. For <b>Glass</b> it is how much the
refracting glass transmits. A material painted opaque stays opaque however it is typed: choosing Water or Glass gives it a transparency to
start with, and so do the Water and Glass presets.</td></tr>
<tr><td valign='top'><b>Roughness</b></td><td>0 is a mirror-like polish, 1 fully matte.</td></tr>
<tr><td valign='top'><b>Metal</b></td><td>1 for metals: the reflection takes the material's colour.</td></tr>
<tr><td valign='top'><b>Relief</b></td><td>How strongly the surface looks raised. Automatic: from the light and dark of the
material's picture when it has one (mortar joints, wood grain), otherwise a fine grain. With the picture, the slider is the
<b>height</b> of the relief (0 to 3 cm from black to white). The picture is softened first, so its grain does not turn into noise
and a joint becomes a groove that catches the light. It shows where the picture changes clearly (joints, edges), and barely where
it changes gently (wood grain): for that, raise the map's <b>Contrast</b>, or use a <b>height map file</b>.</td></tr>
<tr><td valign='top'><b>Ripple size</b></td><td>Water only. The size of the ripples on the surface, from fine (left) to broad waves (right); the
<b>Relief</b> slider is their height (0 gives a flat, mirror-like water). They are a 3-D noise turned into a bump on the glossy surface, the
usual «easy water» recipe of Blender, laid out in metres so a ripple has the same size everywhere. Fine ripples look like grain from far away,
broad ones read as water; the sun then glints on them.</td></tr>
<tr><td valign='top'><b>Glow</b></td><td>0 to 50: how brightly it shines (type Glowing): screens, light panels.</td></tr>
<tr><td valign='top'><b>Grass height</b></td><td>Grass only: how tall the blades are, 1 to 60 cm (a mown lawn is 4 to 8 cm).
The blades exist <b>only in the render</b>: the model stays flat and light to work with. They grow on every face that wears
the material, upright whatever the slope, in small tufts turned and sized at random. Their colour is the material's
<b>picture</b> where each tuft stands (a lawn picture gives the lawn's patches), or its colour, darker at the root; the
face under them fills the gaps. The cube preview shows the height.</td></tr>
<tr><td valign='top'><b>Grass density</b></td><td>Grass only: how many tufts (of a few blades each) grow on a square metre,
20 to 800. A thick lawn is 250 to 400, long grass 60 to 120 (taller tufts are bigger). The live view and the render use
the same density, whatever the camera sees. Only a huge lawn (more than 600 000 tufts in all) is thinned so Blender
does not run out of memory; Blender's log says by how much.</td></tr>
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

<a name="texture_sets"></a>
<h4>Full texture sets</h4>
<p>Material libraries give more than a picture: a <b>normal</b> map, <b>roughness</b>, <b>ambient occlusion</b>,
<b>displacement</b>, <b>metalness</b>, <b>opacity</b>. When the material's picture has them beside it, the render uses
them by itself, placed exactly as the picture (same tile size and rotation); there is nothing to set. They are found:</p>
<ol>
<li>from a small description file next to the picture, <b>&lt;picture name&gt;.pbr.json</b> (written by the asset panel
when it downloads a set; the files it lists must be in the picture's folder);</li>
<li>else by the libraries' own file names: <b>Poly Haven</b> (<i>wood_diff_1k.jpg</i> with <i>wood_nor_gl_1k</i>,
<i>wood_rough_1k</i>, <i>wood_ao_1k</i>, <i>wood_disp_1k</i>, <i>wood_metal_1k</i>, <i>wood_arm_1k</i>) and
<b>ambientCG</b> (<i>Wood049_1K-JPG_Color.jpg</i> with <i>_NormalGL</i>, <i>_Roughness</i>, <i>_AmbientOcclusion</i>,
<i>_Displacement</i>, <i>_Metalness</i>, <i>_Opacity</i>).</li>
</ol>
<p>A picture with none renders as before. With a set:</p>
<ul>
<li>The <b>normal map</b> replaces the <b>automatic</b> relief guessed from the picture; a relief source you chose
(grain, picture, height or normal map file) still applies, on top. A normal map drawn the other common way (its green channel inverted) is turned the right way by itself.
Without a normal map, the <b>displacement</b> map gives the relief (1 cm from black to white).</li>
<li><b>Roughness</b>: the set's map, scaled by the slider (0.5 leaves it as it is; lower polishes it, higher roughens it).
A roughness map you chose here wins.</li>
<li><b>Metal</b>: the set's map; the slider raises its lowest value. A metal map you chose here wins.</li>
<li><b>Ambient occlusion</b> darkens the colour in the grooves; <b>opacity</b> cuts holes where it is black.</li>
<li><b>Glass</b> and <b>Water</b> take only the normal map. <b>White model</b> ignores the sets.</li>
<li>The cube preview shows the picture only; the sets show in the render.</li>
</ul>
<p>The editor shows the set: a line under the picture lists the maps found, and the first choice under <b>Roughness</b>,
<b>Metal</b> and <b>Relief</b> reads <b>Texture set: …</b> with a small preview of that map (for a packed map, the channel used).
Pick another map there to replace it.</p>

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
