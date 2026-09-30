"""The local search choosing aspects ("aspect_pool" owned/any, `wt gear --aspects`):
they count in every check, the build keeps them, and a build's own aspects stay."""
import dataclasses
import json

import pytest

from wynntools import buildfile, cli
from wynntools.agent_aids import check_spec
from wynntools.aspects import recommend
from wynntools.derived import metrics
from wynntools.gear_local import LocalSearch
from wynntools.gear_solver import Spec
from wynntools.presets import preset_weights
from wynntools.rules import ability_points
from wynntools.search import kind_for, run
from wynntools.tree_solver import solve_tree
from wynntools.verify import check_link

LEGION = "Aspect of the Beckoned Legion"


@pytest.fixture(scope="module")
def puppets(gd):
    tree = set(solve_tree(gd.tree("Shaman"), preset_weights("shaman-summoner", gd), ability_points(105)))
    return Spec(cls="Shaman", level=105, objective={"puppet_dps": 1}, floors={"hp": 12000},
                force={"weapon": "Stormdrain"}, atree=tree)


def aspect_id(gd, name):
    return next(a["id"] for a in gd.aspects("Shaman") if a["displayName"] == name)


def test_choices_follow_the_pool(gd):
    spec = Spec(cls="Shaman", level=105, objective={"puppet_dps": 1})
    assert spec.aspect_choices(gd) == []                                  # fixed: none
    every = dataclasses.replace(spec, aspect_pool="any").aspect_choices(gd)
    top = {a["id"]: len(a["tiers"]) for a in gd.aspects("Shaman")}
    assert every and all(t == top[a] for a, t in every)
    unmodelled = [a["id"] for a in gd.aspects("Shaman")
                  if not any(t.get("abilities") for t in a.get("tiers") or [])]
    assert not {a for a, _ in every} & set(unmodelled)                    # never change a number
    legion = aspect_id(gd, LEGION)
    owned = dataclasses.replace(spec, aspect_pool="owned", aspect_supply={LEGION: 1, "Nonsense": 3})
    assert owned.aspect_choices(gd) == [(legion, 1)]                       # at the tier owned
    kept = dataclasses.replace(spec, aspect_pool="any", aspects=[(legion, 2), None, None, None, None])
    assert legion not in {a for a, _ in kept.aspect_choices(gd)}


def test_search_chooses_aspects_and_counts_them(gd, puppets):
    """The chosen aspects are in every check: the reported number is the build's
    own with them, and it beats (or ties) searching gear and then adding aspects."""
    spec = dataclasses.replace(puppets, aspect_pool="any")
    assert kind_for(spec) == "local"
    out = run(spec, gd, explain_failure=False, time_limit=300)
    r = out.result
    assert "aspects chosen from any aspect" in out.note
    assert aspect_id(gd, LEGION) in {a[0] for a in r.aspects if a}
    b = spec.build(r.equipment, None, r.skillpoints, aspects=r.aspects)
    assert metrics(b, gd)["puppet_dps"] == pytest.approx(r.score)
    assert check_link(cli.to_link(b, gd), gd)[0]
    plain = LocalSearch(puppets, gd, time_limit=300).run()
    after = recommend(puppets.build(plain.equipment, None, plain.skillpoints), gd, "puppet_dps",
                      spec.aspect_choices(gd))
    assert r.score >= after["after"] - 1e-6 and r.score > plain.score


def test_owned_aspects_at_the_owned_tier(gd, puppets):
    spec = dataclasses.replace(puppets, aspect_pool="owned", aspect_supply={LEGION: 1})
    r = LocalSearch(spec, gd, time_limit=300).run()
    assert [a for a in r.aspects if a] == [(aspect_id(gd, LEGION), 1)]


def test_kept_aspects_stay_and_empty_slots_fill(gd, puppets):
    other = next(a for a in gd.aspects("Shaman") if a["displayName"] != LEGION)
    kept = [None, (other["id"], 1), None, None, None]
    spec = dataclasses.replace(puppets, aspect_pool="any", aspects=kept)
    r = LocalSearch(spec, gd, time_limit=300).run()
    assert r.aspects[1] == kept[1]
    assert aspect_id(gd, LEGION) in {a[0] for a in r.aspects if a}


def test_item_goal_chooses_no_aspects(gd):
    """Aspects change only damage-model numbers: an item-stat search leaves them alone."""
    spec = Spec(cls="Shaman", level=105, objective={"hp": 1}, force={"weapon": "Stormdrain"},
                aspect_pool="any")
    assert kind_for(spec) == "exact"
    out = run(spec, gd, explain_failure=False)
    assert out.result.aspects is None and "no aspects chosen" in out.note
    _, warnings = check_spec({"class": "Shaman", "level": 105, "objective": {"hp": 1}, "aspect_pool": "any"}, gd)
    assert any("'aspect_pool' does nothing here" in w for w in warnings)


def test_shortlists_refuse_an_aspect_pool(gd, puppets):
    spec = dataclasses.replace(puppets, objective={"hp": 1}, floors={"ehp": 20000}, aspect_pool="owned",
                               aspect_supply={LEGION: 3})
    assert kind_for(spec) == "local"                  # the shortlist search can't choose aspects
    with pytest.raises(ValueError, match="shortlist search can't choose aspects"):
        run(spec, gd, kind="shortlists", explain_failure=False)


def test_carry_over_keeps_chosen_aspects(gd):
    old = {"equipment": [None] * 8 + ["Stormdrain"], "aspects": [["Aspect of Exsanguination", 1]] + [None] * 4}
    chosen = {"equipment": [None] * 8 + ["Stormdrain"], "aspects": [[LEGION, 3]] + [None] * 4}
    assert buildfile.carry_over(dict(chosen), old, gd)["aspects"] == chosen["aspects"]
    plain = {"equipment": [None] * 8 + ["Stormdrain"]}
    assert buildfile.carry_over(dict(plain), old, gd)["aspects"] == old["aspects"]


def test_wt_gear_saves_the_chosen_aspects(gd, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_show_in_app", lambda path: None)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"class": "Shaman", "level": 105, "objective": {"puppet_dps": 1},
                                "floors": {"hp": 12000}, "force": {"weapon": "Stormdrain"}}))
    out_file = tmp_path / "puppets.json"
    with pytest.raises(SystemExit) as done:
        cli.main(["gear", str(spec), "--tree", "shaman-summoner", "--aspects", "any", "--quiet",
                  "--save", str(out_file)])
    assert done.value.code == 0
    text = capsys.readouterr().out
    assert "Aspects the search chose (any): " in text and LEGION in text
    doc = buildfile.read(out_file)
    assert [LEGION, 3] in doc["aspects"] and doc["spec"]["aspect_pool"] == "any"
    assert doc["status"]["verified"]
    from wynntools.agent_aids import report
    _, lines = report(doc, gd, str(out_file))
    assert any("Aspects: chosen by the search from ANY aspect" in line for line in lines)
