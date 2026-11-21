# SPDX-License-Identifier: GPL-3.0-or-later
"""The small modal that says what is happening while the preview opens: the model is exported (a bar that
fills), then Blender starts and builds the scene (a bar that waits, with what it is doing). It closes when the
first picture arrives; Cancel stops the live view."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QProgressDialog

from .i18n import tr

#: The share of the bar the model's export takes; Blender's start and build wait after it.
EXPORT_SHARE = 0.85


class PrepDialog(QProgressDialog):
    def __init__(self, parent=None, text="Preparing the model…"):
        super().__init__(tr(text), tr("Cancel"), 0, 100, parent)
        self.setWindowTitle("Render Studio")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumDuration(0)
        self.setAutoClose(False)
        self.setAutoReset(False)
        self.setMinimumWidth(340)
        self.setValue(0)
        self.show()
        QApplication.processEvents()

    def exporting(self, fraction: float) -> None:
        """The model's export is ``fraction`` done."""
        if self.maximum() == 0:
            self.setRange(0, 100)
        pct = int(max(0.0, min(1.0, fraction)) * 100)
        self.setLabelText(tr("Exporting the model… {pct} %", pct=pct))
        self.setValue(int(pct * EXPORT_SHARE))
        QApplication.processEvents()

    def waiting(self, text: str) -> None:
        """Blender is at work: a bar that waits, with what it is doing."""
        self.setLabelText(tr(text))
        if self.maximum() != 0:
            self.setRange(0, 0)
        QApplication.processEvents()
