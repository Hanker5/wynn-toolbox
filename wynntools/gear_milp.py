"""Exact gear search as a mixed-integer program (scipy/HiGHS), over every usable item.

`solve_gear` (branch and bound) is exact only within per-slot shortlists. This
searches all items at once:

  * one item per slot (rings: two different items; a crafted ring may repeat;
    with an owned-only spec any slot but the weapon may be empty);
  * set bonuses exact, through one-hot "pieces of set s" variables;
  * HP, mana regen and walk speed floors exact (gear, tomes, set bonuses);
  * skill points RELAXED: every chosen item's requirement must hold against the
    assigned points plus the other items' final bonuses (WynnBuilder enforces
    exactly this in its last step; crafts', the weapon's and set bonuses never
    count). The order-dependent part of its rule can only need more, so no
    valid build is cut.

Each solution is then checked exactly (skill points by WynnBuilder's rules, max
mana). Damage floors are not supported (use solve_gear). A build that fails is cut off and the program re-solved;
the first build that passes is optimal over all items.
"""
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .codec import SLOTS
from .gear_solver import CLASS_WEAPON, EMPTY, Result, _crafted_candidates, _usable
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


def solve_gear_exact(spec, gd, progress=None, max_rounds=2000, time_limit=600):
    """Best Result over all usable items, or None. `progress` gets
    {"round", "cuts", "best", "elapsed"} after every re-solve."""
    t0 = time.time()
    memo = {}

    def stat(obj, key):
        k = (id(obj), key)
        if k not in memo:
            memo[k] = _stat(obj, key, spec.roll)
        return memo[k]

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
    tome_ids = list(spec.tomes) + [None] * (14 - len(spec.tomes))
    tomes = [gd.tome(t) for t in tome_ids if t is not None]
    guild = gd.tome(tome_ids[6]) if tome_ids[6] is not None else None
    dmg_floors = fl.get("damage") or {}
    if dmg_floors:
        # Damage isn't linear in the items, so it could only be checked and cut one
        # build at a time; near-optimal builds just under a floor are too many.
        raise ValueError("the exact search doesn't take damage floors; use the shortlist "
                         "search (without --exact) for those")

    # ---- variables: one per (kind, item); a second copy for crafted rings; empties
    var_item, var_kind = [], []           # item dict (or EMPTY) and kind per variable
    by_kind = {k: [] for k in KINDS}
    second_copy = {}                      # first-copy var -> second-copy var (crafted rings)
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
    n_items = len(var_item)
    if not by_kind["weapon"]:
        return None

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
    a_var = list(range(nv, nv + 5))            # assigned skill points (relaxed)
    b_var = list(range(nv + 5, nv + 10))       # bonuses that can help requirements
    nv += 10


    rows = _Rows()
    # slot counts
    for kind in KINDS:
        need = 2 if kind == "ring" else 1
        rows.add([(v, 1) for v in by_kind[kind]], need, need)
    for v, v2 in second_copy.items():
        rows.add([(v2, 1), (v, -1)], hi=0)
    # sets
    for s, ys in set_vars.items():
        rows.add([(y, 1) for y in ys], 1, 1)
        rows.add([(v, 1) for v in set_members[s]] + [(y, -c) for c, y in enumerate(ys)], 0, 0)
    # linear floors
    def floor_row(key, floor, const):
        terms = [(v, stat(it, key)) for v, it in enumerate(var_item) if it is not EMPTY]
        for s, ys in set_vars.items():
            for c, y in enumerate(ys):
                if c:
                    st = set_bonus_stats({s: c}, gd.sets)[0]
                    terms.append((y, st.get("hpBonus", 0) if key == "hp" else st.get(key, 0)))
        rows.add(terms, lo=floor - const)
    if "hp" in fl:
        floor_row("hp", fl["hp"], base_hp(spec.level) + sum(stat(t, "hp") for t in tomes))
    for key in ("mr", "spd"):
        if key in fl:
            floor_row(key, fl[key], sum(stat(t, key) for t in tomes))
    # skill points (relaxation). WynnBuilder's last step raises assigned points until
    # every item's requirement holds against the FINAL totals of the other items
    # (non-crafted equipment and the guild tome, negative bonuses included; never the
    # weapon's bonus). So with b_j = that signed total, for every chosen item i:
    #     a_j + b_j - own_ij >= req_ij
    # is necessary; the order-dependent part of the rule can only need more.
    budget = skill_points(spec.level)
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
    rows.add([(a, 1) for a in a_var], hi=budget)
    # one copy of each normal item even if it fits two kinds (never happens) — and
    # required major IDs
    for major in spec.require_major:
        terms = [(v, 1) for v, it in enumerate(var_item)
                 if it is not EMPTY and major in (it.get("majorIds") or [])]
        for s, ys in set_vars.items():
            for c, y in enumerate(ys):
                if c and major in set_bonus_stats({s: c}, gd.sets)[1]:
                    terms.append((y, 1))
        if not terms:
            raise ValueError(f"no usable item carries major ID {major}")
        rows.add(terms, lo=1)
    # forced items
    for slot, name in (spec.force or {}).items():
        kind = "ring" if slot in ("ring1", "ring2") else slot
        vs = [v for v in by_kind[kind] if var_item[v] is not EMPTY and gd.name(var_item[v]) == name]
        if not vs:
            return None
        rows.add([(v, 1) for v in vs], lo=1)

    # objective (milp minimizes)
    c = np.zeros(nv)
    for v, it in enumerate(var_item):
        if it is not EMPTY:
            c[v] = -sum(w * stat(it, k) for k, w in spec.objective.items())
    for s, ys in set_vars.items():
        for cnt, y in enumerate(ys):
            if cnt:
                st = set_bonus_stats({s: cnt}, gd.sets)[0]
                c[y] = -sum(w * (st.get("hpBonus", 0) if k == "hp" else st.get(k, 0))
                            for k, w in spec.objective.items())
    lb = np.zeros(nv)
    ub = np.ones(nv)
    ub[a_var] = 100
    lb[b_var] = -np.inf
    ub[b_var] = np.inf
    integrality = np.ones(nv)
    integrality[a_var + b_var] = 0

    # ---- solve, check exactly, cut, repeat
    cuts = _Rows()
    for rnd in range(1, max_rounds + 1):
        cons = [rows.constraint(nv)]
        if cuts.lo:
            cons.append(cuts.constraint(nv))
        left = time_limit - (time.time() - t0)
        if left <= 0:
            raise TimeoutError(f"exact search passed {time_limit}s after {rnd - 1} rounds")
        res = milp(c, constraints=cons, integrality=integrality, bounds=Bounds(lb, ub),
                   options={"time_limit": left})
        if res.status == 2 or res.x is None:        # infeasible
            return None
        if res.status != 0:
            raise TimeoutError(f"exact search stopped: {res.message}")
        chosen = [v for v in range(n_items) if res.x[v] > 0.5]
        names = _slots_from(chosen, var_item, var_kind, gd)
        ok = _exact_ok(names, spec, gd, tome_ids, tomes, stat, budget, dmg_floors)
        if progress:
            progress({"round": rnd, "cuts": len(cuts.lo), "best": -res.fun,
                      "elapsed": time.time() - t0})
        if ok is not None:
            return Result(ok, names, build_skillpoints(names, tome_ids, gd).assigned,
                          time.time() - t0)
        cuts.add([(v, 1) for v in chosen], hi=len(chosen) - 1)
    raise TimeoutError(f"exact search gave up after {max_rounds} rounds")


