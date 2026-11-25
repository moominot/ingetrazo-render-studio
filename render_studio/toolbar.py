# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Studio's commands and its toolbar: open the preview, keep it in step with the model and with the camera | the
materials, the lights and the Library.

The commands are the panel's own (they exist, and hold their state, also where there is no window to put a toolbar in);
the toolbar only shows them."""
from __future__ import annotations

import logging

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMessageBox, QToolBar

from . import icons
from .i18n import tr

_log = logging.getLogger(__name__)
OBJECT_NAME = "render_studio_toolbar"          # stable: the saved layout keys on it
#: What the extension manager is asked for: the Library's identifier, which it searches along with its name, whatever it is called.
LIBRARY_SEARCH = "asset_manager"
_SETTINGS = "render_studio/"
#: The toolbar's order; None is a separator.
ORDER = ("preview", "follow_changes", "update", "follow_camera", None, "materials", "lights", "library")


class Commands:
    def __init__(self, panel):
        self.panel = panel
        self.preview = self._action("preview", "Open preview", "A live view of the scene that you can zoom and move, with Render.",
                                    lambda: panel.open_preview())
        self.follow_changes = self._toggle(
            "follow_changes", "Sync changes", "live_follow_changes",
            "On: edits of the model, its textures and the materials show in the preview. Off: it keeps the model and materials "
            "it has (the look and sliders still apply).")
        self.update = self._action("refresh", "Update preview",
                                   "Shows the model and materials as they are now (with «Sync changes» off).",
                                   lambda: panel.update_preview())
        self.follow_camera = self._toggle(
            "follow_camera", "Sync camera", "live_follow_camera",
            "On: the preview follows the 3D view while you move it. Off: the preview keeps its camera.")
        self.materials = self._action("materials", "Materials", "How each material renders: polish, metal, relief, glass, glow.",
                                      lambda: panel.open_materials())
        self.lights = self._action("lights", "Lights", "Point, spot, area and sun lights for the render, placed in the model.",
                                   lambda: panel.open_lights())
        self.library = self._action("comp_manager", "Library", "Models, materials and backgrounds (Render Studio Library).",
                                    lambda: open_library(panel))
        self.update.setVisible(not self.follow_changes.isChecked())          # only when changes do not arrive by themselves
        self.follow_changes.toggled.connect(lambda on: self.update.setVisible(not on))

    def _action(self, key: str, text: str, tip: str, slot) -> QAction:
        act = QAction(icons.icon(key), tr(text), self.panel)
        act.setToolTip(f"{tr(text)} — {tr(tip)}")
        act.triggered.connect(lambda _checked=False: slot())
        return act

    def _toggle(self, key: str, text: str, setting: str, tip: str) -> QAction:
        act = QAction(icons.icon(key), tr(text), self.panel)
        act.setToolTip(f"{tr(text)} — {tr(tip)}")
        act.setCheckable(True)
        act.setChecked(str(QSettings().value(_SETTINGS + setting, "true")).lower() in ("true", "1"))
        act.toggled.connect(lambda on, k=setting: self.panel._follow_toggled(k, on))
        return act

    def need_blender(self, found: bool) -> None:
        """What needs Blender is greyed without it."""
        self.preview.setEnabled(found)
        self.update.setEnabled(found)

    def build(self, app):
        """The toolbar in IngeTrazo's window; None when the window cannot hold one."""
        window = getattr(app, "window", None)
        if window is None or not hasattr(window, "addToolBar"):
            return None
        bar = QToolBar(tr("Render Studio"), window)
        bar.setObjectName(OBJECT_NAME)
        for key in ORDER:
            if key is None:
                bar.addSeparator()
            else:
                bar.addAction(getattr(self, key))
        window.addToolBar(bar)
        restore = getattr(app, "restore_toolbar_layout", None)
        if restore is not None:
            restore()
        return bar


def library_panel():
    """The Library extension's panel, or None when it is not installed (or not loaded)."""
    return next((w for w in QApplication.allWidgets() if type(w).__name__ == "AssetPanel"
                 and type(w).__module__.startswith("asset_manager")), None)


def open_library(panel) -> None:
    """Show the Library's tab; without the extension, say so and offer IngeTrazo's extension manager."""
    library = library_panel()
    if library is not None:
        dock = library
        while dock is not None and not hasattr(dock, "setFloating"):
            dock = dock.parentWidget()
        if dock is not None:
            try:
                panel.app.show_panel(dock)
                return
            except Exception:  # noqa: BLE001 - an IngeTrazo that shows it otherwise
                _log.exception("could not show the Library")
                dock.show()
                dock.raise_()
                return
    window = getattr(panel.app, "window", None)
    manager = getattr(window, "_on_manage_extensions", None)
    if ask_install(panel, callable(manager)):
        QTimer.singleShot(0, lambda: search_manager(window, LIBRARY_SEARCH))     # runs once the dialog is up
        manager()


def search_manager(window, text: str, tries: int = 50) -> None:
    """Type ``text`` in the search box of IngeTrazo's extension manager, on its Browse page. It is the manager's own window,
    with no public way in: an IngeTrazo that builds it otherwise just opens it as it is."""
    dialog = getattr(window, "_extension_manager_dialog", None)
    page = (getattr(dialog, "_pages", None) or {}).get("browse") if dialog is not None else None
    if page is None:
        if tries > 0:
            QTimer.singleShot(100, lambda: search_manager(window, text, tries - 1))
        return
    try:
        tabs = getattr(dialog, "_tabs", None)
        if tabs is not None:
            tabs.setCurrentIndex(0)
        page["search"].setText(text)
    except Exception:  # noqa: BLE001 - never in the way of the manager
        _log.exception("could not search in the extension manager")


def ask_install(panel, can_open: bool) -> bool:
    """«The Library is not installed»: True when the person asks for the extension manager."""
    box = QMessageBox(getattr(panel.app, "window", None) or panel)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(tr("Render Studio Library"))
    box.setText(tr("Render Studio Library is not installed."))
    box.setInformativeText(tr("Install «Render Studio Library» from Extensions ▸ Extension manager, then restart IngeTrazo."))
    open_button = box.addButton(tr("Open the extension manager"), QMessageBox.AcceptRole) if can_open else None
    box.addButton(QMessageBox.Close)
    box.exec()
    return open_button is not None and box.clickedButton() is open_button
