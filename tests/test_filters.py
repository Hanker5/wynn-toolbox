"""Any stat as a minimum or maximum, and major IDs to avoid (search.spec_from + exact search)."""
import pytest

import dataclasses

from wynntools.gear_local import LocalSearch
from wynntools.gear_milp import solve_gear_exact
from wynntools.gear_solver import SUM_FLOORS, solve_gear
from wynntools.search import spec_from
from wynntools.statinfo import LABELS, catalog
from wynntools.verify import stat

BASE = {"class": "Mage", "level": 105, "objective": {"sdPct": 1}}


def test_every_stat_is_a_valid_minimum_and_maximum(gd):
    floors = {k: 0 for k in SUM_FLOORS}
    spec = spec_from({**BASE, "floors": floors, "caps": {k: 10**6 for k in SUM_FLOORS}}, gd)
    assert set(spec.floors) == set(SUM_FLOORS) == set(spec.caps)


def test_bad_limits_are_explained(gd):
    with pytest.raises(ValueError, match="unknown maximum"):
        spec_from({**BASE, "caps": {"nope": 1}}, gd)
    with pytest.raises(ValueError, match="unknown major ID"):
        spec_from({**BASE, "exclude_major": ["NOPE"]}, gd)
    with pytest.raises(ValueError, match="both required and excluded"):
        spec_from({**BASE, "require_major": ["PLAGUE"], "exclude_major": ["PLAGUE"]}, gd)


def test_minimum_on_a_less_common_stat_and_a_cap(gd):
    spec = spec_from({**BASE, "floors": {"mdPct": 20, "hp": 6000}, "caps": {"spd": 5}}, gd)
    r = solve_gear_exact(spec, gd)
    tot = lambda k: sum(stat(gd.item(i), k) for i in r.equipment if i)
    assert tot("mdPct") >= 20 and tot("spd") <= 5


def test_excluded_major_is_never_used(gd):
    spec = spec_from({**BASE, "objective": {"poison": 1}, "floors": {"hp": 8000}, "exclude_major": ["PLAGUE"]}, gd)
    r = solve_gear_exact(spec, gd)
    assert not any("PLAGUE" in (gd.item(i).get("majorIds") or []) for i in r.equipment if i)


def test_catalog_covers_every_stat_once():
    keys = [k for _, ks in catalog(SUM_FLOORS) for k, _ in ks]
    assert sorted(keys) == sorted(SUM_FLOORS)
    assert all(LABELS[k] for k in LABELS)


def _total(gd, r, key):
    return sum(stat(gd.item(i), key) for i in r.equipment if i)


def test_cap_in_the_shortlist_search_matches_the_exact_one(gd):
    raw = {**BASE, "objective": {"poison": 1}, "floors": {"hp": 8000, "mr": 0},
           "require_major": ["PLAGUE"], "topn": 6}
    free = solve_gear_exact(spec_from(raw, gd), gd)
    cap = _total(gd, free, "hp") - 300            # below what the unconstrained best reaches: it binds
    spec = spec_from({**raw, "caps": {"hp": cap}}, gd)
    r = solve_gear(spec, gd)
    assert r is not None and _total(gd, r, "hp") <= cap
    best = solve_gear_exact(spec, gd)
    assert _total(gd, best, "hp") <= cap and best.score >= r.score - 1e-6
    assert best.score <= free.score


def test_cap_in_the_local_search(gd):
    spec = spec_from({"class": "Shaman", "level": 105, "objective": {"ehp": 1},
                      "floors": {"hp": 12000}, "caps": {"spd": 0}, "force": {"weapon": "Stormdrain"}}, gd)
    spec = dataclasses.replace(spec, atree=set())
    r = LocalSearch(spec, gd).run()
    assert r is not None and _total(gd, r, "spd") <= 0
