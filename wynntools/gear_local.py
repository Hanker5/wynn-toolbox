"""Local search for goals that aren't a sum of item stats: effective HP, health
regen with its % bonus, main-attack, puppet and summon DPS, a spell's damage,
the lowest elemental defence (after % bonuses), or a mix with item stats.

These come out of WynnBuilder's damage model, so no linear program can hold
them exactly. The search linearizes the goal around the current build (the
change in the goal for a small change in each stat, worked out with the model
itself), lets the exact gear program (wynntools.gear_milp) pick the best gear
for that straight-line version, then checks the pick exactly, and repeats from
the new build until nothing better turns up. Every build it reports passed
every exact check; "best" means best found, not proven optimal.

Weapons: a goal about damage depends on the weapon's own damage, which no
straight line captures, so the search fixes the weapon and runs once per
candidate: the best few by the goal on their own, then the best few with the
gear the first pass found. Other goals leave the weapon to the program.

Tomes: with "tome_pool" owned/any, the gear program also picks tomes for the
empty tome slots at every step (as the exact search does), and each pick is
checked with those tomes in. A re-searched build's aspects and its powders on
items that stay count from the start (Spec.aspects, Spec.powders).

Spare skill points: with a derived goal, points the gear doesn't need go where
they help the goal most (a few at a time, each step checked exactly), and the
build keeps them as skill points set by hand. Set `"spare_sp": "none"` in the
spec to leave them unassigned instead.
"""
import dataclasses
import time

from .damage import STATIC_IDS, build_stats, damage_report
from .derived import DAMAGE_KEYS, from_report
from .gear_milp import GearModel, Infeasible, _Rows
from .gear_solver import DAMAGE_GOAL_PREFIX, EMPTY, MIN_ELEDEF, Result, assign_for_floors
from .inventory import name_of
from .rules import ROLLED_IDS, SKILLS, max_mana, skill_points
from .verify import build_skillpoints

GOAL_KEYS = sorted(ROLLED_IDS | set(STATIC_IDS) | {"hpBonus"})


@dataclasses.dataclass
class Eval:
    """One build, checked exactly: its goal value and derived numbers."""
    names: list
    value: float
    manual: list | None          # skill points set by hand (final totals) or None
    metrics: dict
    sp_assigned: list
    shortfall: float             # summed relative shortfall on damage-model floors (0 = met)
    tomes: list | None = None    # 14 tome ids (with the ones the search chose)


def _uses_damage(keys):
    return any(k in DAMAGE_KEYS or k.startswith(DAMAGE_GOAL_PREFIX) for k in keys)


