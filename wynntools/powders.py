"""Powder planner: the best powders for a build's weapon and armor, separately.

Weapon powders convert the weapon's neutral damage to their element, in the
order they go on (js/powders.js calc_weapon_powder), so every order of every
element is tried at the chosen tier and scored with WynnBuilder's damage model.

Armor powders add health by tier and move elemental defence (+ to their own
element, - to the one before it in Earth-Thunder-Water-Fire-Air), the same for
every piece, so only how many of each element matters: every mix is tried.

Goals
  weapon: a damage number ("melee_dps", "puppet_dps", "summon_dps" or
          "damage:<spell>"), or "special:<name>" (Quake, Chain Lightning, Curse,
          Courage, Wind Prison): only powder orders that give that special,
          scored by the damage number with the special on at the power they give.
  armor:  "hp" (health; elemental balance breaks ties), "eledef" (the lowest
          elemental defence as high as it goes; health breaks ties), or
          "special:<element letter>": every armor powder of that element (for
          its armor special), the rest as for "hp".
Powder specials are off unless a goal names one (WynnBuilder's default too).
A special takes two or more tier IV+ powders of its element on one item
(wynntools.damage.powder_special).
"""
import itertools

from .codec import POWDERABLE, POWDER_ELEMENTS, POWDER_TIERS, powder_name
from .damage import (POWDER_ARMOR_HP, POWDER_SPECIALS, POWDER_STATS, SKP_ELEMENTS, SPECIAL_BY_NAME,
                     final_stats, powder_special, raw_to_pct_uncapped)
from .derived import metrics, value

# js/powders.js powderLevelReq: the level each tier needs
POWDER_LEVEL = [1, 5, 15, 25, 40, 55, 70]
ARMOR_SLOTS = ("helmet", "chestplate", "leggings", "boots")


def top_tier(level):
    return max(t + 1 for t, lvl in enumerate(POWDER_LEVEL) if lvl <= level)


def pid(element, tier):
    return POWDER_ELEMENTS.index(element) * POWDER_TIERS + tier - 1


def _slots(gd, name):
    return (gd.item(name).get("slots") or 0) if name else 0


def plan_weapon(build, gd, goal="melee_dps", tier=None, roll="base", inventory=None,
                measure="melee_dps"):
    """{"powders": [names], "value", "before", "goal", "special", "tier"} or
    None when the weapon has no powder slots. A special playstyle keeps only
    powder orders that give that special (damage.powder_special), with the
    special on at the power they give, scored by `measure`."""
    weapon = build.equipment[8]
    n = _slots(gd, weapon)
    if not n:
        return None
    tier = tier or top_tier(build.level)
    want = None
    if not goal.startswith("special:"):
        measure = goal
    else:
        name = goal[len("special:"):]
        if name not in SPECIAL_BY_NAME:
            raise ValueError(f"unknown weapon special {name!r}; one of {', '.join(SPECIAL_BY_NAME)}")
        if tier < 4 or n < 2:
            raise ValueError("a powder special needs two powders of tier IV or higher "
                             f"(this plan uses tier {tier}; the weapon has {n} slot(s))")
        want = SPECIAL_BY_NAME[name][0]
    k = POWDERABLE.index(8)

    def score(seq, special):
        old = build.powders[k]
        build.powders[k] = [pid(e, tier) for e in seq]
        try:
            m = metrics(build, gd, roll, inventory, specials=special)
            return value(m, measure[len("damage:"):] if measure.startswith("damage:") else measure), m
        finally:
            build.powders[k] = old
    before = score_current(build, gd, measure, roll, inventory)
    best = None
    for seq in itertools.product(POWDER_ELEMENTS, repeat=n):
        special = None
        if want is not None:
            got = powder_special([pid(e, tier) for e in seq])
            if got is None or got[0] != want:
                continue
            special = {"weapon": [POWDER_SPECIALS[want]["weapon"], got[1]]}
        v, m = score(seq, special)
        burst = (m.get("powder_special") or {}).get("average") or 0
        if best is None or (v, burst) > (best[0], best[2]):
            best = (v, seq, burst, m, special)
    return {"powders": [powder_name(pid(e, tier)) for e in best[1]], "value": best[0],
            "before": before, "goal": goal, "measure": measure, "special": best[4], "tier": tier,
            "burst": best[3].get("powder_special")}


def score_current(build, gd, measure, roll="base", inventory=None):
    m = metrics(build, gd, roll, inventory)
    return value(m, measure[len("damage:"):] if measure.startswith("damage:") else measure)


