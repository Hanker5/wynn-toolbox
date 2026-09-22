import pytest

from wynntools.codec import decode
from wynntools.presets import PRESETS, preset_weights, summoner_hits_per_sec
from wynntools.rules import ability_points
from wynntools.tree_solver import solve_tree
from wynntools.verify import ap_cost, tree_activation


def test_archetype_requirement_is_checked_in_order(gd):
    """Regression: Puppet Master needs 3 OTHER Summoner nodes active BEFORE it.

    Counted over the whole selection this set passes (Air Mastery, Overseer and
    More Puppets), but More Puppets depends on Puppet Master, so the real
    activation order leaves Puppet Master and everything after it off.
    """
    tree = gd.tree("Shaman")
    selected = {0, 1, 3, 5, 6, 7, 8, 9, 12, 17, 21, 25, 28}
    by_id = {n["id"]: n for n in tree}
    summoners = [i for i in selected if i != 21 and by_id[i].get("archetype") == "Summoner"]
    assert len(summoners) >= by_id[21]["archetype_req"]          # naive check passes
    active, failed = tree_activation(tree, selected)
    assert {21, 25, 28} <= failed                                 # real order fails


def _check_preset_trees(gd, levels_for):
    for name, P in PRESETS.items():
        tree = gd.tree(P["class"])
        for level in levels_for(P):
            w = preset_weights(name, gd)
            sel = solve_tree(tree, w, ability_points(level))
            _, failed = tree_activation(tree, sel)
            assert not failed, (name, level)
            assert ap_cost(tree, sel) <= ability_points(level)
            if "archetype" in P:                  # generic presets take all four spells
                spells = {k for k, v in w.items() if v == 5}
                assert spells <= {n["display_name"] for n in tree if n["id"] in sel}, name


def test_presets_solve_to_valid_trees(gd):
    # Goal-tuned presets at both ends; the 15 generic ones at one level here
    # (their level-121 solves take up to ~9s each, see the slow test).
    _check_preset_trees(gd, lambda P: (106,) if "archetype" in P else (105, 121))


@pytest.mark.slow
def test_generic_presets_at_max_level(gd):
    _check_preset_trees(gd, lambda P: (121,) if "archetype" in P else ())


def test_summoner_tree_matches_session(gd, links):
    tree = gd.tree("Shaman")
    sel = solve_tree(tree, preset_weights("summoner-stealing", gd), ability_points(105))
    assert sel == decode(links["shaman_105_stormdrain"]["hash"], gd).atree
    steady, buffed = summoner_hits_per_sec(tree, sel)
    assert steady >= 34 and buffed >= 50


def test_every_archetype_of_every_class_has_a_preset(gd):
    """Only Shaman and Mage used to have presets, so gear searches for the other
    classes came out with an empty tree. (Solved in the test above.)"""
    from wynntools.presets import ARCHETYPES
    for cls in ("Archer", "Assassin", "Warrior", "Mage", "Shaman"):
        in_data = {n.get("archetype") for n in gd.tree(cls)} - {None, ""}
        assert set(ARCHETYPES[cls]) == in_data, cls
        for arch in in_data:
            w = preset_weights(f"{cls.lower()}-{arch.lower().replace(' ', '-')}", gd)
            assert sum(v == 5 for v in w.values()) == 4, (cls, arch, "four spells")

