"""The `wt` commands that work with the running web app: current, show, builds, edit.

Regression for a real session: the AI made a build but never saved it, so it
never appeared in the app's list, and it had no way to know which build the
player meant by "this build".
"""
import json
import time
import urllib.request
from pathlib import Path

import pytest

from wynntools import buildfile, cli
from wynntools.codec import decode

pytest.importorskip("uvicorn")
from tests.ui.harness import TOKEN, AppServer  # noqa: E402


def run(capsys, *argv):
    try:
        code = cli.main(list(argv))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (print(e.code) or 1)
    return code or 0, capsys.readouterr().out


@pytest.fixture()
def builds(tmp_path, gd, links, monkeypatch):
    doc = buildfile.from_build(decode(links["shaman_105_stormdrain"]["hash"], gd), gd)
    buildfile.write(tmp_path / "storm.json", buildfile.refresh({"name": "Storm", **doc}, gd))
    monkeypatch.setattr(cli, "BUILDS", tmp_path)
    return tmp_path


@pytest.fixture()
def app(builds):
    with AppServer(str(builds)) as srv:
        (builds / ".server.json").write_text(json.dumps({"port": srv.port, "token": TOKEN}))
        yield srv


def api(srv, method, path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{srv.port}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"x-wt-token": TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_without_the_app_current_says_so(builds, capsys):
    code, out = run(capsys, "current")
    assert code == 1 and "isn't running" in out
    code, out = run(capsys, "builds")
    assert code == 0 and "Storm · Shaman Lv. 105 · verified" in out


def test_current_reports_unsaved_edits(app, builds, capsys):
    code, out = run(capsys, "current")
    assert code == 1 and "no page" in out
    doc = buildfile.read(builds / "storm.json")
    doc["equipment"][0] = "Sparkweaver"
    api(app, "PUT", "/api/view", {"view": "editor", "file": "storm.json", "dirty": True, "doc": doc})
    code, out = run(capsys, "current")
    assert "looking at" in out and "storm.json" in out and "UNSAVED" in out
    assert "helmet     Sparkweaver" in out                      # the page's copy, not the file's
    # and the AI may not write over those edits
    code, out = run(capsys, "edit", str(builds / "storm.json"), "--notes", "x")
    assert code == 1 and "unsaved edits" in out
    assert buildfile.read(builds / "storm.json").get("notes") != "x"
    # a variant in a new file is fine, and opens in the app
    code, out = run(capsys, "edit", str(builds / "storm.json"), "--item", "helmet=Sparkweaver",
                    "--save-as", str(builds / "storm-spark.json"))
    assert "saved" in out and "opened storm-spark.json in the web app" in out
    new = buildfile.read(builds / "storm-spark.json")
    assert new["equipment"][0] == "Sparkweaver" and new["name"] == "storm-spark"
    code, out = run(capsys, "builds")
    assert "▶" in out and "unsaved" in out


def test_current_on_saved_build_and_show(app, builds, capsys):
    api(app, "PUT", "/api/view", {"view": "editor", "file": "storm.json", "dirty": False})
    code, out = run(capsys, "current")
    assert code == 0 and "UNSAVED" not in out and "VERIFIED OK" in out and "Name: Storm" in out
    code, out = run(capsys, "show", "storm.json")
    assert code == 0 and "opened storm.json" in out
    code, out = run(capsys, "show", "nope.json")
    assert code == 1


def test_edit_checks_items_and_slots(builds, capsys):
    f = str(builds / "storm.json")
    assert run(capsys, "edit", f, "--item", "helm=Sparkweaver")[1].startswith("unknown slot")
    assert "not a helmet" in run(capsys, "edit", f, "--item", "helmet=Stormdrain")[1]
    assert "no item named" in run(capsys, "edit", f, "--item", "helmet=Not An Item")[1]
    code, out = run(capsys, "edit", f, "--item", "ring2=", "--level", "106")
    doc = buildfile.read(f)
    assert doc["equipment"][5] is None and doc["level"] == 106 and doc["status"]
    assert "updated" in out


def test_edit_puts_tomes_only_in_slots_of_their_type(builds, capsys, gd):
    """WynnBuilder counts a tome in a slot of another type as an empty slot, so
    `wt edit --tome` refuses it (and verify flags one found in a link)."""
    from wynntools.codec import TOME_SLOTS, to_link
    from wynntools.verify import check_link
    f = str(builds / "storm.json")
    before = buildfile.read(f)["tomes"]
    code, out = run(capsys, "edit", f, "--tome", "weaponTome1=Blooming Tome of Defensive Mastery III")
    assert code == 1 and "is an armorTome and can't go in weaponTome1" in out
    assert "put it in armorTome1 or armorTome2 or armorTome3 or armorTome4" in out
    assert buildfile.read(f)["tomes"] == before
    code, out = run(capsys, "edit", f, "--tome", "armorTome2=Blooming Tome of Defensive Mastery III")
    assert code == 0 and buildfile.read(f)["tomes"][3] == "Blooming Tome of Defensive Mastery III"
    b = buildfile.to_build(buildfile.read(f), gd)
    b.tomes[TOME_SLOTS.index("guildTome1")] = gd.tome("Abyssal Tome of Combat Mastery III")["id"]
    ok, rep = check_link(to_link(b, gd), gd)
    assert not ok and any("is a weaponTome and can't go in guildTome1" in p for p in rep["problems"])


def test_aspects_list_recommend_and_edit(builds, capsys, tmp_path):
    f = str(builds / "storm.json")
    inv = tmp_path / "inv.json"
    inv.write_text(json.dumps({"aspects": {"Shaman": {"Aspect of the Beckoned Legion": 1}}}))
    code, out = run(capsys, "aspects", f, "--inventory", str(inv))
    assert code == 0 and "Aspect of the Beckoned Legion  (Fabled · owned: tier 1)" in out
    assert "works through: Puppet Master  [in your tree]" in out
    assert "not modelled in WynnBuilder's data" in out            # text-only aspects say so
    code, out = run(capsys, "aspects", f, "--owned", "--recommend", "--goal", "puppet_dps",
                    "--inventory", str(inv))
    assert code == 0 and "Aspect of the Beckoned Legion (tier 1)" in out and "your inventory" in out
    assert '--aspect "Aspect of the Beckoned Legion=1"' in out
    assert "needs --goal" in run(capsys, "aspects", f, "--recommend", "--inventory", str(inv))[1]

    code, out = run(capsys, "edit", f, "--aspect", "Beckoned Legion", "--inventory", str(inv))
    assert code == 0 and "Aspect of the Beckoned Legion tier 1 (owned)" in out
    code, out = run(capsys, "edit", f, "--aspect", "Aspect of Stances", "--tier", "2", "--inventory", str(inv))
    assert "tier 2 (not owned: a goal to collect)" in out
    assert buildfile.read(f)["aspects"][:2] == [["Aspect of the Beckoned Legion", 1], ["Aspect of Stances", 2]]
    assert "has tiers 1-3, not 4" in run(capsys, "edit", f, "--aspect", "Stances=4")[1]
    assert "several Shaman aspects" in run(capsys, "edit", f, "--aspect", "Embodiment")[1]
    assert "no Shaman aspect named" in run(capsys, "edit", f, "--aspect", "Aspect of Nothing")[1]
    run(capsys, "edit", f, "--remove-aspect", "Stances")
    assert buildfile.read(f)["aspects"][:2] == [["Aspect of the Beckoned Legion", 1], None]


def test_a_crashed_server_is_not_running(builds, capsys):
    """Liveness is the heartbeat on .server.json, not a process id: Codex's
    sandbox has its own process namespace and can't see the server."""
    import os
    import time

    from wynntools.web import client
    state = builds / ".server.json"
    state.write_text("{}")
    (builds / ".view.json").write_text(json.dumps({"view": "editor", "file": "storm.json",
                                                   "dirty": False, "doc": None, "at": 1}))
    assert client.running(builds)
    old = time.time() - client.STALE - 1
    os.utime(state, (old, old))
    assert not client.running(builds)
    assert "isn't running" in run(capsys, "current")[1]
    assert run(capsys, "current", "--hook", "UserPromptSubmit")[1].strip() == "{}"


def test_hook_output_names_the_open_build(app, builds, capsys):
    api(app, "PUT", "/api/view", {"view": "editor", "file": "storm.json", "dirty": True,
                                  "doc": buildfile.read(builds / "storm.json")})
    code, out = run(capsys, "current", "--hook", "UserPromptSubmit")
    ctx = json.loads(out)["hookSpecificOutput"]
    assert code == 0 and ctx["hookEventName"] == "UserPromptSubmit"
    assert "storm.json" in ctx["additionalContext"] and "UNSAVED" in ctx["additionalContext"]


# ---- `wt gear --edit`: re-search an existing build instead of making a new one

def _spec(builds, **extra):
    f = builds / "spec.json"
    f.write_text(json.dumps({"objective": {"eSteal": 1}, **extra}))
    return str(f)


def test_gear_edit_changes_only_the_asked_slots_and_keeps_the_rest(builds, capsys):
    f = builds / "storm.json"
    doc = buildfile.read(f)
    doc.update(notes="mine", powders=[["e6"], [], [], [], ["t6", "t6"]])
    buildfile.write(f, buildfile.refresh(doc, cli.GameData()))
    code, out = run(capsys, "gear", _spec(builds), "--edit", str(f), "--change", "helmet", "--quiet")
    new = buildfile.read(f)
    assert code == 0 and f"updated {f}" in out
    assert new["equipment"][1:] == doc["equipment"][1:]      # only the helmet could change
    assert new["name"] == "Storm" and new["notes"] == "mine" and new["tree"] == doc["tree"]
    assert new["powders"][4] == ["t6", "t6"]                # the weapon kept its powders
    assert new["spec"]["class"] == "Shaman" and new["spec"]["force"]["weapon"] == "Stormdrain"
    assert new["status"]["verified"]
    # the second time, the spec comes from the build itself and nothing changes
    code, out = run(capsys, "gear", "--edit", str(f), "--change", "helmet", "--quiet")
    assert code == 0 and "no changes" in out and buildfile.read(f)["equipment"] == new["equipment"]


def test_gear_edit_save_as_leaves_the_original_alone(builds, capsys):
    f, g = builds / "storm.json", builds / "storm2.json"
    before = f.read_text()
    code, out = run(capsys, "gear", _spec(builds), "--edit", str(f), "--keep",
                    "weapon,chestplate,leggings,boots,ring1,ring2,bracelet,necklace",
                    "--save-as", str(g), "--quiet")
    assert code == 0 and f.read_text() == before
    assert buildfile.read(g)["name"] == "storm2"


def test_gear_edit_refuses_what_it_cannot_do(builds, capsys):
    f = str(builds / "storm.json")
    assert "no spec to reuse" in run(capsys, "gear", "--edit", f)[1]
    assert "not both" in run(capsys, "gear", _spec(builds), "--edit", f, "--keep", "helmet",
                             "--change", "boots")[1]
    assert "unknown slot" in run(capsys, "gear", _spec(builds), "--edit", f, "--keep", "helm")[1]
    assert "go with --edit" in run(capsys, "gear", _spec(builds), "--keep", "helmet")[1]
    run(capsys, "edit", f, "--item", "ring2=")
    assert "can't keep ring2" in run(capsys, "gear", _spec(builds), "--edit", f, "--keep", "ring2")[1]
    assert "can't use these kept items" in run(capsys, "gear", _spec(builds, level=50), "--edit", f,
                                               "--keep", "weapon")[1]


def test_gear_edit_keeps_the_copy_a_build_uses(builds, capsys):
    """Owning two Rings of Rubies (+10% and +4% Stealing), a re-search of ring2 leaves
    ring1's +4% copy in place, and the report says where it is kept."""
    from wynntools import inventory as inv_mod
    ten, four = {"eSteal": 10}, {"eSteal": 4}
    inv = inv_mod.Inventory(places={"account": {"pages": {"1": {"updated": "", "slots": [
        {"slot": 0, "name": "Ring of Rubies", "kind": "item", "rolls": ten},
        {"slot": 1, "name": "Ring of Rubies", "kind": "item", "rolls": four}]}}}})
    inv_mod.save(inv, builds / "inv.json")
    f = builds / "storm.json"
    doc = buildfile.read(f)
    doc["equipment"][4] = "Ring of Rubies"
    doc["copies"] = [None] * 4 + [inv_mod.fingerprint(four)] + [None] * 4
    buildfile.write(f, buildfile.refresh(doc, cli.GameData()))
    code, out = run(capsys, "gear", _spec(builds), "--edit", str(f), "--change", "ring2", "--quiet",
                    "--inventory", str(builds / "inv.json"))
    new = buildfile.read(f)
    assert code == 0, out
    assert new["equipment"][4] == "Ring of Rubies" and new["copies"][4] == inv_mod.fingerprint(four)
    code, out = run(capsys, "report", str(f), "--inventory", str(builds / "inv.json"))
    assert "ring1       Ring of Rubies: Account ender chest · page 1 · row 1, column 2" in out


def test_gear_edit_refuses_over_unsaved_edits(app, builds, capsys):
    api(app, "PUT", "/api/view", {"view": "editor", "file": "storm.json", "dirty": True,
                                  "doc": buildfile.read(builds / "storm.json")})
    assert "unsaved edits" in run(capsys, "gear", _spec(builds), "--edit",
                                  str(builds / "storm.json"))[1]


def test_rings_that_only_swapped_places_are_not_a_change():
    old = [None] * 4 + ["A", "B"] + [None] * 3
    new = [None] * 4 + ["B", "C"] + [None] * 3
    cli._same_ring_order(new, old)
    assert new[4:6] == ["C", "B"]
    new = [None] * 4 + ["B", "A"] + [None] * 3
    cli._same_ring_order(new, old)
    assert new[4:6] == ["A", "B"]


def test_merge_drops_what_no_longer_fits(gd, links):
    doc = {"name": "x", "notes": "n", **buildfile.from_build(
        decode(links["shaman_105_stormdrain"]["hash"], gd), gd)}
    doc.update(powders=[["e6"], [], [], [], ["t6"]], skillpoints=[0, 0, 0, 0, 0],
               aspects=[None] * 5)
    new = {**doc, "equipment": ["Morph-Stardust"] + doc["equipment"][1:8] + ["Gaia"], "tree": []}
    out, lines = cli._merge_into(doc, new, gd)
    assert out["powders"] == [[], [], [], [], []]
    assert out["tree"] == [] and out["skillpoints"] is None and out["notes"] == "n"
    assert any("class changed" in x for x in lines)


# ------------------------------------------------------------ progress bars for long commands
def written(builds, check, timeout=5):
    """The one running tool once `check` holds for it. The progress file is
    rewritten by a background thread every 0.25 s, which a slow CI runner
    (macOS) can delay past any fixed sleep."""
    from wynntools.web import client
    end = time.time() + timeout
    while True:
        tools = client.running_tools(builds)
        if (len(tools) == 1 and check(tools[0])) or time.time() > end:
            [t] = tools
            return t
        time.sleep(0.05)


def test_tool_progress_file_appears_late_updates_and_goes(builds):
    from wynntools.web import client
    (builds / ".server.json").write_text("{}")             # the app is running
    tp = client.ToolProgress(builds, "Searching for gear", "wt gear x.json", key="gear",
                             delay=0.2, beat=0.5)
    f = tp.path
    with tp:
        assert not f.exists()                              # quick commands never show
        assert written(builds, lambda t: True)["label"] == "Searching for gear"
        client.report(0.5, "1,000 checked")
        t = written(builds, lambda t: t["fraction"] == 0.5)
        assert (t["label"], t["command"], t["fraction"], t["detail"]) == \
            ("Searching for gear", "wt gear x.json", 0.5, "1,000 checked")
    assert not f.exists() and client.running_tools(builds) == []
    client.report(0.9)                                     # nothing open: ignored


def test_without_the_app_nothing_is_reported_but_the_time_is_remembered(builds):
    """No page to draw a bar, so no run file; the time still goes into the
    history, so the first bar after the app opens is already a good guess."""
    from wynntools.web import client
    with client.ToolProgress(builds, "x", key="gear", delay=0):
        time.sleep(0.3)
    assert list((builds / ".progress").glob(client.RUN_GLOB)) == []
    assert client.expected(builds, "gear") == pytest.approx(0.3, abs=0.2)


def test_a_killed_command_stops_showing(builds):
    from wynntools.web import client
    (builds / ".progress").mkdir()
    old = {"label": "gone", "command": "wt gear", "started": time.time() - 100, "at": time.time() - 60}
    (builds / ".progress" / "run-123.json").write_text(json.dumps(old))
    (builds / ".progress" / "run-124.json").write_text(json.dumps({**old, "at": time.time()}))
    client.remember(builds, "gear", 12)
    assert [t["id"] for t in client.running_tools(builds)] == ["run-124"]
    assert not (builds / ".progress" / "run-123.json").exists()
    assert client.expected(builds, "gear") == 12      # the history is not a run: left alone


def test_wt_commands_report_what_they_do(builds, capsys, monkeypatch):
    from wynntools.web import client
    seen = {}
    monkeypatch.setattr(cli, "cmd_fetch", lambda a: seen.update(label=client._active.state["label"],
                                                               command=client._active.state["command"]))
    run(capsys, "fetch")
    assert seen == {"label": "Downloading WynnBuilder data", "command": "wt fetch"}
    assert client._active is None
    monkeypatch.setattr(cli, "cmd_serve", lambda a: seen.update(serve=client._active))
    run(capsys, "serve")
    assert seen["serve"] is None                           # the app itself gets no bar


def test_events_stream_sends_running_tools(app, builds):
    (builds / ".progress").mkdir()
    (builds / ".progress" / "run-7.json").write_text(json.dumps(
        {"label": "Ranking upgrades", "command": "wt upgrades s.json", "fraction": 0.25,
         "detail": None, "started": time.time() - 3, "at": time.time()}))
    req = urllib.request.Request(f"http://127.0.0.1:{app.port}/api/events", headers={"x-wt-token": TOKEN})
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.readline() == b"event: tools\n"
        [t] = json.loads(r.readline().decode().removeprefix("data: "))
    assert (t["id"], t["label"], t["fraction"], t["estimated"]) == \
        ("run-7", "Ranking upgrades", 0.25, False)
    assert t["elapsed"] >= 3


def test_events_stream_reports_inventory_changes(app, builds):
    """The Inventory page reloads on this event (e.g. after the chest-export mod imports)."""
    (builds / "inventory.json").write_text("{}")
    req = urllib.request.Request(f"http://127.0.0.1:{app.port}/api/events", headers={"x-wt-token": TOKEN})
    with urllib.request.urlopen(req, timeout=10) as r:
        time.sleep(0.2)
        (builds / "inventory.json").write_text('{"items": {"Galleon": {}}}')
        for _ in range(20):
            line = r.readline().decode()
            if line.startswith("data: "):
                break
    assert json.loads(line.removeprefix("data: "))["changed"] == ["inventory.json"]


def test_a_command_that_cannot_measure_itself_is_estimated_from_past_runs(builds):
    """The exact gear search has no percentage of its own, so the bar is worked
    out from how long the last few runs took: 90% at that time, then creeping."""
    from wynntools.web import client
    assert client.expected(builds, "gear") == client.EXPECT["gear"]       # no history yet
    for _ in range(3):
        client.remember(builds, "gear", 40)
    assert client.expected(builds, "gear") == 40
    (builds / ".server.json").write_text("{}")
    with client.ToolProgress(builds, "Searching for gear", key="gear", delay=0, beat=0.5):
        client.report(None, "round 3")
        t = written(builds, lambda t: t["detail"] == "round 3")
    assert t["estimated"] and 0 < t["fraction"] < 0.05
    steps = [client.estimate(s, 40) for s in (0, 10, 20, 40, 80, 400)]
    assert steps == sorted(steps) and steps[3] == pytest.approx(0.9) and steps[-1] < 0.99
    assert client.estimate(1e6, 40) < 1                  # never says it is finished


def test_a_command_that_measures_itself_is_not_estimated(builds):
    """`wt fetch` counts its files, so its own numbers are used and its time is
    not remembered (it would be an estimate for nothing)."""
    from wynntools.web import client
    (builds / ".server.json").write_text("{}")
    with client.ToolProgress(builds, "Downloading WynnBuilder data", key="fetch",
                             delay=0, beat=0.5) as tp:
        client.report(3 / 12, "3/12 files")
        t = written(builds, lambda t: not t["estimated"])
    assert (t["fraction"], t["estimated"]) == (0.25, False)
    assert tp.measured and client.history(builds) == {}


def test_search_progress_feeds_the_bar(builds):
    import io
    from wynntools.progress import ProgressBar
    from wynntools.web import client
    with client.ToolProgress(builds, "Searching for gear") as tp:
        ProgressBar(stream=io.StringIO())({"fraction": 0.37, "nodes": 38000, "best": 44.77, "elapsed": 3})
        assert (tp.state["fraction"], tp.state["detail"]) == (0.37, "38,000 checked · best 44.77")


def test_missing_or_broken_spec_is_explained(tmp_path, capsys):
    """Regression: `wt gear` with a spec path that didn't exist (a local model's
    typo, found by evals/agent_eval.py) crashed with a FileNotFoundError traceback."""
    from wynntools import cli
    with pytest.raises(SystemExit, match="no spec file .*missing.json: write the spec's JSON"):
        cli.main(["gear", str(tmp_path / "missing.json"), "--quiet"])
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    with pytest.raises(SystemExit, match="can't read the spec"):
        cli.main(["spec-check", str(bad)])
