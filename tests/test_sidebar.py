"""The Builds list's own order and groups (wynntools/sidebar.py, `wt group`, `wt builds`).

The page mirrors `arrange` in static/app.js (`arrangeList`); tests/test_ui.py
drives that side.
"""
import json
import time
import urllib.request

import pytest

from wynntools import buildfile, cli, settings
from wynntools import sidebar as sb
from wynntools.codec import decode

BUILDS = [("a.json", None), ("b.json", None), ("c.json", None), ("d.json", None),
          ("a--x.json", "a.json"), ("orphan--y.json", "gone.json")]


def G(name, *files, collapsed=False):
    return {"group": name, "collapsed": collapsed, "builds": list(files)}


def test_arrange_puts_new_builds_first_and_drops_what_is_gone():
    saved = {"items": ["c.json", G("Mage", "b.json", "gone.json", "a--x.json"), "gone.json"]}
    out = sb.arrange(BUILDS, saved)
    # new (unplaced) top-level builds first, alphabetically; a candidate whose parent
    # is gone is a top-level build; a candidate with a parent is never placed
    assert out == {"items": ["a.json", "d.json", "orphan--y.json", "c.json", G("Mage", "b.json")]}
    assert sb.arrange(BUILDS, None)["items"] == ["a.json", "b.json", "c.json", "d.json", "orphan--y.json"]
    assert sb.problem(out) is None


def test_arrange_lists_a_file_once_and_keeps_empty_groups():
    out = sb.arrange(BUILDS, {"items": ["a.json", G("Empty"), G("Twice", "a.json", "b.json")]})
    assert out["items"][-3:] == ["a.json", G("Empty"), G("Twice", "b.json")]


def test_changes():
    top = [(f, None) for f in ("a.json", "b.json", "c.json", "d.json")]
    lay = sb.arrange(top, None)
    lay = sb.add(lay, "Mage", ["c.json", "a.json"])                # new group at the top
    assert lay["items"] == [G("Mage", "c.json", "a.json"), "b.json", "d.json"]
    lay = sb.add(lay, "Mage", ["d.json"])                          # appended to the end
    assert lay["items"] == [G("Mage", "c.json", "a.json", "d.json"), "b.json"]
    lay = sb.ungroup(lay, ["a.json", "d.json"])                    # just below the group
    assert lay["items"] == [G("Mage", "c.json"), "a.json", "d.json", "b.json"]
    lay = sb.move(lay, "b.json", before="c.json")                  # next to a grouped build: into it
    assert lay["items"] == [G("Mage", "b.json", "c.json"), "a.json", "d.json"]
    lay = sb.move(lay, "Mage", after="d.json")
    assert lay["items"] == ["a.json", "d.json", G("Mage", "b.json", "c.json")]
    lay = sb.move(lay, "d.json", top=True)
    assert lay["items"][0] == "d.json"
    lay = sb.add(lay, "Warrior", ["d.json"])
    lay = sb.move(lay, "Warrior", after="b.json")                  # a group can't nest: next to Mage
    assert lay["items"] == ["a.json", G("Mage", "b.json", "c.json"), G("Warrior", "d.json")]
    lay = sb.collapse(sb.rename(lay, "Mage", "Mage builds"), "Mage builds")
    assert lay["items"][1] == G("Mage builds", "b.json", "c.json", collapsed=True)
    lay = sb.delete(lay, "Mage builds")                            # its builds stay, in its place
    assert lay["items"] == ["a.json", "b.json", "c.json", G("Warrior", "d.json")]
    assert sb.problem(lay) is None


@pytest.mark.parametrize("change", [
    lambda l: sb.add(l, "", ["a.json"]),
    lambda l: sb.add(l, "x.json", ["a.json"]),
    lambda l: sb.add(l, "G", ["nope.json"]),
    lambda l: sb.rename(l, "G", "H"),
    lambda l: sb.rename(l, "Nope", "X"),
    lambda l: sb.delete(l, "Nope"),
    lambda l: sb.move(l, "a.json"),
    lambda l: sb.move(l, "a.json", before="a.json"),
    lambda l: sb.move(l, "G", before="b.json"),                   # into itself
])
def test_bad_changes_are_refused(change):
    lay = {"items": ["a.json", G("G", "b.json"), G("H")]}
    with pytest.raises(ValueError):
        change(lay)


