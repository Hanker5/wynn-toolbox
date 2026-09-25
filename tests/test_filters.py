"""Any stat as a minimum or maximum, and major IDs to avoid (search.spec_from + exact search)."""
import pytest

import dataclasses

from wynntools.gear_local import LocalSearch
from wynntools.gear_milp import solve_gear_exact
from wynntools.gear_solver import SUM_FLOORS, solve_gear
from wynntools.search import spec_from
from wynntools.statinfo import LABELS, catalog
from wynntools.verify import build_skillpoints, stat

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


# ------------------------------------------------------------ set bonuses: majors and set-level filters
def _sets_worn(gd, r, level=105):
    return build_skillpoints(r.equipment, [None] * 14, gd).set_counts


MAGE_HP = {"class": "Mage", "level": 105, "objective": {"hp": 1}}


def test_a_major_only_a_set_bonus_grants_can_be_required(gd):
    """CINDERCURSE comes from wearing 3 Cindercurse pieces; both searches find that."""
    spec = spec_from({**MAGE_HP, "objective": {"sdPct": 1}, "require_major": ["CINDERCURSE"], "topn": 5}, gd)
    for r in (solve_gear_exact(spec, gd), solve_gear(spec, gd)):
        assert r is not None and _sets_worn(gd, r).get("Cindercurse", 0) >= 3


def test_avoided_major_is_kept_out_of_set_bonuses(gd):
    """Three Cindercurse pieces would grant the major; with it avoided that can't happen, two are fine."""
    three = {"chestplate": "Cindercurse Cuirass", "leggings": "Cindercurse Cuisses", "weapon": "Cindercurse Crosier"}
    spec = spec_from({**MAGE_HP, "force": three, "topn": 5}, gd)
    assert _sets_worn(gd, solve_gear_exact(spec, gd)).get("Cindercurse") == 3
    banned = spec_from({**MAGE_HP, "force": three, "exclude_major": ["CINDERCURSE"], "topn": 5}, gd)
    assert solve_gear_exact(banned, gd) is None
    assert solve_gear(banned, gd) is None
    two = dict(list(three.items())[:2])
    ok = spec_from({**MAGE_HP, "force": two, "exclude_major": ["CINDERCURSE"], "topn": 5}, gd)
    for r in (solve_gear_exact(ok, gd), solve_gear(ok, gd)):
        assert r is not None and _sets_worn(gd, r).get("Cindercurse", 0) < 3


def test_require_a_set(gd):
    spec = spec_from({**MAGE_HP, "require_sets": {"Air Relic": 4}, "topn": 5}, gd)
    for r in (solve_gear_exact(spec, gd), solve_gear(spec, gd)):
        assert r is not None and _sets_worn(gd, r).get("Air Relic", 0) == 4
    hard = spec_from({**BASE, "objective": {"poison": 1}, "floors": {"hp": 6000},
                      "require_sets": {"Cosmic Foundations": 4}}, gd)       # needs the exact search
    assert _sets_worn(gd, solve_gear_exact(hard, gd)).get("Cosmic Foundations") == 4


def test_exclude_a_set(gd):
    spec = spec_from({**MAGE_HP, "exclude_sets": ["Cindercurse"], "topn": 5}, gd)
    for r in (solve_gear_exact(spec, gd), solve_gear(spec, gd)):
        assert r is not None and not _sets_worn(gd, r).get("Cindercurse")


def test_set_filters_are_checked(gd):
    with pytest.raises(ValueError, match="unknown set"):
        spec_from({**BASE, "require_sets": {"Nope": 2}}, gd)
    with pytest.raises(ValueError, match="piece count"):
        spec_from({**BASE, "require_sets": {"Cindercurse": 0}}, gd)
    with pytest.raises(ValueError, match="both required and excluded"):
        spec_from({**BASE, "require_sets": {"Cindercurse": 2}, "exclude_sets": ["Cindercurse"]}, gd)
