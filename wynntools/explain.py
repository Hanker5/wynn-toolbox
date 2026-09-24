"""Why no build meets a spec, in the player's terms.

When a search comes back empty this finds a smallest set of the player's own
requirements that can't hold together (drop each in turn; keep it only if the
rest then works), says how close each one gets while the others hold, and does
the skill-point arithmetic for the items they kept. Every number comes from the
exact gear program (wynntools.gear_milp) with the same checks as the search.
"""
import dataclasses
import time

import numpy as np

from .derived import DERIVED
from .gear_milp import GearModel, Infeasible
from .gear_solver import DAMAGE_GOAL_PREFIX, MIN_ELEDEF, SKILL_FLOORS, SUM_FLOORS
from .rules import SKILLS, skill_points
from .verify import SKILL_NAMES, build_skillpoints

FLOOR_LABELS = {"hp": "Health", "mr": "Mana regen", "spd": "Walk speed", "hprRaw": "Health regen (raw)",
                "eDef": "Earth defence", "tDef": "Thunder defence", "wDef": "Water defence",
                "fDef": "Fire defence", "aDef": "Air defence", "mana": "Max mana",
                "weapon_dps": "Weapon DPS", MIN_ELEDEF: "Every elemental defence",
                **SKILL_NAMES, **{k: v[0] for k, v in DERIVED.items()}}


def label(key):
    if key.startswith(DAMAGE_GOAL_PREFIX):
        return f"{key[len(DAMAGE_GOAL_PREFIX):]} damage"
    return FLOOR_LABELS.get(key, key)


def _constraints(spec):
    """The player's requirements the exact program can check, as (kind, key, text)."""
    out = [("force", slot, f"{name} in {slot}") for slot, name in (spec.force or {}).items()]
    out += [("major", m, f"major ID {m}") for m in spec.require_major]
    for k, v in spec.floors.items():
        if k in (*SUM_FLOORS, *SKILL_FLOORS, MIN_ELEDEF, "mana", "weapon_dps"):
            out.append(("floor", k, f"{label(k)} at least {v:,}"))
    return out


def _with(spec, keep):
    """The spec with only the requirements in `keep` (and none of its damage-model floors)."""
    kinds = {(k, key) for k, key, _ in keep}
    return dataclasses.replace(
        spec, objective={}, prefer={},
        force={s: n for s, n in spec.force.items() if ("force", s) in kinds},
        require_major=[m for m in spec.require_major if ("major", m) in kinds],
        floors={k: v for k, v in spec.floors.items() if ("floor", k) in kinds})


class _Oracle:
    def __init__(self, gd, deadline):
        self.gd, self.deadline, self.unsure = gd, deadline, False

    def left(self):
        return max(1.0, self.deadline - time.time())

    def feasible(self, spec):
        """True, False, or None (ran out of time)."""
        try:
            model = GearModel(spec, self.gd)
            return model.solve(np.zeros(model.nv), max_rounds=150, time_limit=min(60, self.left())) is not None
        except Infeasible:
            return False
        except TimeoutError:
            self.unsure = True
            return None

    def best(self, spec, key):
        """(value, proven): the most `key` (a floor) reaches under `spec`, and
        whether that is proven the most; None when it can't be said."""
        try:
            probe = dataclasses.replace(spec, objective={MIN_ELEDEF if key == MIN_ELEDEF else key: 1})
            model = GearModel(probe, self.gd)
            if key in SKILLS:                     # final skill: assigned points count too
                j = SKILLS.index(key)
                c = model.objective_vector(lambda it: model.stat(it, key),
                                           lambda b: b.get(key) or 0, 0.0)
                c[model.a_var[j]] = -1
                got = model.solve(c, max_rounds=150, time_limit=min(60, self.left()))
                if got is None:
                    return None
                sp = got[1][2]
                # what the other skill minimums take, then every spare point into this one
                others = sum(max(0, v - sp.final[SKILLS.index(s)])
                             for s, v in spec.skill_floors().items() if s != key)
                spare = skill_points(spec.level) - sp.total_assigned - others
                return sp.final[j] + max(0, min(100 - sp.assigned[j], spare)), False
            if key in ("mana", "weapon_dps"):
                return None
            got = model.solve(max_rounds=150, time_limit=min(60, self.left()))
            if got is None:
                return None
            if key == MIN_ELEDEF:
                return got[1][0], got.proven
            names = got[0]
            items = [self.gd.item(n) for n in names if n]
            sp = got[1][2]
            from .skillpoints import set_bonus_stats
            st = set_bonus_stats(sp.set_counts, self.gd.sets)[0]
            total = sum(model.stat(o, key) for o in (*items, *model.tomes)) + \
                (st.get("hpBonus", 0) if key == "hp" else st.get(key, 0))
            if key == "hp":
                from .rules import base_hp
                total += base_hp(spec.level)
            return total, got.proven
        except (Infeasible, TimeoutError):
            return None


