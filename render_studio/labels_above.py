# SPDX-License-Identifier: GPL-3.0-or-later
"""Labels above their controls: in every form of a window, the name of a setting goes on a line of its own, a
slider's value at the right of that line, and the control under it takes the whole width.

The forms stay forms (``labelForField`` and ``setRowVisible`` work as before) and the name stays the same QLabel.
The control's own value label is NOT moved: it stays where it was made, hidden, and a copy that says the same is
shown beside the name. Moving a widget out of the layout it was built in ended the program at times, much later and
elsewhere (an access violation while a list was cleared): never do it here."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QSlider, QWidget
from shiboken6 import isValid

from . import widgets

_MARK = "rs_value_in_label"
#: The followers, held by Python while their widgets live: without it Python can drop one's attributes while Qt
#: still sends it events.
_ALIVE: set = set()


class _ValueAtRight(QObject):
    """Keeps a copy of ``value`` on the line of ``name``, at the right edge of its row's control. Qt gives a form's
    label only the width of its words, so the copy is put beside it (a child of the same widget), and follows it."""

    FOLLOW = (QEvent.Resize, QEvent.Move, QEvent.ShowToParent, QEvent.HideToParent, QEvent.EnabledChange,
              QEvent.FontChange)

    def __init__(self, name: QLabel, field: QWidget, value: QLabel):
        super().__init__(name)
        self.name, self.field = name, field
        self.width = max(value.minimumWidth(), value.sizeHint().width(), 70)
        self.value = value = copy_of(value, name.parentWidget())
        _ALIVE.add(self)
        self.destroyed.connect(lambda *_a, me=self: _ALIVE.discard(me))
        value.setFixedWidth(self.width)
        name.setContentsMargins(0, 0, self.width + 4, 0)         # room kept: the words never run under the value
        name.setWordWrap(True)                                   # a long name breaks: it must not widen a narrow tray
        name.installEventFilter(self)
        field.installEventFilter(self)
        self.place()

    def place(self) -> None:
        if not (isValid(self.name) and isValid(self.field) and isValid(self.value)):
            return                                               # (the window is going)
        wide = min(190, self.name.fontMetrics().horizontalAdvance(self.name.text()) + self.width + 12)
        if self.name.minimumWidth() != wide:                     # on one line while it fits (a translation changes it)
            self.name.setMinimumWidth(wide)
        right = self.field.geometry().x() + self.field.width()
        self.value.setGeometry(right - self.value.width(), self.name.y(), self.value.width(),
                               max(self.name.height(), self.value.sizeHint().height()))
        self.value.setVisible(not self.name.isHidden())
        self.value.setEnabled(self.name.isEnabled() and self.field.isEnabled())
        self.value.raise_()

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 (Qt)
        if ev.type() in self.FOLLOW:
            self.place()
        return False


def copy_of(original: QLabel, parent: QWidget | None = None) -> QLabel:
    """A new label in ``parent`` that says what ``original`` says, now and whenever the code writes in it; the
    original is hidden where it is."""
    shown = QLabel(original.text(), parent)
    shown.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    shown.setStyleSheet(original.styleSheet())
    shown.setToolTip(original.toolTip())
    write = original.setText

    def both(text, write=write, shown=shown):
        write(text)
        if isValid(shown):
            shown.setText(text)

    original.setText = both                     # (every writer of this value is Python)
    original.hide()
    return shown


def value_of(field) -> QLabel | None:
    """The label that says a slider widget's value, when ``field`` is one."""
    if isinstance(field, widgets.SliderRow):
        return field.value_label
    if isinstance(field, (widgets.NumberSlider, widgets.RadiusSlider)):
        return field.label
    return None


def _value_of(item) -> QLabel | None:
    """The label that says a form row's slider value, when the row has one."""
    field = item.widget()
    if value_of(field) is not None:
        return value_of(field)
    layout = field.layout() if field is not None else item.layout()
    if isinstance(layout, QHBoxLayout) and layout.count() == 2:   # a bare slider with its value beside it
        first, second = layout.itemAt(0).widget(), layout.itemAt(1).widget()
        if isinstance(first, QSlider) and isinstance(second, QLabel):
            return second
    return None


def apply(root: QWidget) -> None:
    """Every form in ``root``: labels above, slider values at the right of their label. Safe to call again."""
    for form in root.findChildren(QFormLayout):
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        for row in range(form.rowCount()):
            name_item = form.itemAt(row, QFormLayout.LabelRole)
            field_item = form.itemAt(row, QFormLayout.FieldRole)
            if name_item is None or field_item is None:
                continue
            name = name_item.widget()
            if not isinstance(name, QLabel) or not name.text() or name.property(_MARK):
                continue
            value, field = _value_of(field_item), field_item.widget()
            if value is None or field is None:
                continue
            name.setProperty(_MARK, True)
            _ValueAtRight(name, field, value)
