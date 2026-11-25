# SPDX-License-Identifier: GPL-3.0-or-later
"""The Sun tab of Render Studio's panel: where the model is, the date and the hour.

It edits IngeTrazo's own data (see :mod:`sun_site`), so the 3D view's shadows, the
Render tab and the render show the same sun. Under the controls: where the sun is
then (height, compass direction), sunrise and sunset, and what the chosen look does
with it (Golden hour lowers it, Overcast and Night have none).
"""
from __future__ import annotations

from .i18n import tr, translate_on_show  # noqa: F401

import math

from PySide6.QtCore import QDate, QLocale, Qt, QTime, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QFormLayout, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QTimeEdit, QToolButton,
                               QVBoxLayout, QWidget)

from . import sun_site as S


def _bold(text: str) -> QLabel:
    lab = QLabel(text)
    f = lab.font()
    f.setBold(True)
    lab.setFont(f)
    return lab


def _wide_button(text: str) -> QToolButton:
    """A button that fills its share of a row but, unlike a push button, has no
    80-pixel minimum: three of them fit a narrow tray."""
    b = QToolButton()
    b.setText(text)
    b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return b


def _note() -> QLabel:
    lab = QLabel("")
    lab.setWordWrap(True)
    lab.setStyleSheet("color: gray; font-size: 11px")
    return lab


def season_of(doy: int, lat: float) -> str:
    """The season of a day of the year (1-365) at latitude ``lat``: from each equinox or solstice to the next, as
    the place lives them (summer is June in the north, December in the south)."""
    starts = sorted((QDate(2026, m, d).dayOfYear(), key) for key, (m, d) in S.seasons(lat).items())
    name = starts[-1][1]                                   # before the first start of the year: the last season
    for start, key in starts:
        if doy >= start:
            name = key
    return name


def hour_marks(info) -> list:
    """The photographers' hours of a day as (minute, label): night, dawn, the golden hour, midday, the golden hour, dusk, night
    (from the sunrise, sunset and solar noon in ``info``, see sun_site.info). Nothing but the night when the sun does not rise."""
    day = info.get("daylight")
    marks = [(0, tr("Night"))]
    if day:
        rise, sset = day
        noon = info["noon"]
        marks += [(max(1, rise - 30), tr("Dawn")), (rise + 45, tr("Golden hour")), (noon, tr("Midday")),
                  (sset - 45, tr("Golden hour")), (min(1438, sset + 30), tr("Dusk")), (1439, tr("Night"))]
    return marks


def part_of_day(minute: int, day, noon: int) -> str:
    """A word for the hour: «night» when the sun has not risen or has set, else dawn, morning, midday, afternoon, dusk
    (from the sunrise, sunset and solar noon of that day)."""
    if not day:
        return "Night"
    rise, sset = day
    if minute < rise - 30 or minute > sset + 30:
        return "Night"
    if minute < rise + 30:
        return "Dawn"
    if minute < noon - 90:
        return "Morning"
    if minute <= noon + 90:
        return "Midday"
    if minute < sset - 60:
        return "Afternoon"
    return "Dusk"


