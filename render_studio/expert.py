# SPDX-License-Identifier: GPL-3.0-or-later
"""The Expert page: every setting of the register, by page and group, with a search box. Each one has its control, an EYE (open:
it is also in its own page), a mark when it is not at its default (seen even when the eye is closed, so nothing hidden changes
a picture unnoticed) and a button back to the default. The eyes make a layout, which can be saved under a name."""
from __future__ import annotations

import json
import logging
import unicodedata

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QToolButton, QVBoxLayout,
                               QWidget)

from . import bindings, icons, layouts, look_model, params, presets, user_presets, widgets
from .i18n import tr

_log = logging.getLogger(__name__)
_SETTINGS = "render_studio/"
_DEFAULT = ""                                   # the default layout's data in the box
#: The eye: flat, with a faint ground only under the pointer.
EYE_STYLE = """
QToolButton, QToolButton:checked, QToolButton:pressed { border: none; background: transparent; padding: 2px; }
QToolButton:hover { background: rgba(128,128,128,50); border-radius: 4px; }
"""
#: The groups whose icon is not called after them.
GROUP_ICONS = {"ambient": "grp_light", "image": "grp_corrections"}


def _plain(text: str) -> str:
    """Without accents or capitals, to search."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))


def default_value(key: str, look: str):
    """What ``key`` is when nobody touched it: the register's, or for a «look's own» slider that look's value."""
    param = params.BY_KEY[key]
    name = params.SLIDER_KEYS.get(key)
    if name is not None:
        _label, _lo, _hi, own, _unit = presets.SLIDERS[name]
        return own if own is not None else presets.studio(look)[0].get(name, 0.0)
    return list(param.default) if isinstance(param.default, tuple) else param.default


def same(a, b) -> bool:
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        return a is not None and b is not None and all(abs(float(x) - float(y)) < 6e-3 for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) < 0.026
    return (a or None) == (b or None) if not isinstance(a, bool) else a == b


class _Row(QWidget):
    def __init__(self, tab, param, control):
        super().__init__()
        self.param = param
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 1, 0, 3)
        v.setSpacing(1)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)
        self.eye = QToolButton()
        self.eye.setCheckable(True)
        self.eye.setAutoRaise(True)
        self.eye.setIconSize(QSize(18, 18))
        self.eye.setStyleSheet(EYE_STYLE)                   # no ground of its own, chosen or not: the drawing says which it is
        self.eye.setCursor(Qt.PointingHandCursor)
        self.eye.clicked.connect(lambda on: tab.set_eye(param.key, on))
        self.name = QLabel(tr(param.label))
        self.name.setWordWrap(True)
        self.mark = QLabel("●")
        self.mark.setStyleSheet("color: #e8742a")
        self.mark.setToolTip(tr("Not at its default"))
        self.reset = QToolButton()
        self.reset.setIcon(icons.icon("undo"))
        self.reset.setAutoRaise(True)
        self.reset.setToolTip(tr("Back to the default"))
        self.reset.clicked.connect(lambda _c=False: tab.reset_value(param.key))
        for w in (self.name, self.mark, self.reset, self.eye):          # the eye at the right edge, all in one column
            top.addWidget(w, 1 if w is self.name else 0)
        v.addLayout(top)
        self.mirror = bindings.Mirror(tab.panel, param.key, control)
        if param.hint:
            self.setToolTip(tr(param.hint))
        v.addWidget(self.mirror.widget)

    def show_eye(self, on: bool) -> None:
        self.eye.setChecked(on)
        self.eye.setIcon(icons.icon("eye" if on else "eye_off"))
        self.eye.setToolTip(tr("In its page: click to hide it there") if on else tr("Only here: click to show it in its page"))


