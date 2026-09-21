import pytest

from wynntools.gear_solver import Spec, solve_gear
from wynntools.verify import stat


def total(gd, names, key):
    return sum(stat(gd.item(n), key) for n in names)


def test_stormdrain_matches_session(gd):
    r = solve_gear(Spec(cls="Shaman", level=105, objective={"eSteal": 1, "lb": 0.01},
                        floors={"hp": 17000, "mr": 20, "spd": 0},
                        require_major=["GREED", "MAGNET"], force={"weapon": "Stormdrain"}), gd)
    assert total(gd, r.equipment, "eSteal") >= 39
    assert total(gd, r.equipment, "hp") + 530 >= 17000
    assert {"Old Keeper's Ring", "Vindicator"} <= set(r.equipment)


def test_gaia_matches_session(gd):
    r = solve_gear(Spec(cls="Mage", level=105, objective={"poison": 1},
                        floors={"hp": 15000, "mr": 20, "mana": 113},
                        require_major=["PLAGUE"], force={"weapon": "Gaia"}), gd)
    assert total(gd, r.equipment, "poison") >= 84300
    assert "Cytotoxic Striders" in r.equipment


def test_impossible_spec_returns_none(gd):
    assert solve_gear(Spec(cls="Mage", level=105, objective={"poison": 1},
                           floors={"hp": 60000}), gd) is None


@pytest.mark.slow
def test_level_121_matches_session(gd):
    r = solve_gear(Spec(cls="Shaman", level=121, objective={"eSteal": 1, "lb": 0.01},
                        floors={"hp": 20000, "mr": 20, "spd": 0, "weapon_dps": 700},
                        require_major=["GREED", "MAGNET"]), gd)
    assert total(gd, r.equipment, "eSteal") >= 40


def test_progress_reports_to_completion(gd):
    seen = []
    solve_gear(Spec(cls="Mage", level=105, objective={"poison": 1},
                    floors={"hp": 15000, "mr": 20, "mana": 113},
                    require_major=["PLAGUE"], force={"weapon": "Gaia"}), gd, progress=seen.append)
    fr = [p["fraction"] for p in seen]
    assert fr and fr[-1] == 1.0
    assert all(a <= b + 1e-9 for a, b in zip(fr, fr[1:]))
