"""The line engine of Croquis for IngeTrazo, by Victor Crespo (3dvic.com · github.com/vicc3d/croquis-ingetrazo), GPL-3.0-or-later.

``visibility.py`` finds the visible parts of a model's edges on a depth buffer, fast, and marks the outlines; ``strokes.py``
turns them into the ink strokes of a hand (corners overshot, wavering, drawn twice, fine detail left out). Both are NumPy only
and are kept here as in Croquis 0.14.2 with two small additions in ``strokes.py`` (marked «Render Studio»): a stroke can be ``straight``
(no bow or waver, whatever the hand) and a stroke with no hand (0) is the same width all along. Updating them means copying the files
again and making those two additions again. Render Studio draws the
outlines of its renders with them (see ``..outlines``) instead of Blender's Freestyle, which takes minutes on a big model.
"""
