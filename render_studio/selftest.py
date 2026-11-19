# SPDX-License-Identifier: GPL-3.0-or-later
"""Self-test inside a real IngeTrazo, run only when the app is started with
``RENDER_STUDIO_SELFTEST=<config.json>`` (and ``--new-window``, so it is a
separate instance that never touches the user's open document).

Loads a model, frames it, renders each look through the panel's own Render
button code, saves every image, a picture of the panel and of the image
window with adjustments, writes ``log.json`` and quits without saving.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer


def schedule(app, panel, config_path: str):
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    out = Path(cfg["out"])
    out.mkdir(parents=True, exist_ok=True)
    log = {"started": time.strftime("%H:%M:%S"), "steps": []}
    keys = list(cfg.get("presets") or [])

    def note(*parts):
        log["steps"].append(" ".join(str(p) for p in parts))
        (out / "log.json").write_text(json.dumps(log, indent=1), encoding="utf-8")

    def finish(ok=True):
        log["ok"] = ok
        log["ended"] = time.strftime("%H:%M:%S")
        note("finish", ok)
        os._exit(0)                       # no save prompt, no settings written back

    def load():
        try:
            vp = app.viewport
            from core.history import SnapshotImport
            from formats.skp import load_skp
            vp.history.execute(SnapshotImport(lambda sc: load_skp(sc, cfg["skp"])))
            vp.notify_scene_changed() if hasattr(vp, "notify_scene_changed") else None
            sc = vp.scene
            lo, hi = sc.bounds()
            from PySide6.QtGui import QVector3D
            centre = (lo + hi) * 0.5
            size = max(hi.x() - lo.x(), hi.y() - lo.y(), hi.z() - lo.z())
            cam = vp.camera
            cam.target = QVector3D(centre.x(), centre.y(), centre.z() * 0.8)
            cam.distance = size * float(cfg.get("distance", 1.0))
            cam.yaw = math.radians(float(cfg.get("yaw", -35.0)))
            cam.pitch = math.radians(float(cfg.get("pitch", 4.0)))
            vp.update()
            note("loaded", cfg["skp"], "groups", len(sc.groups))
            vp.render_image(1280, 720).save(str(out / "viewport.png"))
            panel.width.setValue(int(cfg.get("width", 960)))
            panel.engine.setCurrentIndex(max(0, panel.engine.findData(cfg.get("engine", "eevee"))))
            if cfg.get("materials"):
                # The material editor, driven as a user would: pick, preset.
                ed = panel.open_materials()
                for name, key in cfg["materials"].items():
                    if not ed.select(name):
                        note("material not listed", name)
                        continue
                    i = ed.preset.findData(key)
                    ed.preset.setCurrentIndex(i)
                    ed._preset(i)
                    ed._flush()
                ed.grab().save(str(out / "material_editor.png"))
                note("materials", json.dumps(panel.material_specs()))
            panel.finished.connect(done)
            QTimer.singleShot(300, next_one)
        except Exception:  # noqa: BLE001
            note("load failed", traceback.format_exc())
            finish(False)

    def next_one():
        if not keys:
            return wrap_up()
        run = keys[0]
        # A run is a preset key, or {"name", "preset", "hdri", "rotation", "light"}.
        spec = run if isinstance(run, dict) else {"name": run, "preset": run}
        key = spec["name"]
        panel.preset.setCurrentIndex(panel.preset.findData(spec["preset"]))
        if spec.get("hdri"):
            panel.set_hdri_path(spec["hdri"])
            s = panel.hdri_rotation
            s.setValue(int(round(float(spec.get("rotation", 0.0)) / 360.0 * s.maximum())))
            panel.hdri_light.setChecked(bool(spec.get("light", True)))
        else:
            panel.hdri.setCurrentIndex(0)
        log.setdefault("t", {})[key] = time.time()
        note("render", key, json.dumps(panel.hdri_settings()))
        panel.render()

    def done(path):
        run = keys.pop(0)
        key = run["name"] if isinstance(run, dict) else run
        took = time.time() - log["t"][key]
        if path is None:
            note("FAILED", key, panel.status.text())
        else:
            shutil.copyfile(path, out / f"{key}.png")
            note("ok", key, f"{took:.1f}s")
        QTimer.singleShot(200, next_one)

    def wrap_up():
        try:
            win = panel.window
            if win is not None:
                for k, v in (cfg.get("adjust") or {}).items():
                    s = win.adj[k]
                    lo, hi = float(s.property("lo")), float(s.property("hi"))
                    s.setValue(int(round((v - lo) / (hi - lo) * s.maximum())))
                win.save_to(str(out / "adjusted.png"))
                win.grab().save(str(out / "image_window.png"))
            dock = panel.parentWidget()
            panel.grab().save(str(out / "panel.png"))
            note("pictures saved")
            finish(True)
        except Exception:  # noqa: BLE001
            note("wrap-up failed", traceback.format_exc())
            finish(False)

    QTimer.singleShot(int(cfg.get("delay_ms", 3000)), load)
    QTimer.singleShot(int(cfg.get("timeout_s", 600)) * 1000, lambda: (note("timeout"), finish(False)))