def _slots_from(chosen, var_item, var_kind, gd):
    """Chosen variables -> 9 names in SLOTS order (None for an empty slot)."""
    out = dict.fromkeys(SLOTS)
    rings = []
    for v in chosen:
        it, kind = var_item[v], var_kind[v]
        name = None if it is EMPTY else gd.name(it)
        if kind == "ring":
            rings.append(name)
        else:
            out[kind] = name
    rings.sort(key=lambda n: (n is None, n or ""))
    out["ring1"], out["ring2"] = (rings + [None, None])[:2]
    return [out[s] for s in SLOTS]


def _exact_ok(names, spec, gd, tome_ids, tomes, stat, budget, dmg_floors):
    """Exact score if the build passes every check, else None."""
    sp = build_skillpoints(names, tome_ids, gd)
    if sp.total_assigned > budget or not sp.under_100:
        return None
    set_stats, _ = set_bonus_stats(sp.set_counts, gd.sets)
    items = [gd.item(n) for n in names if n is not None]
    if spec.inventory is not None:
        from .inventory import with_rolls
        items = [with_rolls(it, spec.inventory.rolls(gd.name(it))) for it in items]
    fl = spec.floors
    if "mana" in fl:
        spare = budget - sp.total_assigned
        int_items = sp.final[2] - sp.assigned[2]
        mana = max_mana(sum(stat(o, "maxMana") for o in (*items, *tomes)) + set_stats.get("maxMana", 0),
                        min(100, sp.assigned[2] + spare) + int_items)
        if mana < fl["mana"]:
            return None
    if dmg_floors:
        from .codec import Build
        from .damage import spell_values
        got = spell_values(Build(equipment=list(names), level=spec.level, tomes=tome_ids,
                                 atree=set(spec.atree)), gd, spec.roll, spec.inventory)
        if not all(got.get(k, -1) >= v for k, v in dmg_floors.items()):
            return None
    score = sum(w * stat(it, k) for it in items for k, w in spec.objective.items())
    score += sum(w * (set_stats.get("hpBonus", 0) if k == "hp" else set_stats.get(k, 0))
                 for k, w in spec.objective.items())
    return score