def _sp_lines(spec, gd):
    """Skill-point arithmetic for the kept items and the skill minimums."""
    kept = [spec.force.get(s) for s in ("helmet", "chestplate", "leggings", "boots", "ring1",
                                        "ring2", "bracelet", "necklace", "weapon")]
    floors = spec.skill_floors()
    if not any(kept) and not floors:
        return []
    tomes = list(spec.tomes) + [None] * (14 - len(spec.tomes))
    try:
        sp = build_skillpoints(kept, tomes, gd)
    except KeyError:
        return []
    budget = skill_points(spec.level)
    lines = []
    if any(kept):
        need = ", ".join(f"{SKILL_NAMES[s]} {sp.assigned[j]}" for j, s in enumerate(SKILLS) if sp.assigned[j])
        names = ", ".join(n for n in kept if n)
        lines.append(f"{names} alone need{'s' if sum(map(bool, kept)) == 1 else ''} "
                     f"{sp.total_assigned} of your {budget} skill points" + (f" ({need})" if need else "") + ".")
    if floors:
        extra = {s: max(0, v - sp.final[SKILLS.index(s)]) for s, v in floors.items()}
        more = sum(extra.values())
        asked = ", ".join(f"{SKILL_NAMES[s]} {v}" for s, v in floors.items())
        if more:
            lines.append(f"Your minimums ({asked}) take {more} more points on top"
                         + (" of that" if any(kept) else "") +
                         f", {sp.total_assigned + more} in all, unless other gear gives those skills.")
        over = [SKILL_NAMES[s] for s, v in floors.items()
                if sp.assigned[SKILLS.index(s)] + extra[s] > 100]
        if over:
            lines.append(f"At most 100 points can go into one skill ({', '.join(over)}), so gear "
                         f"has to give the rest.")
        if sp.total_assigned + more > budget:
            lines.append(f"That's more than the {budget} points a level {spec.level} character has, "
                         f"before any other item's requirements.")
    return lines


def explain(spec, gd, found=None, time_limit=180):
    """{"summary", "lines", "conflict": [texts], "unsure": bool} for a spec no
    search could meet. `found`: {floor key: best value a damage-model search
    reached} when that search ran, to report on those floors too."""
    deadline = time.time() + time_limit
    oracle = _Oracle(gd, deadline)
    cons = _constraints(spec)
    out = {"summary": "", "lines": [], "conflict": [], "unsure": False}
    try:
        GearModel(_with(spec, cons), gd)
    except Infeasible as e:
        out["summary"] = str(e)[:1].upper() + str(e)[1:] + "."
        out["lines"] = _sp_lines(spec, gd)
        return out
    except ValueError:
        pass
    ok_all = oracle.feasible(_with(spec, cons))
    if ok_all:
        derived = spec.derived_floors()
        if derived:
            out["summary"] = ("Gear exists for every other requirement; the damage-model minimums "
                              "weren't reached by any build the search checked.")
            for k, v in derived.items():
                got = (found or {}).get(k)
                out["lines"].append(f"{label(k)} at least {v:,}" +
                                    (f": the best found was {got:,.0f}." if got is not None else "."))
            out["conflict"] = [f"{label(k)} at least {v:,}" for k, v in derived.items()]
        else:
            out["summary"] = "A build exists, but the search didn't finish; try again or allow more time."
        return out
    # deletion filter: kept items and major IDs first, so floors stay in the explanation
    order = sorted(cons, key=lambda c: {"force": 0, "major": 1, "floor": 2}[c[0]])
    conflict = list(order)
    for c in order:
        trial = [x for x in conflict if x is not c]
        if time.time() > deadline:
            oracle.unsure = True
            break
        if oracle.feasible(_with(spec, trial)) is False:
            conflict = trial
    out["conflict"] = [t for _, _, t in conflict]
    texts = [t for _, _, t in conflict]
    out["summary"] = ("These can't all hold at once: " + "; ".join(texts) + "."
                      if len(texts) > 1 else f"{texts[0][:1].upper()}{texts[0][1:]} can't be met.")
    for c in conflict:
        if c[0] != "floor":
            continue
        rest = [x for x in conflict if x is not c]
        got = oracle.best(_with(spec, rest), c[1])
        if got is not None:
            best, proven = got
            others = " with the others met" if rest else ""
            how = "the most any legal build reaches" if proven else "the best the search found"
            out["lines"].append(f"{label(c[1])}: {how}{others} is "
                                f"{best:,.0f} (you asked for {spec.floors[c[1]]:,}).")
    if any(c[1] in SKILLS or c[0] == "force" for c in conflict):
        out["lines"] += _sp_lines(_with(spec, conflict), gd)
    out["unsure"] = oracle.unsure
    if oracle.unsure:
        out["lines"].append("Some checks ran out of time, so this may not be the whole story.")
    return out
