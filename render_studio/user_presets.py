# SPDX-License-Identifier: GPL-3.0-or-later
"""The person's own presets: a named copy of the panel's settings (look, sliders, background, ground,
engine, quality, output) to come back to or to share as a file. Pure Python, no Qt.

A preset is the document's ``settings`` block (see settings_store.py) without the ``section`` (that belongs to
the model, not to a look). A file is ``{"render_studio_preset": 1, "name": "...", "settings": {...}}``.
"""
from __future__ import annotations

import json

from . import settings_store

FILE_KEY = "render_studio_preset"
MAX_NAME = 60


def clean_name(name) -> str:
    """A tidy name (no line breaks, at most 60 characters), or ''."""
    text = " ".join(str(name or "").split())
    return text[:MAX_NAME].strip()


def make(settings: dict) -> dict | None:
    """The preset for the panel's ``settings`` (cleaned, with no section), or None when unusable."""
    data = settings_store.clean(settings)
    if data is None:
        return None
    data.pop("section", None)
    return data


def to_file(name: str, settings: dict) -> str:
    """The JSON text of a preset file."""
    return json.dumps({FILE_KEY: 1, "name": clean_name(name), "settings": make(settings) or {}},
                      indent=2, ensure_ascii=False)


def from_file(text: str):
    """``(name, preset)`` read from a preset file's text, or None when it is not one."""
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(raw, dict) or FILE_KEY not in raw:
        return None
    preset = make(raw.get("settings"))
    name = clean_name(raw.get("name"))
    return (name or "Preset", preset) if preset is not None else None


def load_all(raw) -> dict:
    """``{name: preset}`` from what QSettings keeps (a JSON text): the usable ones only."""
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw else {}
    except ValueError:
        return {}
    out = {}
    for name, value in (data.items() if isinstance(data, dict) else ()):
        preset = make(value)
        if clean_name(name) and preset is not None:
            out[clean_name(name)] = preset
    return out


def dump_all(presets: dict) -> str:
    return json.dumps(presets, ensure_ascii=False)
