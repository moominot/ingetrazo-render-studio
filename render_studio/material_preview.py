# SPDX-License-Identifier: GPL-3.0-or-later
"""The material editor's rendered sample (a first version): a Blender kept open in the background draws the
chosen material on a sphere, with the render's own steps, each time it changes. See
``blender/preview_server.py``. Only the latest asked for is rendered: a slider moved while Blender works does
not queue up pictures nobody will see."""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtGui import QPixmap

from . import blender_edit as BE

_log = logging.getLogger(__name__)
SERVER = Path(__file__).parent / "blender" / "preview_server.py"
WIDTH, HEIGHT = 420, 170


class MaterialPreview(QObject):
    """``find_blender()`` gives the Blender to use (``.command``) or None. ``ready(pixmap, seconds)`` is
    said for each sample, ``said(words)`` while there is none to show."""

    ready = Signal(QPixmap, float)
    said = Signal(str)

    def __init__(self, find_blender, parent=None, *, debounce_ms: int = 150, kind: str = "material",
                 size: tuple = (WIDTH, HEIGHT)):
        super().__init__(parent)
        self.kind, self.size = kind, size
        self.find_blender = find_blender
        self._proc = None
        self._up = False                    # Blender has said it listens
        self._busy = False
        self._wanted = None                 # the payload still to be rendered
        self._shown = None                  # …and the one asked last (the same is not rendered twice)
        self._count = 0
        self._buffer = b""
        self.folder = None
        self.started_at = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self._send)

    # -- asking ----------------------------------------------------------------------------------
    def ask(self, payload: list) -> None:
        text = json.dumps(payload, sort_keys=True, default=str)
        if text == self._shown:
            self._wanted = None
            return
        self._wanted = (text, payload)
        if self._proc is None and not self._start():
            return
        self._timer.start()

    def _start(self) -> bool:
        found = self.find_blender() if callable(self.find_blender) else None
        if found is None:
            self.said.emit("")
            return False
        try:
            from core import render_blender as rb
            self.folder = Path(tempfile.mkdtemp(prefix="rs-sample-"))
            shutil.copyfile(rb.render_script(), self.folder / "render_scene.py")
            shutil.copyfile(SERVER.parent / "studio_scene.py", self.folder / "studio_scene.py")
            proc = QProcess(self)
            env = QProcessEnvironment()
            for k, v in rb.clean_env().items():
                env.insert(k, v)
            proc.setProcessEnvironment(env)
            proc.setProcessChannelMode(QProcess.MergedChannels)
            proc.readyReadStandardOutput.connect(self._read)
            proc.finished.connect(self._gone)
            self._proc, self._up, self._busy, self._buffer = proc, False, False, b""
            self.started_at = time.monotonic()
            proc.start(found.command[0], [*found.command[1:], "-b", "--factory-startup", "--python", str(SERVER)])
        except Exception:  # noqa: BLE001 - no sample: the editor works without it
            _log.exception("could not start the sample's Blender")
            self.stop()
            return False
        self.said.emit("starting")
        return True

    def _send(self) -> None:
        if not self._up or self._busy or self._wanted is None or self._proc is None:
            return
        (text, payload), self._wanted = self._wanted, None
        self._shown = text
        self._count += 1
        data = self.folder / "in.json"
        BE.dump(data, payload)
        job = {"id": self._count, "payload": str(data), "out": str(self.folder / f"sample-{self._count}.png"),
               "kind": self.kind, "width": self.size[0], "height": self.size[1]}
        self._busy = True
        self.said.emit("working")
        self._proc.write((json.dumps(job) + "\n").encode("utf-8"))

    # -- answers ---------------------------------------------------------------------------------
    def _read(self) -> None:
        if self._proc is None:
            return
        self._buffer += bytes(self._proc.readAllStandardOutput())
        *lines, self._buffer = self._buffer.split(b"\n")
        for raw in lines:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("RSPREVIEW "):
                continue
            try:
                answer = json.loads(line[10:])
            except ValueError:
                continue
            if answer.get("ready"):
                self._up = True
            else:
                self._busy = False
                picture = QPixmap(answer.get("out", ""))
                if answer.get("error") or picture.isNull():
                    self._shown = None
                    self.said.emit("failed")
                elif self._wanted is None:               # (else a newer one is on its way)
                    self.ready.emit(picture, float(answer.get("seconds", 0.0)))
                for old in self.folder.glob("sample-*.png"):
                    if old.name != Path(answer.get("out", "")).name:
                        old.unlink(missing_ok=True)
            self._send()

    def _gone(self, *_a) -> None:
        self._proc, self._up, self._busy, self._shown = None, False, False, None
        self.said.emit("failed")

    def running(self) -> bool:
        return self._proc is not None

    def stop(self) -> None:
        """Close the background Blender (the window is no longer in sight)."""
        self._timer.stop()
        proc, self._proc = self._proc, None
        self._up = self._busy = False
        self._shown = self._wanted = None
        if proc is not None:
            try:
                proc.finished.disconnect(self._gone)
                proc.readyReadStandardOutput.disconnect(self._read)
            except (RuntimeError, TypeError):
                pass
            proc.closeWriteChannel()                 # its input ends: it leaves by itself
            if not proc.waitForFinished(1500):
                proc.kill()
                proc.waitForFinished(1500)
        if self.folder is not None:
            shutil.rmtree(self.folder, ignore_errors=True)
            self.folder = None
