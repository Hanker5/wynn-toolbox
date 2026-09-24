"""Exact gear search as a mixed-integer program (scipy/HiGHS), over every usable item.

`solve_gear` (branch and bound) is exact only within per-slot shortlists. This
searches all items at once:

  * one item per slot (rings: two different items; a crafted ring may repeat;
    with an owned-only spec any slot but the weapon may be empty);
  * set bonuses exact, through one-hot "pieces of set s" variables;
  * floors on sums of stats exact (gear, tomes, set bonuses: HP, mana regen,
    walk speed, raw health regen, elemental defences, the lowest elemental
    defence), and so is a "lowest elemental defence" goal;
  * skill points RELAXED: every chosen item's requirement must hold against the
    assigned points plus the other items' final bonuses (WynnBuilder enforces
    exactly this in its last step; crafts', the weapon's and set bonuses never
    count). The order-dependent part of its rule can only need more, so no
    valid build is cut. Floors on final skill points add assigned points;
  * "at most one of these items" groups, and preferred items as a tiebreak.

Each solution is then checked exactly (skill points by WynnBuilder's rules, max
mana). Damage-model floors are not supported (use solve_gear). A build that
fails is cut off and the program re-solved; the first build that passes is
optimal over all items.

`GearModel` keeps the program so other searches can re-solve it with another
objective (wynntools.gear_local) or fewer floors (wynntools.explain).
"""
import time
from typing import NamedTuple

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .codec import SLOTS
from .gear_solver import (CLASS_WEAPON, ELEDEF_KEYS, EMPTY, MIN_ELEDEF, SUM_FLOORS, Result,
                          _crafted_candidates, _usable, assign_for_floors, derived_goal,
                          linear_value)
from .rules import SKILLS, base_hp, max_mana, skill_points
from .skillpoints import set_bonus_stats
from .verify import REQ, build_skillpoints
from .verify import stat as _stat

KINDS = ["helmet", "chestplate", "leggings", "boots", "ring", "bracelet", "necklace", "weapon"]


class _Rows:
    """Sparse constraint rows: lo <= sum(coef * var) <= hi."""

    def __init__(self):
        self.r, self.c, self.v, self.lo, self.hi = [], [], [], [], []

    def add(self, terms, lo=-np.inf, hi=np.inf):
        k = len(self.lo)
        for var, coef in terms:
            if coef:
                self.r.append(k)
                self.c.append(var)
                self.v.append(coef)
        self.lo.append(lo)
        self.hi.append(hi)

    def constraint(self, nvars):
        m = coo_matrix((self.v, (self.r, self.c)), shape=(len(self.lo), nvars)).tocsr()
        return LinearConstraint(m, self.lo, self.hi)


class Infeasible(ValueError):
    """The spec can't be met; `reason` says which part, when it's that simple."""

    def __init__(self, reason=None):
        super().__init__(reason or "no build satisfies these constraints")
        self.reason = reason


class Solved(NamedTuple):
    names: list          # 9 item names in SLOTS order
    checked: tuple       # check(): (score, manual skill points, sp)
    cuts: object         # the _Rows of cuts so far (to ask for the next best)
    proven: bool         # nothing better exists under the objective
    value: float         # the objective's value for this build (the program's own)
    bound: float         # the best any build could still reach


