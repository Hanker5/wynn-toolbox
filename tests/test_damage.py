"""Offline checks for wynntools.damage (the live page check is test_wynnbuilder_live)."""
import json
from pathlib import Path

import pytest

from wynntools.codec import decode
from wynntools.damage import (damage_report, merge_stat, spell_values, summary,
                              weapon_powder_damage)
from wynntools.gear_solver import Spec, solve_gear
from wynntools.presets import PRESETS
from wynntools.rules import ability_points
from wynntools.tree_solver import solve_tree

EXPECTED = json.loads((Path(__file__).parent / "fixtures" / "damage.json").read_text())


@pytest.mark.parametrize("name", [k for k in EXPECTED if not k.startswith("_")])
def test_matches_snapshot_of_wynnbuilder_page(gd, links, name):
    want = EXPECTED[name]
    r = damage_report(decode(links[name]["hash"], gd), gd)
    got = spell_values(decode(links[name]["hash"], gd), gd, "max")
    assert {k: round(v, 2) for k, v in got.items()} == pytest.approx(want["spells"], abs=0.01)
    assert r["defense"]["ehp"] == pytest.approx(want["ehp"], abs=0.01)
    assert r["defense"]["hpr"] == pytest.approx(want["hpr"], abs=0.01)
    assert r["poison_tick"] == want["poison_tick"]


def test_numbers_read_off_the_wynnbuilder_page(gd, links):
    """Typed in from wynnbuilder.github.io for this link, not produced by our code."""
    got = spell_values(decode(links["mage_105_gaia_lightbender"]["hash"], gd), gd, "max")
    assert round(got["Wand Melee"], 2) == 4548.33
    assert round(got["Ophanim"], 2) == 19482.73
    assert round(got["Earthen Splinter"], 2) == 101923.44
    d = damage_report(decode(links["mage_105_gaia_lightbender"]["hash"], gd), gd)["defense"]
    assert (round(d["hp"]), round(d["ehp"], 2), round(d["ehp_no_agi"], 2)) == (17125, 21980.71, 21805.24)


def test_typical_rolls_are_lower_and_summary_has_both(gd, links):
    s = summary(decode(links["mage_105_gaia_lightbender"]["hash"], gd), gd)
    typ = {x["name"]: x["summary"] for x in s["typical"]["spells"]}
    per = {x["name"]: x["summary"] for x in s["perfect"]["spells"]}
    assert typ["Ophanim"] < per["Ophanim"]
    assert s["perfect"]["poison_tick"] == 36100 and s["typical"]["poison_tick"] == 28100


def test_merge_stat_multipliers():
    st = {}
    merge_stat(st, "damMult.Potion", 20)
    merge_stat(st, "damMult.Potion", 10)          # non-stacking: highest wins
    merge_stat(st, "damMult.Stack", 10)
    merge_stat(st, "damMult.Stack", 10)           # others add
    merge_stat(st, "damMult.Part:3.Orb", 5)       # a part-specific key keeps its full name
    merge_stat(st, "sdPct", 3)
    merge_stat(st, "sdPct", 4)
    assert st == {"damMult": {"Potion": 20, "Stack": 20, "Part:3.Orb": 5}, "sdPct": 7}


def test_weapon_powders_convert_neutral_in_order():
    # 100-200 neutral wand; powder ids are element*7 + tier-1 in ETWFA order.
    # Two fire T6 (37% conversion, +9-14 each) merge into one 74% step, then earth
    # T6 (46%, +11-12) converts 46% of the neutral that is left.
    w = {"nDam": "100-200", "eDam": "0-0", "tDam": "0-0", "wDam": "0-0", "fDam": "0-0", "aDam": "0-0"}
    fire6, earth6 = 3 * 7 + 5, 0 * 7 + 5
    dam, present = weapon_powder_damage(w, [fire6, fire6, earth6])
    assert dam[4] == pytest.approx([74 + 18, 148 + 28])
    assert dam[1] == pytest.approx([26 * 0.46 + 11, 52 * 0.46 + 12])
    assert dam[0] == pytest.approx([26 - 26 * 0.46, 52 - 52 * 0.46])
    assert present == [True, True, False, False, True, False]


def _mage_spec(**kw):
    return Spec(cls="Mage", level=105, objective={"poison": 1}, floors={"hp": 15000, "mr": 20},
                require_major=["PLAGUE"], force={"weapon": "Gaia"}, topn=3, **kw)


def test_damage_floor_needs_a_tree(gd):
    spec = _mage_spec()
    spec.floors["damage"] = {"Ophanim": 1}
    with pytest.raises(ValueError, match="tree"):
        solve_gear(spec, gd)


def test_damage_floor_is_respected(gd):
    tree = set(solve_tree(gd.tree("Mage"), PRESETS["mage-poison-lightbender"]["weights"],
                          ability_points(105)))
    base = solve_gear(_mage_spec(atree=tree), gd)
    from wynntools.codec import Build
    ophanim = lambda eq: spell_values(Build(equipment=eq, level=105, atree=tree), gd)["Ophanim"]
    before = ophanim(base.equipment)
    spec = _mage_spec(atree=tree)
    spec.floors["damage"] = {"Ophanim": before + 1000}
    r = solve_gear(spec, gd)
    assert r is not None and ophanim(r.equipment) >= before + 1000
    assert r.score <= base.score          # the floor costs poison, never adds it


def test_crit_damage_and_strength_scale_like_wynnbuilder():
    """damage_calc.js step 6: normal x (1+str%) x mults; crit adds (1 + critDamPct%)."""
    from wynntools.damage import calculate_spell_damage
    from wynntools.rules import sp_to_pct
    weapon = {"damages": [[100, 100]] + [[0, 0]] * 5, "present": [True] + [False] * 5,
              "atkSpd": "NORMAL"}
    stats = {"str": 50, "critDamPct": 40, "damMult": {"Potion": 20}}
    norm, crit, per, _ = calculate_spell_damage(stats, weapon, [100, 0, 0, 0, 0, 0], True)
    s = sp_to_pct(50)
    base = 100 * 2.05                           # NORMAL attack speed, 100% neutral
    assert norm == pytest.approx([base * (1 + s) * 1.2] * 2)
    assert crit == pytest.approx([base * (1 + s + 1.4) * 1.2] * 2)
    norm_nostr, crit_nostr, _, _ = calculate_spell_damage(stats, weapon, [100, 0, 0, 0, 0, 0], True,
                                                          ignore_str=True)
    assert norm_nostr == pytest.approx([base * 1.2] * 2) and crit_nostr == norm_nostr
