# SPDX-License-Identifier: GPL-3.0-or-later
"""The place, the date and the hour of the sun — IngeTrazo's own.

Render Studio does not keep a sun of its own: it reads and writes the same
document data as IngeTrazo's Shadows panel (``scene.shadows``: date, hour,
time zone), its location (``scene.georef``, which the map and the terrain
follow too) and its north (``scene.north_deg`` without a location). So the
shadows of the 3D view, the Render tab and Render Studio always show the same
sun. Every change here is one undo step (:class:`SunCommand`).
"""
from __future__ import annotations

import datetime as _dt

try:
    from core.history import Command
except Exception:  # noqa: BLE001 - plain Python
    class Command:                      # type: ignore[no-redef]
        pass


def _sun():
    from core import sun
    return sun


def site(scene) -> dict:
    """``{"lat", "lon", "located", "north", "month", "day", "hour", "minute",
    "utc_offset" (None = from the longitude), "zone" (the hours used), "shadows"}``."""
    sun = _sun()
    datum = getattr(scene, "georef", None)
    lat, lon = getattr(datum, "lat", None), getattr(datum, "lon", None)
    located = lat is not None and lon is not None
    if not located:
        lat, lon = sun.DEFAULT_LAT, sun.DEFAULT_LON
    sh = getattr(scene, "shadows", None) or sun.ShadowSettings()
    off = sh.utc_offset
    return {"lat": float(lat), "lon": float(lon), "located": located,
            "north": float(sun.scene_north_deg(scene)),
            "month": sh.month, "day": sh.day, "hour": sh.hour, "minute": sh.minute,
            "utc_offset": off, "zone": off if off is not None else sun.default_utc_offset(lon),
            "shadows": bool(sh.enabled)}


def when_utc(s: dict) -> _dt.datetime | None:
    try:
        local = _dt.datetime(_dt.date.today().year, s["month"], s["day"], s["hour"], s["minute"],
                             tzinfo=_dt.timezone(_dt.timedelta(hours=s["zone"])))
    except ValueError:
        return None
    return local.astimezone(_dt.timezone.utc)


def info(s: dict) -> dict:
    """``{"elevation", "azimuth" (true, clockwise from north), "up" (sun above the
    horizon), "daylight": (first, last minute) or None, "noon": minute}``."""
    sun = _sun()
    when = when_utc(s)
    elev, az = sun.solar_position(s["lat"], s["lon"], when) if when else (-90.0, 0.0)
    try:
        day = sun.daylight_minutes(round(s["lat"], 4), round(s["lon"], 4), s["month"], s["day"], s["zone"])
    except ValueError:
        day = None
    noon = (day[0] + day[1]) // 2 if day else 12 * 60
    return {"elevation": float(elev), "azimuth": float(az), "up": elev > 0.0, "daylight": day, "noon": noon}


def seasons(lat: float) -> dict:
    """The equinoxes and solstices as the site lives them: summer is June in the north,
    December in the south. ``{"spring": (m, d), "summer", "autumn", "winter"}``."""
    north = {"spring": (3, 20), "summer": (6, 21), "autumn": (9, 22), "winter": (12, 21)}
    if lat >= 0:
        return north
    return {"spring": (9, 22), "summer": (12, 21), "autumn": (3, 20), "winter": (6, 21)}


def compass(az: float) -> str:
    names = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
    return names[int((az % 360.0) / 22.5 + 0.5) % 16]


def look_note(look: str, hdri_lights: bool) -> str:
    """What the chosen look does with this sun (empty when it uses it as it is)."""
    if hdri_lights:
        return "The 360° background lights the scene: its own sun is used, not this one."
    return {
        "golden_hour": "The Golden hour look lowers this sun to 7° above the horizon (it keeps its compass "
                       "direction).",
        "overcast": "The Overcast look has no sun, only a soft sky from about this direction.",
        "night": "The Night look has no sun.",
        "interior": "",
    }.get(look, "")


class SunCommand(Command):
    """Date, hour, zone and shadows (``shadows`` = dict for ``ShadowSettings``),
    north (degrees) and the location (``lat``, ``lon``) in one undo step. A new
    location is a new datum (kept: its height and north); the terrain is let go,
    as IngeTrazo's own north does, and the window builds it again."""

    keeps_paint = True
    keeps_groups = True

    def __init__(self, shadows: dict | None = None, north: float | None = None,
                 location: tuple | None = None) -> None:
        self.shadows = dict(shadows) if shadows else None
        self.north = north
        self.location = location
        self.before = None
        self._new_datum = None

    def do(self, scene) -> None:
        sun = _sun()
        old_sh = getattr(scene, "shadows", None)
        self.before = (old_sh.to_dict() if old_sh is not None else None, getattr(scene, "georef", None),
                       float(getattr(scene, "north_deg", 0.0) or 0.0), getattr(scene, "terrain", None))
        if self.shadows is not None:
            merged = dict(old_sh.to_dict() if old_sh is not None else {})
            merged.update(self.shadows)
            if "utc_offset" in self.shadows and self.shadows["utc_offset"] is None:
                merged.pop("utc_offset", None)
            scene.shadows = sun.ShadowSettings.from_dict(merged)
        datum = getattr(scene, "georef", None)
        north = sun.wrap_north_deg(self.north) if self.north is not None else sun.scene_north_deg(scene)
        if self.location is not None or (self.north is not None and datum is not None):
            if self._new_datum is None:
                from georef.datum import SceneDatum
                lat, lon = self.location if self.location is not None else (datum.lat, datum.lon)
                self._new_datum = SceneDatum(float(lat), float(lon), alt=float(getattr(datum, "alt", 0.0) or 0.0),
                                             north=north)
            scene.georef = self._new_datum
            if getattr(scene, "terrain", None) is not None:
                scene.terrain = None
        elif self.north is not None:
            scene.north_deg = north
        scene.version += 1
        if self.location is None:
            # Not the model: the live preview keeps its exported model (see panel.live_model_key).
            scene._rs_not_model = getattr(scene, "_rs_not_model", 0) + 1

    def undo(self, scene) -> None:
        sun = _sun()
        sh, datum, north, terrain = self.before
        if sh is not None:
            scene.shadows = sun.ShadowSettings.from_dict(sh)
        scene.georef = datum
        scene.north_deg = north
        if terrain is not None:
            scene.terrain = terrain
        scene.version += 1
        if self.location is None:
            scene._rs_not_model = getattr(scene, "_rs_not_model", 0) + 1


def apply(app, **changes) -> None:
    vp = app.viewport
    vp.history.execute(SunCommand(**changes))
    notify = getattr(vp, "notify_scene_changed", None)
    if callable(notify):
        notify()
    vp.update()


def minutes_text(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def angle_text(deg: float) -> str:
    return f"{deg:.1f}°"


def distance_deg(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)

