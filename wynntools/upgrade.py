"""Carry a build made with an older version's data over to today's.

WynnBuilder reads an old link with that version's own data, and offers to
"update to the latest version", which reads the same item ids and tree bits
against today's data and warns that this "may break the build and ability tree".
Here the old link is read with its own data first, then matched to today's by
name: items (by id when an item was renamed), tomes, aspects and ability nodes.
Everything that differs is reported, so the player knows what changed.
"""
from dataclasses import replace

from .codec import SLOTS, TOME_SLOTS, decode, link_hash
from .data import VERSIONS, GameData, latest
from .rules import ROLLED_IDS, SKILLS
from .statinfo import LABELS
from .verify import SKILL_NAMES, STAT_KEYS

# What an item can change about a build's numbers: every rolled ID, base stats,
# requirements, skill bonuses, damage, attack speed, powder slots and major IDs.
# Names, lore, icons and drop sources are left out.
_COMPARED = (ROLLED_IDS | set(STAT_KEYS) | set(SKILLS) | {f"{s}Req" for s in SKILLS}
             | {"hp", "hpBonus", "lvl", "classReq", "slots", "atkSpd", "majorIds", "fixID"}
             | {f"{e}Dam" for e in "netwfa"})
_SHOWN = 6                                  # stat differences listed per item


def _value(v):
    return v.get("raw") if isinstance(v, dict) else v


def _stat_changes(old, new):
    diff = [(k, _value(old.get(k)), _value(new.get(k))) for k in sorted(_COMPARED)]
    return [(k, a, b) for k, a, b in diff if (a or None) != (b or None)]


def _describe(changes):
    def show(v):
        return "none" if v in (None, 0, "", []) else str(v)
    parts = [f"{LABELS.get(k) or SKILL_NAMES.get(k, k)} {show(a)} → {show(b)}" for k, a, b in changes[:_SHOWN]]
    if len(changes) > _SHOWN:
        parts.append(f"{len(changes) - _SHOWN} more")
    return ", ".join(parts)


def _item(name, slot, old_gd, gd, notes):
    if name.startswith("CR-"):
        return _craft(name, slot, old_gd, gd, notes)
    old = old_gd.item(name)
    new = gd.item_by_name.get(name) or gd.item_by_id.get(old["id"])
    if new is None:
        notes.append({"kind": "removed", "slot": slot,
                      "message": f"{name} ({slot}) is no longer in the game's data; the slot is empty"})
        return None
    now = gd.name(new)
    if now != name:
        notes.append({"kind": "renamed", "slot": slot, "message": f"{name} ({slot}) is now called {now}"})
    diff = _stat_changes(old, new)
    if diff:
        notes.append({"kind": "changed", "slot": slot,
                      "message": f"{now} ({slot}) changed: {_describe(diff)}"})
    return now


def _craft(name, slot, old_gd, gd, notes):
    from .crafting import decode_craft_hash, encode_craft_hash
    craft = decode_craft_hash(name, old_gd.crafts)
    missing = [i for i in craft.ingredients if i not in gd.crafts.ing_by_name]
    if craft.recipe not in gd.crafts.recipe_by_name or missing:
        what = ", ".join(missing) or f"the {craft.recipe} recipe"
        notes.append({"kind": "removed", "slot": slot,
                      "message": f"The crafted {slot} uses {what}, no longer in the game's data; "
                                 f"the slot is empty"})
        return None
    now = encode_craft_hash(craft, gd.crafts)
    diff = _stat_changes(old_gd.item(name), gd.item(now))
    if diff:
        notes.append({"kind": "changed", "slot": slot,
                      "message": f"The crafted {slot} changed with its ingredients: {_describe(diff)}"})
    return now


