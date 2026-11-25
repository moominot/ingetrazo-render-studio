# SPDX-License-Identifier: GPL-3.0-or-later
"""Presets as files: each one a ``.rspreset`` (a ZIP) with the settings, its thumbnail and the pictures it uses.

A preset is the whole LOOK of the picture: surface, outline, shadows, finish, environment, picture corrections and ambient. It
does not hold the camera (the angle of view, the depth of field), the quality, the section or the output: those belong to the
drawing or to each render.

    preset.json   {"render_studio_preset": 2, "name": "...", "settings": {format 1, without what is not of the look}}
    thumb.png     the thumbnail, when there is one
    assets/...    the panorama or the picture behind, when the preset has one

Pure Python: no Qt.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from . import look_model, params, presets, settings_store, user_presets

SUFFIX = ".rspreset"
FILE_KEY = user_presets.FILE_KEY
#: The parts of the settings that are not of the look.
NOT_OF_THE_LOOK = ("section", "output", "engine", "quality", "width")
CAMERA_SLIDERS = ("dof", "focus")
MAX_ASSET = 400 * 1024 * 1024
MAX_THUMB = 8 * 1024 * 1024
_ASSET_KEYS = ("hdri", "backdrop")
_FINE_ASSETS = ("finish.texture_path",)             # pictures among the finer settings


def look_of(settings: dict) -> dict | None:
    """The part of ``settings`` a preset keeps, or None when they are of no use."""
    data = settings_store.clean(settings)
    if data is None:
        return None
    for key in NOT_OF_THE_LOOK:
        data.pop(key, None)
    data["sliders"] = {k: v for k, v in data["sliders"].items() if k not in CAMERA_SLIDERS}
    return data


def apply_to(current: dict, preset: dict) -> dict:
    """``current`` (the panel's settings) wearing ``preset``: everything of the look is the preset's, the rest stays. A slider
    the preset does not name goes back to its look's own value."""
    look = look_of(preset) or {}
    out = dict(current)
    out.pop("fine", None)                                  # the finer settings are of the look: none unless the preset has them
    out.update({k: v for k, v in look.items() if k != "sliders"})
    block, _ambience = presets.studio(look.get("look", "clear"))
    sliders = {}
    for key, (_label, _lo, _hi, default, _unit) in presets.SLIDERS.items():
        sliders[key] = default if default is not None else block.get(key, 0.0)
    sliders.update(look.get("sliders") or {})
    sliders.update({k: v for k, v in (current.get("sliders") or {}).items() if k in CAMERA_SLIDERS})
    out["sliders"] = sliders
    return out


# ---- the ones that come with Render Studio --------------------------------------------------
def _built(**changes) -> dict:
    model = dict(params.defaults(), **{k.replace("__", "."): v for k, v in changes.items()})
    return look_of(look_model.to_v1(model))


def builtins() -> list:
    """``[(key, name, settings)]``: the presets that come with Render Studio (they are not files and cannot be changed)."""
    white = dict(surface__kind="mono", surface__colour=list(params.WHITE), surface__keep_glass=True)
    return [
        ("realistic", "Realistic", _built()),
        ("white_model", "White model", _built(outline__on=True, outline__width=0.8, sky__clouds=0.2, image__saturation=0.85, **white)),
        ("sketch", "Sketch", _built(outline__on=True, outline__width=1.0, outline__hand=0.5, outline__extend=0.4,
                                    background__paper_sky=True, ground__on=False, shadows__draw="lines", shadows__opacity=0.5, **white)),
        ("watercolour", "Watercolour", _built(finish__kind="watercolour", outline__on=True, outline__width=0.8)),
        ("plan", "Plan on white", _built(outline__on=True, outline__width=0.8, background__kind="flat", ground__on=False,
                                         shadows__draw="colour", shadows__colour=[0.2, 0.25, 0.35], shadows__opacity=0.35, **white)),
        # every face pure white, nothing shaded: only the edges that are seen
        ("lines", "Line drawing", _built(surface__kind="paper", outline__on=True, outline__width=1.0, background__paper_sky=True,
                                         background__kind="flat", ground__on=False, shadows__floor=False)),
        ("lux", "Light analysis", _built(surface__kind="lux", outline__on=True, outline__width=0.8)),
    ]


# ---- the files ----------------------------------------------------------------------------
def write(path: Path, name: str, settings: dict, thumb: bytes | None = None) -> None:
    """The preset file ``path``: the look of ``settings``, ``thumb`` (PNG bytes) and the pictures it uses."""
    look = look_of(settings)
    if look is None:
        raise ValueError("there are no settings to keep")
    assets = {}
    for key in _ASSET_KEYS:
        block = look.get(key)
        if not block:
            continue
        source = Path(block["path"])
        if source.is_file() and source.stat().st_size <= MAX_ASSET:
            member = f"assets/{key}_{source.name}"
            assets[member] = source
            look[key] = dict(block, path=member)
    for key in _FINE_ASSETS:
        source = Path((look.get("fine") or {}).get(key) or "")
        if source.is_file() and source.stat().st_size <= MAX_ASSET:
            member = f"assets/{key}_{source.name}"
            assets[member] = source
            look["fine"] = dict(look["fine"], **{key: member})
    data = {FILE_KEY: 2, "name": user_presets.clean_name(name), "settings": look}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("preset.json", json.dumps(data, indent=1, ensure_ascii=False))
        if thumb:
            z.writestr("thumb.png", thumb)
        for member, source in assets.items():
            z.write(source, member)
    tmp.replace(path)


def _take_out(z, member: str, names: set, assets_to) -> str | None:
    """The picture ``member`` of the open preset ``z`` written into ``assets_to`` by its plain name: where, or None."""
    plain = member.rsplit("/", 1)[-1].replace("\\", "_")
    if member not in names or plain in ("", ".", "..") or assets_to is None or z.getinfo(member).file_size > MAX_ASSET:
        return None
    target = Path(assets_to) / plain
    if not target.is_file() or target.stat().st_size != z.getinfo(member).file_size:
        target.parent.mkdir(parents=True, exist_ok=True)
        with z.open(member) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return str(target)


def read(path: Path, assets_to: Path | None = None):
    """``(name, settings, thumbnail bytes or None)`` of a preset file, or None when it is not one. Its pictures are taken out into
    ``assets_to`` (only files of its ``assets/`` folder, by their plain names), and the settings point there. A file of the old
    kind (the JSON Render Studio exported) is read too."""
    path = Path(path)
    if not zipfile.is_zipfile(path):
        try:
            got = user_presets.from_file(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            return None
        return None if got is None else (got[0], look_of(got[1]), None)
    try:
        with zipfile.ZipFile(path) as z:
            data = json.loads(z.read("preset.json").decode("utf-8"))
            if not isinstance(data, dict) or FILE_KEY not in data:
                return None
            raw = dict(data.get("settings") or {})
            names = set(z.namelist())
            for key in _ASSET_KEYS:
                block = raw.get(key)
                if not isinstance(block, dict):
                    continue
                member = str(block.get("path") or "")
                if not member.startswith("assets/"):
                    continue                                   # a picture kept by its place on this computer
                target = _take_out(z, member, names, assets_to)
                raw[key] = dict(block, path=target) if target else None
            for key in _FINE_ASSETS:
                fine = raw.get("fine")
                member = str(fine.get(key) or "") if isinstance(fine, dict) else ""
                if member.startswith("assets/"):
                    raw["fine"] = dict(fine, **{key: _take_out(z, member, names, assets_to)})
            thumb = z.read("thumb.png") if "thumb.png" in names and z.getinfo("thumb.png").file_size <= MAX_THUMB else None
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, RuntimeError):
        return None
    look = look_of(raw)
    if look is None:
        return None
    return user_presets.clean_name(data.get("name")) or path.stem, look, thumb


def _file_name(name: str) -> str:
    kept = "".join(c if c.isalnum() or c in " -_().'·" else "_" for c in name).strip(" .")
    return kept or "preset"


class Folder:
    """The person's presets: the ``.rspreset`` files of one folder."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def assets_of(self, path: Path) -> Path:
        return self.root / "assets" / Path(path).stem

    def entries(self) -> list:
        """``[(path, name, thumbnail bytes or None)]``, by name."""
        out = []
        for path in sorted(self.root.glob("*" + SUFFIX)) if self.root.is_dir() else ():
            try:
                with zipfile.ZipFile(path) as z:
                    data = json.loads(z.read("preset.json").decode("utf-8"))
                    thumb = z.read("thumb.png") if "thumb.png" in z.namelist() else None
                if FILE_KEY in data:
                    out.append((path, user_presets.clean_name(data.get("name")) or path.stem, thumb))
            except (OSError, KeyError, ValueError, zipfile.BadZipFile, RuntimeError, AttributeError, TypeError):
                continue
        return sorted(out, key=lambda e: e[1].lower())

    def find(self, name: str):
        return next((p for p, n, _t in self.entries() if n.lower() == name.lower()), None)

    def free_path(self, name: str) -> Path:
        base, n = _file_name(name), 2
        path = self.root / (base + SUFFIX)
        while path.exists():
            path = self.root / f"{base} {n}{SUFFIX}"
            n += 1
        return path

    def free_name(self, name: str) -> str:
        taken = {n.lower() for _p, n, _t in self.entries()}
        out, n = name, 2
        while out.lower() in taken:
            out, n = f"{name} {n}", n + 1
        return out

    def save(self, name: str, settings: dict, thumb: bytes | None = None) -> Path:
        """A new preset, or the one of that name anew (its thumbnail stays when none is given)."""
        path = self.find(name)
        if path is None:
            path = self.free_path(name)
        elif thumb is None:
            old = self.load(path)
            thumb = old[2] if old else None
        write(path, name, settings, thumb)
        return path

    def load(self, path: Path):
        return read(path, self.assets_of(path))

    def set_thumbnail(self, path: Path, thumb: bytes) -> None:
        got = self.load(path)
        if got is not None:
            write(path, got[0], got[1], thumb)

    def rename(self, path: Path, name: str) -> Path:
        got = self.load(path)
        if got is None:
            return path
        new = self.free_path(name)
        write(new, name, got[1], got[2])
        self.delete(path)
        return new

    def duplicate(self, name: str, settings: dict, thumb: bytes | None = None) -> Path:
        name = self.free_name(name)
        path = self.free_path(name)
        write(path, name, settings, thumb)
        return path

    def delete(self, path: Path) -> None:
        Path(path).unlink(missing_ok=True)
        # (its pictures stay while the new file of a rename still points at them)
        folder = self.assets_of(path)
        if folder.is_dir() and not any(self._uses(p, folder) for p, _n, _t in self.entries()):
            shutil.rmtree(folder, ignore_errors=True)

    def _uses(self, path: Path, folder: Path) -> bool:
        got = self.load(path)
        return bool(got) and any(str(folder) in str((got[1].get(k) or {}).get("path", "")) for k in _ASSET_KEYS)

    def import_file(self, source: Path) -> Path | None:
        """A preset file from anywhere (new or old kind) into the folder; None when it is not one."""
        scratch = self.root / "assets" / ("import_" + _file_name(Path(source).stem))
        got = read(source, scratch)
        if got is None:
            shutil.rmtree(scratch, ignore_errors=True)
            return None
        name = self.free_name(got[0])
        path = self.free_path(name)
        write(path, name, got[1], got[2])                      # the pictures go inside the new file…
        shutil.rmtree(scratch, ignore_errors=True)             # …and come out again when it is used
        return path

    def migrate(self, raw: str) -> int:
        """The presets Render Studio kept in the program's settings (``raw``: their JSON text), as files; one of a name already
        here is left alone. Returns how many were made. The old ones are not touched."""
        made = 0
        for name, settings in user_presets.load_all(raw).items():
            if self.find(name) is None:
                try:
                    self.save(name, settings)
                    made += 1
                except (OSError, ValueError):
                    continue
        return made
