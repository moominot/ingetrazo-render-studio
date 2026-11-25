# SPDX-License-Identifier: GPL-3.0-or-later
"""Layouts: which settings each page shows. A layout only decides what is in view: it changes no value of the render and is not
kept in the drawing. The default one is the register's simple view and cannot be changed or deleted; a person's own ones are
``.json`` files in the extension's folder::

    {"render_studio_layout": 1, "name": "...", "shown": [keys], "known": [keys there were when it was saved]}

A setting added to Render Studio after a layout was saved shows as the simple view has it. Pure Python: no Qt.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import params, user_presets

FILE_KEY = "render_studio_layout"
#: Goes up when the simple view changes: a stored copy of the old default gives way to the new one.
BASIC = 2


def default() -> set:
    return set(params.simple_layout())


def from_data(data) -> tuple | None:
    """``(name, shown)`` of a layout's data, or None when it is not one."""
    if not isinstance(data, dict) or FILE_KEY not in data or not isinstance(data.get("shown"), list):
        return None
    shown = {k for k in data["shown"] if isinstance(k, str) and k in params.BY_KEY}
    known = {k for k in data.get("known") or [] if isinstance(k, str)}
    if known:
        shown |= {k for k in default() if k not in known}
    return user_presets.clean_name(data.get("name")), shown


def to_data(name: str, shown) -> dict:
    return {FILE_KEY: 1, "basic": BASIC, "name": user_presets.clean_name(name), "shown": sorted(k for k in shown if k in params.BY_KEY),
            "known": sorted(params.BY_KEY)}


def _file_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in " -_().'·" else "_" for c in name).strip(" .") or "layout"


class Folder:
    def __init__(self, root: Path):
        self.root = Path(root)

    def entries(self) -> list:
        """``[(path, name, shown)]``, by name."""
        out = []
        for path in sorted(self.root.glob("*.json")) if self.root.is_dir() else ():
            try:
                got = from_data(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, UnicodeError):
                continue
            if got is not None:
                out.append((path, got[0] or path.stem, got[1]))
        return sorted(out, key=lambda e: e[1].lower())

    def find(self, name: str):
        return next((e for e in self.entries() if e[1].lower() == name.lower()), None)

    def save(self, name: str, shown) -> Path:
        name = user_presets.clean_name(name)
        if not name:
            raise ValueError("a layout needs a name")
        have = self.find(name)
        if have is not None:
            path = have[0]
        else:
            path, n = self.root / (_file_name(name) + ".json"), 2
            while path.exists():
                path, n = self.root / f"{_file_name(name)} {n}.json", n + 1
        self.root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(to_data(name, shown), indent=1, ensure_ascii=False), encoding="utf-8")
        return path

    def delete(self, name: str) -> None:
        have = self.find(name)
        if have is not None:
            have[0].unlink(missing_ok=True)