class MarkedSlider(QSlider):
    """A horizontal slider with named marks under its groove (the seasons, the photographers' hours): a mark's label is drawn
    when there is room, and the handle clicks onto a mark when released within ``snap`` of it."""

    def __init__(self, snap: int = 0, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.marks: list[tuple[int, str]] = []
        self.snap = snap
        self.setMinimumHeight(34)
        self.sliderReleased.connect(self._snap_to_mark)

    def set_marks(self, marks) -> None:
        self.marks = [(int(v), str(t)) for v, t in marks]
        self.update()

    def _snap_to_mark(self) -> None:
        if not self.snap:
            return
        near = min(self.marks, key=lambda m: abs(m[0] - self.value()), default=None)
        if near is not None and abs(near[0] - self.value()) <= self.snap:
            self.setValue(near[0])

    def _x(self, v: int) -> float:
        span = max(1, self.maximum() - self.minimum())
        return 8 + (self.width() - 16) * (v - self.minimum()) / span

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if not self.marks:
            return
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        col = self.palette().windowText().color()
        col.setAlpha(150)
        p.setPen(col)
        f = p.font()
        f.setPixelSize(9)
        p.setFont(f)
        fm = p.fontMetrics()
        right = -1e9
        for v, text in sorted(self.marks):
            x = self._x(v)
            p.drawLine(int(x), self.height() - 17, int(x), self.height() - 13)
            w = fm.horizontalAdvance(text)
            left = min(max(0, x - w / 2), self.width() - w)
            if left > right + 4:                       # a label that would overlap the last one is left out
                p.drawText(int(left), self.height() - 3, text)
                right = left + w
        p.end()


class SunQuick(QWidget):
    """The quick way to the sun's date and hour, always in view: a slider through the year that says the season and a
    slider through the day that says the part of the day. They drive the date and the hour of the sun tab (which has the
    calendar, the exact time, the zone and the place, folded below)."""

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self.tab = tab
        self._syncing = False
        self.setVisible(False)                # a holder: the two rows below are put in the sky group's own form (aligned with it)
        self.date_slider = MarkedSlider(snap=3)
        self.date_slider.setRange(0, 364)
        self.date_slider.setPageStep(30)
        self.date_slider.setToolTip("The date, through the year: the label says the season (as the site lives it: summer "
                                    "is June in the north, December in the south).")
        self.date_label = QLabel("")
        self.date_label.setStyleSheet("color: gray; font-size: 11px")
        self.date_label.setWordWrap(True)
        self.hour_slider = MarkedSlider(snap=12)
        self.hour_slider.setRange(0, 1439)
        self.hour_slider.setSingleStep(5)
        self.hour_slider.setPageStep(60)
        self.hour_slider.setToolTip("The hour, through the day: the label says the part of the day (night when the sun has "
                                    "set at that place, date and hour).")
        self.hour_label = QLabel("")
        self.hour_label.setStyleSheet("color: gray; font-size: 11px")
        self.hour_label.setWordWrap(True)
        for s in (self.date_slider, self.hour_slider):
            s.setMinimumWidth(40)
            s.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.date_box, self.hour_box = QWidget(), QWidget()
        box1 = QVBoxLayout(self.date_box)
        box1.setContentsMargins(0, 0, 0, 0)
        box1.setSpacing(0)
        box1.addWidget(self.date_slider)
        box1.addWidget(self.date_label)
        box2 = QVBoxLayout(self.hour_box)
        box2.setContentsMargins(0, 0, 0, 0)
        box2.setSpacing(0)
        box2.addWidget(self.hour_slider)
        box2.addWidget(self.hour_label)
        self.date_slider.valueChanged.connect(self._date_moved)
        self.hour_slider.valueChanged.connect(self._hour_moved)
        self.sync()

    def _date_moved(self, v: int) -> None:
        if self._syncing:
            return
        d = QDate(2026, 1, 1).addDays(int(v))
        self.tab.date.setDate(d)                          # the tab's own edit: it writes the document
        self.sync()

    def _hour_moved(self, v: int) -> None:
        if self._syncing:
            return
        self.tab.set_minutes(int(v))
        self.sync()

    def sync(self) -> None:
        """Follow the sun tab (its pending edits included)."""
        try:
            s = self.tab._preview_site()
        except Exception:  # noqa: BLE001 - the site not read yet
            return
        d = QDate(2026, s["month"], s["day"])
        minute = s["hour"] * 60 + s["minute"]
        names_ = {"spring": "Spring", "summer": "Summer", "autumn": "Autumn", "winter": "Winter"}
        self._syncing = True
        try:
            self.date_slider.setValue(d.dayOfYear() - 1)
            self.hour_slider.setValue(minute)
        finally:
            self._syncing = False
        self.date_slider.set_marks(
            (QDate(2026, m, dd).dayOfYear() - 1, tr(names_[k]))
            for k, (m, dd) in S.seasons(s["lat"]).items())
        season = season_of(d.dayOfYear(), s["lat"])
        names = {"spring": "Spring", "summer": "Summer", "autumn": "Autumn", "winter": "Winter"}
        self.date_label.setText(f"{QLocale().toString(d, 'd MMMM')} · {tr(names[season])}")
        i = S.info(s)
        self.hour_slider.set_marks(hour_marks(i))
        self.hour_label.setText(f"{minute // 60:02d}:{minute % 60:02d} · {tr(part_of_day(minute, i['daylight'], i['noon']))}")


class SunTab(QWidget):
    def __init__(self, app, panel=None, parent=None):
        super().__init__(parent)
        self.app = app
        self.panel = panel
        self.quick = None                       # the always-visible date and hour sliders (see SunQuick)
        self._filling = False
        self._pending = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._commit)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.head_place = _bold("Place")
        lay.addWidget(self.head_place)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)        # (the group has its margins: a narrow tray has no room for more)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.where = _note()
        form.addRow(self.where)
        self.lat = QDoubleSpinBox()
        self.lat.setRange(-89.9, 89.9)
        self.lat.setDecimals(4)
        self.lat.setSuffix("°")
        self.lat.setToolTip("Latitude: north positive, south negative")
        self.lon = QDoubleSpinBox()
        self.lon.setRange(-180.0, 180.0)
        self.lon.setDecimals(4)
        self.lon.setSuffix("°")
        self.lon.setToolTip("Longitude: east positive, west negative")
        for w in (self.lat, self.lon):
            w.setMinimumWidth(62)                      # not as wide as ±180.0000 asks: the tray is narrow
            w.setButtonSymbols(QDoubleSpinBox.NoButtons)   # typed, not stepped
            w.setSizePolicy(QSizePolicy.Ignored, w.sizePolicy().verticalPolicy())
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self._location_edited)
        lrow = QHBoxLayout()
        lrow.setContentsMargins(0, 0, 0, 0)
        lrow.addWidget(self.lat)
        lrow.addWidget(self.lon)
        self.map_btn = QToolButton()
        self.map_btn.setText("Map…")
        self.map_btn.setToolTip("Choose the place on a map")
        self.map_btn.clicked.connect(self._pick_on_map)
        lrow.addWidget(self.map_btn)
        box = QWidget()
        box.setLayout(lrow)
        form.addRow("Latitude, longitude", box)
        self.north = QDoubleSpinBox()
        self.north.setRange(-180.0, 180.0)
        self.north.setDecimals(1)
        self.north.setSingleStep(5.0)
        self.north.setSuffix("°")
        self.north.setWrapping(True)
        self.north.setKeyboardTracking(False)
        self.north.setToolTip("Where true north lies, clockwise from the green (Y) axis. The shadows turn; "
                              "the model does not move.")
        self.north.valueChanged.connect(lambda v: self._edit(north=v))
        form.addRow("North", self.north)
        lay.addLayout(form)

        self.head_clock = _bold("Date and hour")
        lay.addWidget(self.head_clock)
        form2 = QFormLayout()
        form2.setContentsMargins(0, 0, 0, 0)        # (the group has its margins: a narrow tray has no room for more)
        self.form_clock = form2
        form2.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.date = QDateEdit()
        self.date.setDisplayFormat("d MMMM")
        self.date.setCalendarPopup(True)
        self.date.dateChanged.connect(self._date_edited)
        form2.addRow("Date", self.date)
        trow = QHBoxLayout()
        trow.setContentsMargins(0, 0, 0, 0)
        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setMinimumWidth(40)
        self.time_slider.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.time_slider.setRange(0, 1439)
        self.time_slider.setSingleStep(5)
        self.time_slider.setPageStep(60)
        self.time_slider.valueChanged.connect(self._slid)
        self.time = QTimeEdit()
        self.time.setDisplayFormat("HH:mm")
        self.time.timeChanged.connect(self._time_edited)
        trow.addWidget(self.time_slider, 1)
        trow.addWidget(self.time)
        tbox = QWidget()
        tbox.setLayout(trow)
        self.hour_row_box = tbox
        form2.addRow("Hour", tbox)
        self.daylight = _note()
        form2.addRow("", self.daylight)
        self.zone = QComboBox()
        self.zone.addItem(tr("From the longitude"), None)
        for h in range(-12, 15):
            self.zone.addItem(f"UTC{h:+d}", h)
        self.zone.setToolTip("The clock the hour is read on. «From the longitude» is solar time; choose the "
                             "real zone (summer time included) to match a watch.")
        self.zone.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.zone.setMinimumContentsLength(8)
        self.zone.currentIndexChanged.connect(lambda _i: self._edit(utc_offset=self.zone.currentData()))
        form2.addRow("Time zone", self.zone)
        self.shadows = QCheckBox("Shadows in the 3D view")
        self.shadows.setToolTip("IngeTrazo's own sun shadows in the model, with this date and hour")
        self.shadows.toggled.connect(lambda on: self._edit(enabled=bool(on)))
        form2.addRow("", self.shadows)
        lay.addLayout(form2)

        lay.addWidget(_bold("The sun then"))
        self.sun_now = QLabel("")
        self.sun_now.setWordWrap(True)
        lay.addWidget(self.sun_now)
        self.look = _note()
        lay.addWidget(self.look)
        lay.addStretch(1)
        self.refresh()

    def embed(self) -> None:
        """Used inside the Sun and sky group, under its own date and hour sliders: this tab's calendar and hour are the same two values, so
        they are not shown again (what is left is the place, the north, the time zone, the shadows and what the sun does then)."""
        self.form_clock.setRowVisible(self.date, False)
        self.form_clock.setRowVisible(self.hour_row_box, False)
        self.head_clock.setText(tr("Clock"))
        self.head_place.setText(tr("Place"))

    # ---- showing ----------------------------------------------------------------------
    def _help(self):
        from . import ui_help
        ui_help.show(self, "sun")

    def refresh(self) -> None:
        if self._timer.isActive():
            return
        s = S.site(self.app.scene)
        self._filling = True
        widgets = (self.lat, self.lon, self.north, self.date, self.time, self.time_slider, self.zone, self.shadows)
        for w in widgets:
            w.blockSignals(True)
        try:
            self.lat.setValue(s["lat"])
            self.lon.setValue(s["lon"])
            self.north.setValue(s["north"])
            self.date.setDate(QDate(2026, s["month"], s["day"]))
            self.time.setTime(QTime(s["hour"], s["minute"]))
            self.time_slider.setValue(s["hour"] * 60 + s["minute"])
            i = self.zone.findData(s["utc_offset"])
            self.zone.setCurrentIndex(i if i >= 0 else 0)
            self.zone.setItemText(0, tr("From the longitude (UTC{zone})", zone=f"{s['zone']:+d}"))
            self.shadows.setChecked(s["shadows"])
        finally:
            for w in widgets:
                w.blockSignals(False)
            self._filling = False
        self.where.setText(tr("The model's location (the map and the terrain follow it too).") if s["located"] else
                           tr("The model has no location yet: the sun stands at IngeTrazo's default place. Type the "
                              "real one, or choose it on the map; it becomes the model's location."))
        self._show_sun(s)

    def _show_sun(self, s=None) -> None:
        s = s or S.site(self.app.scene)
        if self.quick is not None:
            self.quick.sync()
        if self.panel is not None and hasattr(self.panel, "update_night_rows"):
            self.panel.update_night_rows(S.info(s)["up"])
        i = S.info(s)
        day = i["daylight"]
        if day:
            self.daylight.setText(tr("Daylight {a} – {b} on that clock", a=S.minutes_text(day[0]), b=S.minutes_text(day[1])))
        else:
            self.daylight.setText(tr("The sun does not rise that day (polar night)."))
        if i["up"]:
            self.sun_now.setText(tr("{elev:.1f}° above the horizon, from the {dir} ({az:.0f}° from north). "
                                    "Shadows {ratio:.1f}× as long as the things that cast them.",
                                    elev=i['elevation'], dir=S.compass(i['azimuth']), az=i['azimuth'],
                                    ratio=1 / max(0.01, math.tan(math.radians(i['elevation'])))))
        else:
            self.sun_now.setText(tr("Below the horizon: night. The render shows the night sky, with stars and moonlight "
                                    "(their sliders are in the Environment tab); choose an hour with sun for a day."))
        look, hdri = "clear", False
        if self.panel is not None:
            look = self.panel.preset.currentData()
            h = self.panel.hdri_settings()
            hdri = bool(h and h.get("light"))
        self.look.setText(tr(S.look_note(look, hdri)))
        self.look.setVisible(bool(self.look.text()))

    # ---- editing ------------------------------------------------------------------------
    def _edit(self, **changes) -> None:
        if self._filling:
            return
        self._pending.update(changes)
        self._timer.start()
        self._show_sun(self._preview_site())

    def _preview_site(self) -> dict:
        """The site as it will be once the pending changes are written (for the readout)."""
        s = S.site(self.app.scene)
        p = self._pending
        for k in ("month", "day", "hour", "minute"):
            if k in p:
                s[k] = p[k]
        if "utc_offset" in p:
            s["utc_offset"] = p["utc_offset"]
        if "location" in p:
            s["lat"], s["lon"] = p["location"]
        from core import sun
        s["zone"] = s["utc_offset"] if s["utc_offset"] is not None else sun.default_utc_offset(s["lon"])
        return s

    def flush(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._commit()

    def _commit(self) -> None:
        p, self._pending = self._pending, {}
        if not p:
            return
        shadows = {k: p[k] for k in ("month", "day", "hour", "minute", "enabled") if k in p}
        if "utc_offset" in p:
            shadows["utc_offset"] = p["utc_offset"]
        S.apply(self.app, shadows=shadows or None, north=p.get("north"), location=p.get("location"))
        self.refresh()

    def _location_edited(self, *_a) -> None:
        self._edit(location=(self.lat.value(), self.lon.value()))

    def _date_edited(self, d) -> None:
        self._edit(month=d.month(), day=d.day())

    def _slid(self, v: int) -> None:
        if self._filling:
            return
        self.time.blockSignals(True)
        self.time.setTime(QTime(v // 60, v % 60))
        self.time.blockSignals(False)
        self._edit(hour=v // 60, minute=v % 60)

    def _time_edited(self, t) -> None:
        if self._filling:
            return
        self.time_slider.blockSignals(True)
        self.time_slider.setValue(t.hour() * 60 + t.minute())
        self.time_slider.blockSignals(False)
        self._edit(hour=t.hour(), minute=t.minute())

    def set_minutes(self, m: int) -> None:
        m = max(0, min(1439, int(m)))
        self.time_slider.setValue(m)

    def _quick(self, which: str) -> None:
        i = S.info(self._preview_site())
        day = i["daylight"]
        if not day:
            return
        self.set_minutes({"morning": day[0] + 60, "noon": i["noon"], "evening": day[1] - 60}[which])

    def _season(self, key: str) -> None:
        m, d = S.seasons(self._preview_site()["lat"])[key]
        self.date.setDate(QDate(2026, m, d))

    def _pick_on_map(self) -> None:
        try:
            from georef.tiles import DEFAULT_SOURCE_ID, PRESETS
            from views.location_dialog import pick_location
        except Exception:  # noqa: BLE001 - an IngeTrazo without the map
            self.where.setText("This IngeTrazo has no map: type the latitude and longitude.")
            return
        s = self._preview_site()
        result = pick_location(PRESETS[DEFAULT_SOURCE_ID], s["lat"], s["lon"], self.window())
        if result is None:
            return
        lat, lon = result[0], result[1]
        self.lat.blockSignals(True)
        self.lon.blockSignals(True)
        self.lat.setValue(lat)
        self.lon.setValue(lon)
        self.lat.blockSignals(False)
        self.lon.blockSignals(False)
        self._edit(location=(lat, lon))
        self.flush()

    def document_changed(self) -> None:
        self.refresh()

