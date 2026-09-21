from wynntools.codec import decode
from wynntools.presets import PRESETS, summoner_hits_per_sec
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


def test_presets_solve_to_valid_trees(gd):
    for name, P in PRESETS.items():
        tree = gd.tree(P["class"])
        for level in (105, 121):
            sel = solve_tree(tree, P["weights"], ability_points(level))
            _, failed = tree_activation(tree, sel)
            assert not failed, (name, level)
            assert ap_cost(tree, sel) <= ability_points(level)


def test_summoner_tree_matches_session(gd, links):
    tree = gd.tree("Shaman")
    sel = solve_tree(tree, PRESETS["summoner-stealing"]["weights"], ability_points(105))
    assert sel == decode(links["shaman_105_stormdrain"]["hash"], gd).atree
    steady, buffed = summoner_hits_per_sec(tree, sel)
    assert steady >= 34 and buffed >= 50
