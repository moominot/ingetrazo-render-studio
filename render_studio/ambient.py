# SPDX-License-Identifier: GPL-3.0-or-later
"""The five ambients of the Main page: they change only the LIGHT (the look: sun, sky, exposure, white balance), never the
surface, the outlines or the finish. Each is one of the panel's looks."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QGroupBox, QLabel, QToolButton

from . import icons
from .i18n import tr

#: (look, icon, name, what it is)
AMBIENTS = (
    ("clear", "amb_sunny", "Sunny", "Outside, a clear sunny day."),
    ("overcast", "amb_cloudy", "Cloudy", "Outside, an overcast sky: soft light, hardly any shadow."),
    ("golden_hour", "amb_golden", "Golden", "Golden hour: a low, warm sun and long shadows."),
    ("night", "amb_night", "Night", "Night: the moon, the stars and the lamps."),
    ("interior", "amb_interior", "Interior", "A room: metered for the inside, the window allowed to burn out."),
)
COLUMNS = 5


class AmbientBox(QGroupBox):
    chosen = Signal(str)                    # the look a person pressed

    def __init__(self, parent=None):
        super().__init__("Light", parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(False)            # (a look with no button, as an old document's, leaves them all up)
        self.buttons = {}
        for i, (look, icon_key, name, tip) in enumerate(AMBIENTS):
            b = QToolButton()
            b.setText(tr(name))
            b.setToolTip(tr(tip))
            b.setIcon(icons.icon(icon_key))
            b.setIconSize(QSize(26, 26))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setCheckable(True)
            b.setMinimumWidth(36)
            b.setStyleSheet("QToolButton { font-size: 10px; padding: 2px 0; }")
            b.clicked.connect(lambda _c=False, key=look: self.chosen.emit(key))
            grid.addWidget(b, i // COLUMNS, i % COLUMNS)
            grid.setColumnStretch(i % COLUMNS, 1)
            self.group.addButton(b)
            self.buttons[look] = b
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray; font-size: 11px")
        self.note.setVisible(False)
        grid.addWidget(self.note, 1, 0, 1, COLUMNS)

    def show_state(self, look: str, sun_set: bool = False) -> None:
        """Press the button of what the picture will be: ``look``, or the night when the sun has set (``sun_set``) under a look
        of the day."""
        shown = "night" if sun_set else look
        for key, button in self.buttons.items():
            button.setChecked(key == shown)
        text = tr("The sun is below the horizon at that date and hour: the picture is a night. Change the hour in Environment.") \
            if sun_set else ""
        self.note.setText(text)
        self.note.setVisible(bool(text))
