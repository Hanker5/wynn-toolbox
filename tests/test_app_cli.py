"""The `wt` commands that work with the running web app: current, show, builds, edit.

Regression for a real session: the AI made a build but never saved it, so it
never appeared in the app's list, and it had no way to know which build the
player meant by "this build".
"""
import json
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
