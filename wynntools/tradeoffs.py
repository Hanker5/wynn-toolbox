"""A few legal builds from all-out damage to all-out survival, side by side.

Runs the local search (wynntools.gear_local) for the most damage, for the
most effective HP, and for the most damage with effective HP held at points
in between. Every build those searches checked that meets the spec is a legal
choice; the ones no other build beats on both damage and effective HP (the
Pareto set) are kept, and a handful spread from max damage to max survival
are shown with HP, health regen, effective HP, skill points and puppet DPS.
"""
import dataclasses

from .gear_local import LocalSearch
from .gear_solver import Result

LABELS = ("max damage", "balanced", "tanky", "max survival")


def _value(m, key):
    if key.startswith("damage:"):
        return m["spells"].get(key[len("damage:"):]) or 0.0
    return m[key]


def tradeoffs(spec, gd, damage="melee_dps", tank="ehp", steps=(1 / 3, 2 / 3), show=4,
              progress=None, time_limit=900):
    """{"damage": key, "tank": key, "options": [...], "checked": n}. Each option:
    {"label", "result" (a gear_solver.Result), "damage", "tank", "hp", "hpr",
    "ehp", "sp_total", "skillpoints", "puppet_dps", "summon_dps"}."""
    pool = {}                                        # names -> Eval, every legal build seen
    runs = []

    def search(objective, floors, share):
        s = dataclasses.replace(spec, objective=objective, floors={**spec.floors, **floors})

        def tick(p):
            if progress:
                progress({**p, "fraction": None if p["fraction"] is None
                          else (len(runs) + p["fraction"]) / share})
        ls = LocalSearch(s, gd, progress=tick, time_limit=time_limit)
        r = ls.run()
        runs.append(r)
        for key in ls.legal:
            ev = ls.evaluated.get(key)
            if ev is not None and _meets(spec, ev.metrics):
                pool.setdefault(key, ev)
        return r

    total = 2 + len(steps)
    hi_dmg = search({damage: 1}, {}, total)
    hi_tank = search({tank: 1}, {}, total)
    if hi_dmg is None and hi_tank is None:
        return {"damage": damage, "tank": tank, "options": [], "checked": len(pool)}
    lo = _value(hi_dmg.metrics, tank) if hi_dmg else 0.0
    top = _value(hi_tank.metrics, tank) if hi_tank else lo
    for t in steps:
        if top > lo:
            search({damage: 1}, {tank: lo + t * (top - lo)}, total)
    frontier = _pareto(pool.values(), damage, tank)
    picks = _spread(frontier, show, tank)
    options = []
    for i, ev in enumerate(picks):
        label = LABELS[0] if i == 0 else LABELS[-1] if i == len(picks) - 1 else \
            LABELS[1] if i == 1 or len(picks) <= 3 else LABELS[2]
        m = ev.metrics
        options.append({
            "label": label,
            "result": Result(_value(m, damage), ev.names, ev.sp_assigned, 0,
                             skillpoints=ev.manual, metrics=m),
            "damage": _value(m, damage), "tank": _value(m, tank), "hp": m["hp"], "hpr": m["hpr"],
            "ehp": m["ehp"], "sp_total": sum(ev.sp_assigned), "skillpoints": ev.manual,
            "sp_assigned": ev.sp_assigned,
            "puppet_dps": m["puppet_dps"], "summon_dps": m["summon_dps"]})
    return {"damage": damage, "tank": tank, "options": options, "checked": len(pool)}


def _meets(spec, m):
    for k, v in spec.derived_floors().items():
        if _value(m, k) < v:
            return False
    return True


def _pareto(evals, a, b):
    """Builds no other build beats on both `a` and `b`, by `a` descending."""
    pts = sorted(evals, key=lambda e: (-_value(e.metrics, a), -_value(e.metrics, b)))
    out, best_b = [], float("-inf")
    for e in pts:
        vb = _value(e.metrics, b)
        if vb > best_b + 1e-9:
            out.append(e)
            best_b = vb
    return out


def _spread(frontier, n, tank):
    """Up to n builds from the frontier: both ends, and the rest nearest to
    evenly spaced survival values between them."""
    if len(frontier) <= n:
        return list(frontier)
    lo, hi = _value(frontier[0].metrics, tank), _value(frontier[-1].metrics, tank)
    picks = {0, len(frontier) - 1}
    for k in range(1, n - 1):
        want = lo + k / (n - 1) * (hi - lo)
        rest = [i for i in range(len(frontier)) if i not in picks]
        if rest:
            picks.add(min(rest, key=lambda i: abs(_value(frontier[i].metrics, tank) - want)))
    return [frontier[i] for i in sorted(picks)]