# ------------------------------------------------------------------ wt group / wt builds
def run(capsys, *argv):
    try:
        code = cli.main(list(argv))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (print(e.code) or 1)
    return code or 0, capsys.readouterr().out


@pytest.fixture()
def builds(tmp_path, gd, links, monkeypatch):
    doc = buildfile.from_build(decode(links["shaman_105_stormdrain"]["hash"], gd), gd)
    for f, name in [("storm.json", "Storm"), ("rain.json", "Rain"), ("hail.json", "Hail")]:
        buildfile.write(tmp_path / f, buildfile.refresh({"name": name, **doc}, gd))
    buildfile.write(tmp_path / "storm--alt.json", {**json.loads((tmp_path / "storm.json").read_text()),
                                                   "name": "Storm: alt", "parent": "storm.json"})
    monkeypatch.setattr(cli, "BUILDS", tmp_path)
    return tmp_path


def names(out):
    """The build names and group headings of `wt builds`, in order, with their indent."""
    rows = []
    for line in out.splitlines():
        if "▾" in line or "▸" in line:
            rows.append(line.strip().split(" (")[0])
        elif " · " in line:
            body = line[2:]                                         # after the ▶ mark
            indent = body[:len(body) - len(body.lstrip())]
            rows.append(indent + body.lstrip().split(None, 1)[1].split(" · ")[0])
    return rows


def test_wt_group_arranges_what_wt_builds_shows(builds, capsys):
    code, out = run(capsys, "builds")
    assert code == 0 and names(out) == ["Hail", "Rain", "Storm", "  Storm: alt"]
    code, out = run(capsys, "group", "add", "Shaman", "builds/storm.json", "rain")
    assert code == 0 and names(out) == ["▾ Shaman", "    Storm", "      Storm: alt", "    Rain", "Hail"]
    code, out = run(capsys, "group", "move", "Shaman", "--bottom")
    assert names(out)[0] == "Hail"
    code, out = run(capsys, "group", "move", "hail.json", "--after", "storm.json")
    assert names(out) == ["▾ Shaman", "    Storm", "      Storm: alt", "    Hail", "    Rain"]
    code, out = run(capsys, "group", "collapse", "Shaman")
    assert "▸ Shaman (3 builds, collapsed)" in out
    assert settings.load(builds / "settings.json")["sidebar"]["items"][0]["collapsed"] is True
    code, out = run(capsys, "group", "out", "rain.json")
    assert names(out)[-1] == "Rain"
    code, out = run(capsys, "group", "rename", "Shaman", "Storms")
    code, out = run(capsys, "group", "delete", "Storms")
    assert code == 0 and names(out) == ["Storm", "  Storm: alt", "Hail", "Rain"]
    code, out = run(capsys, "config", "--file", str(builds / "settings.json"))
    assert "sidebar = arranged by hand, 0 groups" in out


def test_wt_group_refuses_candidates_and_unknown_files(builds, capsys):
    code, out = run(capsys, "group", "add", "G", "storm--alt.json")
    assert code != 0 and "candidate" in out
    code, out = run(capsys, "group", "add", "G", "nope.json")
    assert code != 0 and "no build file" in out
    code, out = run(capsys, "group", "rename", "G", "H")
    assert code != 0 and "no group" in out
    assert not (builds / "settings.json").exists()


def test_events_stream_reports_layout_changes(builds):
    """`wt group` writes settings.json; the page reloads its list on this event."""
    pytest.importorskip("uvicorn")
    from tests.ui.harness import TOKEN, AppServer
    with AppServer(str(builds)) as app:
        req = urllib.request.Request(f"http://127.0.0.1:{app.port}/api/events", headers={"x-wt-token": TOKEN})
        with urllib.request.urlopen(req, timeout=10) as r:
            time.sleep(0.2)
            sb.save({"items": [G("G", "rain.json")]}, builds / "settings.json")
            for _ in range(20):
                line = r.readline().decode()
                if line.startswith("data: "):
                    break
    assert json.loads(line.removeprefix("data: "))["changed"] == ["settings.json"]
