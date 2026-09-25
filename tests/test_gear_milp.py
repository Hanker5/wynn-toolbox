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


# ---- the search choosing tomes (tome_pool owned / any)
TOME_SPEC = Spec(cls="Shaman", level=105, objective={"eSteal": 1}, floors={"hp": 9000})


def tome_names(gd, r):
    return [gd.name(gd.tome(t)) for t in r.tomes if t is not None]


def verified(gd, spec, r):
    ok, rep = check_link(to_link(Build(equipment=r.equipment, level=spec.level, tomes=r.tomes,
                                       skillpoints=r.skillpoints), gd), gd)
    assert ok, rep["problems"]


def test_any_tome_beats_no_tomes_and_the_link_verifies(gd):
    fixed = solve_gear_exact(TOME_SPEC, gd)
    anyt = solve_gear_exact(dataclasses.replace(TOME_SPEC, tome_pool="any"), gd)
    assert fixed.tomes is None and anyt.tomes and anyt.score > fixed.score
    verified(gd, TOME_SPEC, anyt)


def test_owned_pool_uses_only_owned_tomes_and_their_counts(gd):
    have = ["Tome of Scavenging Expertise III", "Tome of Scavenging Expertise II"]
    inv = Inventory(tomes=have + ["Tome of Scavenging Expertise III"])       # two copies of III
    spec = dataclasses.replace(TOME_SPEC, tome_pool="owned", tome_supply=inv.tome_counts())
    r = solve_gear_exact(spec, gd)
    got = tome_names(gd, r)
    assert set(got) <= set(have) and got.count("Tome of Scavenging Expertise III") <= 2
    one = dataclasses.replace(spec, tome_supply={have[0]: 1})
    assert tome_names(gd, solve_gear_exact(one, gd)).count(have[0]) == 1
    empty = dataclasses.replace(spec, tome_supply={})
    assert solve_gear_exact(empty, gd).tomes == [None] * 14
    verified(gd, spec, r)


def test_fixed_tomes_stay_and_the_pool_fills_the_rest(gd):
    keep = gd.tome("Tome of Scavenging Expertise III")["id"]
    spec = dataclasses.replace(TOME_SPEC, tome_pool="any", tomes=[None] * 12 + [keep, None])
    r = solve_gear_exact(spec, gd)
    assert r.tomes[12] == keep and sum(t is not None for t in r.tomes) >= 1


def test_a_guild_tome_can_make_a_skill_minimum_reachable(gd):
    guild = "Brute's Tome of Allegiance"                # +4 Strength
    spec = dataclasses.replace(TOME_SPEC, floors={"str": 164})
    without = solve_gear_exact(spec, gd)
    with_it = solve_gear_exact(dataclasses.replace(spec, tome_pool="owned", tome_supply={guild: 1}), gd)
    assert with_it.score > without.score and tome_names(gd, with_it) == [guild]
    verified(gd, spec, with_it)


def test_choosing_tomes_needs_the_exact_search(gd):
    from wynntools.search import run
    spec = dataclasses.replace(TOME_SPEC, tome_pool="any", objective={"ehp": 1})
    with pytest.raises(ValueError, match="exact search"):
        run(spec, gd, explain_failure=False)
