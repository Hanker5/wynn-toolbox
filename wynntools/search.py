"""Pick and run the right gear search for a spec, so the CLI and the web app agree.

  exact       the mixed-integer program over every usable item (gear_milp):
              floors on sums of stats and on skill points, "lowest elemental
              defence" goal. Proven best, unless it stops at the time limit.
  shortlists  branch and bound over per-slot shortlists (gear_solver), for
              floors only WynnBuilder's damage model can check (effective HP,
              health regen with %, DPS, spell damage). Best within the shortlists.
  local       for goals only the damage model can work out (gear_local). Best
              found by a local search; not proven best.

When nothing meets the spec, `explanation` says why (wynntools.explain).
"""
import dataclasses

from .gear_solver import (DAMAGE_GOAL_PREFIX, DERIVED_FLOORS, DERIVED_GOALS, MIN_ELEDEF,
                          SKILL_FLOORS, SUM_FLOORS, Spec, solve_gear)
from .rules import ROLLED_IDS

FLOOR_KEYS = (*SUM_FLOORS, *SKILL_FLOORS, MIN_ELEDEF, *DERIVED_FLOORS, "mana", "weapon_dps", "damage")


def spec_from(raw, gd, inventory=None):
    """A Spec from a spec file's JSON (see AGENTS.md and the build skill). Items
    the player marked unavailable in `inventory` are left out. Raises ValueError
    with the valid choices for anything it doesn't know."""
    from .damage import STATIC_IDS
    stat_keys = set(ROLLED_IDS) | set(STATIC_IDS) | {"hpBonus"}
    objective = dict(raw.get("objective") or {})
    if not objective:
        raise ValueError("the spec needs an objective, e.g. {\"hp\": 1} or {\"ehp\": 1}")
    for k, w in objective.items():
        if not (k in stat_keys or k in DERIVED_GOALS or k == MIN_ELEDEF or k.startswith(DAMAGE_GOAL_PREFIX)):
            raise ValueError(f"unknown goal {k!r}: use an item stat (hp, eSteal, sdPct, ...), "
                             f"{', '.join(DERIVED_GOALS)}, {MIN_ELEDEF} or damage:<spell name>")
        if not isinstance(w, (int, float)) or isinstance(w, bool):
            raise ValueError(f"goal {k!r} needs a number as its weight, not {w!r}")
    floors = dict(raw.get("floors") or {})
    for k, v in floors.items():
        if k not in FLOOR_KEYS:
            raise ValueError(f"unknown minimum {k!r}; minimums are {', '.join(FLOOR_KEYS)}")
        if k == "damage":
            if not isinstance(v, dict):
                raise ValueError('"damage" minimums look like {"Spell Name": 15000}')
        elif not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(f"minimum {k!r} needs a number, not {v!r}")
    prefer = raw.get("prefer") or {}
    if isinstance(prefer, list):
        prefer = {n: 0 for n in prefer}        # 0: a tiebreak only
    groups = raw.get("at_most_one") or []
    if not all(isinstance(g, list) for g in groups):
        raise ValueError('"at_most_one" is a list of item-name lists, e.g. [["Galleon", "Gaia"]]')
    named = [*prefer, *(n for g in groups for n in g), *(raw.get("exclude") or []),
             *(v for v in (raw.get("force") or {}).values() if v)]
    for n in named:
        if not n.startswith("CR-"):
            gd.item(n)                          # KeyError names the typo
    exclude = set(raw.get("exclude") or [])
    unavailable = set(getattr(inventory, "unavailable", None) or {})
    forced = {v for v in (raw.get("force") or {}).values() if v}
    exclude |= unavailable - forced
    return Spec(cls=raw["class"], level=int(raw["level"]), objective=objective, floors=floors,
                require_major=list(raw.get("require_major") or []),
                force={k: v for k, v in (raw.get("force") or {}).items() if v},
                exclude=exclude, exclude_tiers=set(raw.get("exclude_tiers") or []),
                tomes=[None if t is None else gd.tome(t)["id"] for t in raw.get("tomes") or []],
                topn=int(raw.get("topn") or 8), crafted=bool(raw.get("crafted")),
                roll=raw.get("roll") or "base", at_most_one=[list(g) for g in groups],
                prefer=prefer, spare_sp=raw.get("spare_sp"))


def needs_tree(spec):
    """Whether the spec's goals or floors depend on an ability tree (damage)."""
    from .derived import DAMAGE_KEYS
    keys = [*spec.objective, *spec.derived_floors()]
    return any(k in DAMAGE_KEYS or k.startswith(DAMAGE_GOAL_PREFIX) for k in keys)


def uses_tree(spec):
    """Whether the damage model runs at all (a tree then changes the numbers)."""
    return bool(spec.derived_floors()) or spec.derived_objective()


