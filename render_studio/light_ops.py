# SPDX-License-Identifier: GPL-3.0-or-later
"""Edits of Render Studio's lights, each ONE undo step.

A light can live in three places (see :mod:`lights`): the document's data
(free lights), an object's ``group.ext`` (lights on an object) or the Render
tab's data. Moving a light from one to another — attach, detach, convert —
touches two of them, so one command keeps them all.
"""
from __future__ import annotations

import copy
import json

from . import lights as L

try:                                    # inside IngeTrazo
    from core.history import Command
except Exception:  # noqa: BLE001 - plain Python (tests of the format)
    class Command:                      # type: ignore[no-redef]
        pass


def _not_model(scene) -> None:
    """A version bump that is not the model's: the live preview keeps the model it
    exported (see ``panel.live_model_key``)."""
    scene._rs_not_model = getattr(scene, "_rs_not_model", 0) + 1


class LightsCommand(Command):
    """Set, in one step: the free lights (``free``), some groups' ``ext``
    (``groups`` = {group: new ext}) and the Render tab's data (``tab``).
    ``None`` for ``free``/``tab`` leaves that one alone."""

    keeps_paint = True
    keeps_groups = True

    def __init__(self, free=None, groups=None, tab=None) -> None:
        self.free = None if free is None else json.loads(json.dumps(free))
        self.groups = [(g, copy.deepcopy(ext)) for g, ext in (groups or {}).items()]
        self.tab = None if tab is None else json.loads(json.dumps(tab))
        self.before = None

    def do(self, scene) -> None:
        data = scene.plugin_data
        self.before = (copy.deepcopy(data.get(L.KEY)), copy.deepcopy(data.get("render_blender")),
                       [(g, copy.deepcopy(getattr(g, "ext", None))) for g, _e in self.groups])
        if self.free is not None:
            block = dict(data.get(L.KEY) or {}) if isinstance(data.get(L.KEY), dict) else {}
            if self.free:
                block["lights"] = copy.deepcopy(self.free)
            else:
                block.pop("lights", None)
            if block:
                data[L.KEY] = block
            else:
                data.pop(L.KEY, None)
        if self.tab is not None:
            data["render_blender"] = copy.deepcopy(self.tab)
        for g, ext in self.groups:
            g.ext = copy.deepcopy(ext)
        scene.version += 1
        _not_model(scene)

    def undo(self, scene) -> None:
        mine, tab, exts = self.before
        data = scene.plugin_data
        for key, value in ((L.KEY, mine), ("render_blender", tab)):
            if value is None:
                data.pop(key, None)
            else:
                data[key] = copy.deepcopy(value)
        for g, ext in exts:
            g.ext = copy.deepcopy(ext)
        scene.version += 1
        _not_model(scene)


def run(app, cmd) -> None:
    vp = app.viewport
    vp.history.execute(cmd)
    notify = getattr(vp, "notify_scene_changed", None)
    if callable(notify):
        notify()
    vp.update()


# ---- reading ----------------------------------------------------------------------------

def entry(scene, key):
    """The :func:`lights.all_lights` entry named ``key``, or None."""
    for e in L.all_lights(scene):
        if e["key"] == key:
            return e
    return None


# ---- the edits ------------------------------------------------------------------------------

def add_free(app, light) -> tuple:
    free = L.free_lights(app.scene.plugin_data)
    light = L.clean_light(light)
    free.append(light)
    run(app, LightsCommand(free=free))
    return ("free", light["id"])


def add_to_object(app, group, world_light) -> tuple:
    """Put ``world_light`` on the top-level object ``group``, in its axes."""
    frame = L.frame_at(app.scene, (group.uid,))
    local = L.clean_light(L.to_local(L.clean_light(world_light), frame))
    lts = L.group_lights(group) + [local]
    run(app, LightsCommand(groups={group: L.with_lights(group.ext, lts)}))
    return ("object", (group.uid,), local["id"])