class LocalSearch:
    def __init__(self, spec, gd, progress=None, weapons=4, rounds=5, time_limit=900,
                 spare_sp=None):
        self.spec, self.gd, self.progress = spec, gd, progress
        self.weapons, self.rounds, self.time_limit = weapons, rounds, time_limit
        self.spare = spare_sp or spec.spare_sp or ("goal" if spec.derived_objective() else "none")
        self.budget = skill_points(spec.level)
        self.choose_tomes = spec.tome_pool != "fixed"
        self.tome_ids = list(spec.tomes) + [None] * (14 - len(spec.tomes))
        self.derived = spec.derived_floors()
        keys = list(spec.objective) + list(self.derived)
        self.damage = _uses_damage(keys)
        if self.damage and not spec.atree:
            raise ValueError("damage goals need an ability tree: give a tree preset")
        self.evaluated = {}                   # key(names, tomes) -> Eval or None
        self.legal = set()                    # builds the program proposed: every other check passed
        self.t0 = time.time()

    # ------------------------------------------------------------ exact evaluation
    def goal(self, stats, m):
        """The spec's objective for a build, from its stat map and derived numbers."""
        total = 0.0
        for k, w in self.spec.objective.items():
            if k.startswith(DAMAGE_GOAL_PREFIX):
                v = m["spells"].get(k[len(DAMAGE_GOAL_PREFIX):]) or 0.0
            elif k == MIN_ELEDEF or k in m and k in ("ehp", "ehp_no_agi", "hpr", "melee_dps",
                                                      "puppet_dps", "summon_dps"):
                v = m[k]
            elif k == "hp":
                v = stats.get("hp", 0) + stats.get("hpBonus", 0)
            else:
                v = stats.get(k, 0)
                v = v if isinstance(v, (int, float)) else 0
            total += w * v
        return total

    def shortfall(self, m):
        out = 0.0
        for k, floor in self.derived.items():
            v = m["spells"].get(k[len(DAMAGE_GOAL_PREFIX):]) if k.startswith(DAMAGE_GOAL_PREFIX) else m[k]
            v = v or 0.0
            if v < floor:
                out += (floor - v) / max(abs(floor), 1.0)
        return out

    def key(self, names, tomes=None):
        """A candidate's key in `evaluated` and `legal`: its 9 names, and its tomes
        when the search chooses them."""
        return tuple(names) + (tuple(tomes or self.tome_ids) if self.choose_tomes else ())

    def _build(self, names, manual, tomes=None):
        return self.spec.build(names, tomes or self.tome_ids, manual)

    def _score(self, names, manual, tomes=None):
        b = self._build(names, manual, tomes)
        stats = build_stats(b, self.gd, self.spec.roll, self.spec.inventory)
        rep = damage_report(b, self.gd, self.spec.roll, self.spec.inventory, base=stats)
        m = from_report(rep)
        return self.goal(stats, m), self.shortfall(m), m, stats

    def _mana_ok(self, stats, int_final, spare_left):
        if "mana" not in self.spec.floors:
            return True
        return max_mana(stats.get("maxMana", 0), min(int_final + max(spare_left, 0), 10**9)) \
            >= self.spec.floors["mana"]

    def evaluate(self, names, tomes=None):
        """Eval for a build (None if it fails a check). Cached by items (and tomes)."""
        tomes = list(tomes or self.tome_ids)
        key = self.key(names, tomes)
        if key in self.evaluated:
            return self.evaluated[key]
        self.evaluated[key] = None
        spec, gd = self.spec, self.gd
        sp = build_skillpoints(list(names), tomes, gd)
        if sp.total_assigned > self.budget or not sp.under_100:
            return None
        got = assign_for_floors(sp, spec.skill_floors(), self.budget)
        if got is None:
            return None
        extra, _ = got
        spare = self.budget - sp.total_assigned - sum(extra)

        def manual_for(ex):
            return None if not any(ex) else [sp.final[j] + ex[j] if ex[j] else None for j in range(5)]

        def attempt(ex):
            left = self.budget - sp.total_assigned - sum(ex)
            v, short, m, stats = self._score(names, manual_for(ex), tomes)
            # Intelligence set by hand counts as is; points left over may still go there.
            int_final = sp.final[2] + ex[2]
            spare_to_int = min(left, 100 - sp.assigned[2] - ex[2])
            if not self._mana_ok(stats, int_final, spare_to_int):
                return None
            return (-short, v), m
        cur = attempt(extra)
        if cur is None:
            return None
        if self.spare == "goal" and spare > 0:
            chunk = max(1, spare // 6)
            while spare > 0:
                best = None
                for j in range(5):
                    room = 100 - sp.assigned[j] - extra[j]
                    step = min(chunk, spare, room)
                    if step <= 0:
                        continue
                    trial = list(extra)
                    trial[j] += step
                    got = attempt(trial)
                    if got and got[0] > cur[0] and (best is None or got[0] > best[1][0]):
                        best = (trial, got, step)
                if best:
                    extra, cur, spare = best[0], best[1], spare - best[2]
                elif chunk > 1:
                    chunk = max(1, chunk // 2)
                else:
                    break
        (neg_short, value), m = cur
        ev = Eval(list(names), value, manual_for(extra), m,
                  [sp.assigned[j] + extra[j] for j in range(5)], -neg_short, tomes)
        self.evaluated[key] = ev
        return ev

    # ------------------------------------------------------------ linearization
    def gradient(self, names, manual, tomes=None):
        """d(goal)/d(stat) at a build, for every stat an item can carry, and the
        same for each derived floor. Skill keys mean final skill points."""
        b = self._build(names, manual, tomes)
        base = build_stats(b, self.gd, self.spec.roll, self.spec.inventory)
        v0, m0 = self._goal_and_floors(b, base)
        keys = self.keys
        g = {"goal": {}, **{k: {} for k in self.derived}}
        for k in keys:
            cur = base.get(k, 0)
            if not isinstance(cur, (int, float)):
                continue
            d = 1 if k in SKILLS else max(1, round(abs(cur) * 0.02))   # stats are whole numbers
            s2 = dict(base)
            s2[k] = cur + d
            v1, m1 = self._goal_and_floors(b, s2)
            g["goal"][k] = (v1 - v0) / d
            for f in self.derived:
                g[f][k] = (m1[f] - m0[f]) / d
        return g, v0, m0

    def _goal_and_floors(self, b, stats):
        rep = damage_report(b, self.gd, self.spec.roll, self.spec.inventory, base=stats)
        m = from_report(rep)
        floors = {}
        for k in self.derived:
            floors[k] = (m["spells"].get(k[len(DAMAGE_GOAL_PREFIX):]) or 0.0) \
                if k.startswith(DAMAGE_GOAL_PREFIX) else m[k]
        return self.goal(stats, m), floors

    def item_vec(self, it):
        """An item's stats as build_stats adds them up (rolled IDs at the roll)."""
        out = {}
        for k in self.keys:
            if k in ROLLED_IDS or k == "hpBonus":
                v = self.model.stat(it, k) if k != "hpBonus" else \
                    self.model.stat(it, "hp") - (it.get("hp") or 0)
            else:
                v = it.get(k) or 0
                v = 0 if isinstance(v, (dict, str)) else v
            if v:
                out[k] = v
        return out

    # ------------------------------------------------------------ the search
    def run(self):
        spec = self.spec
        base_model = GearModel(dataclasses.replace(spec, floors={
            k: v for k, v in spec.floors.items() if k not in self.derived and k != "damage"}), self.gd)
        self.model = base_model
        self.keys = self._keys(base_model)
        rank = self.damage and "weapon" not in spec.force
        plan = self._rank_weapons(base_model, [None] * 8)[:self.weapons] if rank \
            else [spec.force.get("weapon")]
        best, tried = None, []

        def climb(weapons, of):
            nonlocal best
            for w in weapons:
                tried.append(w)
                ev = self._climb(w, len(tried) - 1, of)
                if ev and (best is None or (-ev.shortfall, ev.value) > (-best.shortfall, best.value)):
                    best = ev
        extra = max(1, self.weapons // 2) if rank else 0
        climb(plan, len(plan) + extra)
        if rank and best:          # second pass: every weapon, with the best gear so far
            more = [w for w in self._rank_weapons(base_model, best.names[:8]) if w not in tried]
            climb(more[:extra], len(plan) + extra)
        self.best = best
        if best is None or best.shortfall > 0:
            return None
        return Result(best.value, best.names, best.sp_assigned, time.time() - self.t0,
                      skillpoints=best.manual, metrics=best.metrics,
                      tomes=best.tomes if self.choose_tomes else None)

    def _keys(self, model):
        keys = set(SKILLS)
        for it in model.var_item:
            if it is EMPTY:
                continue
            for k in GOAL_KEYS:
                v = it.get(k)
                if v and not isinstance(v, str):
                    keys.add(k)
            if it.get("rolls"):
                keys.update(k for k in it["rolls"] if k in GOAL_KEYS)
        keys.discard("hp")
        return sorted(keys | {"hp", "hpBonus"})

    def _rank_weapons(self, model, armor):
        """Usable weapons, best first by the goal with `armor` (8 names or None).
        A quick look: skill-point floors are met, spare points stay unassigned."""
        scored = []
        for v in model.by_kind["weapon"]:
            names = list(armor) + [name_of(self.gd, model.var_item[v])]
            sp = build_skillpoints(names, self.tome_ids, self.gd)
            if sp.total_assigned > self.budget or not sp.under_100:
                continue
            got = assign_for_floors(sp, self.spec.skill_floors(), self.budget)
            if got is None:
                continue
            value, short, _, _ = self._score(names, got[1])
            scored.append(((-short, value), names[8]))
            self._tick(None)
        scored.sort(reverse=True)
        return [n for _, n in scored]

    def _tick(self, fraction, best=None):
        if self.progress:
            self.progress({"fraction": fraction, "evaluated": len(self.evaluated),
                           "best": best, "elapsed": time.time() - self.t0})
        if time.time() - self.t0 > self.time_limit:
            raise TimeoutError(f"local search passed {self.time_limit}s")

    def _climb(self, weapon, index, total):
        """Linearize, re-solve, check; repeat while the build improves. Only
        builds the program proposed count (a weapon-only start is just a place
        to linearize from: it misses the spec's other minimums)."""
        spec = self.spec
        sub = spec if weapon is None else dataclasses.replace(
            spec, force={**spec.force, "weapon": weapon})
        sub = dataclasses.replace(sub, floors={k: v for k, v in sub.floors.items()
                                               if k not in self.derived and k != "damage"})
        try:
            model = GearModel(sub, self.gd)
        except Infeasible:
            return None
        self.model = model

        def accept(names, _ok, tomes=None):
            if self.evaluate(names, tomes) is None:
                return False
            self.legal.add(self.key(names, tomes))
            return True

        def left():
            return max(1, self.time_limit - (time.time() - self.t0))
        best = None
        cur = self.evaluate([None] * 8 + [weapon]) if weapon else None
        if cur is None:              # no weapon yet, or the weapon alone fails: the program's pick
            got = model.solve(max_rounds=200, time_limit=left(), accept=accept)
            if got is None:
                return None
            cur = best = self.evaluate(got.names, got.tomes)
        for rnd in range(self.rounds):
            self._tick((index + rnd / self.rounds) / max(total, 1), best and best.value)
            g, _, m0 = self.gradient(cur.names, cur.manual, cur.tomes)
            c = self._objective(model, g["goal"])
            rows = self._floor_rows(model, g, m0, cur)
            proposals = []
            for extra in (rows, None):           # linearized floors can be too strict
                try:
                    got = model.solve(c, extra_rows=extra, max_rounds=60, time_limit=left(),
                                      accept=accept, margins=())
                except TimeoutError:
                    got = None
                if got:
                    proposals.append((got.names, got.tomes))
                    model.cut(got.cuts, got.names, got.tomes)   # and the runner-up, for variety
                    try:
                        nxt = model.solve(c, extra_rows=got.cuts, max_rounds=20, time_limit=left(),
                                          accept=accept, margins=())
                    except TimeoutError:
                        nxt = None
                    if nxt:
                        proposals.append((nxt.names, nxt.tomes))
                    break
            improved = False
            for names, tomes in proposals:
                ev = self.evaluate(names, tomes)
                if ev and (best is None or (-ev.shortfall, ev.value) > (-best.shortfall, best.value + 1e-9)):
                    best, improved = ev, True
            if not improved:
                break
            cur = best
        return best

    def _objective(self, model, grad):
        lam = max(0.0, max(grad.get(s, 0.0) for s in SKILLS)) if self.spare == "goal" else 0.0
        item_value = lambda it: sum(grad.get(k, 0.0) * v for k, v in self.item_vec(it).items())

        def set_value(bonus):
            total = 0.0
            for k, v in bonus.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    total += grad.get(k, 0.0) * v
            return total
        if self.spare == "goal":
            per_point = [lam - grad.get(s, 0.0) for s in SKILLS]
        else:
            per_point = [1e-6] * 5     # don't reward points the build won't assign
        return model.objective_vector(item_value, set_value, per_point)

    def _floor_rows(self, model, g, m0, cur):
        """Each damage-model floor as a straight line around the current build."""
        rows = _Rows()
        if not self.derived:
            return rows
        cur_vec = {}
        chosen = [self.gd.tome(t) for k, t in enumerate(cur.tomes or ())      # the search's tome picks
                  if t is not None and self.tome_ids[k] is None]
        for it in [self.gd.item(n) for n in cur.names if n] + chosen:
            for k, v in self.item_vec(it).items():
                cur_vec[k] = cur_vec.get(k, 0) + v
        for f, floor in self.derived.items():
            grad = g[f]
            terms = [(v, sum(grad.get(k, 0.0) * x for k, x in self.item_vec(it).items()))
                     for v, it in enumerate(model.var_item) if it is not EMPTY]
            terms += [(v, sum(grad.get(k, 0.0) * x for k, x in self.item_vec(t).items()))
                      for v, (_, t) in model.tome_vars.items()]
            here = sum(grad.get(k, 0.0) * x for k, x in cur_vec.items())
            rows.add(terms, lo=floor - m0[f] + here)
        return rows


def solve_local(spec, gd, progress=None, **kw):
    """The best build found for a spec with a derived goal, or None."""
    return LocalSearch(spec, gd, progress=progress, **kw).run()