class GearModel:
    """The mixed-integer program for a spec. solve() finds the best build that
    passes every exact check, for the spec's objective or another one."""

    def __init__(self, spec, gd):
        self.spec, self.gd = spec, gd
        memo = {}

        def stat(obj, key):
            k = (id(obj), key)
            if k not in memo:
                memo[k] = _stat(obj, key, spec.roll)
            return memo[k]
        self.stat = stat
        pools = _usable(gd, spec)
        if spec.crafted:
            for kind, items in _crafted_candidates(spec, gd).items():
                slots = ("ring1", "ring2") if kind == "ring" else \
                    ("weapon",) if kind == CLASS_WEAPON[spec.cls] else (kind,)
                for s in slots:
                    pools[s].extend(items)
        fl = spec.floors
        if "weapon_dps" in fl:
            pools["weapon"] = [i for i in pools["weapon"] if (i.get("averageDps") or 0) >= fl["weapon_dps"]]
        self.tome_ids = list(spec.tomes) + [None] * (14 - len(spec.tomes))
        self.tomes = [gd.tome(t) for t in self.tome_ids if t is not None]
        guild = gd.tome(self.tome_ids[6]) if self.tome_ids[6] is not None else None
        if spec.derived_floors():
            # Damage isn't linear in the items, so it could only be checked and cut one
            # build at a time; near-optimal builds just under a floor are too many.
            raise ValueError("the exact search doesn't take damage-model floors (effective HP, "
                             "health regen with %, DPS, spell damage); use the shortlist search")

        # ---- variables: one per (kind, item); a second copy for crafted rings; empties
        var_item, var_kind = [], []
        by_kind = {k: [] for k in KINDS}
        second_copy = {}
        for kind in KINDS:
            pool = pools["ring1" if kind == "ring" else kind]
            seen = set()
            for it in pool:
                nm = gd.name(it)
                if nm in seen:
                    continue
                seen.add(nm)
                v = len(var_item)
                var_item.append(it)
                var_kind.append(kind)
                by_kind[kind].append(v)
                if kind == "ring" and nm.startswith("CR-"):
                    v2 = len(var_item)
                    var_item.append(it)
                    var_kind.append(kind)
                    by_kind[kind].append(v2)
                    second_copy[v] = v2
            if spec.only is not None and kind != "weapon":
                for _ in range(2 if kind == "ring" else 1):
                    v = len(var_item)
                    var_item.append(EMPTY)
                    var_kind.append(kind)
                    by_kind[kind].append(v)
        self.var_item, self.var_kind, self.by_kind = var_item, var_kind, by_kind
        self.n_items = n_items = len(var_item)
        if not by_kind["weapon"]:
            raise Infeasible("no usable weapon (check the class, level, weapon DPS "
                             "minimum, exclusions and inventory)")

        # sets: y[s][c] one-hot for "c pieces of set s"
        set_members = {}
        for v, it in enumerate(var_item):
            if it is EMPTY:
                continue
            s = gd.set_of.get(gd.name(it))
            if s:
                set_members.setdefault(s, []).append(v)
        set_vars = {}
        nv = n_items
        for s, members in sorted(set_members.items()):
            top = min(len(members), len(gd.sets[s]["bonuses"]), 9)
            set_vars[s] = list(range(nv, nv + top + 1))
            nv += top + 1
        self.set_vars = set_vars
        self.a_var = a_var = list(range(nv, nv + 5))    # assigned skill points (relaxed)
        self.b_var = b_var = list(range(nv + 5, nv + 10))   # bonuses that can help requirements
        self.z_var = nv + 10                             # lowest elemental defence (goal)
        self.nv = nv = nv + 11

        rows = _Rows()
        self.rows = rows
        for kind in KINDS:
            need = 2 if kind == "ring" else 1
            rows.add([(v, 1) for v in by_kind[kind]], need, need)
        for v, v2 in second_copy.items():
            rows.add([(v2, 1), (v, -1)], hi=0)
        for s, ys in set_vars.items():
            rows.add([(y, 1) for y in ys], 1, 1)
            rows.add([(v, 1) for v in set_members[s]] + [(y, -c) for c, y in enumerate(ys)], 0, 0)

        # ---- floors on sums of stats
        base_const = {"hp": base_hp(spec.level)}
        for key in SUM_FLOORS:
            if key in fl:
                terms, const = self.stat_terms(key)
                rows.add(terms, lo=fl[key] - const - base_const.get(key, 0))
        if MIN_ELEDEF in fl:
            for key in ELEDEF_KEYS:
                terms, const = self.stat_terms(key)
                rows.add(terms, lo=fl[MIN_ELEDEF] - const)
        if MIN_ELEDEF in spec.objective:       # z <= every elemental defence
            for key in ELEDEF_KEYS:
                terms, const = self.stat_terms(key)
                rows.add(terms + [(self.z_var, -1)], lo=-const)

        # ---- skill points (relaxation). WynnBuilder's last step raises assigned points
        # until every item's requirement holds against the FINAL totals of the other items
        # (non-crafted equipment and the guild tome, negative bonuses included; never the
        # weapon's bonus). So with b_j = that signed total, for every chosen item i:
        #     a_j + b_j - own_ij >= req_ij
        # is necessary; the order-dependent part of the rule can only need more.
        self.budget = budget = skill_points(spec.level)
        helps = lambda v: var_kind[v] != "weapon" and not gd.name(var_item[v]).startswith("CR-")
        for j, s in enumerate(SKILLS):
            const = stat(guild, s) if guild else 0
            terms = [(b_var[j], 1)]
            worst = const                     # most negative b_j can get (for the big-M)
            for kind in KINDS:
                lows = [stat(var_item[v], s) for v in by_kind[kind]
                        if var_item[v] is not EMPTY and helps(v)] + [0]
                worst += min(0, min(lows)) * (2 if kind == "ring" else 1)
            for v, it in enumerate(var_item):
                if it is EMPTY or not helps(v):
                    continue
                bonus = stat(it, s)
                if bonus:
                    terms.append((v, -bonus))
            rows.add(terms, const, const)
            big = max(0, -worst)
            for v, it in enumerate(var_item):
                if it is EMPTY:
                    continue
                req = it.get(REQ[j]) or 0
                if req <= 0:
                    continue
                own = stat(it, s) if helps(v) else 0
                # x=1: a + b - own >= req;  x=0: a + b >= -big (always true)
                rows.add([(a_var[j], 1), (b_var[j], 1), (v, -(own + req + big))], lo=-big)
            # The same requirement without a big-M, per slot type: whichever item is
            # chosen, its requirement is covered by assigned points plus at most the
            # POSITIVE bonuses of the other chosen items. Weaker for one item, but it
            # makes the program's relaxation much tighter (proving a spec impossible
            # took minutes without it). Rings: two are chosen, so not per type.
            pos = {v: max(0, stat(var_item[v], s)) for v in range(n_items)
                   if var_item[v] is not EMPTY and helps(v)}
            for kind in KINDS:
                if kind == "ring":
                    continue
                reqs = [(v, var_item[v].get(REQ[j]) or 0) for v in by_kind[kind]
                        if var_item[v] is not EMPTY]
                if not any(r > 0 for _, r in reqs):
                    continue
                terms = [(a_var[j], 1)] + [(v, b) for v, b in pos.items()
                                           if var_kind[v] != kind]
                terms += [(v, -r) for v, r in reqs if r > 0]
                rows.add(terms, lo=-max(0, const))
            # a floor on the final skill: assigned + every bonus (weapon, crafts and
            # set bonuses included) >= floor
            if s in fl:
                terms = [(a_var[j], 1)] + [(v, stat(it, s)) for v, it in enumerate(var_item)
                                           if it is not EMPTY]
                for st, ys in set_vars.items():
                    for c, y in enumerate(ys):
                        if c:
                            terms.append((y, gd.sets[st]["bonuses"][c - 1].get(s) or 0))
                rows.add(terms, lo=fl[s] - const)
        rows.add([(a, 1) for a in a_var], hi=budget)
        for major in spec.require_major:
            terms = [(v, 1) for v, it in enumerate(var_item)
                     if it is not EMPTY and major in (it.get("majorIds") or [])]
            for s, ys in set_vars.items():
                for c, y in enumerate(ys):
                    if c and major in set_bonus_stats({s: c}, gd.sets)[1]:
                        terms.append((y, 1))
            if not terms:
                raise Infeasible(f"no usable item carries major ID {major}")
            rows.add(terms, lo=1)
        for slot, name in (spec.force or {}).items():
            kind = "ring" if slot in ("ring1", "ring2") else slot
            vs = [v for v in by_kind[kind] if var_item[v] is not EMPTY and gd.name(var_item[v]) == name]
            if not vs:
                raise Infeasible(f"{name} can't go in {slot} (above the level, excluded, not "
                                 f"owned, or for another class)")
            rows.add([(v, 1) for v in vs], lo=1)
        for group in spec.at_most_one:
            names = set(group)
            terms = [(v, 1) for v, it in enumerate(var_item) if it is not EMPTY and gd.name(it) in names]
            if len(terms) > 1:
                rows.add(terms, hi=1)

        self.lb = np.zeros(nv)
        self.ub = np.ones(nv)
        self.ub[a_var] = 100
        self.lb[b_var] = -np.inf
        self.ub[b_var] = np.inf
        self.lb[self.z_var], self.ub[self.z_var] = -np.inf, np.inf
        self.integrality = np.ones(nv)
        self.integrality[a_var + b_var + [self.z_var]] = 0

    # ------------------------------------------------------------ helpers
    def stat_terms(self, key):
        """(terms, constant): a stat's total as a linear expression (items, sets, tomes)."""
        gd, stat = self.gd, self.stat
        terms = [(v, stat(it, key)) for v, it in enumerate(self.var_item) if it is not EMPTY]
        for s, ys in self.set_vars.items():
            for c, y in enumerate(ys):
                if c:
                    st = set_bonus_stats({s: c}, gd.sets)[0]
                    terms.append((y, st.get("hpBonus", 0) if key == "hp" else st.get(key, 0)))
        return terms, sum(stat(t, key) for t in self.tomes)

    def objective_vector(self, item_value=None, set_value=None, per_point=0.0):
        """Coefficients to minimize: minus the value of each item and set bonus,
        plus `per_point` (a number, or one per skill) for every assigned skill
        point. `set_value` gets a set bonus as the data lists it (skill points
        included). By default the spec's objective, with preferred items as a
        tiebreak."""
        spec, gd = self.spec, self.gd
        keys = {k: w for k, w in spec.objective.items() if not derived_goal(k) and k != MIN_ELEDEF}
        item_value = item_value or (lambda it: sum(w * self.stat(it, k) for k, w in keys.items()))
        set_value = set_value or (lambda st: sum(
            w * (st.get("hpBonus", 0) if k == "hp" else st.get(k, 0)) for k, w in keys.items()))
        c = np.zeros(self.nv)
        for v, it in enumerate(self.var_item):
            if it is not EMPTY:
                c[v] = -item_value(it)
        for s, ys in self.set_vars.items():
            for cnt, y in enumerate(ys):
                if cnt:
                    c[y] = -set_value(gd.sets[s]["bonuses"][cnt - 1])
        if MIN_ELEDEF in spec.objective:
            c[self.z_var] = -spec.objective[MIN_ELEDEF]
        c[self.a_var] = per_point
        if spec.prefer:
            scale = max(1e-9, float(np.max(np.abs(c[:self.n_items]))))
            for v, it in enumerate(self.var_item):
                if it is not EMPTY and gd.name(it) in spec.prefer:
                    bonus = spec.prefer[gd.name(it)]
                    c[v] -= bonus if bonus else 1e-4 * scale     # 0/None: tiebreak only
        return c

    def names(self, chosen):
        """Chosen variables -> 9 names in SLOTS order (None for an empty slot)."""
        out = dict.fromkeys(SLOTS)
        rings = []
        for v in chosen:
            it, kind = self.var_item[v], self.var_kind[v]
            name = None if it is EMPTY else self.gd.name(it)
            if kind == "ring":
                rings.append(name)
            else:
                out[kind] = name
        rings.sort(key=lambda n: (n is None, n or ""))
        out["ring1"], out["ring2"] = (rings + [None, None])[:2]
        return [out[s] for s in SLOTS]

    def check(self, names):
        """Exact checks for a build: (score, manual skill points, sp) or None."""
        spec, gd, stat = self.spec, self.gd, self.stat
        sp = build_skillpoints(names, self.tome_ids, gd)
        if sp.total_assigned > self.budget or not sp.under_100:
            return None
        got = assign_for_floors(sp, spec.skill_floors(), self.budget)
        if got is None:
            return None
        extra, manual = got
        set_stats, _ = set_bonus_stats(sp.set_counts, gd.sets)
        items = [gd.item(n) for n in names if n is not None]
        if spec.inventory is not None:
            from .inventory import with_rolls
            items = [with_rolls(it, spec.inventory.rolls(gd.name(it))) for it in items]
        fl = spec.floors
        if "mana" in fl:
            spare = self.budget - sp.total_assigned - sum(extra)
            int_items = sp.final[2] - sp.assigned[2]
            mana = max_mana(sum(stat(o, "maxMana") for o in (*items, *self.tomes))
                            + set_stats.get("maxMana", 0),
                            min(100, sp.assigned[2] + extra[2] + spare) + int_items)
            if mana < fl["mana"]:
                return None
        score = linear_value(items, set_stats, spec.objective, stat)
        if MIN_ELEDEF in spec.objective:
            score += spec.objective[MIN_ELEDEF] * min(
                sum(stat(o, k) for o in (*items, *self.tomes)) + set_stats.get(k, 0)
                for k in ELEDEF_KEYS)
        return score, manual, sp

    def solve(self, c=None, extra_rows=None, max_rounds=2000, time_limit=600, progress=None,
              accept=None, t0=None, margins=(8, 20, 40)):
        """The best build under objective `c` (objective_vector()) that passes
        check() and `accept(names, checked)` if given, as a Solved; None when
        nothing does. Raises TimeoutError when time runs out with no build.

        The skill-point relaxation can be short of WynnBuilder's exact rule by a
        few points, so near the budget many proposals fail one after another.
        Every so often the program is also solved with a few points held back
        (`margins`): that gives a valid build early, and the search stops as
        soon as nothing left can beat it (which proves it best). If time runs
        out first, that build comes back with proven=False."""
        t0 = t0 or time.time()
        c = self.objective_vector() if c is None else c
        cuts = extra_rows or _Rows()
        margins = list(margins)
        next_margin = 3
        incumbent = None                              # Solved, proven=False
        bound = None
        for rnd in range(1, max_rounds + 1):
            left = time_limit - (time.time() - t0)
            if left <= 0:
                break
            res = self._milp(c, cuts, left)
            if res is None:                            # nothing left: the incumbent is best
                return incumbent and incumbent._replace(proven=True, bound=incumbent.value)
            if res == "timeout":
                break
            bound = -res.fun
            if incumbent and incumbent.value >= bound - 1e-9 * max(1.0, abs(bound)):
                return incumbent._replace(proven=True, bound=bound)
            chosen = [v for v in range(self.n_items) if res.x[v] > 0.5]
            names = self.names(chosen)
            ok = self.check(names)
            if ok is not None and accept is not None and not accept(names, ok):
                ok = None
            if progress:
                progress({"round": rnd, "cuts": len(cuts.lo), "best": bound,
                          "elapsed": time.time() - t0})
            if ok is not None:
                return Solved(names, ok, cuts, True, bound, bound)
            self.cut(cuts, names)
            if rnd == next_margin and margins:
                next_margin = rnd * 3
                got = self._with_margin(c, cuts, margins.pop(0), accept, t0, time_limit)
                if got and (incumbent is None or got.value > incumbent.value):
                    incumbent = got
                    self.cut(cuts, got.names)          # the main loop needn't find it again
        if incumbent:
            return incumbent._replace(bound=bound if bound is not None else incumbent.value)
        raise TimeoutError(f"exact search found no valid build in {time.time() - t0:.0f}s "
                           f"({rnd} rounds)")

    def _milp(self, c, cuts, left):
        cons = [self.rows.constraint(self.nv)]
        if cuts.lo:
            cons.append(cuts.constraint(self.nv))
        res = milp(c, constraints=cons, integrality=self.integrality,
                   bounds=Bounds(self.lb, self.ub), options={"time_limit": left})
        if res.status == 2 or (res.x is None and res.status != 1):     # infeasible
            return None
        if res.status != 0:
            return "timeout"
        return res

    def _with_margin(self, c, cuts, margin, accept, t0, time_limit):
        """A valid build with `margin` skill points held back, or None."""
        rows = _Rows()
        for attr in ("r", "c", "v", "lo", "hi"):
            setattr(rows, attr, list(getattr(cuts, attr)))
        rows.add([(a, 1) for a in self.a_var], hi=self.budget - margin)
        for _ in range(15):
            left = time_limit - (time.time() - t0)
            if left <= 0:
                return None
            res = self._milp(c, rows, left)
            if res is None or res == "timeout":
                return None
            names = self.names([v for v in range(self.n_items) if res.x[v] > 0.5])
            ok = self.check(names)
            if ok is not None and (accept is None or accept(names, ok)):
                return Solved(names, ok, cuts, False, -res.fun, -res.fun)
            self.cut(rows, names)
        return None

    def cut(self, cuts, names):
        """Forbid exactly this combination of items from now on."""
        chosen = self.chosen_vars(names)
        cuts.add([(v, 1) for v in chosen], hi=len(chosen) - 1)

    def chosen_vars(self, names):
        out, rings = [], [n for n, s in zip(names, SLOTS) if s in ("ring1", "ring2")]
        for kind in KINDS:
            want = rings if kind == "ring" else [names[SLOTS.index(kind)]]
            pool = list(self.by_kind[kind])
            for name in want:
                for v in pool:
                    it = self.var_item[v]
                    if (it is EMPTY and name is None) or (it is not EMPTY and self.gd.name(it) == name):
                        out.append(v)
                        pool.remove(v)
                        break
        return out


def solve_gear_exact(spec, gd, progress=None, max_rounds=2000, time_limit=600):
    """Best Result over all usable items, or None. `progress` gets
    {"round", "cuts", "best", "elapsed"} after every re-solve."""
    t0 = time.time()
    model = GearModel(spec, gd)          # raises Infeasible when a part is plainly impossible
    got = model.solve(progress=progress, max_rounds=max_rounds, time_limit=time_limit, t0=t0)
    if got is None:
        return None
    score, manual, sp = got.checked
    return Result(score, got.names, sp.assigned, time.time() - t0, skillpoints=manual,
                  proven=got.proven, bound=got.bound)
