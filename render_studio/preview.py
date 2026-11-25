# SPDX-License-Identifier: GPL-3.0-or-later
"""The preview window: where Render Studio shows its pictures.

It is the one place to look at the scene and to make the final picture, in three states:

* **preview** (the live view): a quick draft that follows the 3D view and the model, in which the
  mouse moves the camera (preview_nav.py). Buttons: **Save this picture…** (what is on screen, as it
  is), **Render** (makes the final picture, then shows the retouch tools) and, under its arrow,
  **Render and save…** (makes it and saves it straight away, with no retouching).
* **rendering**: the progress, and Cancel.
* **final**: the finished picture with the retouch sliders (instant, no new render), **Save image…**
  and **Back to preview**.

Alone (``panel`` None, as the tests use it) it is just the final-picture viewer.
"""
from __future__ import annotations

from .i18n import tr, translate_on_show  # noqa: F401

from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QMenu, QScrollArea, QProgressBar, QPushButton, QSizePolicy, QToolButton, QVBoxLayout,
                               QWidget)

from . import icons, wheel_guard
from . import post
from .preview_nav import Navigator, PreviewView
from .widgets import Card, ChoiceButtons, SliderRow, flat_style, slider, split_button, value, set_value

_SETTINGS = "render_studio/"
#: Every control of the window's bar is this tall, with icons of BAR_ICON (pixels).
BAR_HEIGHT, BAR_ICON = 32, 20
#: The bar: one faint rounded strip; its buttons have no ground of their own until the pointer is on them. The one that
#: matters most in each state (``primary``) is tinted with the accent.
BAR_STYLE = """
QFrame#rs_window_bar {{ background: rgba(128,128,128,26); border-radius: 8px; }}
QFrame#rs_window_bar QPushButton, QFrame#rs_window_bar QToolButton {{
    border: none; border-radius: 5px; padding: 0px 10px; background: transparent; color: palette(button-text); }}
QFrame#rs_window_bar QPushButton:hover, QFrame#rs_window_bar QToolButton:hover {{ background: rgba(128,128,128,60); }}
QFrame#rs_window_bar QPushButton:pressed, QFrame#rs_window_bar QToolButton:pressed {{ background: rgba(128,128,128,95); }}
QFrame#rs_window_bar QPushButton:disabled, QFrame#rs_window_bar QToolButton:disabled {{ color: palette(mid); }}
QFrame#rs_window_bar QToolButton[popupMode="1"] {{ padding: 0px 24px 0px 10px; }}
QFrame#rs_window_bar QToolButton::menu-button {{ border: none; border-left: 1px solid rgba(128,128,128,70); width: 18px;
    border-top-right-radius: 5px; border-bottom-right-radius: 5px; }}
QFrame#rs_window_bar QToolButton::menu-button:hover {{ background: rgba(128,128,128,60); }}
QFrame#rs_window_bar QToolButton::menu-arrow {{ width: 8px; height: 8px; }}
QFrame#rs_window_bar QToolButton[primary="true"], QFrame#rs_window_bar QPushButton[primary="true"] {{
    background: rgba({r},{g},{b},70); }}
QFrame#rs_window_bar QToolButton[primary="true"]:hover, QFrame#rs_window_bar QPushButton[primary="true"]:hover {{
    background: rgba({r},{g},{b},120); }}
QFrame#rs_window_bar QToolButton[primary="true"]:disabled {{ background: rgba(128,128,128,20); }}
QFrame#rs_window_bar QToolButton:checked {{ background: rgba({r},{g},{b},80); }}
QFrame#rs_window_bar QToolButton:checked:hover {{ background: rgba({r},{g},{b},120); }}
QFrame#rs_window_bar QToolButton[square="true"] {{ padding: 0px; }}
"""
#: The narrowest the window goes; below what the bar's words need, the quality and «New scene…» show their icons alone.
MIN_WINDOW_WIDTH = 760
#: The side bar's width: the sliders and their words fit, the picture keeps the rest.
SIDE_WIDTH = 360

NOTES = {
    "preview": "Live preview: a quick draft that follows your 3D view. Drag: orbit · Shift+drag: pan · wheel: zoom · "
               "Ctrl+wheel or Ctrl+drag: look closely at the picture · right click: save or copy it.",
    "rendering": "Rendering the final picture…",
    "final": "Final picture. The sliders retouch it instantly (the scene is not rendered again); "
             "Save image… saves what you see.",
}


