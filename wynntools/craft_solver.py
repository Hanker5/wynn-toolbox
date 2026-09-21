"""Crafting suggestions: the best ingredients and layout for a slot and goal.

Ingredient effects depend on position (effectiveness modifiers like "touching"
or "above"), so this searches layouts, scoring each with the exact crafting math
in crafting.py. The search is a multi-start hill climb over a shortlist of
ingredients: the results are strong but not proven optimal.
"""
import random
from dataclasses import dataclass, field

from .crafting import NO_INGREDIENT, WEAPON_TYPES, Craft, craft_item
from .rules import SKILLS
from .verify import stat

POS_KEYS = ("left", "right", "above", "under", "touching", "notTouching")


@dataclass
class CraftSpec:
    item_type: str                  # "helmet", "ring", "relik", ...
    level: int                      # player level; the craft's level must not exceed it
    objective: dict                 # stat -> weight, e.g. {"eSteal": 1}
    roll: str = "base"              # crafted IDs: "min", "base" (midpoint) or "max"
    max_total_reqs: int | None = None
    atk_spd: str | None = None      # weapons: fixed speed, or None to try all three
    exclude: set = field(default_factory=set)
    shortlist: int = 24
    restarts: int = 24
    seed: int = 0


def _score(item, spec):
    return sum(w * stat(item, k, spec.roll) for k, w in spec.objective.items())


def _ing_value(ing, spec):
    """Objective value of one ingredient at 100% effectiveness."""
    total = 0
    for k, w in spec.objective.items():
        rng = ing["ids"].get(k)
        if rng:
            lo, hi = rng["minimum"], rng["maximum"]
            total += w * {"min": lo, "max": hi, "base": (lo + hi) // 2}[spec.roll]
    return total


def suggest_crafts(spec, cd, top=5):
    """Return up to `top` (score, item) pairs, best first. item["craft"] is the Craft."""
    typ = spec.item_type.upper()
    recipes = sorted((r for r in cd.recipes if r["type"] == typ and r["lvl"]["maximum"] <= spec.level),
                     key=lambda r: -r["lvl"]["maximum"])[:1]
    if not recipes:
        return []
    speeds = [spec.atk_spd] if spec.atk_spd else (
        ["SLOW", "NORMAL", "FAST"] if spec.item_type.lower() in WEAPON_TYPES else ["NORMAL"])
    rng = random.Random(spec.seed)
    results = {}
    for recipe in recipes:
        usable = [i for i in cd.ingredients
                  if recipe["skill"] in i["skills"] and (i.get("lvl") or 0) <= recipe["lvl"]["maximum"]
                  and not i.get("isPowder") and i["displayName"] not in spec.exclude]
        by_value = sorted(usable, key=lambda i: -_ing_value(i, spec))
        stat_ings = [i for i in by_value if _ing_value(i, spec) > 0][:spec.shortlist]
        boosters = sorted((i for i in usable if any(v > 0 for v in i["posMods"].values())),
                          key=lambda i: -sum(max(0, v) for v in i["posMods"].values()))[:spec.shortlist // 2]
        pool = [i["displayName"] for i in
                {i["displayName"]: i for i in [cd.ing_by_name[NO_INGREDIENT], *stat_ings, *boosters]}.values()]
        if len(pool) == 1:
            continue
        for spd in speeds:
            def evaluate(names):
                it = craft_item(Craft(recipe["name"], list(names), (3, 3), spd), cd)
                if it["problems"]:
                    return None, it
                if spec.max_total_reqs is not None and \
                        sum(it[f"{s}Req"] for s in SKILLS) > spec.max_total_reqs:
                    return None, it
                # tiebreak: fewer requirements, then more durability
                return (_score(it, spec), -sum(max(0, it[f"{s}Req"]) for s in SKILLS),
                        it["durability"][0]), it

            starts = [[NO_INGREDIENT] * 6]
            if stat_ings:
                starts.append([stat_ings[0]["displayName"]] * 6)
            starts += [[rng.choice(pool) for _ in range(6)] for _ in range(spec.restarts)]
            for layout in starts:
                cur, item = evaluate(layout)
                if cur is None:
                    layout, (cur, item) = [NO_INGREDIENT] * 6, evaluate([NO_INGREDIENT] * 6)
                    if cur is None:
                        continue
                improved = True
                while improved:
                    improved = False
                    moves = [(k, name) for k in range(6) for name in pool]
                    moves += [("swap", a, b) for a in range(6) for b in range(a + 1, 6)]
                    for mv in moves:
                        cand = list(layout)
                        if mv[0] == "swap":
                            cand[mv[1]], cand[mv[2]] = cand[mv[2]], cand[mv[1]]
                        else:
                            cand[mv[0]] = mv[1]
                        if cand == layout:
                            continue
                        val, it = evaluate(cand)
                        if val is not None and val > cur:
                            layout, cur, item, improved = cand, val, it, True
                # mirror-image layouts give identical stats; keep one of each
                key = (cur, tuple(sorted(layout)), spd)
                results.setdefault(key, (cur, item))
    ranked = sorted(results.values(), key=lambda x: x[0], reverse=True)
    return [(v[0], it) for v, it in ranked[:top]]
