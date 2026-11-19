# SPDX-License-Identifier: GPL-3.0-or-later
"""Live view: one Blender kept open with the scene and the look loaded, and a
draft image that follows IngeTrazo's 3D view.

It speaks the protocol of IngeTrazo's own «Sync with the view» (the render
script's ``serve`` mode): Blender builds the scene once, says ``INGETRAZO
ready``, and renders one image per JSON line it reads on its input, saying
``INGETRAZO done <file>``. The studio script serves the same way after it has
applied the look, so the live image has the look, the sky, the 360°
background and the material settings of the final render, at draft quality.

The scene is loaded again when the model, the look or any setting changes;
the camera only asks for a new image once it has rested.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication

_log = logging.getLogger(__name__)


class LiveSession(QObject):
    image = Signal(object)          # Path of a new draft image
    state = Signal(str)             # what it is doing, for the status line

    def __init__(self, panel, *, argv_factory=None, poll_ms: int = 250, rest_ms: int | None = None):
        super().__init__(panel)
        self.panel = panel
        self._argv_factory = argv_factory      # tests: (job, script) -> argv of a stand-in for Blender
        self._rest_ms = rest_ms
        self._timer = QTimer(self)
        self._timer.setInterval(poll_ms)
        self._timer.timeout.connect(self._poll)
        self._proc = None
        self._ready = self._busy = False
        self._buf = ""
        self._scene_key = self._seen_key = self._done_key = None
        self._still_since = 0.0
        self._work = None
        self._count = 0
        self.loads = 0                         # how many times the scene was loaded (for tests)

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        if self.active:
            return
        self._scene_key = self._seen_key = self._done_key = None
        self._timer.start()
        self._poll()

    def stop(self) -> None:
        self._timer.stop()
        self._shutdown()

    # ---- watching the camera and the model ------------------------------------
    def _rest(self) -> float:
        if self._rest_ms is not None:
            return self._rest_ms
        from core import render_blender as rb
        return rb.SYNC_REST_MS

    def _poll(self) -> None:
        from core import render_blender as rb
        try:
            cam_key = rb.camera_key(self.panel.app.viewport.camera)
        except Exception:  # noqa: BLE001 - a tab switching underneath
            return
        now = time.monotonic()
        if cam_key != self._seen_key:
            self._seen_key = cam_key
            self._still_since = now
            return
        if QApplication.mouseButtons() != Qt.NoButton:
            self._still_since = now            # still dragging, only paused
            return
        if (now - self._still_since) * 1000 < self._rest():
            return
        key = self.panel.live_key()
        if key != self._scene_key:
            self._load(key)
            return
        if cam_key != self._done_key and self._ready and not self._busy:
            self._render(cam_key)

    # ---- the Blender that waits -------------------------------------------------
    def _height(self) -> int:
        from core import render_blender as rb
        return max(2, round(rb.SYNC_WIDTH / self.panel._aspect()))

    def _load(self, key) -> None:
        from core import render_blender as rb
        self._shutdown()
        self._scene_key = key
        self._done_key = None
        self.state.emit("Loading the scene into Blender…")
        self._work = rb.work_base().parent / "render-studio" / "live"
        try:
            job, script = self.panel.live_job(self._work, rb.SYNC_WIDTH, self._height())
            if self._argv_factory is not None:
                argv = self._argv_factory(job, script)
            else:
                found = self.panel.blender()
                if found is None:
                    raise RuntimeError("Blender was not found. Set it up in IngeTrazo's Render tab first.")
                argv = [*found.command, "-b", "--factory-startup", "--python", str(script), "--", str(job)]
        except Exception as exc:  # noqa: BLE001 - say it, never crash the app
            _log.exception("live view could not start")
            self.state.emit(f"Live view stopped: {exc}")
            self._timer.stop()
            return
        proc = QProcess(self)
        env = QProcessEnvironment()
        for k, v in rb.clean_env().items():
            env.insert(k, v)
        proc.setProcessEnvironment(env)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._read)
        proc.finished.connect(self._ended)
        self._proc = proc
        self._ready = self._busy = False
        self._buf = ""
        self.loads += 1
        proc.start(argv[0], argv[1:])

    def _render(self, cam_key) -> None:
        from core import render_blender as rb
        self._count += 1
        out = self._work / f"live-{self._count:04d}.png"
        stale = self._work / f"live-{self._count - 3:04d}.png"
        if stale.exists():                     # keep the last few only
            try:
                stale.unlink()
            except OSError:
                pass
        self._busy = True
        self._done_key = cam_key
        self.state.emit("Rendering the view…")
        self._proc.write(rb.sync_request(
            self.panel.app.viewport.camera, out, rb.SYNC_WIDTH, self._height(),
            self.panel.engine.currentData()).encode())

    def _read(self) -> None:
        if self._proc is None:
            return
        self._buf += bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            if line.startswith("INGETRAZO ready"):
                self._ready = True
                self.state.emit("Live view: in sync (stop moving to update)")
            elif line.startswith("INGETRAZO done "):
                self._busy = False
                self.image.emit(Path(line[len("INGETRAZO done "):].strip()))
                self.state.emit("Live view: in sync (stop moving to update)")

    def _ended(self, *_a) -> None:
        if self.sender() is not self._proc:
            return
        self._proc = None
        self._ready = self._busy = False
        if self.active:
            self._scene_key = None             # try again at the next rest
            self.state.emit("Blender stopped; it will start again")

    def _shutdown(self) -> None:
        proc, self._proc = self._proc, None
        self._ready = self._busy = False
        self._scene_key = None
        if proc is None:
            return
        try:
            proc.finished.disconnect(self._ended)
        except (RuntimeError, TypeError):
            pass
        if proc.state() != QProcess.NotRunning:
            proc.write(b'{"quit": true}\n')
            proc.closeWriteChannel()
            if not proc.waitForFinished(1500):
                proc.kill()
                proc.waitForFinished(1000)
        proc.deleteLater()
