# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit a material's picture in another program (GIMP, Krita, Photoshop, the system's own) and have the
material take it back when it is saved.

The picture is copied to a working folder and opened there, so the original file is never touched. The
folder is watched: whenever an image in it is saved (File ▸ Overwrite, or Export As with any name or
format) the material's picture is replaced in the model by it, with the same reach and undo step as
«Change picture…» (``texture_swap``): every face and object that wears it changes, the live preview and the
render follow, and each save is one undo step.
"""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QProcess, QSettings, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage

from .i18n import tr

_log = logging.getLogger(__name__)

SETTINGS_KEY = "render_studio/image_editor"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".tga")
#: Where programs of this kind usually are on Windows (the first one that exists is used).
_CANDIDATES = (
    r"C:\Program Files\GIMP 3\bin\gimp-3*.exe",
    r"C:\Program Files\GIMP 2\bin\gimp-2*.exe",
    r"C:\Program Files\Krita (x64)\bin\krita.exe",
)


def find_editor() -> str:
    """The program chosen (remembered), else a GIMP or Krita found where they are installed, else ''
    (then the system's own program for the file is used)."""
    chosen = str(QSettings().value(SETTINGS_KEY, "") or "")
    if chosen and Path(chosen).is_file():
        return chosen
    import glob
    for pattern in _CANDIDATES:
        found = sorted(glob.glob(pattern))
        found = [f for f in found if "console" not in f.lower()]
        if found:
            return found[-1]
    return ""


def remember_editor(path: str) -> None:
    QSettings().setValue(SETTINGS_KEY, str(path or ""))


def open_in_program(program: str, path) -> bool:
    """Open ``path`` in ``program``, or in the system's own program for it when there is none."""
    if program:
        proc = QProcess()
        res = proc.startDetached(program, [str(path)])
        return res[0] if isinstance(res, tuple) else bool(res)
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))


def _safe(name: str) -> str:
    return re.sub(r"[^\w\-. ]+", "_", name).strip() or "material"


class PictureEdit(QObject):
    """One picture being edited outside: the working copy, the watch on its folder, and the swap into the
    model when it is saved. ``changed(message)`` is said after each swap, ``failed(message)`` when something
    is wrong."""
    changed = Signal(str)
    failed = Signal(str)

    def __init__(self, app, name, parent=None, *, debounce_ms: int = 700, root=None):
        super().__init__(parent)
        self.app, self.name = app, name
        self.folder = None
        self.file = None
        self.could_not_open = False                     # the picture was ready, no program opened it
        self._seen = {}                                  # file → (mtime, size) already taken into the model
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._schedule)
        self._watcher.fileChanged.connect(self._schedule)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self._check)
        self._root = Path(root) if root else Path(tempfile.gettempdir()) / "render-studio-edit"
        self.swaps = 0

    def start(self, program: str = "") -> bool:
        """Copy the picture, open the copy, watch. False (and ``failed``) when it cannot."""
        from . import texture_swap
        src = texture_swap.material_picture(self.app.scene, self.name)
        if not src or not Path(src).is_file():
            self.failed.emit(tr("«{name}» has no picture file to edit.", name=self.name))
            return False
        self.folder = self._root / f"{_safe(self.name)}-{time.strftime('%H%M%S')}"
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            self.file = self.folder / (_safe(self.name) + Path(src).suffix.lower())
            shutil.copyfile(src, self.file)
        except OSError as exc:
            self.failed.emit(tr("Could not prepare the picture: {error}", error=exc))
            return False
        self._remember(self.file)
        self._watcher.addPath(str(self.folder))
        self._watcher.addPath(str(self.file))
        if not open_in_program(program, self.file):
            self.could_not_open = True
            self.stop()
            self.failed.emit(tr("Could not open the picture in {program}.", program=program or tr("the system's program")))
            return False
        return True

    def stop(self) -> None:
        self._timer.stop()
        paths = self._watcher.files() + self._watcher.directories()
        if paths:
            self._watcher.removePaths(paths)

    # -- watching --------------------------------------------------------------------------------
    def _remember(self, p: Path) -> None:
        try:
            st = p.stat()
            self._seen[str(p)] = (st.st_mtime_ns, st.st_size)
        except OSError:
            pass

    def _schedule(self, *_a) -> None:
        self._timer.start()                              # the program may write in several goes

    def _newest_change(self):
        """The image in the folder saved since it was last taken (the newest), or None."""
        best = None
        for p in self.folder.iterdir():
            if p.suffix.lower() not in IMAGE_SUFFIXES or not p.is_file():
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if self._seen.get(str(p)) == (st.st_mtime_ns, st.st_size):
                continue
            if best is None or st.st_mtime_ns > best[0]:
                best = (st.st_mtime_ns, p)
        return best[1] if best else None

    def _check(self) -> None:
        if self.folder is None or not self.folder.is_dir():
            return
        # A program that saves by writing a new file and renaming it drops the watch on the old one.
        for path in (self.file, self.folder):
            if path is not None and str(path) not in self._watcher.files() + self._watcher.directories() and Path(path).exists():
                self._watcher.addPath(str(path))
        p = self._newest_change()
        if p is None:
            return
        img = QImage(str(p))
        if img.isNull():                                 # still being written: the next change tries again
            return
        self._remember(p)
        from . import texture_swap
        done, message = texture_swap.swap_picture(self.app, self.name, p, True)
        if done:
            self.swaps += 1
            self.changed.emit(tr("{name} took {file} from the other program ({n}).", name=self.name, file=p.name, n=self.swaps))
        else:
            self.failed.emit(message)


def editor_name(program: str = "") -> str:
    """A short name for the program that edits pictures: «GIMP», «Krita», the file's name, or '' when the
    system's own program is used."""
    program = program if program else find_editor()
    if not program:
        return ""
    stem = Path(program).stem
    low = stem.lower()
    if "gimp" in low:
        return "GIMP"
    if "krita" in low:
        return "Krita"
    return stem[:1].upper() + stem[1:]
