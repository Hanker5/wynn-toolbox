"""Checks every build must pass before a link is handed to anyone.

Each check here exists because the design session produced a wrong answer
without it; see knowledge/mechanics.md "Mistakes the verifiers catch".
"""
from .codec import SLOTS, TOME_SLOTS, decode, encode, link_hash
from .skillpoints import WYNN_ORDER, SPItem, apply_manual, calculate_skillpoints, set_bonus_stats
from .rules import SKILLS, base_hp, max_mana, poison_per_second, rolled, skill_points

REQ = [s + "Req" for s in SKILLS]
SKILL_NAMES = {"str": "Strength", "dex": "Dexterity", "int": "Intelligence", "def": "Defence",
               "agi": "Agility"}
STAT_KEYS = ["hp", "maxMana", "mr", "ms", "spd", "eSteal", "lb", "poison", "sdPct",
             "mdPct", "hprRaw", "hprPct", "ls", "xpb", "sdRaw", "mdRaw", "atkTier",
             "eDef", "tDef", "wDef", "fDef", "aDef", "thorns", "ref", "expd"]


def stat(obj, key, roll="base"):
    """An item's or tome's stat at the given roll. "hp" is base health (static)
    plus Health Bonus (rolled). Crafted items carry explicit min/max values."""
    if key == "hp":
        return (obj.get("hp") or 0) + stat(obj, "hpBonus", roll)
    actual = obj.get("_actual")
    if actual and key in actual:                          # a real roll from the inventory
        return actual[key]
    if "rolls" in obj and key in obj["rolls"]:          # crafted item
        lo, hi = obj["rolls"][key]
        return {"min": lo, "max": hi, "base": (lo + hi) // 2}[roll]
    value = obj.get(key) or 0
    if isinstance(value, dict):          # {"static": true, "raw": n}: fixed, never rolls
        return value.get("raw") or 0
    if isinstance(value, str):           # damage ranges like "10-20" are not stats
        return 0
    return rolled(key, value, roll, fixed=bool(obj.get("fixID")))


def sp_requirements(items, bonus_sources=()):
    """Minimum skill points to assign so every item's requirements are met.

    An item's requirement is covered by assigned points plus the skill bonuses of
    every OTHER equipped item and tome, negatives included. (The first solver
    ignored negative bonuses, which is how an "OK" build needed 244 of 200 points.)
    """
    tot = [sum(stat(o, s) for o in (*items, *bonus_sources)) for s in SKILLS]
    need = [0] * 5
    for it in items:
        for j, s in enumerate(SKILLS):
            need[j] = max(need[j], (it.get(REQ[j]) or 0) - (tot[j] - (it.get(s) or 0)))
    return [max(0, n) for n in need]


def _sp_items(equipment, tomes, gd):
    """calculate_skillpoints' inputs: the nine equippables in WYNN_ORDER, and the weapon."""
    by_slot = dict(zip(SLOTS, equipment))
    guild_id = tomes[TOME_SLOTS.index("guildTome1")] if tomes else None
    eq = []
    for slot in WYNN_ORDER:
        if slot == "guildTome1":
            eq.append(SPItem.of(gd.tome(guild_id)) if guild_id is not None else SPItem())
        else:
            name = by_slot.get(slot)
            eq.append(SPItem.of(gd.item(name), gd.set_of.get(name)) if name else SPItem())
    weapon = by_slot.get("weapon")
    w = SPItem.of(gd.item(weapon), gd.set_of.get(weapon)) if weapon else SPItem()
    return eq, w


def build_skillpoints(equipment, tomes, gd):
    """WynnBuilder's skill-point result for gear (9 names in SLOTS order, None for
    empty) and tome ids (14, TOME_SLOTS order). See wynntools.skillpoints."""
    eq, w = _sp_items(equipment, tomes, gd)
    return calculate_skillpoints(eq, w, gd.sets)


def resolve_skillpoints(build, gd):
    """The build's skill points with any set by hand (a ManualSP): automatic
    ones as WynnBuilder assigns them, manual ones as the link's final totals."""
    eq, w = _sp_items(build.equipment, build.tomes, gd)
    return apply_manual(calculate_skillpoints(eq, w, gd.sets), build.skillpoints, eq, w)


def sp_feasible(need, level):
    return sum(need) <= skill_points(level) and max(need) <= 100


def wynnbuilder_order(tree):
    """Node ids in the order WynnBuilder checks them (get_sorted_class_atree:
    Kosaraju's SCC order from the root, js/utils.js make_SCC_graph). The order
    matters for one-way blockers: WynnBuilder lists "Ophanim blocks
    Thunderstorm" but not the reverse, so whichever it checks first wins."""
    by_id = {n["id"]: n for n in tree}
    children = {n["id"]: [] for n in tree}
    for n in tree:
        for p in n["parents"]:
            children[p].append(n["id"])
    root = next(n["id"] for n in tree if not n["parents"])
    post, visited = [], set()

    def visit(u):
        visited.add(u)
        for c in children[u]:
            if c not in visited:
                visit(c)
        post.append(u)
    visit(root)
    order, assigned = [], set()

    def assign(u):
        if u in assigned:
            return
        assigned.add(u)
        order.append(u)
        for p in by_id[u]["parents"]:
            assign(p)
    for u in reversed(post):
        assign(u)
    return order


def tree_activation(tree, selected):
    """Replay WynnBuilder's node-by-node activation.

    A node turns on only once a parent is on, all dependencies are on, no blocker
    is on, and enough OTHER nodes of its archetype are ALREADY on. Checking the
    archetype count over the whole selection instead of in order is the bug that
    let a 29-node tree through where only 10 nodes could actually activate.
    Returns (active_ids, failed_ids).
    """
    by_id = {n["id"]: n for n in tree}
    root = next(n["id"] for n in tree if not n["parents"])
    active, arch = {root}, {}
    order = wynnbuilder_order(tree)
    order += sorted(set(by_id) - set(order))     # unreachable from the root: never activate
    pending = set(selected) - active
    if by_id[root].get("archetype"):
        arch[by_id[root]["archetype"]] = 1
    changed = True
    while changed:
        changed = False
        for nid in [i for i in order if i in pending]:
            n = by_id[nid]
            if not any(p in active for p in n["parents"]):
                continue
            if any(d not in active for d in n.get("dependencies") or []):
                continue
            if any(b in active for b in n.get("blockers") or []):
                continue
            req = n.get("archetype_req") or 0
            if req and arch.get(n.get("req_archetype") or n.get("archetype"), 0) < req:
                continue
            active.add(nid)
            pending.discard(nid)
            if n.get("archetype"):
                arch[n["archetype"]] = arch.get(n["archetype"], 0) + 1
            changed = True
    return active, set(selected) - active


def ap_cost(tree, selected):
    by_id = {n["id"]: n for n in tree}
    return sum(by_id[i].get("cost") or 0 for i in selected)


def summarize(build, gd, roll="base", inventory=None):
    """Totals for a build: gear, tomes, set bonuses and base stats combined.

    `totals` use `roll`; `totals_max` are perfect rolls, which is what
    WynnBuilder's build page displays. Skill points follow WynnBuilder exactly
    (build_skillpoints).
    """
    from .inventory import with_rolls
    items = [with_rolls(gd.item(n), inventory.rolls(n) if inventory else None)
             for n in build.equipment if n is not None]
    tomes = [gd.tome(t) for t in build.tomes if t is not None]
    msp = resolve_skillpoints(build, gd)
    sp = msp.auto
    set_stats, set_majors = set_bonus_stats(sp.set_counts, gd.sets)
    totals = {k: sum(stat(o, k, roll) for o in (*items, *tomes)) for k in STAT_KEYS}
    totals_max = {k: sum(stat(o, k, "max") for o in (*items, *tomes)) for k in STAT_KEYS}
    from .codec import POWDERABLE
    from .damage import armor_powder_stats       # applyArmorPowders: +def, -def, +hp
    powder = {}
    for idx, pw in zip(POWDERABLE, build.powders):
        name = build.equipment[idx]
        if name and pw and gd.item(name).get("category") == "armor":
            for k, v in armor_powder_stats(gd.item(name), pw).items():
                powder[k] = powder.get(k, 0) + v
    for t in (totals, totals_max):
        for k, v in powder.items():
            t[k] += v
        t["hp"] += base_hp(build.level) + set_stats.get("hpBonus", 0)
    effective = list(msp.final)          # skill points after the tree's bonuses too
    if build.weapon is not None:
        # Stats the ability tree adds (e.g. +5 mana regen), as WynnBuilder's page shows
        from .damage import build_stats, final_stats
        for r, t in ((roll, totals), ("max", totals_max)):
            before, after = build_stats(build, gd, r, inventory), final_stats(build, gd, r, inventory)[0]
            if r == roll:
                effective = [after.get(k, 0) for k in SKILLS]
            for k in STAT_KEYS:
                if k == "hp":
                    d = after.get("hp", 0) + after.get("hpBonus", 0) - before.get("hp", 0) - before.get("hpBonus", 0)
                else:
                    d = after.get(k, 0) - before.get(k, 0)
                if d:
                    t[k] += d
        for k, v in set_stats.items():
            if k in t and k != "hpBonus":
                t[k] += v
    available = skill_points(build.level)
    spare = available - msp.total_assigned
    int_from_items = msp.final[2] - msp.assigned[2]
    mana_min = max_mana(totals["maxMana"], msp.final[2])
    # With Intelligence set by hand the player already chose; don't move points.
    mana_spare_int = mana_min if msp.manual[2] else \
        max_mana(totals["maxMana"], min(100, msp.assigned[2] + max(spare, 0)) + int_from_items)
    sets = [{"name": name, "pieces": count, "of": len(gd.sets[name]["items"]),
             "bonus": {k: v for k, v in gd.sets[name]["bonuses"][count - 1].items()}}
            for name, count in sorted(sp.set_counts.items())]
    return {"totals": totals, "totals_max": totals_max, "roll": roll,
            "sp_need": dict(zip(SKILLS, msp.assigned)), "sp_total": msp.total_assigned,
            "sp_final": dict(zip(SKILLS, msp.final)),
            "sp_under_100": all(a <= 100 for a in msp.assigned),
            "sp_manual": dict(zip(SKILLS, msp.manual)), "sp_wearable": msp.wearable,
            "sp_effective": dict(zip(SKILLS, effective)),
            "sp_auto_need": dict(zip(SKILLS, sp.assigned)),
            "sp_auto_final": dict(zip(SKILLS, sp.final)),
            "sp_available": available, "spare_sp": spare,
            "mana_min_int": mana_min, "mana_spare_into_int": mana_spare_int,
            "poison_per_second": poison_per_second(totals["poison"]),
            "sets": sets, "set_majors": sorted(set_majors)}


def check_link(link, gd=None, inventory=None):
    """Run every check on a link. Returns (ok, report)."""
    h = link_hash(link)
    build = decode(h, gd)
    from .data import GameData
    gd = gd if gd is not None and gd.version == build.version else GameData(build.version)
    report = {"build": build, "summary": summarize(build, gd, inventory=inventory), "problems": []}
    if encode(build, gd) != h:
        report["problems"].append("link does not round-trip through the encoder")
    s = report["summary"]
    for slot, name in zip(("helmet", "chestplate", "leggings", "boots", "ring1", "ring2",
                           "bracelet", "necklace", "weapon"), build.equipment):
        if name and name.startswith("CR-"):
            for p in gd.item(name).get("problems", []):
                report["problems"].append(f"crafted {slot}: {p}")
    manual = any(s["sp_manual"].values())
    if s["sp_total"] > s["sp_available"]:
        report["problems"].append(f"{'assigns' if manual else 'needs'} {s['sp_total']} skill points, "
                                  f"only {s['sp_available']} available")
    if not s["sp_under_100"]:
        over = [f"{SKILL_NAMES[k]} {v}" for k, v in s["sp_need"].items() if v > 100]
        report["problems"].append("more than 100 points assigned to one skill: " + ", ".join(over))
    if not s["sp_wearable"]:
        low = [f"{SKILL_NAMES[k]} {s['sp_need'][k]} assigned, the gear needs {s['sp_auto_need'][k]}"
               for k in SKILLS if s["sp_need"][k] < s["sp_auto_need"][k]]
        report["problems"].append("skill points set by hand are too low to wear every item: "
                                  + ", ".join(low))
    if build.weapon is not None:
        from .rules import ability_points
        tree = gd.tree(gd.weapon_class(build.weapon))
        _, failed = tree_activation(tree, build.atree)
        names = {n["id"]: n["display_name"] for n in tree}
        report["tree_failed"] = sorted(names[i] for i in failed)
        if failed:
            report["problems"].append("ability nodes cannot activate: " +
                                      ", ".join(report["tree_failed"]))
        cost, cap = ap_cost(tree, build.atree), ability_points(build.level)
        if cost > cap:
            report["problems"].append(f"ability tree costs {cost} AP, cap is {cap}")
        report["ap"] = (cost, cap)
    return not report["problems"], report
