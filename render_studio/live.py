# SPDX-License-Identifier: GPL-3.0-or-later
"""Live view: one Blender kept open with the scene and the look loaded, and an
image that follows IngeTrazo's 3D view and model.

It speaks the protocol of IngeTrazo's own «Sync with the view» (the render
script's ``serve`` mode): Blender builds the scene once, says ``INGETRAZO
ready``, and renders one image per JSON line it reads on its input, saying
``INGETRAZO done <file>``; ``{"reload": job}`` builds another job's scene in
the same Blender, ``{"update": job}`` does too but changes only the materials that
changed when that is all that did (the model is not imported again). The studio script serves the same way after it has applied
the look, so the live image has the look, the sky, the 360° background and
the material settings of the final render, as a light EEVEE draft (the
panel's Engine and Quality are for Render).

Two switches, as in other real-time viewers:

* **Follow the camera** — while the camera moves, small, rough frames come
  one after another as fast as Blender renders them (each shows the camera
  as it is when Blender is free); once it rests a quarter of a second a
  quick image comes, then the cleaner draft. Off: the image keeps the
  camera it had, whatever the 3D view does.
* **Follow changes** — an edit of the model, its textures or the materials'
  render settings rebuilds the scene (in the same Blender; the model is
  exported again only if it changed). Off: the live scene keeps the model
  and materials it had; the look and the panel's sliders still apply.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import view_camera

_log = logging.getLogger(__name__)

#: How often the 3D view is looked at (ms).
POLL_MS = 40
#: How long the camera must rest before the quick image (ms).
QUICK_REST_MS = 250
#: Frames while the camera moves: this fraction of the draft's width, one sample.
MOTION_SCALE = 1.0 / 3.0
MOTION_SAMPLES = 1
#: The quick image once it rests: this fraction of the draft's width, this many samples.
QUICK_SCALE = 0.5
QUICK_SAMPLES = 1
#: The draft that follows it.
DRAFT_SAMPLES = 8
#: The Interior look's live view is Cycles (EEVEE can't fill a window-lit room): samples
#: of the moving frames, the quick image and the draft (each denoised).
CYCLES_SAMPLES = {"motion": 2, "quick": 4, "draft": 32}


#: The preview's quality: how big the frames are (a factor of the draft's width) and how many samples they take (a factor too,
#: at least one). «normal» is the numbers above.
QUALITY = {"fast": (0.6, 0.5), "normal": (1.0, 1.0), "high": (1.0, 2.0)}


def quality_numbers(level: str, kind: str, samples: int) -> tuple[float, int]:
    """(the width factor, the samples) of a frame of ``kind`` at the preview quality ``level``. «High» also keeps the moving
    frames and the quick image as sharp as it can (they were a third and a half of the width)."""
    wf, sf = QUALITY.get(level, QUALITY["normal"])
    if level == "high" and kind != "draft":
        wf = 1.5 if kind == "motion" else 1.3                   # 1/3 → 1/2 of the width, 1/2 → 2/3
    return wf, max(1, round(samples * sf))


def _copy_camera(cam):
    """A copy of the viewport camera that does not move with it."""
    import copy
    try:
        return copy.deepcopy(cam)
    except Exception:  # noqa: BLE001 - a shallow copy with its own vectors
        out = copy.copy(cam)
        for attr in ("target",):
            v = getattr(cam, attr, None)
            if v is not None:
                setattr(out, attr, type(v)(v))
        return out


class LiveSession(QObject):
    image = Signal(object)          # Path of a new image
    state = Signal(str)             # what it is doing, for the status line
    line = Signal(str)              # a line Blender said while it makes a final picture (the progress)

    def __init__(self, panel, *, argv_factory=None, poll_ms: int = POLL_MS, rest_ms: int | None = None):
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
        self._scene_key = self._seen_key = None
        self._done_key = self._quick_key = self._motion_key = None
        self._model_key = None
        self._kept_specs = None                # the materials' settings the live scene has
        self._frozen = None                    # the camera kept while Follow the camera is off
        self.frozen_camera = None              # ...as a camera object (Render and New scene use it)
        self._still_since = 0.0
        self._work = None
        self._count = 0
        self.follow_camera = True
        self.follow_changes = True
        self._final = None                     # (done, refused) callbacks while it makes a final picture
        self._force = False                    # «Update»: take the model and materials as they are now, once
        self.loads = 0                         # how many times the scene was loaded (for tests)
        self.starts = 0                        # how many times a Blender was started (for tests)
        self.frames = 0                        # how many frames were asked while moving (for tests)
        self.tail = []                         # Blender's last lines (to say why it stopped)

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    @property
    def usable(self) -> bool:
        """Blender is running with its scene ready (the view may be paused: see :meth:`pause`)."""
        return self._proc is not None and self._ready

    def pause(self) -> None:
        """The view stops following the camera and the changes, but Blender and its scene stay: :meth:`start` takes it up again
        with no new build (the preview window shows a final picture meanwhile)."""
        self._timer.stop()

    def start(self) -> None:
        if self.active:
            return
        if self._proc is None or not self._ready:
            self._scene_key = None             # (a paused view keeps its scene: it is rebuilt only if something changed)
        self._seen_key = None
        self._done_key = self._quick_key = self._motion_key = None
        self._timer.start()
        self._poll()

    def stop(self, wait: bool = True) -> None:
        """Stop the live view. ``wait`` False: Blender is told to quit and left to do it (a final render made in its scene does not
        wait for it)."""
        self._timer.stop()
        self._shutdown(wait)

    # ---- the two switches -------------------------------------------------------
    def set_follow_camera(self, on: bool) -> None:
        """Off: the image keeps the camera it has now."""
        from core import render_blender as rb
        on = bool(on)
        if on == self.follow_camera:
            return
        self.follow_camera = on
        if not on:
            try:
                cam = self.panel.app.viewport.camera
                self._frozen = view_camera.camera_dict(cam)
                self.frozen_camera = _copy_camera(cam)
            except Exception:  # noqa: BLE001
                self._frozen = None
                self.frozen_camera = None
        else:
            self._frozen = None
            self.frozen_camera = None
        self._seen_key = None

    def set_follow_changes(self, on: bool) -> None:
        """Off: the live scene keeps its model and materials (look and sliders still apply)."""
        self.follow_changes = bool(on)

    def render_final(self, camera, output, width, height, samples, engine, on_done, on_refused, lines=None) -> bool:
        """The final picture of ``camera`` made by THIS Blender, in the scene it already has (the model, the materials and the look
        are in it: nothing is exported or built again). False when it cannot: no scene that is ready and up to date with the
        panel. ``on_done(path)`` when the picture is written, ``on_refused()`` when Blender says its scene is only a draft (see
        studio_scene.as_final): the caller makes the picture the long way."""
        from core import render_blender as rb
        if not (self.usable and not self._busy and self._final is None):
            return False
        try:
            if self._scene_key is None or self.panel.live_key() != self._scene_key:
                return False                   # the scene is behind the panel (or Follow changes is off and something changed)
        except Exception:  # noqa: BLE001
            return False
        req = json.loads(rb.sync_request(camera, output, width, height, engine))
        req["camera"] = view_camera.camera_dict(camera)
        req["samples"] = int(samples)
        req["final"] = True
        if lines:
            req["lines"] = str(lines)
        self._final = (on_done, on_refused)
        self._busy = True
        self._proc.write((json.dumps(req) + chr(10)).encode())
        return True

    def live_engine_name(self) -> str:
        return self.panel.live_engine()

    def quality_changed(self) -> None:
        """The preview's quality was changed: the picture of the camera as it is is made again."""
        self._motion_key = self._quick_key = self._done_key = None

    def update_now(self) -> None:
        """With Follow changes off: take the model and the materials as they are now, once (the scene
        is rebuilt as soon as the camera rests; the model is exported again only if it changed)."""
        if self.active:
            self._force = True

    # ---- watching the camera and the model ------------------------------------
    def _rest(self) -> float:
        return self._rest_ms if self._rest_ms is not None else QUICK_REST_MS

    def _camera_key(self):
        from core import render_blender as rb
        if not self.follow_camera and self._frozen is not None:
            return ("kept", json.dumps(self._frozen, sort_keys=True))
        return view_camera.camera_key(self.panel.app.viewport.camera)

    def _wanted_key(self):
        """What the live scene should be: (model, materials, settings) — with the
        model and materials it has when Follow changes is off."""
        model, mats_, settings = self.panel.live_key()
        if not self.follow_changes and not self._force and self._scene_key is not None:
            model, mats_ = self._scene_key[0], self._scene_key[1]
        return (model, mats_, settings)

    def _poll(self) -> None:
        try:
            cam_key = self._camera_key()
        except Exception:  # noqa: BLE001 - a tab switching underneath
            return
        now = time.monotonic()
        moving = cam_key != self._seen_key
        if moving:
            self._seen_key = cam_key
            self._still_since = now
        key = self._wanted_key()
        if key != self._scene_key:
            # A change: rebuilt once the camera is not moving; an image on its way, or a
            # build under way (another change just before), finishes first.
            building = (self._proc is not None and not self._ready
                        and self._proc.state() != QProcess.NotRunning)
            if (not moving and not self._busy and not building
                    and (now - self._still_since) * 1000 >= self._rest()):
                self._load(key)
            return
        if not self._ready or self._busy:
            return
        if moving or (now - self._still_since) * 1000 < self._rest():
            if cam_key != self._motion_key and cam_key != self._quick_key:
                self._render(cam_key, "motion")          # the camera moves: a frame as it is now
            return
        if cam_key != self._quick_key:
            self._render(cam_key, "quick")
        elif cam_key != self._done_key and QApplication.mouseButtons() == Qt.NoButton:
            self._render(cam_key, "draft")

    # ---- the Blender that waits -------------------------------------------------
    def _height(self) -> int:
        from core import render_blender as rb
        return max(2, round(rb.SYNC_WIDTH / self.panel._aspect()))

    def _load(self, key) -> None:
        from core import render_blender as rb
        running = (self._proc is not None and self._ready
                   and self._proc.state() == QProcess.Running)
        if not running:
            if self._proc is not None:
                _log.info("live Blender restarted (ready %s, state %s)", self._ready, self._proc.state())
                self.restarts_why = (self._ready, str(self._proc.state()), list(self.tail[-6:]))
            self._shutdown()
        follow = self.follow_changes or self._force or self._kept_specs is None or not running
        self._force = False
        model_key = key[0]
        reuse = running and (model_key == self._model_key or not follow)
        specs = self.panel.material_specs() if follow else self._kept_specs
        self._scene_key = key
        self._done_key = self._quick_key = self._motion_key = None
        self._work = rb.work_base().parent / "render-studio" / "live"
        if running:
            self.state.emit("Updating the scene in Blender…")
            try:
                job, _script = self.panel.live_job(self._work, rb.SYNC_WIDTH, self._height(),
                                                   reuse_model=reuse, materials=specs)
            except Exception as exc:  # noqa: BLE001 - say it, never crash the app
                _log.exception("live view could not update")
                self.state.emit(f"Live view stopped: {exc}")
                self._timer.stop()
                return
            if not reuse:
                self._model_key = model_key
            self._kept_specs = specs
            self._ready = False
            self.loads += 1
            self._proc.write((json.dumps({"reload": str(job)}) + "\n").encode())
            return
        self.state.emit("Loading the scene into Blender…")
        try:
            job, script = self.panel.live_job(self._work, rb.SYNC_WIDTH, self._height(), materials=specs)
            self._model_key = model_key
            self._kept_specs = specs
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
        self.state.emit("Starting Blender…")
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
        self.starts += 1
        proc.start(argv[0], argv[1:])

    def _render(self, cam_key, kind: str = "draft") -> None:
        """A frame while moving («motion»), the quick image once it rests
        («quick») or the draft («draft»), of the camera as it is (or as kept)."""
        from core import render_blender as rb
        self._count += 1
        out = self._work / f"live-{self._count:04d}.png"
        stale = self._work / f"live-{self._count - 4:04d}.png"
        if stale.exists():                     # keep the last few only
            try:
                stale.unlink()
            except OSError:
                pass
        self._busy = True
        k, samples = {"motion": (MOTION_SCALE, MOTION_SAMPLES), "quick": (QUICK_SCALE, QUICK_SAMPLES),
                      "draft": (1.0, DRAFT_SAMPLES)}[kind]
        engine = self.panel.live_engine()
        if engine == "cycles":
            samples = CYCLES_SAMPLES[kind]
        wf, samples = quality_numbers(self.panel.preview_quality.currentData(), kind, samples)
        k = min(1.0, k * wf)
        if kind == "motion":
            self._motion_key = cam_key
            self.frames += 1
        elif kind == "quick":
            self._quick_key = cam_key
        else:
            self._done_key = cam_key
        if kind != "motion":
            self.state.emit("Live view: quick image…" if kind == "quick" else "Live view: refining…")
        width, height = max(16, round(rb.SYNC_WIDTH * k)), max(2, round(self._height() * k))
        req = json.loads(rb.sync_request(self.panel.app.viewport.camera, out, width, height, engine))
        if not self.follow_camera and self._frozen is not None:
            req["camera"] = self._frozen
        else:
            req["camera"] = view_camera.camera_dict(self.panel.app.viewport.camera)
        req["samples"] = samples
        # The outlines are drawn here (outlines.py: tenths of a second on an ordinary model, seconds on a very big one, and the 3D view
        # waits meanwhile): not on the frames of a moving camera, and not on a big model; the final render always has them.
        try:
            big = bool(self.panel._big_model())
        except Exception:  # noqa: BLE001
            big = False
        if kind != "motion" and not big:
            lines = self._work / f"lines-{self._count:04d}.png"
            try:
                (self._work / f"lines-{self._count - 4:04d}.png").unlink()
            except OSError:
                pass
            cam = self.frozen_camera if (not self.follow_camera and self.frozen_camera is not None) else self.panel.app.viewport.camera
            made = self.panel.line_layer(cam, width, height, lines, quiet=True)
            if made:
                req["lines"] = made
        self._proc.write((json.dumps(req) + "\n").encode())

    def _read(self) -> None:
        if self._proc is None:
            return
        self._buf += bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        *lines, self._buf = self._buf.split("\n")
        self.tail = (self.tail + lines)[-40:]
        for line in lines:
            if self._final is not None:
                if line.startswith("INGETRAZO final refused"):
                    (_d, refused), self._final = self._final, None
                    self._busy = False
                    refused()
                    continue
                if line.startswith("INGETRAZO done "):
                    (done, _r), self._final = self._final, None
                    self._busy = False
                    self._motion_key = self._quick_key = self._done_key = None      # the draft of the camera is made again
                    done(Path(line[len("INGETRAZO done "):].strip()))
                    continue
                self.line.emit(line)
                continue
            if line.startswith("INGETRAZO ready"):
                self._ready = True
                self.state.emit("Live view: in sync")
            elif line.startswith("INGETRAZO imported"):
                self.state.emit("Blender: the model is in; applying the look…")
            elif line.startswith("INGETRAZO ") and not self._ready:
                self.state.emit("Blender: " + line[len("INGETRAZO "):].strip()[:70] + "…")      # the step it is at (a big model takes a while)
            elif line.startswith("INGETRAZO done "):
                self._busy = False
                self.image.emit(Path(line[len("INGETRAZO done "):].strip()))
                if self._done_key is not None and self._done_key == self._quick_key:
                    self.state.emit("Live view: in sync")

    def _ended(self, *_a) -> None:
        if self.sender() is not self._proc:
            return
        self.ended_tail = list(self.tail)      # what it said last (for the log and tests)
        self._proc = None
        self._ready = self._busy = False
        if self.active:
            self._scene_key = None             # try again at the next rest
            _log.warning("live Blender stopped:\n%s", "\n".join(self.tail[-15:]))
            self.state.emit("Blender stopped; it will start again")

    def _shutdown(self, wait: bool = True) -> None:
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
            if not wait:                               # left to quit by itself
                proc.finished.connect(proc.deleteLater)
                return
            if not proc.waitForFinished(1500):
                proc.kill()
                proc.waitForFinished(1000)
        proc.deleteLater()
