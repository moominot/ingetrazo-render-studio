# SPDX-License-Identifier: GPL-3.0-or-later
"""The Sun tab of Render Studio's panel: where the model is, the date and the hour.

It edits IngeTrazo's own data (see :mod:`sun_site`), so the 3D view's shadows, the
Render tab and the render show the same sun. Under the controls: where the sun is
then (height, compass direction), sunrise and sunset, and what the chosen look does
with it (Golden hour lowers it, Overcast and Night have none).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QDate, Qt, QTime, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QFormLayout, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QSlider, QTimeEdit, QToolButton,
                               QVBoxLayout, QWidget)

from . import sun_site as S


def _bold(text: str) -> QLabel:
    lab = QLabel(text)
    f = lab.font()
    f.setBold(True)
    lab.setFont(f)
    return lab


def _note() -> QLabel:
    lab = QLabel("")
    lab.setWordWrap(True)
    lab.setStyleSheet("color: gray; font-size: 11px")
    return lab


class SunTab(QWidget):
    def __init__(self, app, panel=None, parent=None):
        super().__init__(parent)
        self.app = app
        self.panel = panel
        self._filling = False
        self._pending = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._commit)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        top.addWidget(_bold("Place"))
        top.addStretch(1)
        help_btn = QToolButton()
        help_btn.setText("?")
        help_btn.setToolTip("The place, the date and the hour of the sun")
        help_btn.clicked.connect(self._help)
        top.addWidget(help_btn)
        lay.addLayout(top)
        form = QFormLayout()
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
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self._location_edited)
        lrow = QHBoxLayout()
        lrow.setContentsMargins(0, 0, 0, 0)
        lrow.addWidget(self.lat)
        lrow.addWidget(self.lon)
        self.map_btn = QPushButton("Map…")
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

        lay.addWidget(_bold("Date and hour"))
        form2 = QFormLayout()
        form2.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.date = QDateEdit()
        self.date.setDisplayFormat("d MMMM")
        self.date.setCalendarPopup(True)
        self.date.dateChanged.connect(self._date_edited)
        form2.addRow("Date", self.date)
        srow = QGridLayout()
        srow.setContentsMargins(0, 0, 0, 0)
        self.season_btns = {}
        for i, (key, label) in enumerate((("spring", "Spring equinox"), ("summer", "Summer solstice"),
                                          ("autumn", "Autumn equinox"), ("winter", "Winter solstice"))):
            b = QPushButton(label)
            b.setToolTip("As the site lives it: summer is June in the north, December in the south")
            b.clicked.connect(lambda _c=False, k=key: self._season(k))
            self.season_btns[key] = b
            srow.addWidget(b, i // 2, i % 2)
        seasons = QWidget()
        seasons.setLayout(srow)
        form2.addRow(seasons)
        trow = QHBoxLayout()
        trow.setContentsMargins(0, 0, 0, 0)
        self.time_slider = QSlider(Qt.Horizontal)
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
        form2.addRow("Hour", tbox)
        self.daylight = _note()
        form2.addRow("", self.daylight)
        qrow = QHBoxLayout()
        qrow.setContentsMargins(0, 0, 0, 0)
        for label, which in (("Sunrise + 1 h", "morning"), ("Noon", "noon"), ("Sunset − 1 h", "evening")):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, w=which: self._quick(w))
            qrow.addWidget(b)
        qbox = QWidget()
        qbox.setLayout(qrow)
        form2.addRow(qbox)
        self.zone = QComboBox()
        self.zone.addItem("From the longitude", None)
        for h in range(-12, 15):
            self.zone.addItem(f"UTC{h:+d}", h)
        self.zone.setToolTip("The clock the hour is read on. «From the longitude» is solar time; choose the "
                             "real zone (summer time included) to match a watch.")
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
            self.zone.setItemText(0, f"From the longitude (UTC{s['zone']:+d})")
            self.shadows.setChecked(s["shadows"])
        finally:
            for w in widgets:
                w.blockSignals(False)
            self._filling = False
        self.where.setText("The model's location (the map and the terrain follow it too)." if s["located"] else
                           "The model has no location yet: the sun stands at IngeTrazo's default place. Type the "
                           "real one, or choose it on the map; it becomes the model's location.")
        self._show_sun(s)

    def _show_sun(self, s=None) -> None:
        s = s or S.site(self.app.scene)
        i = S.info(s)
        day = i["daylight"]
        if day:
            self.daylight.setText(f"Daylight {S.minutes_text(day[0])} – {S.minutes_text(day[1])} on that clock")
        else:
            self.daylight.setText("The sun does not rise that day (polar night).")
        if i["up"]:
            self.sun_now.setText(f"{i['elevation']:.1f}° above the horizon, from the {S.compass(i['azimuth'])} "
                                 f"({i['azimuth']:.0f}° from north). Shadows "
                                 f"{1 / max(0.01, math.tan(math.radians(i['elevation']))):.1f}× "
                                 "as long as the things that cast them.")
        else:
            self.sun_now.setText("Below the horizon: night. A day look renders with sky light only; choose an hour "
                                 "with sun, or the Night look.")
        look, hdri = "clear", False
        if self.panel is not None:
            look = self.panel.preset.currentData()
            h = self.panel.hdri_settings()
            hdri = bool(h and h.get("light"))
        self.look.setText(S.look_note(look, hdri))
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

