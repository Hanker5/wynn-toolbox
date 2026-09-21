"""The exact MILP gear search (wynntools.gear_milp) against the shortlist search.

The MILP considers every usable item, so it can never score below solve_gear; on
the session specs the shortlists were already optimal, so the scores are equal.
Every MILP build must pass WynnBuilder's exact skill-point rules.
"""
import dataclasses
import random

import pytest

from wynntools.codec import Build, to_link
from wynntools.gear_milp import solve_gear_exact
from wynntools.gear_solver import Spec, solve_gear
from wynntools.inventory import Inventory
from wynntools.rules import skill_points
from wynntools.verify import build_skillpoints, check_link

MAGE = Spec(cls="Mage", level=105, objective={"poison": 1},
            floors={"hp": 15000, "mr": 20, "mana": 113}, require_major=["PLAGUE"])
SHAMAN = Spec(cls="Shaman", level=105, objective={"eSteal": 1, "lb": 0.01},
              floors={"hp": 17000, "mr": 20, "spd": 0}, require_major=["GREED", "MAGNET"],
              force={"weapon": "Stormdrain"})


def valid(gd, spec, r):
    sp = build_skillpoints(r.equipment, list(spec.tomes) + [None] * (14 - len(spec.tomes)), gd)
    assert sp.total_assigned <= skill_points(spec.level) and sp.under_100
    ok, rep = check_link(to_link(Build(equipment=r.equipment, level=spec.level), gd), gd)
    assert ok, rep["problems"]


@pytest.mark.parametrize("spec", [MAGE, dataclasses.replace(MAGE, force={"weapon": "Gaia"}), SHAMAN],
                         ids=["mage", "mage-gaia", "shaman-stormdrain"])
def test_matches_shortlist_search_on_session_specs(gd, spec):
    a, b = solve_gear(spec, gd), solve_gear_exact(spec, gd)
    assert b.score == pytest.approx(a.score)
    valid(gd, spec, b)


def test_owned_only_with_empty_slots(gd):
    gaia = ["Slimy Shako", "Contagion", "Caterpillar", "Cytotoxic Striders", "Coral Ring",
            "Summa", "Contrast", "Gaia", "Sequoia"]            # no bracelet owned
    inv = Inventory(items={n: {} for n in gaia})
    spec = dataclasses.replace(MAGE, only=inv.names(), inventory=inv)
    a, b = solve_gear(spec, gd), solve_gear_exact(spec, gd)
    assert set(n for n in b.equipment if n) <= inv.names() and b.equipment[6] is None
    assert b.score == pytest.approx(a.score)


def test_impossible_is_none(gd):
    assert solve_gear_exact(dataclasses.replace(MAGE, floors={"hp": 60000}), gd) is None


def test_damage_floor_is_refused_with_a_pointer(gd):
    spec = dataclasses.replace(MAGE, floors={**MAGE.floors, "damage": {"Ophanim": 1}})
    with pytest.raises(ValueError, match="shortlist"):
        solve_gear_exact(spec, gd)


@pytest.mark.slow
@pytest.mark.parametrize("seed", range(12))
def test_never_worse_than_shortlists_on_random_specs(gd, seed):
    """Random classes, goals and floors: the exact search is at least as good, and valid."""
    rng = random.Random(seed)
    cls = rng.choice(["Mage", "Shaman", "Warrior", "Archer", "Assassin"])
    goal = rng.choice(["poison", "eSteal", "sdPct", "mdPct", "hprRaw", "spd", "lb", "xpb", "mr"])
    level = rng.choice([90, 105, 121])
    floors = {"hp": rng.choice([0, 10000, 14000, 17000])}
    if rng.random() < 0.5:
        floors["mr"] = rng.choice([5, 15, 25])
    spec = Spec(cls=cls, level=level, objective={goal: 1}, floors=floors)
    a, b = solve_gear(spec, gd), solve_gear_exact(spec, gd)
    if a is None:
        assert b is None or b.score is not None      # shortlists may miss a feasible build
        return
    assert b is not None and b.score >= a.score - 1e-9
    valid(gd, spec, b)
