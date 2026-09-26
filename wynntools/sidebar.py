"""How the player arranged the web app's Builds list: their own order and
named, collapsible groups. Kept in builds/settings.json under "sidebar":

    {"items": ["a.json",
               {"group": "Mage", "collapsed": false, "builds": ["x.json", "y.json"]},
               "b.json"]}

Only top-level builds are placed; a candidate (a build whose "parent" file
exists) always follows its parent. Builds not in the layout yet (a new one the
AI just made) go first, alphabetically. Files that no longer exist are left out
of `arrange`, so a build restored from the trash is simply new again.

`static/app.js` (`arrangeList`) mirrors `arrange`; keep the two in step.
"""
import json
from pathlib import Path

from . import settings as settings_mod

NOT_BUILDS = {"inventory.json", "settings.json"}


def problem(value):
    """Why `value` isn't a valid layout, or None if it is."""
    if not isinstance(value, dict) or set(value) != {"items"} or not isinstance(value["items"], list):
        return 'sidebar must be {"items": [...]}'
    seen, groups = set(), set()

    def file_problem(f):
        if not isinstance(f, str) or not f.endswith(".json") or "/" in f or "\\" in f:
            return f"sidebar: {f!r} is not a build file name"
        if f in seen:
            return f"sidebar: {f} is listed twice"
        seen.add(f)
        return None

    for it in value["items"]:
        if isinstance(it, dict):
            if set(it) != {"group", "collapsed", "builds"}:
                return "sidebar: a group needs exactly: group, collapsed, builds"
            name = it["group"]
            if not isinstance(name, str) or not name.strip() or name.endswith(".json"):
                return f"sidebar: {name!r} is not a group name"
            if name in groups:
                return f"sidebar: two groups are called {name}"
            groups.add(name)
            if not isinstance(it["collapsed"], bool) or not isinstance(it["builds"], list):
                return f"sidebar: group {name} has the wrong shape"
            for f in it["builds"]:
                if (p := file_problem(f)):
                    return p
        elif (p := file_problem(it)):
            return p
    return None


def load(settings_path=settings_mod.DEFAULT):
    return settings_mod.load(settings_path)["sidebar"] or {"items": []}


def save(layout, settings_path=settings_mod.DEFAULT):
    settings_mod.save({"sidebar": layout}, settings_path)


def scan(folder):
    """[(file name, parent)] for the build files in `folder` (unreadable ones too)."""
    out = []
    for p in sorted(Path(folder).glob("*.json")):
        if p.name in NOT_BUILDS or p.name.startswith("."):
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        out.append((p.name, doc.get("parent") if isinstance(doc, dict) else None))
    return out


def top_level(builds):
    """The files of `builds` [(file, parent)] that aren't candidates of another one there."""
    files = {f for f, _ in builds}
    return [f for f, parent in builds if not (parent and parent in files)]


def arrange(builds, layout):
    """The layout for these builds: unplaced top-level builds first (alphabetical),
    then the saved items, without files that are gone or are candidates."""
    top = set(top_level(builds))
    items = (layout or {}).get("items") or []
    placed = set()
    out = []
    for it in items:
        if isinstance(it, dict):
            keep = [f for f in it["builds"] if f in top and f not in placed]
            placed.update(keep)
            out.append({**it, "builds": keep})
        elif it in top and it not in placed:
            placed.add(it)
            out.append(it)
    return {"items": sorted(top - placed) + out}


# ------------------------------------------------------------------ changes
# Each takes an arranged layout and returns a new one; ValueError on a bad request.

def _copy(layout):
    return {"items": [dict(it, builds=list(it["builds"])) if isinstance(it, dict) else it
                      for it in layout["items"]]}


def _group(layout, name):
    for it in layout["items"]:
        if isinstance(it, dict) and it["group"] == name:
            return it
    raise ValueError(f"no group called {name!r}")


def _where(layout, file):
    """(list holding `file`, group or None)."""
    for it in layout["items"]:
        if isinstance(it, dict) and file in it["builds"]:
            return it["builds"], it
    if file in layout["items"]:
        return layout["items"], None
    raise ValueError(f"{file} isn't in the list (a candidate follows its parent)")


def groups(layout):
    return [it["group"] for it in layout["items"] if isinstance(it, dict)]


def add(layout, name, files):
    """Put `files` at the end of group `name`, making the group (at the top) if new."""
    name = name.strip()
    if not name or name.endswith(".json"):
        raise ValueError(f"{name!r} can't be a group name")
    out = _copy(layout)
    for f in files:
        _where(out, f)                              # every file must be placeable
    if name not in groups(out):
        out["items"].insert(0, {"group": name, "collapsed": False, "builds": []})
    for f in files:
        _where(out, f)[0].remove(f)
    _group(out, name)["builds"].extend(files)
    return out


def ungroup(layout, files):
    """Take `files` out of their groups, to the top level just below the group."""
    out = _copy(layout)
    for f in reversed(files):
        where, group = _where(out, f)
        if group is not None:
            where.remove(f)
            out["items"].insert(out["items"].index(group) + 1, f)
    return out


def rename(layout, old, new):
    new = new.strip()
    if not new or new.endswith(".json"):
        raise ValueError(f"{new!r} can't be a group name")
    out = _copy(layout)
    g = _group(out, old)
    if new != old and new in groups(out):
        raise ValueError(f"there is already a group called {new!r}")
    g["group"] = new
    return out


def delete(layout, name):
    """Remove group `name`; its builds stay, at the top level where it was."""
    out = _copy(layout)
    g = _group(out, name)
    i = out["items"].index(g)
    out["items"][i:i + 1] = g["builds"]
    return out


def collapse(layout, name, collapsed=True):
    out = _copy(layout)
    _group(out, name)["collapsed"] = collapsed
    return out


def move(layout, item, before=None, after=None, top=False, bottom=False):
    """Move a build file or a group next to another build or group, or to the
    top or bottom of the list. Next to a build in a group means into that group;
    a group can't go into another group, so it goes next to that group instead."""
    if [before is not None, after is not None, bool(top), bool(bottom)].count(True) != 1:
        raise ValueError("say where: before, after, top or bottom")
    out = _copy(layout)
    is_group = item in groups(out)
    if is_group:
        moving = _group(out, item)
        out["items"].remove(moving)
    else:
        moving = item
        _where(out, item)[0].remove(item)
    if top or bottom:
        out["items"].insert(0 if top else len(out["items"]), moving)
        return out
    target = before if before is not None else after
    if target == item or (is_group and target in moving["builds"]):
        raise ValueError("can't move something next to itself")
    if target in groups(out):
        where, anchor = out["items"], _group(out, target)
    else:
        where, group = _where(out, target)
        anchor = target
        if is_group and group is not None:
            where, anchor = out["items"], group
    where.insert(where.index(anchor) + (after is not None), moving)
    return out