KIND_NOTES = {
    "exact": "exact search: the best build over every usable item",
    "shortlists": "shortlist search: the best build within per-slot shortlists (it can miss "
                  "the best build; --confirm re-runs with larger ones)",
    "local": "local search: the best build found by following the goal from build to build "
             "with WynnBuilder's damage model (good, but not proven the best)",
}


@dataclasses.dataclass
class Outcome:
    result: object              # gear_solver.Result or None
    kind: str                   # "exact", "shortlists" or "local"
    note: str                   # which search ran, in words for the player
    explanation: dict | None = None
    confirm: str | None = None  # what --confirm found, when it ran


def kind_for(spec, shortlists=False):
    if spec.derived_objective() or (MIN_ELEDEF in spec.objective and spec.derived_floors()):
        return "local"
    if spec.derived_floors() or shortlists:
        return "shortlists"
    return "exact"


def run(spec, gd, kind=None, progress=None, confirm=False, explain_failure=True,
        time_limit=600):
    """Search. `progress` gets {"fraction" (None if unknown), "nodes", "best",
    "elapsed", "text"} as the search goes."""
    kind = kind or kind_for(spec)
    note = KIND_NOTES[kind]
    confirm_note = None
    found = None
    if kind == "exact":
        from .gear_milp import solve_gear_exact

        def rounds(p):
            if progress:
                progress({"fraction": None, "nodes": p["round"], "best": p["best"],
                          "elapsed": p["elapsed"], "text": f"round {p['round']} · best bound {p['best']:g}"})
        r = solve_gear_exact(spec, gd, progress=rounds, time_limit=time_limit)
        if r is not None and not r.proven:
            gap = (r.bound - r.score) / max(abs(r.score), 1e-9) * 100 if r.bound is not None else None
            note = ("exact search, stopped at the time limit: a valid build, but not proven the "
                    "best" + (f"; no build can beat it by more than {gap:.1f}%" if gap is not None else ""))
    elif kind == "shortlists":
        def shortlist_progress(p):
            if progress:
                progress({**p, "text": f"{p['nodes']:,} checked · best {p['best'] if p['best'] is not None else '—'}"})
        r = solve_gear(spec, gd, progress=shortlist_progress)
        if r is not None and confirm:
            bigger = dataclasses.replace(spec, topn=spec.topn + 3)
            r2 = solve_gear(bigger, gd, progress=shortlist_progress)
            if r2 and r2.score > r.score + 1e-9:
                confirm_note = f"larger shortlists found a better build ({r2.score:g} > {r.score:g})"
                r = r2
            else:
                confirm_note = "larger shortlists found nothing better"
    else:
        from .gear_local import LocalSearch

        def local_progress(p):
            if progress:
                best = p["best"]
                progress({"fraction": p["fraction"], "nodes": p["evaluated"], "best": best,
                          "elapsed": p["elapsed"],
                          "text": f"{p['evaluated']} builds checked" +
                                  (f" · best {best:,.0f}" if best is not None else "")})
        ls = LocalSearch(spec, gd, progress=local_progress, time_limit=time_limit)
        r = ls.run()
        if r is None and ls.best is not None:
            found = {k: ls.best.metrics.get(k) for k in spec.derived_floors() if k in ls.best.metrics}
            for k in spec.derived_floors():
                if k.startswith("damage:"):
                    found[k] = ls.best.metrics["spells"].get(k[len("damage:"):])
    explanation = None
    if r is None and explain_failure:
        from .explain import explain
        if progress:
            progress({"fraction": None, "nodes": 0, "best": None, "elapsed": 0,
                      "text": "working out why nothing fits"})
        if kind == "shortlists" and not found:
            found = _best_derived(spec, gd)
        explanation = explain(spec, gd, found=found)
    return Outcome(r, kind, note, explanation, confirm_note)


def _best_derived(spec, gd):
    """For a failed shortlist search: the damage-model numbers of the best build
    without those floors, as a hint of how far off they are."""
    from .codec import Build
    from .derived import metrics, value
    from .gear_milp import solve_gear_exact
    try:
        plain = dataclasses.replace(spec, floors={k: v for k, v in spec.floors.items()
                                                  if k not in spec.derived_floors() and k != "damage"})
        r = solve_gear_exact(plain, gd, time_limit=60)
    except (ValueError, TimeoutError):
        return None
    if r is None:
        return None
    b = Build(equipment=r.equipment, level=spec.level,
              tomes=list(spec.tomes) + [None] * (14 - len(spec.tomes)),
              atree=set(spec.atree or ()), skillpoints=r.skillpoints)
    m = metrics(b, gd, spec.roll, spec.inventory)
    return {k: value(m, k[len("damage:"):] if k.startswith("damage:") else k)
            for k in spec.derived_floors()}


def describe_explanation(ex):
    """Lines of text for a terminal."""
    if not ex:
        return []
    return [ex["summary"], *["  - " + line for line in ex["lines"]]]
