# SPDX-License-Identifier: GPL-3.0-or-later
"""One help window for Render Studio, opened at the section that fits the
button pressed (panel, image window or material editor)."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLineEdit, QTextBrowser, QVBoxLayout

from . import help_text

_dialog = None


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Render Studio: help")
        self.resize(560, 660)
        lay = QVBoxLayout(self)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Search the help (e.g. Cycles, roughness, vignette)")
        self.find.setClearButtonEnabled(True)
        self.find.returnPressed.connect(self._find_next)
        self.find.textChanged.connect(lambda _t: self._find_next(restart=True))
        lay.addWidget(self.find)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setHtml(help_text.html())
        lay.addWidget(self.view)

    def goto(self, anchor: str) -> None:
        self.view.scrollToAnchor(anchor or "panel")

    def _find_next(self, restart: bool = False):
        text = self.find.text()
        if restart:
            cur = self.view.textCursor()
            cur.setPosition(0)
            self.view.setTextCursor(cur)
        if text and not self.view.find(text):          # wrap around
            cur = self.view.textCursor()
            cur.setPosition(0)
            self.view.setTextCursor(cur)
            self.view.find(text)


def show(parent=None, anchor: str = "panel") -> HelpDialog:
    """The shared, non-modal help window, scrolled to ``anchor``."""
    global _dialog
    if _dialog is None:
        _dialog = HelpDialog(parent)
    _dialog.show()
    _dialog.goto(anchor)
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog
