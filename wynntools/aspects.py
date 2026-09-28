"""Aspects: what each one does, which ability-tree nodes it works through,
and which ones raise a build's damage or survival numbers.

An aspect tier's abilities merge into a base ability (damage.merge_tree, as
WynnBuilder's atree_merge does), so an aspect whose base node is not in the
build's tree changes nothing there. A build has 5 aspect slots; a build file
keeps them as [name, tier] or null.
"""
import html
import re

from .derived import metrics, value

SLOTS = 5
RARITY_ORDER = {"Mythic": 0, "Fabled": 1, "Legendary": 2}


def plain(desc):
    """An aspect description from WynnBuilder's HTML as one line of text."""
    text = re.sub(r"<\s*/?\s*br\s*/?\s*>", "; ", desc or "")
    text = html.unescape(re.sub(r"<[^>]+>", "", text)).replace(" ", " ")
    text = re.sub(r"\s*;\s*(;\s*)*", "; ", text)
    text = re.sub(r"\.; ", ". ", text)
    return re.sub(r"\s+", " ", text).strip(" ;")


def by_name(gd, cls):
    return {a["displayName"]: a for a in gd.aspects(cls)}


def find(gd, cls, name):
    """The class's aspect called `name` (case-insensitive; a unique part of a name
    also works). Raises KeyError naming close matches."""
    known = by_name(gd, cls)
    if name in known:
        return known[name]
    low = name.lower()
    hits = [n for n in known if n.lower() == low] or [n for n in known if low in n.lower()]
    if len(hits) == 1:
        return known[hits[0]]
    if hits:
        raise KeyError(f"{name!r} matches several {cls} aspects: {', '.join(sorted(hits))}")
    raise KeyError(f"no {cls} aspect named {name!r}; `wt aspects <build>` lists them")


def _node_names(gd, cls):
    names = {n["id"]: n["display_name"] for n in gd.tree(cls)}
    names.update({999: f"{cls} Melee", 998: "Elemental Mastery"})
    return names


def _base_nodes(abil, names):
    """(node id or None, node name) the ability merges into."""
    base = abil.get("base_abil")
    if isinstance(base, int):
        return base, names.get(base, f"node {base}")
    if isinstance(base, str):
        ids = {v: k for k, v in names.items()}
        return ids.get(base), base
    return None, None


def describe(gd, cls, atree=None):
    """Every aspect of a class: [{"name", "rarity", "tiers": [{"tier", "text",
    "nodes": [names], "needs": [names], "active": bool | None, "modelled": bool}]}].
    "nodes" are the tree nodes a tier modifies, "needs" the nodes it also depends
    on, "active" whether the given tree (node ids) has all of them (None: no tree,
    or not modelled), and "modelled" whether WynnBuilder's data gives the tier any
    effect at all (some are text only: its numbers ignore them)."""
    names = _node_names(gd, cls)
    always = {999, 998}
    out = []
    for asp in gd.aspects(cls):
        tiers = []
        for k, t in enumerate(asp.get("tiers") or [], 1):
            nodes, needs, ids = [], [], set()
            for abil in t.get("abilities") or ():
                nid, nname = _base_nodes(abil, names)
                if nname and nname not in nodes:
                    nodes.append(nname)
                if nid is not None:
                    ids.add(nid)
                for d in abil.get("dependencies") or ():
                    dn = names.get(d, str(d))
                    if dn not in needs and dn not in nodes:
                        needs.append(dn)
                    if isinstance(d, int):
                        ids.add(d)
            modelled = bool(t.get("abilities"))
            active = None if atree is None or not modelled else all(i in atree or i in always for i in ids)
            tiers.append({"tier": k, "text": plain(t.get("description")), "nodes": nodes,
                          "needs": needs, "active": active, "modelled": modelled})
        out.append({"name": asp["displayName"], "rarity": asp.get("tier"), "tiers": tiers})
    out.sort(key=lambda a: (RARITY_ORDER.get(a["rarity"], 9), a["name"]))
    return out


def put(doc, gd, name, tier=None, inventory=None):
    """Put an aspect in a build file dict: at `tier` (default: the tier the
    player owns, else the top tier), replacing the same aspect or filling the
    first empty slot. Returns (canonical name, tier, owned tier). Raises
    ValueError for anything the game or WynnBuilder wouldn't take."""
    cls = _class_of(doc, gd)
    asp = find(gd, cls, name)
    name = asp["displayName"]
    top = len(asp.get("tiers") or [])
    owned = inventory.aspect_tier(cls, name) if inventory is not None else 0
    tier = tier if tier is not None else (owned or top)
    if not 1 <= tier <= top:
        raise ValueError(f"{name} has tiers 1-{top}, not {tier}")
    slots = list(doc.get("aspects") or []) + [None] * SLOTS
    slots = slots[:SLOTS]
    at = next((k for k, e in enumerate(slots) if e and e[0] == name), None)
    if at is None:
        at = next((k for k, e in enumerate(slots) if not e), None)
    if at is None:
        raise ValueError(f"all {SLOTS} aspect slots are full ({', '.join(e[0] for e in slots)}); "
                         f"remove one first (--remove-aspect NAME)")
    slots[at] = [name, tier]
    doc["aspects"] = slots
    return name, tier, owned


def remove(doc, gd, name):
    """Take an aspect out of a build file dict. Returns its canonical name."""
    cls = _class_of(doc, gd)
    name = find(gd, cls, name)["displayName"]
    slots = list(doc.get("aspects") or [])
    if not any(e and e[0] == name for e in slots):
        raise ValueError(f"the build has no {name}")
    doc["aspects"] = [None if (e and e[0] == name) else e for e in slots]
    return name


def _class_of(doc, gd):
    weapon = (doc.get("equipment") or [None] * 9)[8]
    if not weapon:
        raise ValueError("aspects need a weapon (they belong to a class)")
    return gd.weapon_class(weapon)


def recommend(build, gd, goal, choices, roll="base", inventory=None):
    """Aspects for the build's empty slots, best first by `goal` (a derived key
    such as puppet_dps or ehp, or a spell name), in WynnBuilder's damage model.

    `choices`: [(aspect id, tier)] to consider (e.g. every aspect at its top
    tier, or the ones the player owns at the tier they own). Aspects already
    in the build stay. Returns {"before", "singles": [(id, tier, gain)] each
    alone, best first, "picked": [(id, tier, gain)] filled one at a time, each
    the best on top of those before it, "after"}."""
    have = list(build.aspects or []) + [None] * SLOTS
    have = have[:SLOTS]
    taken = {a[0] for a in have if a}
    choices = [c for c in choices if c[0] not in taken]
    old = build.aspects

    def score(aspects):
        build.aspects = aspects
        try:
            m = metrics(build, gd, roll, inventory)
            return value(m, goal) if m is not None else 0.0
        finally:
            build.aspects = old

    before = score(have)
    free = [k for k, a in enumerate(have) if not a]
    singles = []
    if free:
        for aid, tier in choices:
            trial = list(have)
            trial[free[0]] = (aid, tier)
            singles.append((aid, tier, score(trial) - before))
    singles.sort(key=lambda s: -s[2])
    picked, cur, cur_v = [], list(have), before
    pool = [(a, t) for a, t, gain in singles]
    for k in free:
        best = None
        for aid, tier in pool:
            trial = list(cur)
            trial[k] = (aid, tier)
            v = score(trial)
            if best is None or v > best[2]:
                best = (aid, tier, v)
        if best is None or best[2] <= cur_v + 1e-9:
            break
        cur[k] = (best[0], best[1])
        picked.append((best[0], best[1], best[2] - cur_v))
        cur_v = best[2]
        pool = [p for p in pool if p[0] != best[0]]
    return {"before": before, "singles": singles, "picked": picked, "after": cur_v}
