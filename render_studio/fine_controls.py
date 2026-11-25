# SPDX-License-Identifier: GPL-3.0-or-later
"""The controls of the finer settings (those the register marks ``extra``), made from the register itself: each one goes at the
end of its group's form. A setting added to the register gets its control, its row in the Expert page, its place in the
document and its way to Blender with no more code here.

Only what is not at its default is kept, so a drawing that never used them is saved as before."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog

from . import params, widgets
from .i18n import tr
from .section_panel import ColourButton

_CHOOSE = "\x00choose"
PICTURES = "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)"


class PathBox(QComboBox):
    """A file: none, the one chosen, or «Choose a file…»."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(8)
        self.addItem(tr("None"), "")
        self.addItem(tr("Choose a file…"), _CHOOSE)
        self._path = ""
        self.activated.connect(self._chosen)

    def path(self):
        return self._path or None

    def set_path(self, path) -> None:
        self._path = path or ""
        was = self.blockSignals(True)
        try:
            if self._path and self.findData(self._path) < 0:
                self.insertItem(self.count() - 1, Path(self._path).name, self._path)
            self.setCurrentIndex(max(0, self.findData(self._path)))
        finally:
            self.blockSignals(was)

    def _chosen(self, _i) -> None:
        picked = self.currentData()
        if picked == _CHOOSE:
            picked = QFileDialog.getOpenFileName(self.window(), tr("Choose a file…"), "", PICTURES)[0] or self._path
        changed = (picked or "") != self._path
        self.set_path(picked)
        if changed:
            self.changed.emit()


class FineControls(QObject):
    changed = Signal()

    def __init__(self, panel, forms: dict):
        """``forms``: group -> the form its finer settings are added to."""
        super().__init__(panel)
        self.panel = panel
        self.rows: dict = {}                      # key -> (control, form)
        for p in params.PARAMS:
            if not p.extra:
                continue
            form = forms[p.group]
            control = self._make(p)
            if p.hint:
                control.setToolTip(p.hint)
            if isinstance(control, QCheckBox):
                form.addRow(control)
            else:
                form.addRow(p.label, control)
            self.rows[p.key] = (control, form)
        self.set_values(params.defaults())

    def _make(self, p):
        if p.kind == "choice":
            box = QComboBox()
            for key in p.choices:
                box.addItem(tr(params.CHOICE_NAMES[p.key][key]), key)
            box.currentIndexChanged.connect(self._changed)
            return box
        if p.kind == "bool":
            check = QCheckBox(p.label)
            check.toggled.connect(self._changed)
            return check
        if p.kind == "path":
            box = PathBox()
            box.changed.connect(self._changed)
            return box
        if p.kind == "colour":
            button = ColourButton(list(p.default or (0.5, 0.5, 0.5)), p.label, linear=p.colour_space == "linear")
            button.changed.connect(self._changed)
            return button
        step, fmt, scale = p.step or 0.05, p.fmt or "{:.2f}", None
        slider = widgets.NumberSlider(p.lo, p.hi, step, fmt, special=p.special)
        slider.valueChanged.connect(self._changed)
        return slider

    def control(self, key):
        return self.rows[key][0]

    # -- the values ------------------------------------------------------------------------
    def values(self) -> dict:
        out = {}
        for key, (control, _form) in self.rows.items():
            p = params.BY_KEY[key]
            if p.kind == "choice":
                out[key] = control.currentData()
            elif p.kind == "bool":
                out[key] = control.isChecked()
            elif p.kind == "path":
                out[key] = control.path()
            elif p.kind == "colour":
                out[key] = control.rgb()
            else:
                out[key] = round(control.value(), 4)
        return out

    def settings(self) -> dict:
        """What the document keeps: the settings not at their default."""
        return params.fine_clean(self.values())

    def set_values(self, model: dict) -> None:
        """Put ``model`` in the controls without saying anything changed."""
        for key, (control, _form) in self.rows.items():
            p = params.BY_KEY[key]
            value = model.get(key, p.default)
            was = control.blockSignals(True)
            try:
                if p.kind == "choice":
                    control.setCurrentIndex(max(0, control.findData(value)))
                elif p.kind == "bool":
                    control.setChecked(bool(value))
                elif p.kind == "path":
                    control.set_path(value)
                elif p.kind == "colour":
                    control.set_rgb(list(value or p.default or (0.5, 0.5, 0.5)))
                else:
                    control.setValue(p.default if value is None else value)
            finally:
                control.blockSignals(was)

    # -- what shows ------------------------------------------------------------------------
    def enable(self, model: dict) -> None:
        """Show the rows that mean something with ``model`` (the rest of the settings) and these values."""
        full = dict(params.defaults(), **model)
        full.update(self.values())
        for key, (control, form) in self.rows.items():
            form.setRowVisible(control, params.applies(params.BY_KEY[key], full))

    def _changed(self, *_a) -> None:
        self.changed.emit()