def plan_armor(build, gd, goal="hp", tier=None, roll="base", inventory=None):
    """{"powders": {slot: [names]}, "hp", "eledefs", "before": {...}, "goal", "tier"}."""
    tier = tier or top_tier(build.level)
    slots = {s: _slots(gd, build.equipment[i]) for i, s in enumerate(ARMOR_SLOTS)}
    total = sum(slots.values())
    raw, pct, hp0 = _defences_without_armor_powders(build, gd, roll, inventory)
    if goal.startswith("special:"):
        e = goal[len("special:"):]
        if e not in SKP_ELEMENTS:
            raise ValueError("armor special goal is special:<e|t|w|f|a>")
        mixes = [tuple(total if x == e else 0 for x in SKP_ELEMENTS)]
    elif goal in ("hp", "eledef"):
        mixes = [c for c in _compositions(total, 5)]
    else:
        raise ValueError("armor goal is hp, eledef or special:<element>")
    stats = POWDER_STATS

    def result(mix):
        d = dict(raw)
        for i, count in enumerate(mix):
            if not count:
                continue
            p = stats[i * POWDER_TIERS + tier - 1]
            d[SKP_ELEMENTS[i]] += p[3] * count
            d[SKP_ELEMENTS[(i + 4) % 5]] -= p[4] * count
        eledefs = {e: raw_to_pct_uncapped(d[e], pct[e]) for e in SKP_ELEMENTS}
        return hp0 + POWDER_ARMOR_HP[tier - 1] * sum(mix), eledefs
    scored = []
    for mix in mixes:
        hp, ed = result(mix)
        low = min(ed.values())
        key = (hp, low) if goal != "eledef" else (low, hp)
        scored.append((key, mix, hp, ed))
    key, mix, hp, ed = max(scored, key=lambda x: (x[0], -sum(x[1])))
    # hand the mix out piece by piece
    pool = [e for e, c in zip(SKP_ELEMENTS, mix) for _ in range(c)]
    out = {}
    for s in ARMOR_SLOTS:
        out[s] = [powder_name(pid(e, tier)) for e in pool[:slots[s]]]
        pool = pool[slots[s]:]
    cur_hp, cur_ed = _current_armor(build, gd, roll, inventory)
    return {"powders": out, "hp": hp, "eledefs": ed, "lowest": min(ed.values()),
            "before": {"hp": cur_hp, "eledefs": cur_ed, "lowest": min(cur_ed.values())},
            "goal": goal, "tier": tier, "slots": slots}


def _compositions(n, k):
    """Every way to pick up to n powders among k elements (counts per element)."""
    for total in range(n + 1):
        for cut in itertools.combinations(range(total + k - 1), k - 1):
            prev, parts = -1, []
            for c in cut:
                parts.append(c - prev - 1)
                prev = c
            parts.append(total + k - 1 - prev - 1)
            yield tuple(parts)


def _defences_without_armor_powders(build, gd, roll, inventory):
    """Raw elemental defences, their % bonuses and health, as if the armor had no powders."""
    k_armor = [POWDERABLE.index(i) for i in range(4)]
    saved = [build.powders[k] for k in k_armor]
    for k in k_armor:
        build.powders[k] = []
    try:
        if build.equipment[8]:
            stats = final_stats(build, gd, roll, inventory)[0]
        else:
            from .damage import build_stats
            stats = build_stats(build, gd, roll, inventory)
    finally:
        for k, v in zip(k_armor, saved):
            build.powders[k] = v
    raw = {e: stats.get(e + "Def", 0) for e in SKP_ELEMENTS}
    pct = {e: (stats.get(e + "DefPct", 0) + stats.get("rDefPct", 0)) / 100 for e in SKP_ELEMENTS}
    return raw, pct, stats.get("hp", 0) + stats.get("hpBonus", 0)


def _current_armor(build, gd, roll, inventory):
    if build.equipment[8]:
        stats = final_stats(build, gd, roll, inventory)[0]
    else:
        from .damage import build_stats
        stats = build_stats(build, gd, roll, inventory)
    ed = {e: raw_to_pct_uncapped(stats.get(e + "Def", 0),
                                 (stats.get(e + "DefPct", 0) + stats.get("rDefPct", 0)) / 100)
          for e in SKP_ELEMENTS}
    return stats.get("hp", 0) + stats.get("hpBonus", 0), ed


ARMOR_SPECIALS = {e: sp["armor"] for e, sp in zip(SKP_ELEMENTS, POWDER_SPECIALS)}
