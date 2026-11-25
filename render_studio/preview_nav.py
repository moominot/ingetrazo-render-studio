# SPDX-License-Identifier: GPL-3.0-or-later
"""Moving the camera from the preview window, as in the 3D view.

While the window shows the live view, a drag orbits, Shift pans and the wheel zooms towards the pointer, with IngeTrazo's own
pivot, zoom and preferences. With «Sync camera» on it is the 3D view's camera that moves (and the preview follows it, as
always); off, it is the camera the preview keeps, and the 3D view stays where it is. Ctrl keeps the picture's own zoom and
pan (to look closely at its pixels). In the other states the view is a plain :class:`widgets.ZoomView`.
"""
from __future__ import annotations

import contextlib
import logging

from PySide6.QtCore import QPointF, Qt, Signal

from .widgets import ZoomView

_log = logging.getLogger(__name__)


class Navigator:
    """The camera moves, in the pixels of the picture as it is on screen."""

    def __init__(self, panel):
        self.panel = panel

    # -- whose camera -------------------------------------------------------------------
    def _viewport(self):
        return self.panel.app.viewport

    def _live(self):
        return getattr(self.panel, "_live", None)

    def _kept(self):
        """The camera the preview keeps (Sync camera off), or None: the 3D view's is the one."""
        live = self._live()
        if live is not None and not live.follow_camera:
            return live.frozen_camera
        return None

    def available(self) -> bool:
        live = self._live()
        return live is not None and live.active

    def camera(self):
        kept = self._kept()
        return kept if kept is not None else self._viewport().camera

    @contextlib.contextmanager
    def _as_viewports_camera(self):
        """The 3D view's own picking and zoom work on ITS camera: for a moment, the one the preview keeps is that camera
        (nothing is drawn meanwhile)."""
        kept, vp = self._kept(), self._viewport()
        if kept is None:
            yield vp
            return
        own = vp.camera
        vp.camera = kept
        try:
            yield vp
        finally:
            vp.camera = own

    def _moved(self) -> None:
        if self._kept() is not None:
            self._live().camera_moved()
        else:
            self._viewport().update()

    # -- where the pointer is, in the 3D view's pixels --------------------------------------
    def _in_viewport(self, fx: float, fy: float):
        """The 3D view's pixel that shows what the picture shows at (``fx``, ``fy``) (fractions of its width and height). Both
        have the same field of view from top to bottom; across, the picture may be narrower or wider than the view."""
        vp = self._viewport()
        w, h = float(vp.width()), float(vp.height())
        aspect = float(self.panel._aspect())
        return w / 2.0 + (fx - 0.5) * aspect * h, fy * h

    # -- the three moves --------------------------------------------------------------------
    def begin(self, fx: float, fy: float):
        """What a drag that starts here turns around, and how far that is (for the pan): (pivot or None, depth or None)."""
        pivot = depth = None
        try:
            with self._as_viewports_camera() as vp:
                pivot = vp._orbit_pivot_at(*self._in_viewport(fx, fy))
                depth = vp._depth_of(pivot)
        except Exception:  # noqa: BLE001 - another IngeTrazo: around the camera's target
            _log.debug("no pivot under the pointer", exc_info=True)
        return pivot, depth

    def orbit(self, dx: float, dy: float, height: float, pivot=None) -> None:
        if getattr(self._viewport(), "_invert_orbit_y", False):
            dy = -dy
        cam = self.camera()
        if pivot is not None:
            cam.orbit_about(pivot, dx, dy, int(max(1.0, height)))
        else:
            cam.orbit(dx, dy, int(max(1.0, height)))
        self._moved()

    def pan(self, dx: float, dy: float, height: float, depth=None) -> None:
        self.camera().pan(dx, dy, int(max(1.0, height)), depth=depth)
        self._moved()

    def zoom(self, steps: float, fx: float, fy: float) -> None:
        if getattr(self._viewport(), "_invert_wheel", False):
            steps = -steps
        try:
            with self._as_viewports_camera() as vp:
                vp._zoom_at(steps, QPointF(*self._in_viewport(fx, fy)))
        except Exception:  # noqa: BLE001 - another IngeTrazo: towards the middle
            _log.debug("zoom towards the pointer failed", exc_info=True)
            self.camera().zoom(steps)
        self._moved()

    def middle_pans(self) -> bool:
        """IngeTrazo's preference «Middle-button drag pans»."""
        return bool(getattr(self._viewport(), "_middle_drag_pans", False))