def _tomes(tomes, old_gd, gd, notes):
    out, seen = [], {}
    for slot, tid in zip(TOME_SLOTS, tomes):
        if tid is None:
            out.append(None)
            continue
        if tid not in seen:
            old = old_gd.tome(tid)
            new = gd.tome_by_name.get(old_gd.name(old)) or gd.tome_by_id.get(tid)
            diff = _stat_changes(old, new) if new else []
            seen[tid] = (old_gd.name(old), new, diff, [])
        name, new, diff, slots = seen[tid]
        slots.append(slot)
        out.append(new["id"] if new else None)
    for name, new, diff, slots in seen.values():
        where = ", ".join(slots)
        if new is None:
            notes.append({"kind": "removed", "slot": where,
                          "message": f"The tome {name} ({where}) is no longer in the game's data"})
        elif diff:
            notes.append({"kind": "changed", "slot": where,
                          "message": f"{gd.name(new)} ({where}) changed: {_describe(diff)}"})
    return out


def _aspects(aspects, old_cls, cls, old_gd, gd, notes):
    if not aspects:
        return aspects
    old = {a["id"]: a for a in old_gd.aspects(old_cls)} if old_cls else {}
    new = {a["displayName"]: a for a in gd.aspects(cls)} if cls else {}
    out = []
    for a in aspects:
        if a is None:
            out.append(None)
            continue
        aid, tier = a
        name = old[aid]["displayName"] if aid in old else f"aspect {aid}"
        now = new.get(name)
        if now is None:
            notes.append({"kind": "removed", "slot": "aspects",
                          "message": f"{name} is no longer an aspect of this class; its slot is empty"})
            out.append(None)
            continue
        if aid in old and old[aid]["tiers"] != now["tiers"]:
            notes.append({"kind": "changed", "slot": "aspects", "message": f"{name} changed"})
        out.append((now["id"], min(tier, len(now["tiers"]))))
    return out


def _tree(atree, old_cls, cls, old_gd, gd, notes):
    from .verify import tree_activation
    if not cls:
        return set()
    old = {n["id"]: n["display_name"] for n in old_gd.tree(old_cls)}
    tree = gd.tree(cls)
    new = {n["display_name"]: n["id"] for n in tree}
    names = [old[i] for i in sorted(atree) if i in old]
    gone = sorted(n for n in names if n not in new)
    active, failed = tree_activation(tree, {new[n] for n in names if n in new})
    if gone:
        notes.append({"kind": "tree", "slot": "tree",
                      "message": "Ability nodes no longer in the tree: " + ", ".join(gone)})
    if failed:
        by_id = {n["id"]: n["display_name"] for n in tree}
        notes.append({"kind": "tree", "slot": "tree",
                      "message": "Ability nodes that can't activate in today's tree, left out: "
                                 + ", ".join(sorted(by_id[i] for i in failed))})
    return active


def upgrade(build, gd=None):
    """(today's build, notes) for a build decoded with an older version's data.
    Each note: {"kind": removed|renamed|changed|tree, "slot", "message"}."""
    gd = gd if gd is not None and gd.version == latest() else GameData()
    old_gd = GameData(build.version)
    notes = []
    equipment = [None if n is None else _item(n, slot, old_gd, gd, notes)
                 for slot, n in zip(SLOTS, build.equipment)]
    tomes = _tomes(build.tomes, old_gd, gd, notes)
    old_cls = old_gd.weapon_class(build.weapon) if build.weapon else None
    cls = gd.weapon_class(equipment[8]) if equipment[8] else None
    aspects = _aspects(build.aspects, old_cls, cls, old_gd, gd, notes)
    atree = _tree(build.atree, old_cls, cls, old_gd, gd, notes)
    return replace(build, equipment=equipment, tomes=tomes, aspects=aspects, atree=atree,
                   version=gd.version, remapped=[]), notes


def read_link(link, gd=None):
    """Decode a link and bring it to today's data. Returns (build, info): info is
    None for a link made with today's data, else {"from": version name, "to",
    "notes", "old_build"}."""
    b = decode(link_hash(link), gd)
    if b.version >= latest():
        return b, None
    new, notes = upgrade(b, gd)
    return new, {"from": VERSIONS[b.version], "to": VERSIONS[new.version], "notes": notes,
                 "old_build": b}


def summary_lines(info):
    """What to tell the player about an upgraded link."""
    if not info:
        return []
    head = (f"This link was made with WynnBuilder's data for {info['from']}; it is read with "
            f"today's ({info['to']}).")
    if not info["notes"]:
        return [head + " Nothing in it changed since."]
    return [head + " Changed since:"] + [f"  - {n['message']}" for n in info["notes"]]