def update(app, key, world_light, all_copies: bool = False) -> tuple:
    """Replace the light ``key`` with ``world_light`` (world coordinates, as
    the editor shows it). ``all_copies``: on a component, every top-level copy
    holding the same light gets the change (each in its own axes)."""
    scene = app.scene
    new = L.clean_light(world_light)
    if key[0] == "free":
        free = [new if lt["id"] == key[1] else lt for lt in L.free_lights(scene.plugin_data)]
        run(app, LightsCommand(free=free))
        return ("free", new["id"])
    if key[0] == "tab":
        data = copy.deepcopy((scene.plugin_data or {}).get("render_blender") or {})
        lts = list(data.get("lights") or [])
        i = key[1]
        if 0 <= i < len(lts):
            lts[i] = dict(lts[i], pos=new["pos"], dir=new["dir"], on=new["on"], name=new["name"],
                          power=L.blender_watts(new), angle=new["spot_angle"],
                          kelvin=new["kelvin"] if new["kelvin"] is not None else lts[i].get("kelvin"))
            data["lights"] = lts
            run(app, LightsCommand(tab=data))
        return key
    _kind, path, lid = key
    group = L.find_group(scene, path)
    if group is None:
        return key
    frame = L.frame_at(scene, path)
    local = L.clean_light(dict(L.to_local(new, frame), id=lid))
    targets = [group]
    if all_copies and len(path) == 1:
        targets = [g for g in L.siblings(scene, group) if any(lt["id"] == lid for lt in L.group_lights(g))]
    # Moved or turned inside its object: every copy moves it the same way, in
    # its own axes. Otherwise each copy keeps where its light is.
    moved = _moved(group, lid, local)
    changes = {}
    for g in targets:
        lts = []
        for lt in L.group_lights(g):
            if lt["id"] != lid:
                lts.append(lt)
            elif g is group or moved:
                lts.append(local)
            else:
                lts.append(dict(local, pos=lt["pos"], dir=lt["dir"], spin=lt["spin"]))
        changes[g] = L.with_lights(g.ext, lts)
    run(app, LightsCommand(groups=changes))
    return key


def _moved(group, lid, local) -> bool:
    """Whether the edit moved or turned the light inside its object."""
    old = next((lt for lt in L.group_lights(group) if lt["id"] == lid), None)
    if old is None:
        return False
    return any(abs(a - b) > 1e-6 for a, b in zip(old["pos"] + old["dir"] + [old["spin"]],
                                                   local["pos"] + local["dir"] + [local["spin"]]))


def delete(app, key, all_copies: bool = False) -> None:
    scene = app.scene
    if key[0] == "free":
        run(app, LightsCommand(free=[lt for lt in L.free_lights(scene.plugin_data) if lt["id"] != key[1]]))
    elif key[0] == "tab":
        data = copy.deepcopy((scene.plugin_data or {}).get("render_blender") or {})
        lts = list(data.get("lights") or [])
        if 0 <= key[1] < len(lts):
            del lts[key[1]]
            data["lights"] = lts
            run(app, LightsCommand(tab=data))
    else:
        _kind, path, lid = key
        group = L.find_group(scene, path)
        if group is None:
            return
        targets = L.siblings(scene, group) if all_copies and len(path) == 1 else [group]
        changes = {g: L.with_lights(g.ext, [lt for lt in L.group_lights(g) if lt["id"] != lid])
                   for g in targets if any(lt["id"] == lid for lt in L.group_lights(g))}
        run(app, LightsCommand(groups=changes))


def attach(app, key, group) -> tuple:
    """A free (or Render tab) light goes onto the top-level object ``group``,
    staying where it is in the world."""
    e = entry(app.scene, key)
    if e is None or group is None:
        return key
    world = dict(e["world"])
    if key[0] == "tab":
        world["id"] = L.new_id()
    frame = L.frame_at(app.scene, (group.uid,))
    local = L.clean_light(L.to_local(world, frame))
    changes = {group: L.with_lights(group.ext, L.group_lights(group) + [local])}
    free = tab = None
    if key[0] == "free":
        free = [lt for lt in L.free_lights(app.scene.plugin_data) if lt["id"] != key[1]]
    elif key[0] == "tab":
        tab = _tab_without(app.scene, key[1])
    elif key[0] == "object":
        old = L.find_group(app.scene, key[1])
        if old is group:
            return key
        if old is not None:
            changes[old] = L.with_lights(old.ext, [lt for lt in L.group_lights(old) if lt["id"] != key[2]])
    run(app, LightsCommand(free=free, groups=changes, tab=tab))
    return ("object", (group.uid,), local["id"])


def detach(app, key) -> tuple:
    """A light on an object becomes a free light, where it is now."""
    e = entry(app.scene, key)
    if e is None or key[0] != "object":
        return key
    group = L.find_group(app.scene, key[1])
    world = L.clean_light(dict(e["world"], id=L.new_id()))
    free = L.free_lights(app.scene.plugin_data) + [world]
    changes = {group: L.with_lights(group.ext, [lt for lt in L.group_lights(group) if lt["id"] != key[2]])}
    run(app, LightsCommand(free=free, groups=changes))
    return ("free", world["id"])


def _tab_without(scene, index):
    data = copy.deepcopy((scene.plugin_data or {}).get("render_blender") or {})
    lts = list(data.get("lights") or [])
    if 0 <= index < len(lts):
        del lts[index]
    data["lights"] = lts
    return data


def convert_tab(app, index) -> tuple:
    """A Render tab light becomes a Render Studio light (free), in the same
    step taken out of the Render tab. IngeTrazo's own Render tab then no
    longer renders it."""
    e = entry(app.scene, ("tab", index))
    if e is None:
        return ("tab", index)
    light = L.clean_light(dict(e["light"], id=L.new_id()))
    free = L.free_lights(app.scene.plugin_data) + [light]
    run(app, LightsCommand(free=free, tab=_tab_without(app.scene, index)))
    return ("free", light["id"])