class PreviewView(ZoomView):
    """The window's picture: while ``navigating()``, the mouse moves the camera. ``menu_asked`` is a right click."""

    menu_asked = Signal(QPointF)            # the global position of a right click

    def __init__(self, parent=None, navigator: Navigator | None = None):
        super().__init__(parent)
        self.navigator = navigator
        self.live_state = False             # the window shows the live view
        self._drag = None                   # (button, last position, pivot, depth)

    def navigating(self) -> bool:
        return bool(self.live_state and self.navigator is not None and self.navigator.available() and self.has_picture())

    def set_live_state(self, on: bool) -> None:
        self.live_state = bool(on)
        self._end()
        live = self.live_state and self.navigator is not None
        # (no tool tip over a picture one is moving about in: the ? button says how)
        self.setToolTip("" if live else "Wheel: zoom · drag: move · double click: fit / 100 %")
        self.setDragMode(ZoomView.NoDrag if live else ZoomView.ScrollHandDrag)
        if live:
            self.viewport().setCursor(Qt.OpenHandCursor)

    def _picture_rect(self):
        return self.mapFromScene(self.sceneRect()).boundingRect()

    def _fraction(self, pos) -> tuple[float, float]:
        r = self._picture_rect()
        if r.width() <= 0 or r.height() <= 0:
            return 0.5, 0.5
        return (pos.x() - r.x()) / r.width(), (pos.y() - r.y()) / r.height()

    def _end(self) -> None:
        if self._drag is not None:
            self._drag = None
            self.viewport().setCursor(Qt.OpenHandCursor)

    # -- the mouse ------------------------------------------------------------------------
    def mousePressEvent(self, ev) -> None:       # noqa: N802 (Qt)
        if self.navigating() and ev.button() in (Qt.LeftButton, Qt.MiddleButton):
            if ev.modifiers() & Qt.ControlModifier:                      # the picture itself, moved about
                self._drag = ("picture", ev.position(), None, None)
            else:
                pivot, depth = self.navigator.begin(*self._fraction(ev.position()))
                self._drag = (ev.button(), ev.position(), pivot, depth)
            self.viewport().setCursor(Qt.ClosedHandCursor)
            self.setFocus()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:        # noqa: N802
        if self._drag is None:
            if self.navigating():
                ev.accept()
                return
            return super().mouseMoveEvent(ev)
        if ev.buttons() == Qt.NoButton:          # a release that never arrived
            self._end()
            return
        button, last, pivot, depth = self._drag
        now = ev.position()
        dx, dy = now.x() - last.x(), now.y() - last.y()
        self._drag = (button, now, pivot, depth)
        if button == "picture":
            for bar, d in ((self.horizontalScrollBar(), dx), (self.verticalScrollBar(), dy)):
                bar.setValue(bar.value() - round(d))
        else:
            shift = bool(ev.modifiers() & Qt.ShiftModifier)
            pans = shift != self.navigator.middle_pans() if button == Qt.MiddleButton else shift
            height = self._picture_rect().height()
            if pans:
                self.navigator.pan(dx, dy, height, depth)
            else:
                self.navigator.orbit(dx, dy, height, pivot)
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:     # noqa: N802
        if self._drag is not None:
            self._end()
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev) -> None:            # noqa: N802
        if self.navigating() and not (ev.modifiers() & Qt.ControlModifier):
            dy = ev.angleDelta().y()
            if dy:
                self.navigator.zoom(dy / 120.0, *self._fraction(ev.position()))
            ev.accept()
            return
        super().wheelEvent(ev)

    def contextMenuEvent(self, ev) -> None:      # noqa: N802
        if self.has_picture():
            self.menu_asked.emit(QPointF(ev.globalPos()))
            ev.accept()
