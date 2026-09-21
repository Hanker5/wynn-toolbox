"""Checks every build must pass before a link is handed to anyone.

Each check here exists because the design session produced a wrong answer
without it; see knowledge/mechanics.md "Mistakes the verifiers catch".
"""
from .codec import decode, encode, link_hash
from .rules import SKILLS, base_hp, max_mana, poison_per_second, rolled, skill_points

REQ = [s + "Req" for s in SKILLS]
STAT_KEYS = ["hp", "maxMana", "mr", "ms", "spd", "eSteal", "lb", "poison", "sdPct",
             "mdPct", "hprRaw", "hprPct", "ls", "xpb", "sdRaw", "mdRaw", "atkTier",
             "eDef", "tDef", "wDef", "fDef", "aDef", "thorns", "ref", "expd"]


def stat(obj, key, roll="base"):
    """An item's or tome's stat at the given roll. "hp" is base health (static)
    plus Health Bonus (rolled). Crafted items carry explicit min/max values."""
    if key == "hp":
        return (obj.get("hp") or 0) + stat(obj, "hpBonus", roll)
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


def sp_feasible(need, level):
    return sum(need) <= skill_points(level) and max(need) <= 100


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
    if by_id[root].get("archetype"):
        arch[by_id[root]["archetype"]] = 1
    changed = True
    while changed:
        changed = False
        for nid in sorted(set(selected) - active):
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
            if n.get("archetype"):
                arch[n["archetype"]] = arch.get(n["archetype"], 0) + 1
            changed = True
    return active, set(selected) - active


def ap_cost(tree, selected):
    by_id = {n["id"]: n for n in tree}
    return sum(by_id[i].get("cost") or 0 for i in selected)


def summarize(build, gd, roll="base"):
    """Totals for a build, with gear, tomes and base stats combined.

    `totals` use `roll`; `totals_max` are perfect rolls, which is what
    WynnBuilder's build page displays.
    """
    items = [gd.item(n) for n in build.equipment if n is not None]
    tomes = [gd.tome(t) for t in build.tomes if t is not None]
    need = sp_requirements(items, tomes)
    spare = skill_points(build.level) - sum(need)
    totals = {k: sum(stat(o, k, roll) for o in (*items, *tomes)) for k in STAT_KEYS}
    totals["hp"] += base_hp(build.level)
    totals_max = {k: sum(stat(o, k, "max") for o in (*items, *tomes)) for k in STAT_KEYS}
    totals_max["hp"] += base_hp(build.level)
    bonus_int = sum(stat(o, "int") for o in (*items, *tomes))
    mana_min = max_mana(totals["maxMana"], need[2] + bonus_int)
    # (skill points never roll, so requirements and Int bonuses are roll-independent)
    mana_spare_int = max_mana(totals["maxMana"], min(100, need[2] + max(spare, 0)) + bonus_int)
    return {"totals": totals, "totals_max": totals_max, "roll": roll, "sp_need": dict(zip(SKILLS, need)), "sp_total": sum(need),
            "sp_available": skill_points(build.level), "spare_sp": spare,
            "mana_min_int": mana_min, "mana_spare_into_int": mana_spare_int,
            "poison_per_second": poison_per_second(totals["poison"])}


def check_link(link, gd=None):
    """Run every check on a link. Returns (ok, report)."""
    h = link_hash(link)
    build = decode(h, gd)
    from .data import GameData
    gd = gd if gd is not None and gd.version == build.version else GameData(build.version)
    report = {"build": build, "summary": summarize(build, gd), "problems": []}
    if encode(build, gd) != h:
        report["problems"].append("link does not round-trip through the encoder")
    s = report["summary"]
    for slot, name in zip(("helmet", "chestplate", "leggings", "boots", "ring1", "ring2",
                           "bracelet", "necklace", "weapon"), build.equipment):
        if name and name.startswith("CR-"):
            for p in gd.item(name).get("problems", []):
                report["problems"].append(f"crafted {slot}: {p}")
    if s["sp_total"] > s["sp_available"]:
        report["problems"].append(f"needs {s['sp_total']} skill points, only {s['sp_available']} available")
    if max(s["sp_need"].values()) > 100:
        report["problems"].append("a skill needs more than 100 assigned points")
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
