"""The line engine of Croquis for IngeTrazo, by Victor Crespo (3dvic.com · github.com/vicc3d/croquis-ingetrazo), GPL-3.0-or-later.

``visibility.py`` finds the visible parts of a model's edges on a depth buffer, fast, and marks the outlines; ``strokes.py``
turns them into the ink strokes of a hand (corners overshot, wavering, drawn twice, fine detail left out). Both are NumPy only
and are kept here exactly as in Croquis 0.14.2, so they can be updated by copying the files again. Render Studio draws the
outlines of its renders with them (see ``..outlines``) instead of Blender's Freestyle, which takes minutes on a big model.
"""
