# SPDX-License-Identifier: GPL-3.0-or-later
"""One «Edit in Blender» session (lights or materials): open Blender, watch the .blend, take it back.

See :mod:`blender_edit` for what comes back. The .blend is written in a working folder; each time it is
saved, a Blender without a window reads it to a JSON file and the drawing takes the result as ONE undo step.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QProcess, QProcessEnvironment, QTimer, Signal

from . import blender_edit as BE, light_ops, lights as L, materials as M, studio_data
from .i18n import tr

_log = logging.getLogger(__name__)


class BlenderSession(QObject):
    """``kind``: "lights" or "materials". ``found``: the Blender found (``.command`` list)."""
    changed = Signal(str)               # said after each save taken back
    failed = Signal(str)

    def __init__(self, app, kind: str, found, parent=None, *, debounce_ms: int = 900, only=None, launch=None):
        super().__init__(parent)
        self.app, self.kind, self.found = app, kind, found
        self.launch = launch                # (arguments, blend path, folder): Blender opens the render's scene, not a stage
        self.only = only                    # materials: the one name to open (None: every material of the model)
        self.folder = None
        self.blend = None
        self._sent = None               # what was sent (to tell the person's edits from the trip's rounding)
        self._seen = None
        self.takes = 0
        self._reading = None
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._schedule)
        self._watcher.fileChanged.connect(self._schedule)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self._check)

    # -- sending ---------------------------------------------------------------------------------
    def _start_scene(self) -> bool:
        """Lights, with the whole model in view: the render's own scene (as «Open in Blender…» makes it) is opened and
        its .blend watched; what comes back is the lights."""
        args, blend, folder = self.launch
        self._sent = L.free_lights(self.app.scene.plugin_data)
        self.folder, self.blend = Path(folder), Path(blend)
        BE.dump(self.folder / "in.json", BE.lights_to_blender(self._sent))     # what was sent, to tell what changed
        self._watcher.addPath(str(self.folder))
        proc = QProcess(self)
        proc.setProcessEnvironment(self._env())
        proc.setProgram(self.found.command[0])
        proc.setArguments(list(args))
        res = proc.startDetached()
        if not (res[0] if isinstance(res, tuple) else bool(res)):
            self.failed.emit(tr("Blender did not start."))
            return False
        return True

    def start(self) -> bool:
        if self.launch is not None:
            return self._start_scene()
        scene = self.app.scene
        if self.kind == "lights":
            self._sent = L.free_lights(scene.plugin_data)
            payload = BE.lights_to_blender(self._sent)
        else:
            names = [self.only] if self.only else sorted(M.used_materials(scene), key=str.lower)
            payload = BE.materials_to_blender(scene, self._specs(), names)
            if not payload:
                self.failed.emit(tr("The model has no materials to edit."))
                return False
        self.folder = BE.work_folder(self.kind)
        if self.kind == "materials" and any(not (p.get("package") or {}).get("blend") for p in payload):
            try:                                    # the render's own scripts: they grow the grass
                from core import render_blender as rb
                import shutil
                shutil.copyfile(rb.render_script(), self.folder / "render_scene.py")
                shutil.copyfile(BE.SCRIPT.parent / "studio_scene.py", self.folder / "studio_scene.py")
            except Exception:  # noqa: BLE001 - without them the material opens, flat
                _log.exception("grass scripts not copied")
        data = self.folder / "in.json"
        BE.dump(data, payload)
        self.blend = self.folder / "scene.blend"
        self._watcher.addPath(str(self.folder))
        proc = QProcess(self)
        proc.setProcessEnvironment(self._env())
        proc.setProgram(self.found.command[0])
        proc.setArguments([*self.found.command[1:], "--python", str(BE.SCRIPT), "--", "make", self.kind,
                           str(data), str(self.blend)])
        res = proc.startDetached()
        if not (res[0] if isinstance(res, tuple) else bool(res)):
            self.failed.emit(tr("Blender did not start."))
            return False
        return True

    def stop(self) -> None:
        self._timer.stop()
        paths = self._watcher.files() + self._watcher.directories()
        if paths:
            self._watcher.removePaths(paths)

    @staticmethod
    def _env():
        from core import render_blender as rb
        env = QProcessEnvironment()
        for k, v in rb.clean_env().items():
            env.insert(k, v)
        return env

    def _specs(self) -> dict:
        data = self.app.document_data({}) or {}
        return dict(data.get("materials") or {})

    # -- watching and reading ----------------------------------------------------------------------
    def _schedule(self, *_a) -> None:
        self._timer.start()             # Blender writes in several goes

    def _stamp(self):
        try:
            st = self.blend.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _check(self) -> None:
        if self.blend is None or not self.blend.is_file():
            return
        if str(self.blend) not in self._watcher.files():
            self._watcher.addPath(str(self.blend))      # a save that renames drops the watch
        stamp = self._stamp()
        if stamp is None or stamp == self._seen or self._reading is not None:
            if self._reading is not None:
                self._timer.start()
            return
        self._seen = stamp
        out = self.folder / f"out-{self.takes + 1}.json"
        proc = QProcess(self)
        proc.setProcessEnvironment(self._env())
        proc.setProgram(self.found.command[0])
        extra = [str(self.folder / "in.json")] if self.kind == "lights" and (self.folder / "in.json").is_file() else []
        proc.setArguments([*self.found.command[1:], "-b", str(self.blend), "--python", str(BE.SCRIPT), "--",
                           "read", self.kind, str(out), *extra])
        proc.finished.connect(lambda _c, _s, p=proc, o=out: self._read_done(p, o))
        proc.errorOccurred.connect(lambda _e, p=proc: self._read_failed(p))
        self._reading = proc
        proc.start()

    def _read_failed(self, proc) -> None:
        if self._reading is proc:
            self._reading = None
            self.failed.emit(tr("Could not read the Blender file."))

    def _read_done(self, proc, out: Path) -> None:
        self._reading = None
        proc.deleteLater()
        try:
            read = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.failed.emit(tr("Could not read the Blender file."))
            return
        try:
            self.apply(read)
        except Exception as exc:  # noqa: BLE001 - say it, never crash the app
            _log.exception("could not take the Blender edit")
            self.failed.emit(tr("Could not take the changes: {error}", error=exc))

    # -- taking back -----------------------------------------------------------------------------
    def apply(self, read: list) -> bool:
        """Put what Blender holds in the drawing (one undo step). False when nothing changed."""
        if self.kind == "lights":
            old = L.free_lights(self.app.scene.plugin_data)
            new = BE.lights_from_blender(self._sent, read, whole_scene=self.launch is not None)
            if BE.same(old, new):
                return False
            light_ops.run(self.app, light_ops.LightsCommand(free=new))
            self._sent = new                       # the next save is compared with what the drawing has now
            self.takes += 1
            self.changed.emit(tr("Blender: {n} lights taken ({count}).", n=len(new), count=self.takes))
            return True
        specs = self._specs()
        try:
            current = M.with_detected(self.app.scene, specs)
        except Exception:  # noqa: BLE001
            current = specs
        changed = BE.materials_from_blender(specs, read, current)
        if not changed:
            return False
        data = self.app.document_data({}) or {}
        mats = dict(data.get("materials") or {})
        mats.update(changed)
        data["materials"] = mats
        studio_data.write(self.app, data)
        self.takes += 1
        self.changed.emit(tr("Blender: {n} materials taken ({count}).", n=len(changed), count=self.takes))
        return True
