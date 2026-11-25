# SPDX-License-Identifier: GPL-3.0-or-later
"""Which graphics card Cycles can use: what «Automatic» chooses the preview's engine by.

Blender itself is asked, once for each Blender (the answer is remembered, and asked again when the program file changes): it
knows which of its backends finds a card on this computer, which a list of the computer's cards would not say. With a card,
Cycles is the quicker live view: it keeps the scene in the card between frames, while a Blender without a window builds
EEVEE's again for each one."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings

_log = logging.getLogger(__name__)
_SETTING = "render_studio/gpu_probe"
_MARK = "RENDERSTUDIO GPU"
#: The same backends, in the same order, as IngeTrazo's render script (render_scene.set_engine).
SCRIPT = f"""
import bpy
found = ""
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for backend in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = backend
        except TypeError:
            continue
        prefs.get_devices()
        if any(d.type == backend for d in prefs.devices):
            found = backend
            break
except Exception as exc:
    print(exc)
print("{_MARK}", found)
"""
_memory: dict[str, str] = {}


def _key(command) -> str:
    stamp = ""
    for part in command:
        try:
            if Path(part).is_file():
                stamp = str(int(Path(part).stat().st_mtime))
        except OSError:
            pass
    return "|".join(str(c) for c in command) + "|" + stamp


def _run(command) -> str | None:
    """The backend Blender finds ("" none), or None when it could not be asked."""
    from core import render_blender as rb
    try:
        out = subprocess.run([*command, "-b", "--factory-startup", "--python-expr", SCRIPT], capture_output=True,
                             text=True, errors="replace", timeout=40, env=rb.clean_env(),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError):
        _log.warning("Blender could not be asked about the graphics card", exc_info=True)
        return None
    for line in out.stdout.splitlines():
        if line.startswith(_MARK):
            return line[len(_MARK):].strip()
    return None


def known(found) -> str | None:
    """What is already known for this Blender, without starting it: the backend, "" for none, None when never asked."""
    command = getattr(found, "command", None)
    if not command:
        return None
    key = _key(command)
    if key in _memory:
        return _memory[key]
    try:
        kept = json.loads(QSettings().value(_SETTING, "") or "{}")
    except (ValueError, TypeError):
        return None
    return str(kept.get("backend") or "") if kept.get("key") == key else None


def gpu_backend(found) -> str:
    """"OPTIX", "CUDA", "HIP", "METAL" or "ONEAPI" when Cycles can use a graphics card with this Blender (``found``, as
    IngeTrazo's ``find_blender`` gives it), else "". The first time for a Blender it takes a few seconds."""
    command = getattr(found, "command", None)
    if not command:
        return ""
    key = _key(command)
    if key in _memory:
        return _memory[key]
    try:
        kept = json.loads(QSettings().value(_SETTING, "") or "{}")
    except (ValueError, TypeError):
        kept = {}
    if kept.get("key") == key:
        _memory[key] = str(kept.get("backend") or "")
        return _memory[key]
    backend = _run(command)
    if backend is None:                      # not remembered: asked again next time IngeTrazo starts
        _memory[key] = ""
        return ""
    _memory[key] = backend
    QSettings().setValue(_SETTING, json.dumps({"key": key, "backend": backend}))
    _log.info("Cycles graphics card: %s", backend or "none")
    return backend