class ExpertTab(QWidget):
    def __init__(self, panel, folder: layouts.Folder):
        super().__init__()
        self.panel, self.folder = panel, folder
        self.controls = bindings.controls(panel)
        self.filter = bindings.LayoutFilter(panel, self.controls)
        self.layout_name, shown = self._stored()
        self._pending = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 4, 2)                    # (as the other pages: room above, under the tabs)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search a setting…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._filter_rows())
        v.addWidget(self.search)
        self.layout_box = QComboBox()
        self.layout_box.setToolTip("The layout: which settings each page shows. It changes no value of the render.")
        self.layout_box.activated.connect(lambda _i: self.load_layout(self.layout_box.currentData()))
        self.menu_btn = QToolButton()
        self.menu_btn.setIcon(icons.icon("more"))
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)
        self.menu_btn.setToolTip("Save the layout, delete it, or go back to the default one")
        menu = QMenu(self.menu_btn)
        self.save_act = menu.addAction(tr("Save layout…"), lambda: self.save_layout())
        self.delete_act = menu.addAction(tr("Delete this layout"), lambda: self.delete_layout())
        menu.addSeparator()
        self.reset_act = menu.addAction(tr("Default layout"), lambda: self.load_layout(_DEFAULT))
        self.menu_btn.setMenu(menu)
        row = QHBoxLayout()
        row.addWidget(self.layout_box, 1)
        row.addWidget(self.menu_btn)
        v.addLayout(row)
        self.layout_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.layout_box.setMinimumContentsLength(8)

        self.rows: dict = {}
        self.headers: list = []                      # (label, [keys])
        for tab_key, (tab_name, groups) in params.TABS.items():
            for group in groups:
                keys = [p.key for p in params.PARAMS if p.tab == tab_key and p.group == group and p.key in self.controls]
                if not keys:
                    continue
                header = widgets.Card(f"{tr(tab_name)} ▸ {tr(params.GROUPS[group])}", f"expert_{tab_key}_{group}",
                                      icon=GROUP_ICONS.get(group, "grp_" + group), kind="column")
                v.addWidget(header)
                self.headers.append((header, keys))
                for key in keys:
                    try:
                        self.rows[key] = _Row(self, params.BY_KEY[key], self.controls[key])
                    except Exception:  # noqa: BLE001 - one control without a mirror must not take the page with it
                        _log.exception("no expert row for %s", key)
                        continue
                    header.body_layout.addWidget(self.rows[key])
        v.addStretch(1)
        self.filter.set_shown(shown)
        for key, control in self.controls.items():
            for signal in bindings.change_signals(control):
                signal.connect(self._changed)
        self._fill_layouts()
        self.refresh()

    # -- the layout ------------------------------------------------------------------------
    def _stored(self):
        """The layout in use, as the program's settings keep it."""
        raw = QSettings().value(_SETTINGS + "layout", "")
        try:
            data = json.loads(raw) if raw else None
            got = layouts.from_data(data) if data else None
            if got is not None and not got[0] and data.get("basic") != layouts.BASIC:
                got = None                          # the default of before: the new basic view
        except (TypeError, ValueError, AttributeError):
            got = None
        return got if got is not None else ("", layouts.default())

    def _store(self) -> None:
        QSettings().setValue(_SETTINGS + "layout", json.dumps(layouts.to_data(self.layout_name, self.filter.shown)))

    @property
    def shown(self) -> set:
        return set(self.filter.shown) & set(self.controls)

    def modified(self) -> bool:
        """Whether the eyes differ from the layout that is named."""
        saved = self.folder.find(self.layout_name) if self.layout_name else None
        base = saved[2] if saved is not None else layouts.default()
        return self.shown != base & set(self.controls)

    def _fill_layouts(self) -> None:
        box = self.layout_box
        box.blockSignals(True)
        box.clear()
        box.addItem(tr("Default layout"), _DEFAULT)
        for _path, name, _shown in self.folder.entries():
            box.addItem(name, name)
        index = max(0, box.findData(self.layout_name))
        if self.modified():
            box.setItemText(index, box.itemText(index) + " " + tr("(changed)"))
        box.setCurrentIndex(index)
        box.blockSignals(False)
        self.delete_act.setEnabled(bool(self.layout_name) and self.folder.find(self.layout_name) is not None)

    def set_eye(self, key: str, on: bool) -> None:
        shown = set(self.filter.shown)
        shown.add(key) if on else shown.discard(key)
        self.filter.set_shown(shown)
        self.rows[key].show_eye(on)
        self._store()
        self._fill_layouts()

    def load_layout(self, name: str) -> None:
        saved = self.folder.find(name) if name else None
        self.layout_name = saved[1] if saved is not None else ""
        self.filter.set_shown(saved[2] if saved is not None else layouts.default())
        self._store()
        self._fill_layouts()
        self.refresh()

    def save_layout(self, name: str = "") -> None:
        if not name:
            name, ok = QInputDialog.getText(self.window(), tr("Save layout…"), tr("Name of the layout"), text=self.layout_name)
            name = user_presets.clean_name(name)
            if not ok or not name:
                return
            if name != self.layout_name and self.folder.find(name) is not None and QMessageBox.question(
                    self.window(), tr("Save layout…"), tr("A layout called «{name}» exists. Replace it?", name=name)) != QMessageBox.Yes:
                return
        try:
            self.folder.save(name, self.filter.shown)
        except (OSError, ValueError) as exc:
            self.panel._set_status(tr("Could not write the file: {error}", error=exc))
            return
        self.layout_name = name
        self._store()
        self._fill_layouts()

    def delete_layout(self) -> None:
        if not self.layout_name or QMessageBox.question(
                self.window(), tr("Delete"), tr("Delete the layout «{name}»?", name=self.layout_name)) != QMessageBox.Yes:
            return
        self.folder.delete(self.layout_name)
        self.load_layout(_DEFAULT)

    # -- the values ------------------------------------------------------------------------
    def reset_value(self, key: str) -> None:
        """``key`` back to its default."""
        if params.BY_KEY[key].local:                      # not of the drawing: its control alone holds it
            control = self.controls[key]
            control.setCurrentIndex(control.findData(params.BY_KEY[key].default))
            self.refresh()
            return
        now = self.panel.settings_dict()
        model = look_model.from_v1(now)
        if key == "ambient.look":
            self.panel.set_ambient("clear")
        else:
            model[key] = default_value(key, model["ambient.look"])
            self.panel.apply_settings(look_model.to_v1(model, now))
            self.panel._schedule_save()
        self.refresh()

    def _changed(self, *_a) -> None:
        self.filter.apply()                         # (after the panel's own handlers: they were connected first)
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self._refresh_later)

    def _refresh_later(self) -> None:
        self._pending = False
        if self.isVisible():
            self.refresh()

    def refresh(self) -> None:
        """Every mirror takes its control's state; the marks and what does not apply now follow."""
        try:
            model = look_model.from_v1(self.panel.settings_dict())
        except Exception:  # noqa: BLE001 - while the panel is being built
            return
        model.update({key: self.controls[key].currentData() for key in self.rows
                      if params.BY_KEY[key].local and params.BY_KEY[key].kind == "choice"})
        for key, row in self.rows.items():
            row.mirror.pull()
            row.show_eye(key in self.filter.shown)
            applies = params.applies(row.param, model)
            row.mirror.widget.setEnabled(applies)
            row.name.setEnabled(applies)
            differs = applies and row.param.kind != "program" and \
                not same(model[key], default_value(key, model["ambient.look"]))
            row.mark.setVisible(differs)
            row.reset.setVisible(differs)
        self._filter_rows()

    def _filter_rows(self) -> None:
        words = _plain(self.search.text()).split()
        for header, keys in self.headers:
            any_left = False
            for key in keys:
                row = self.rows.get(key)
                if row is None:
                    continue
                text = _plain(f"{header.title()} {row.name.text()} {row.param.label}")
                match = all(w in text for w in words)
                row.setVisible(match)
                any_left = any_left or match
            header.setVisible(any_left)
            header.force_open(bool(words))              # (a search shows what it finds, folded or not)

    def showEvent(self, ev):  # noqa: N802 (Qt)
        super().showEvent(ev)
        self.refresh()
