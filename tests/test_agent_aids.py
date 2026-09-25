"""`wt intake`, `wt spec-check` and `wt report`: what keeps an AI agent on the rails."""
import json

from wynntools import agent_aids, cli
from wynntools.data import GameData


def run(capsys, *argv):
    try:
        code = cli.main(list(argv))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (print(e.code) or 1)
    return code or 0, capsys.readouterr().out


def test_intake_lists_only_what_is_missing():
    lines = "\n".join(agent_aids.intake({"class": "Mage", "level": 105, "objective": {"poison": 1}}))
    assert "Class: Mage" in lines and "Goal: poison x1" in lines
    assert "Which class" not in lines and "What should it be best at" not in lines
    assert "Tomes" in lines
    assert "Required before a search" not in lines
    assert "Required before a search: Class, Level, Goal" in "\n".join(agent_aids.intake(None))


def test_spec_check_catches_mistakes_before_a_search():
    gd = GameData()
    ok = {"class": "Mage", "level": 105, "objective": {"poison": 1}}
    assert agent_aids.check_spec(ok, gd)[0] == []
    assert any("need an ability tree" in e for e in agent_aids.check_spec(
        {**ok, "objective": {"puppet_dps": 1}}, gd)[0])
    assert agent_aids.check_spec({**ok, "objective": {"puppet_dps": 1}}, gd, tree="mage-arcanist")[0] == []
    assert agent_aids.check_spec({"objective": {"hp": 1}}, gd)[0]            # no class or level
    assert agent_aids.check_spec({**ok, "level": 130}, gd)[0]
    assert agent_aids.check_spec({**ok, "objective": {"nonsense": 1}}, gd)[0]
    assert agent_aids.check_spec({**ok, "tomes": ["x"] * 3}, gd)[0]
    _, warns = agent_aids.check_spec({**ok, "objective": {"poison": 1, "hp": 0.5}}, gd)
    assert any("similar weights" in w for w in warns)
    _, warns = agent_aids.check_spec({**ok, "objective": {"ehp": 1}}, gd)
    assert any("local search" in w for w in warns)


def test_spec_check_command_exit_codes(tmp_path, capsys):
    good, bad = tmp_path / "g.json", tmp_path / "b.json"
    good.write_text(json.dumps({"class": "Shaman", "level": 105, "objective": {"eSteal": 1}}))
    bad.write_text(json.dumps({"class": "Shaman", "level": 105, "objective": {"typo": 1}}))
    assert run(capsys, "spec-check", str(good))[0] == 0
    code, out = run(capsys, "spec-check", str(bad))
    assert code == 1 and "ERROR" in out


def test_report_has_the_link_search_kind_and_assumptions(tmp_path, gd, links, capsys):
    from wynntools import buildfile
    from wynntools.codec import decode
    doc = buildfile.from_build(decode(links["shaman_105_stormdrain"]["hash"], gd), gd)
    doc.update(name="Storm", spec={"class": "Shaman", "level": 105, "objective": {"eSteal": 1}})
    path = tmp_path / "storm.json"
    buildfile.write(path, buildfile.refresh(doc, gd))
    code, out = run(capsys, "report", str(path))
    assert code == 0 and "VERIFIED OK" in out
    assert "Search: exact" in out and "100% rolls" in out and "Aspects:" in out and "Tomes:" in out
    doc.pop("spec")
    buildfile.write(path, buildfile.refresh(doc, gd))
    assert "no search ran" in run(capsys, "report", str(path))[1]


def test_intake_command_reads_a_spec_file(tmp_path, capsys):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"class": "Mage", "level": 105, "objective": {"poison": 1}}))
    code, out = run(capsys, "intake", str(f))
    assert code == 0 and "Class: Mage" in out and "Tomes" in out