class ImageWindow(QWidget):
    """The picture, with zoom and pan; see the module's docstring for the three states."""

    def __init__(self, parent=None, panel=None):
        super().__init__(parent, Qt.Window)
        self.panel = panel
        self.setWindowTitle("Render Studio")
        self.setMinimumWidth(MIN_WINDOW_WIDTH)
        self._compact, self._full_bar, self._scene_words = False, 0, ""
        self.resize(1100, 780)
        self.path = None
        self.original = None            # H×W×3 uint8 of the final picture
        self.shown = None               # …as retouched
        self.alpha = None               # H×W uint8 when the sky was left transparent
        self.rendered_file = None       # a 16-bit or EXR file Blender wrote, saved as it is
        self.rendered_label = ""
        self.lines = None               # (LineSet, style): the outlines, still vectors, over the picture without them
        self._lines_base = None
        self._lines_timer = None
        self.mode = "final"
        self._saved_to = None
        lay = QVBoxLayout(self)

        # -- the picture: the whole top of the window
        self.view = PreviewView(navigator=Navigator(panel) if panel is not None else None)
        self.view.menu_asked.connect(self._picture_menu)
        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.addWidget(self.view, 1)
        # The finished picture's tools (the retouch and the outlines) are a panel beside it, which a handle on its
        # edge (as IngeTrazo's own side trays have) hides and shows: more picture when it is not needed.
        self.side = QWidget()
        self.side.setFixedWidth(SIDE_WIDTH)
        side_outer = QVBoxLayout(self.side)
        side_outer.setContentsMargins(0, 0, 0, 0)
        side_outer.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        side_body = QWidget()
        self.side_lay = QVBoxLayout(side_body)
        self.side_lay.setContentsMargins(0, 0, 6, 0)
        scroll.setWidget(side_body)
        side_outer.addWidget(scroll, 1)
        self.side_footer = QVBoxLayout()
        self.side_footer.setContentsMargins(0, 0, 6, 0)
        self.side_footer.setSpacing(4)
        side_outer.addLayout(self.side_footer)
        mid.addWidget(self.side)
        lay.addLayout(mid, 1)

        # -- the bar, at the top: the way back to the panel and help, then what the state needs
        self.tool_bar = QFrame()
        self.tool_bar.setObjectName("rs_window_bar")
        controls = QHBoxLayout(self.tool_bar)
        controls.setContentsMargins(4, 4, 4, 4)
        controls.setSpacing(4)
        self.panel_btn = QPushButton("Panel")
        self.panel_btn.setIcon(icons.icon("side_panel"))
        self.panel_btn.setToolTip("Brings Render Studio's panel into view (this window moves aside if it covers it)")
        self.panel_btn.clicked.connect(lambda: self.show_panel())
        self.panel_btn.setVisible(panel is not None)
        controls.addWidget(self.panel_btn)
        self.help_btn = QToolButton()
        self.help_btn.setText("?")
        self.help_btn.setFixedWidth(BAR_HEIGHT)
        self.help_btn.clicked.connect(self._help)
        controls.addWidget(self.help_btn)
        controls.addWidget(self._separator())
        lay.insertWidget(0, self.tool_bar)

        # -- preview: what is on screen and what Render will make; the quality, a new scene, save this picture, Render
        self.bar_preview = QWidget()
        main = QHBoxLayout(self.bar_preview)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(4)
        self.info_row = QWidget()
        info = QHBoxLayout(self.info_row)
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(12)
        self.preview_info = QLabel("")
        self.summary = QLabel("")
        for label in (self.preview_info, self.summary):
            label.setStyleSheet("color: gray")
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)      # (never widens the window)
        self.summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        info.addWidget(self.preview_info, 2)
        info.addWidget(self.summary, 3)
        lay.addWidget(self.info_row)                           # under the picture, above the messages
        self.preview_info.setToolTip("The picture on screen: «Save picture…» saves exactly this one. With High "
                                     "preview quality it is as big as the window shows it.")
        self.summary.setToolTip("The final picture, made anew with the engine, quality and size set in the panel: more "
                                "samples and every effect. The preview is a draft of it.")
        # the live view's switches: the toolbar's own commands, so both always say the same
        self.sync_buttons = []
        commands = getattr(panel, "commands", None)
        for name in ("follow_camera", "follow_changes", "update") if commands is not None else ():
            button = QToolButton()
            button.setDefaultAction(getattr(commands, name))
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setProperty("square", True)
            button.setFixedWidth(BAR_HEIGHT + 4)
            self.sync_buttons.append(button)
            main.addWidget(button)
        main.addStretch(1)
        self._link_quality()
        if self.quality_buttons is not None:
            main.addWidget(self.quality_buttons)
        main.addWidget(self._separator())
        self.scene_btn = QPushButton("New scene…")
        self.scene_btn.setIcon(icons.icon("grp_camera"))
        self.scene_btn.setToolTip("Saves the view this preview shows (the camera it keeps while Follow the camera is off, "
                                  "else the 3D view's) as a scene of the drawing, to come back to it or render it later.")
        self.scene_btn.clicked.connect(lambda: self.panel and self.panel.scene_from_preview())
        main.addWidget(self.scene_btn)               # always in view
        self.copy_action = QAction("Copy picture", self)
        self.copy_action.triggered.connect(lambda: self.copy_picture())
        self.snapshot_btn = split_button(
            "Save picture…", lambda: self.save_snapshot(),
            "Saves the picture on screen, as it is, without rendering anything. The arrow: Copy picture. "
            "Also with a right click on the picture.", [self.copy_action])
        self._in_bar(self.snapshot_btn, "save")
        main.addWidget(self.snapshot_btn)
        self.expert_btn = QAction("Open in Blender…", self)
        self.expert_btn.setToolTip("Expert mode: opens this scene, as Render would make it, in a Blender with its own "
                                   "window to work in it. Nothing is rendered; the file is saved first.")
        self.expert_btn.triggered.connect(lambda: self.panel and self.panel.open_in_blender())
        self.render_save_btn = QAction("Render and save…", self)
        self.render_save_btn.setToolTip("Asks where to save, makes the final picture and saves it straight away, "
                                        "without retouching.")
        self.render_save_btn.triggered.connect(lambda: self.panel and self.panel.render_and_save())
        self.render_btn = split_button(
            "Render", lambda: self.panel and self.panel.render_main(),
            "Makes the final picture with the panel's engine, quality and width, then shows the retouch tools and "
            "Save image…. The arrow: Render and save…, Open in Blender….", [self.render_save_btn, self.expert_btn])
        self._in_bar(self.render_btn, "capture", primary=True)
        main.addWidget(self._separator())
        main.addWidget(self.render_btn)
        controls.addWidget(self.bar_preview, 1)

        # -- final: the retouch sliders, the outlines and Save, all in the side panel (everything in view: there is room)
        box = Card(tr("Retouch"), "window_retouch", icon="grp_corrections", kind="column")
        form = box.body_layout
        self.adj, self.adj_rows = {}, {}
        for key, label, lo, hi, fmt, hint in post.ADJUSTMENTS:
            s_ = slider(lo, hi, post.NEUTRAL[key])
            s_.valueChanged.connect(self._refresh)
            row = SliderRow(s_, fmt, hint)
            self.adj[key], self.adj_rows[key] = s_, row
            line = QHBoxLayout()
            name = QLabel(label)
            name.setMinimumWidth(96)
            name.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            line.addWidget(name)
            line.addWidget(row, 1)
            form.addLayout(line)
        self.side_lay.addWidget(box)
        self._build_lines_box(self.side_lay)
        self.side_lay.addStretch(1)
        self.reset_btn = QPushButton("Reset retouch")
        self.reset_btn.setIcon(icons.icon("undo"))
        self.reset_btn.setMinimumHeight(28)
        self.reset_btn.setToolTip("Puts every retouch slider back to neutral (the picture as rendered)")
        self.reset_btn.clicked.connect(self._reset)
        self.back_btn = QPushButton("Back to preview")
        self.back_btn.setIcon(icons.icon("preview"))
        self.back_btn.setToolTip("Closes the final picture and returns to the live preview, to change the scene "
                                 "and render again")
        self.back_btn.clicked.connect(lambda: self.panel and self.panel.back_to_preview())
        self.save_btn = QPushButton("Save image…")
        self.save_btn.setIcon(icons.icon("save"))
        self.save_btn.setToolTip("Saves the picture as you see it (with the retouching) as PNG or JPEG")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setProperty("primary", True)
        self.save_btn.setAutoDefault(False)
        self.side_footer.addWidget(self.reset_btn)      # only what belongs to the panel's own sliders: the way out is below, always in view
        # Back to preview and Save image… are NOT in the panel: they stay at the bottom, whether the panel is shown or folded.
        self.bar_final = QWidget()
        frow = QHBoxLayout(self.bar_final)
        frow.setContentsMargins(0, 0, 0, 0)
        frow.setSpacing(4)
        self.fit_btn = QToolButton()                    # the final picture's zoom
        self.fit_btn.setText("Fit")
        self.fit_btn.setToolTip("The whole picture in the window (key 0, or double click)")
        self.actual_btn = QToolButton()
        self.actual_btn.setText("100 %")
        self.actual_btn.setToolTip("One picture pixel per screen pixel (key 1, or double click)")
        self.zoom_label = QLabel("")
        self.zoom_label.setMinimumWidth(44)
        self.zoom_label.setStyleSheet("color: gray")
        self.view.zoomed.connect(lambda p: self.zoom_label.setText(f"{p:.0f} %"))
        self.fit_btn.clicked.connect(self.view.fit)
        self.actual_btn.clicked.connect(lambda: self.view.actual_size())
        for w in (self.fit_btn, self.actual_btn):
            frow.addWidget(w)
        frow.addWidget(self.zoom_label)
        frow.addStretch(1)
        frow.addWidget(self.back_btn)
        frow.addWidget(self.save_btn)
        controls.addWidget(self.bar_final, 1)

        # -- the last line: only what is going on (and a render's progress, time and Cancel)
        prow = QHBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(lambda: self.panel and self.panel.cancel_render())
        from .widgets import ClockLabel
        self.clock = ClockLabel()
        prow.addWidget(self.status, 1)
        prow.addWidget(self.clock)
        prow.addWidget(self.bar)
        prow.addWidget(self.cancel_btn)
        lay.addLayout(prow)
        flat = flat_style()
        for w in (self.side, self.cancel_btn):
            w.setStyleSheet(flat)
        accent = icons._accent()
        self.tool_bar.setStyleSheet(BAR_STYLE.format(r=accent.red(), g=accent.green(), b=accent.blue()))
        quality = self.quality_buttons._buttons if self.quality_buttons is not None else []
        for w in (self.panel_btn, self.help_btn, *self.sync_buttons, *quality, self.scene_btn, self.snapshot_btn,
                  self.render_btn, self.fit_btn, self.actual_btn, self.back_btn, self.save_btn):      # one height for all
            w.setFixedHeight(BAR_HEIGHT)
            if hasattr(w, "setIconSize"):
                w.setIconSize(QSize(BAR_ICON, BAR_ICON))
        self._resharpen = QTimer(self)                # High quality follows the window's size, once it rests
        self._resharpen.setSingleShot(True)
        self._resharpen.setInterval(600)
        self._resharpen.timeout.connect(self._sharpen)
        self._side_open = str(QSettings().value(_SETTINGS + "side_open", "true")).lower() != "false"
        self._build_side_handle()
        self.set_mode("final" if panel is None else "preview")
        wheel_guard.watch(self)          # (the wheel scrolls; it changes only a picked field)

    # -- the side panel's handle: IngeTrazo's own (a chevron on the line between the picture and the panel) --------------------

    def _build_side_handle(self) -> None:
        from PySide6.QtCore import QSize
        h = QToolButton(self)
        h.setFixedSize(14, 56)
        h.setIconSize(QSize(12, 12))
        h.setAutoRaise(True)
        h.setCursor(Qt.PointingHandCursor)
        h.clicked.connect(lambda: self._set_side_open(not self._side_open))
        qss = ("QToolButton {{ background: palette(mid); border: none; border-radius: 4px; }}"
               "QToolButton:hover {{ background: rgb({accent_rgb}); }}")
        try:
            from views.theme import style as theme_style          # the accent colour of Preferences
            theme_style(h, qss)
        except Exception:  # noqa: BLE001 - outside IngeTrazo (tests): the palette's highlight
            h.setStyleSheet(qss.replace("rgb({accent_rgb})", "palette(highlight)").replace("{{", "{").replace("}}", "}"))
        self.side_handle = h
        self._apply_side()

    def _chevron(self, right: bool):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap
        from PySide6.QtWidgets import QApplication
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(24 * dpr), int(24 * dpr))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.scale(dpr, dpr)
        pen = QPen(QApplication.palette().windowText().color(), 2.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        x0, x1 = (8.0, 16.0) if right else (16.0, 8.0)
        p.drawPolyline([QPointF(x0, 5.0), QPointF(x1, 12.0), QPointF(x0, 19.0)])
        p.end()
        pm.setDevicePixelRatio(dpr)
        return QIcon(pm)

    def _set_side_open(self, on: bool) -> None:
        self._side_open = bool(on)
        try:
            QSettings().setValue(_SETTINGS + "side_open", "true" if on else "false")
        except Exception:  # noqa: BLE001
            pass
        self._apply_side()

    def _apply_side(self) -> None:
        """The side panel shown (a finished picture, panel open) or folded; the handle's chevron points the way it will go."""
        from PySide6.QtCore import QTimer
        final = self.mode == "final"
        self.side.setVisible(final and self._side_open)
        self.side_handle.setVisible(final)
        self.side_handle.setIcon(self._chevron(self._side_open))
        self.side_handle.setToolTip(tr("Hide the retouch and outlines panel") if self._side_open else tr("Show the retouch and outlines panel"))
        QTimer.singleShot(0, self._place_side_handle)

    def _place_side_handle(self) -> None:
        """On the line between the picture and the panel, half-way down; at the window's edge when the panel is folded."""
        from PySide6.QtCore import QPoint
        h = getattr(self, "side_handle", None)
        if h is None or not h.isVisible():
            return
        edge = self.view.mapTo(self, QPoint(self.view.width(), 0))
        x = max(0, min(edge.x() - h.width() // 2, self.width() - h.width()))
        h.move(x, max(0, edge.y() + (self.view.height() - h.height()) // 2))
        h.raise_()

    def resizeEvent(self, ev) -> None:           # noqa: N802 (Qt)
        super().resizeEvent(ev)
        self._place_side_handle()
        self._fit_bar()
        if hasattr(self, "_resharpen"):
            self._resharpen.start()

    def showEvent(self, ev) -> None:             # noqa: N802 (Qt)
        super().showEvent(ev)
        QTimer.singleShot(0, self._place_side_handle)
        QTimer.singleShot(0, self._fit_bar)

    # -- the outlines: vectors until the picture is saved ----------------------------------------
    def _build_lines_box(self, parent_layout) -> None:
        from PySide6.QtCore import QTimer
        from .section_panel import ColourButton
        from .widgets import NumberSlider
        self.lines_box = Card(tr("Outlines"), "window_outlines", icon="grp_outline")
        form = self.lines_box.form

        def heading(text):
            lab = QLabel(text)
            f = lab.font()
            f.setBold(True)
            lab.setFont(f)
            return lab
        # the model's own lines
        top = QHBoxLayout()
        self.lines_on = QCheckBox(tr("Outlines of the model"))
        self.lines_colour = ColourButton([0.05, 0.05, 0.05], "Outline colour", linear=True)
        self.lines_colour.setMaximumWidth(60)
        self.lines_reset = QPushButton(tr("As rendered"))
        self.lines_reset.setToolTip(tr("The outlines as the panel's style drew them"))
        top.addWidget(self.lines_on)
        top.addWidget(self.lines_colour)
        top.addStretch(1)
        top.addWidget(self.lines_reset)
        form.addRow(top)
        self.lines_width = NumberSlider(0.0, 10.0, 0.1, "{:.1f} px", special="No outlines")
        self.lines_width.setToolTip(tr("The thickness of the model's lines, in pixels of this picture. 0: no outlines"))
        self.lines_hand = NumberSlider(0.0, 1.0, 0.05, "{:.0%}")
        self.lines_hand.setToolTip(tr("From a ruler (0: straight lines, the same width all along) to a loose hand: wavering, swelling, drawn twice, broken"))
        self.lines_extend = NumberSlider(0.0, 50.0, 1.0, "{:.0f} cm")
        self.lines_extend.setToolTip(tr("How far the lines run past their corners, in centimetres of the model (estimated at the model's own "
                                        "distance from the camera). A ruler goes exactly that far; a hand, a little less or more"))
        self.lines_opacity = NumberSlider(0.2, 1.0, 0.05, "{:.0%}")
        self.lines_opacity.setToolTip(tr("How dark the ink is (the model's lines and the cut's)"))
        form.addRow(tr("Line thickness"), self.lines_width)
        form.addRow(tr("Hand"), self.lines_hand)
        form.addRow(tr("Line extension"), self.lines_extend)
        form.addRow(tr("Ink"), self.lines_opacity)
        # the rim of the cap, when a section cuts the model: apart from the model's lines, with its own colour and thickness (always a ruled line)
        self.cut_row = QWidget()
        cr = QHBoxLayout(self.cut_row)
        cr.setContentsMargins(0, 0, 0, 0)
        self.cut_on = QCheckBox(tr("Cut outline"))
        self.cut_colour = ColourButton([0.05, 0.05, 0.05], "Colour of the cap's outline")
        self.cut_colour.setMaximumWidth(60)
        cr.addWidget(self.cut_on)
        cr.addWidget(self.cut_colour)
        cr.addStretch(1)
        self.cut_width = NumberSlider(0.5, 10.0, 0.1, "{:.1f} px")
        self.cut_width.setToolTip(tr("The thickness of the rim of the cut, in pixels of this picture"))
        self.cut_width_label = QLabel(tr("Cut thickness"))
        form.addRow(self.cut_row)
        form.addRow(self.cut_width_label, self.cut_width)
        self._lines_timer = QTimer(self)
        self._lines_timer.setSingleShot(True)
        self._lines_timer.setInterval(120)
        self._lines_timer.timeout.connect(self._recompose)
        for sig in (self.lines_on.toggled, self.lines_colour.changed, self.lines_width.valueChanged, self.lines_hand.valueChanged,
                    self.lines_extend.valueChanged, self.lines_opacity.valueChanged, self.cut_on.toggled, self.cut_colour.changed,
                    self.cut_width.valueChanged):
            sig.connect(lambda *_a: self._lines_timer.start())
        self.lines_width.valueChanged.connect(self._width_moved)
        self.lines_on.toggled.connect(self._model_toggled)
        for sig in (self.lines_on.toggled, self.lines_width.valueChanged, self.cut_on.toggled):
            sig.connect(lambda *_a: self._sync_enabled())
        self.lines_reset.clicked.connect(self._lines_to_initial)
        self.lines_box.setVisible(False)
        parent_layout.addWidget(self.lines_box)

    def _width_moved(self, v: float) -> None:
        """Moving the thickness from 0 turns the model's outlines on (it would have done nothing otherwise)."""
        if v > 0.0 and not self.lines_on.isChecked():
            self.lines_on.setChecked(True)

    def _model_toggled(self, on: bool) -> None:
        """Turning the model's outlines on with no thickness gives them a thin one."""
        if on and self.lines_width.value() <= 0.0:
            self.lines_width.setValue(1.5)

    def _sync_enabled(self) -> None:
        """What a control does is what it shows: the model's colour, hand and extension wait while there are no model outlines (their
        thickness 0, or switched off), the cut's colour and thickness while the cut outline is off."""
        model = self.lines_on.isChecked() and self.lines_width.value() > 0.0
        for w in (self.lines_colour, self.lines_hand, self.lines_extend):
            w.setEnabled(model)
        for w in (self.cut_colour, self.cut_width):
            w.setEnabled(self.cut_on.isChecked())

    def set_outlines(self, lines, style: dict, base_path) -> None:
        """The picture's outlines as vectors: ``lines`` (outlines.LineSet), ``style`` (outlines.window_style: where the controls start)
        and ``base_path``, the render without them. Call it after :meth:`set_image`; the controls then restyle the lines instantly."""
        base = QImage(str(base_path))
        if lines is None or base.isNull():
            return self.clear_outlines()
        self.lines = (lines, dict(style))
        self._lines_base = base
        self._lines_set_controls(style)
        self.lines_box.setVisible(True)
        self._recompose()

    def clear_outlines(self) -> None:
        self.lines = None
        self._lines_base = None
        if getattr(self, "lines_box", None) is not None:
            self.lines_box.setVisible(False)

    def _lines_set_controls(self, style: dict) -> None:
        controls = (self.lines_on, self.lines_colour, self.lines_width, self.lines_hand, self.lines_extend, self.lines_opacity,
                    self.cut_on, self.cut_colour, self.cut_width)
        for w in controls:
            w.blockSignals(True)
        width = float(style.get("width", 0.0))
        self.lines_on.setChecked(bool(style.get("model_on", width > 0.0)))
        self.lines_colour.set_rgb(style.get("color") or [0.05, 0.05, 0.05])
        self.lines_width.setValue(width)
        self.lines_hand.setValue(float(style.get("hand", 0.0)))
        cm = style.get("extend_cm")
        self.lines_extend.setValue(float(cm) if cm is not None else float(style.get("extend", 0.0)) * 50.0)
        self.lines_opacity.setValue(float(style.get("opacity", 1.0)))
        cutd = style.get("cut") or {}
        self.cut_on.setChecked(bool(cutd.get("on", True)))
        self.cut_colour.set_rgb(cutd.get("color") or [0.05, 0.05, 0.05])
        self.cut_width.setValue(float(cutd.get("width", 2.4)))
        for w in controls:
            w.blockSignals(False)
        has_cut = bool(self.lines is not None and len(getattr(self.lines[0], "cut", ())))
        self.cut_row.setVisible(has_cut)
        self.cut_width.setVisible(has_cut)
        self.cut_width_label.setVisible(has_cut)
        self._sync_enabled()

    def lines_style(self) -> dict:
        """The outlines' style as the controls say it."""
        base = dict(self.lines[1]) if self.lines else {}
        base.update(width=self.lines_width.value(), color=self.lines_colour.rgb(), hand=self.lines_hand.value(),
                    extend_cm=self.lines_extend.value(), opacity=self.lines_opacity.value(), model_on=self.lines_on.isChecked())
        base.pop("extend", None)
        if base.get("cut") is not None:
            base["cut"] = dict(base["cut"], on=self.cut_on.isChecked(), color=self.cut_colour.rgb(), width=self.cut_width.value(),
                               opacity=self.lines_opacity.value(), srgb=True)
        return base

    def _lines_to_initial(self) -> None:
        if self.lines:
            self._lines_set_controls(self.lines[1])
            self._recompose()

    def _recompose(self) -> None:
        """The picture again: the render without lines, the lines in the controls' style over it, then the retouch."""
        if self.lines is None or self._lines_base is None:
            return
        from . import outlines
        img = outlines.composite(self._lines_base, self.lines[0], self.lines_style())
        self._load_qimage(img)
        self._refresh()

    # -- the three states ------------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        """«preview», «rendering» or «final»: which controls show."""
        self.mode = mode
        has_panel = self.panel is not None
        self.view.set_live_state(mode == "preview" and has_panel)
        self.info_row.setVisible(mode in ("preview", "rendering") and has_panel)
        QTimer.singleShot(0, self._fit_bar)
        self.bar_preview.setVisible(mode in ("preview", "rendering") and has_panel)
        for w in (self.render_btn, self.render_save_btn, self.expert_btn):
            w.setEnabled(mode == "preview")
        self._sync_snapshot()
        self.bar_final.setVisible(mode == "final")
        if hasattr(self, "side_handle"):
            self._apply_side()
        self.back_btn.setVisible(has_panel)
        self.bar.setVisible(mode == "rendering")
        self.cancel_btn.setVisible(mode == "rendering" and has_panel)
        if mode == "rendering":
            self.bar.setValue(0)
        self.help_btn.setToolTip(tr(NOTES[mode]) if has_panel or mode == "final" else "")
        if mode == "final":
            self.status.setText("")

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_clock(self, text) -> None:
        """The render's elapsed time beside the progress (None: no render is running)."""
        self.clock.set_text(text)

    def set_progress(self, fraction: float) -> None:
        if self.bar.maximum() == 0:
            self.bar.setRange(0, 100)
        self.bar.setValue(int(max(0.0, min(1.0, fraction)) * 100))

    def set_busy(self) -> None:
        """A bar that waits (nothing to measure yet: Blender is starting or building the scene)."""
        self.bar.setRange(0, 0)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)

    def has_image(self) -> bool:
        return self.view.has_picture()

    def _help(self):
        from . import ui_help
        ui_help.show(self, "image")

    # -- the picture on screen, saved or copied -----------------------------------------------
    @staticmethod
    def _in_bar(button, icon_key: str, primary: bool = False) -> None:
        """A split button as one of the bar's: its icon beside its words, as wide as they need, in the bar's style."""
        button.setStyleSheet("")                 # (the bar's style, not the one a split button has on its own)
        button.setIcon(icons.icon(icon_key))
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setProperty("primary", primary)
        button.setMinimumWidth(150)

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFixedSize(1, BAR_HEIGHT - 10)
        line.setStyleSheet("background: rgba(128,128,128,80)")
        return line

    # -- the way back to the panel ------------------------------------------------------------
    def show_panel(self) -> None:
        """Render Studio's panel in view, and IngeTrazo's window in front. This window belongs to that one, so it stays
        above it: when it covers the panel it moves beside it (or, with no room beside it, is minimised)."""
        if self.panel is None:
            return
        from .toolbar import show_dock
        if not show_dock(self.panel, self.panel):
            self.panel.show()
        main = self.panel.window_of_the_program()
        if main is not None:
            if main.isMinimized():
                main.showNormal()
            main.raise_()
            main.activateWindow()
        self._uncover(self.panel)

    def _uncover(self, widget) -> None:
        from PySide6.QtCore import QPoint, QRect
        if not (widget.isVisible() and self.isVisible()):
            return
        shown = QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())
        mine = self.frameGeometry()
        if not mine.intersects(shown):
            return
        screen = widget.screen().availableGeometry()
        left = QRect(screen.left(), screen.top(), shown.left() - screen.left(), screen.height())
        right = QRect(shown.right() + 1, screen.top(), screen.right() - shown.right(), screen.height())
        room = max((left, right), key=lambda r: r.width())
        frame_w = mine.width() - self.width()
        frame_h = mine.height() - self.height()
        if room.width() - frame_w < max(self.minimumSizeHint().width(), 640):
            self.showMinimized()
            return
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        width = min(self.width(), room.width() - frame_w)
        height = min(self.height(), room.height() - frame_h)
        x = room.right() + 1 - width - frame_w if room is left else room.left()
        y = max(room.top(), min(mine.top(), room.bottom() + 1 - height - frame_h))
        self.resize(width, height)
        self.move(x, y)

    def _link_quality(self) -> None:
        """The preview's quality, here too: the same choice as the panel's, as three buttons like the panel's own."""
        self.quality_buttons = None
        own = getattr(self.panel, "preview_quality", None)
        if own is None:
            return
        buttons = ChoiceButtons([own.itemText(i) for i in range(own.count())], icons=("q_draft", "q_medium", "q_high"))
        buttons.layout().setSpacing(0)
        buttons.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        tip = tr("Preview quality. High: as sharp as the window shows it, so a picture saved from the preview is bigger "
                 "too. Render has its own quality.")
        for i, button in enumerate(buttons._buttons):                    # in the bar: icon beside the word, one line
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setFont(self.font())
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            button.setToolTip(f"{own.itemText(i)} — {tip}")
        buttons.setCurrentIndex(own.currentIndex())
        buttons.currentIndexChanged.connect(own.setCurrentIndex)
        own.currentIndexChanged.connect(buttons.setCurrentIndex)
        self.quality_buttons = buttons

    def _fit_bar(self) -> None:
        """The words that can go, gone when the window is too narrow for them (their tool tips still say them)."""
        if not hasattr(self, "scene_btn") or self.mode == "final" or self.panel is None:
            return
        if not self._compact:
            self.tool_bar.layout().activate()
            margins = self.layout().contentsMargins()
            self._full_bar = self.tool_bar.sizeHint().width() + margins.left() + margins.right()
        narrow = self.width() < self._full_bar
        if narrow == self._compact:
            return
        self._compact = narrow
        if narrow:
            self._scene_words = self.scene_btn.text()
        self.scene_btn.setText("" if narrow else self._scene_words)
        self.scene_btn.setProperty("square", narrow)
        self.scene_btn.setMinimumWidth(BAR_HEIGHT + 4 if narrow else 0)
        self.scene_btn.style().unpolish(self.scene_btn)
        self.scene_btn.style().polish(self.scene_btn)
        if self.quality_buttons is not None:
            for button in self.quality_buttons._buttons:
                button.setToolButtonStyle(Qt.ToolButtonIconOnly if narrow else Qt.ToolButtonTextBesideIcon)
                button.setProperty("square", narrow)
                button.setMinimumWidth(BAR_HEIGHT if narrow else 0)
                button.setMaximumWidth(BAR_HEIGHT if narrow else (1 << 24) - 1)
                button.style().unpolish(button)
                button.style().polish(button)

    def _sync_snapshot(self) -> None:
        if hasattr(self, "snapshot_btn"):
            on = self.mode == "preview" and self.view.has_picture()
            self.snapshot_btn.setEnabled(on)
            self.copy_action.setEnabled(on)

    def set_preview_info(self, text: str) -> None:
        self.preview_info.setText(text)

    def picture_pixels(self, aspect: float) -> int:
        """How many screen pixels wide a picture of ``aspect`` is when it fits the view."""
        vp = self.view.viewport()
        return int(min(vp.width(), vp.height() * aspect) * self.devicePixelRatioF())

    def _sharpen(self) -> None:
        live = getattr(self.panel, "_live", None)
        own = getattr(self.panel, "preview_quality", None)
        if live is not None and self.mode == "preview" and own is not None and own.currentData() == "high":
            live.sharpen()

    def picture(self) -> QImage:
        """What the window shows, as a picture of its own size: the live frame, or the final picture as retouched (with
        its transparency). Null when there is nothing."""
        if self.mode == "final" and self.shown is not None:
            h, w = self.shown.shape[:2]
            if self.alpha is not None and self.alpha.shape == (h, w):
                import numpy as np
                rgba = np.ascontiguousarray(np.dstack([self.shown, self.alpha]))
                return QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
            return QImage(self.shown.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        return self.view.pixmap().toImage()

    def copy_picture(self) -> bool:
        img = self.picture()
        if img.isNull():
            return False
        QApplication.clipboard().setImage(img)
        self.status.setText(tr("Picture copied ({w} × {h} px).", w=img.width(), h=img.height()))
        return True

    def save_picture(self, path: str, img: QImage | None = None) -> bool:
        """``img`` (default: what the window shows) as PNG or JPEG; what is see-through goes over white in a JPEG."""
        img = self.picture() if img is None else img
        if img.isNull():
            return False
        if Path(path).suffix.lower() in (".jpg", ".jpeg"):
            if img.hasAlphaChannel():
                flat = QImage(img.size(), QImage.Format_RGB32)
                flat.fill(Qt.white)
                painter = QPainter(flat)
                painter.drawImage(0, 0, img)
                painter.end()
                img = flat
            return img.save(path, None, 95)
        return img.save(path)

    def save_snapshot(self) -> None:
        """Asks where, then saves the preview's picture. It is taken when the file has been chosen: the live view goes
        on meanwhile, so a picture that was still being refined is saved refined."""
        if self.picture().isNull():
            return
        from time import strftime
        start = Path(QSettings().value(_SETTINGS + "save_dir", str(Path.home()))) / f"view-{strftime('%Y%m%d-%H%M%S')}.png"
        path, chosen = QFileDialog.getSaveFileName(self, tr("Save this picture"), str(start), "PNG (*.png);;JPEG (*.jpg)")
        if not path:
            return
        if not Path(path).suffix:
            path += ".jpg" if "jpg" in chosen else ".png"
        img = self.picture()
        if self.save_picture(path, img):
            QSettings().setValue(_SETTINGS + "save_dir", str(Path(path).parent))
            self.status.setText(tr("Saved ({w} × {h} px): {path}", w=img.width(), h=img.height(), path=path))
        else:
            self.status.setText(tr("Could not write {path}", path=path))

    def picture_menu(self) -> QMenu:
        """The right click's menu."""
        menu = QMenu(self)
        final = self.mode == "final"
        save_it = menu.addAction(icons.icon("save"), tr("Save image…") if final else tr("Save picture…"))
        save_it.triggered.connect(lambda _c=False: self._save() if final else self.save_snapshot())
        menu.addAction(tr("Copy picture")).triggered.connect(lambda _c=False: self.copy_picture())
        if self.view.navigating():
            menu.addSeparator()
            scene = menu.addAction(icons.icon("grp_camera"), tr("New scene from this view…"))
            scene.triggered.connect(lambda _c=False: self.panel.scene_from_preview())
            if not self.view.is_fitted():
                menu.addAction(tr("Fit")).triggered.connect(lambda _c=False: self.view.fit())
        return menu

    def _picture_menu(self, where) -> None:
        if self.mode != "rendering":
            self.picture_menu().exec(where.toPoint())

    # -- the picture --------------------------------------------------------------------------
    def show_draft(self, path) -> None:
        """A frame of the live view (not retouched; keeps the zoom and place)."""
        pm = QPixmap(str(path))
        if not pm.isNull():
            self.path = Path(path)
            self.view.set_pixmap(pm)
            self._sync_snapshot()

    def set_image(self, path, final: bool = True) -> None:
        """The finished picture, to retouch (``final``), or a live frame."""
        if not final:
            return self.show_draft(path)
        self.path = Path(path)
        self.clear_outlines()
        self._load_qimage(QImage(str(path)))
        was = self.mode
        self.set_mode("final")
        self._refresh(refit=was != "final")

    def _load_qimage(self, src) -> None:
        """``original`` (and ``alpha``, when the sky is clear) from a picture."""
        import numpy as np
        self.alpha = None
        if src.hasAlphaChannel():
            # A transparent sky: straight colours, and the alpha kept apart for saving.
            rgba = src.convertToFormat(QImage.Format_RGBA8888)
            w, h = rgba.width(), rgba.height()
            a = np.frombuffer(rgba.constBits(), dtype=np.uint8, count=rgba.bytesPerLine() * h)
            a = a.reshape(h, rgba.bytesPerLine())[:, : w * 4].reshape(h, w, 4)
            self.alpha = a[..., 3].copy()
            self.original = a[..., :3].copy()
        else:
            img = src.convertToFormat(QImage.Format_RGB888)
            w, h = img.width(), img.height()
            ptr = img.constBits()
            arr = np.frombuffer(ptr, dtype=np.uint8, count=img.bytesPerLine() * h)
            arr = arr.reshape(h, img.bytesPerLine())[:, : w * 3].reshape(h, w, 3)
            self.original = arr.copy()

    def adjustments(self) -> dict:
        return {k: value(s) for k, s in self.adj.items()}

    def _reset(self):
        for key, s in self.adj.items():
            set_value(s, post.NEUTRAL[key])

    def _refresh(self, *_a, refit: bool = False):
        if self.original is None:
            return
        out = post.adjust(self.original, self.adjustments())
        self.shown = out
        h, w = out.shape[:2]
        if self.alpha is not None and self.alpha.shape == (h, w):
            # With its transparency: the view puts its checkerboard behind (widgets.ZoomView.drawBackground).
            import numpy as np
            disp = np.ascontiguousarray(np.dstack([out, self.alpha]))
            qimg = QImage(disp.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
        else:
            qimg = QImage(out.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self.view.set_pixmap(QPixmap.fromImage(qimg), refit=refit is True)

    def save_to(self, path: str) -> bool:
        if self.shown is None:
            return False
        h, w = self.shown.shape[:2]
        jpeg = Path(path).suffix.lower() in (".jpg", ".jpeg")
        if self.alpha is not None and self.alpha.shape == (h, w):
            import numpy as np
            if jpeg:                    # no transparency in a JPEG: over white
                a = self.alpha[..., None].astype(np.float32) / 255.0
                flat = np.ascontiguousarray((self.shown * a + 255.0 * (1.0 - a)).astype(np.uint8))
                return QImage(flat.data, w, h, 3 * w, QImage.Format_RGB888).copy().save(path, None, 95)
            rgba = np.ascontiguousarray(np.dstack([self.shown, self.alpha]))
            return QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy().save(path)
        return QImage(self.shown.data, w, h, 3 * w, QImage.Format_RGB888).copy().save(path)

    def set_rendered_file(self, path, label: str = "") -> None:
        """A 16-bit or EXR file Blender wrote beside the picture: Save image… offers it as it is."""
        self.rendered_file = Path(path) if path else None
        self.rendered_label = label

    def _save(self):
        start = str(Path(QSettings().value(_SETTINGS + "save_dir", str(Path.home()))) /
                    ((self.path.stem if self.path else "render") + ".png"))
        filters = "PNG (*.png);;JPEG (*.jpg)"
        extra = self.rendered_file if self.rendered_file is not None and self.rendered_file.is_file() else None
        if extra is not None:
            ext = extra.suffix
            filters = tr("{label}, as rendered, without the retouching (*{ext})", label=self.rendered_label, ext=ext) + ";;" + filters
            start = str(Path(start).with_suffix(ext))
        path, chosen = QFileDialog.getSaveFileName(self, tr("Save image"), start, filters)
        if path and extra is not None and (chosen.startswith(self.rendered_label) or (
                extra.suffix.lower() not in (".png", ".jpg", ".jpeg") and path.lower().endswith(extra.suffix.lower()))):
            import shutil
            try:
                shutil.copyfile(extra, path)
            except OSError:
                self.status.setText(tr("Could not write {path}", path=path))
                return
            QSettings().setValue(_SETTINGS + "save_dir", str(Path(path).parent))
            self.status.setText(tr("Saved as rendered: {path}", path=path))
            return
        if path and self.save_to(path):
            QSettings().setValue(_SETTINGS + "save_dir", str(Path(path).parent))
            self.status.setText(tr("Saved: {path}", path=path))

    def closeEvent(self, ev):          # noqa: N802
        if self.panel is not None:
            self.panel.preview_closed()
        super().closeEvent(ev)
