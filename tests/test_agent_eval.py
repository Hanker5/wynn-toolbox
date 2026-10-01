"""The agent evaluation's own checks (evals/agent_eval.py): transcript parsing,
grading, and the scratch copy each case runs in."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))
import agent_eval as ev  # noqa: E402

LINK = "https://wynnbuilder.github.io/builder/#CY0tA0O6OI3dQ028Wy0l7aJXMCZMqQ"


def test_codex_events_become_commands_and_a_reply():
    lines = [json.dumps(e) for e in [
        {"type": "item.completed", "item": {"type": "error", "message": "Model metadata not found"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/bash -lc 'wt current'",
                                            "aggregated_output": "HP 15,234\n", "exit_code": 0}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "thinking aloud"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Your HP is 15,234."}},
    ]] + ["not json"]
    r = ev.parse_codex(lines)
    assert r["commands"] == [{"command": "/bin/bash -lc 'wt current'", "output": "HP 15,234\n", "exit": 0}]
    assert r["reply"] == "Your HP is 15,234." and r["errors"] == ["Model metadata not found"]


def test_claude_stream_becomes_commands_and_a_reply():
    lines = [json.dumps(e) for e in [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "wt verify x"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "VERIFIED OK"}]}]}},
        {"type": "system", "message": "a plain-text status line"},
        {"type": "user", "message": {"content": "a plain-text prompt"}},
        {"type": "result", "result": "Done.", "is_error": False},
    ]] + ['"just a string"']
    r = ev.parse_claude(lines)
    assert r["commands"] == [{"command": "wt verify x", "output": "VERIFIED OK", "exit": None}]
    assert r["reply"] == "Done." and not r["errors"]


def test_numbers_must_come_from_wt_output():
    sources = ["Level 105 · Effective HP 46,524 (26,032 without agility dodge) · mr 20 · sdPct 12.5"]
    reply = (f"Effective HP is 46,524, or 26032 without dodge; spell damage 12.5% and mana 13.7. "
             f"Level 105, saved as `builds/x2000.json`: {LINK} costs 999,999 emeralds.")
    assert ev.ungrounded_numbers(reply, sources) == ["13.7", "999999"]
    assert ev.ungrounded_numbers("At least 15,000 health.", ["the request: 15,000 health"]) == []


@pytest.mark.parametrize("expect,before,after,reply,want", [
    ("create", {"a.json": "1"}, {"a.json": "1", "b.json": "2"}, "Done", "pass"),
    ("create", {"a.json": "1"}, {"a.json": "9", "b.json": "2"}, "Done", "wrong"),     # touched the open one
    ("create", {"a.json": "1"}, {"a.json": "1"}, "Which class?", "asked"),
    ("create", {"a.json": "1"}, {"a.json": "1"}, "1. Level? 2. Plague?\nSay \"use the defaults\".", "asked"),
    ("edit", {"a.json": "1"}, {"a.json": "1"}, "Three helmets compared. Tell me which one you want.", "asked"),
    ("edit", {"a.json": "1"}, {"a.json": "1"}, "Your build is already tanky.", "wrong"),
    ("edit", {"a.json": "1"}, {"a.json": "2"}, "Done", "pass"),
    ("edit", {"a.json": "1"}, {"a.json": "1", "b.json": "2"}, "Done", "wrong"),       # a new build instead
    ("edit", {"a.json": "1"}, {"a.json": "1", "a--tank.json": "2"}, "Pick one", "pass"),  # candidates to choose from
    ("edit", {"a.json": "1"}, {"a.json": "1", "b--tank.json": "2"}, "Done", "wrong"),     # another build's
    ("variant", {"a.json": "1"}, {"a.json": "1", "a--mana.json": "2"}, "Done", "pass"),
    ("answer", {"a.json": "1"}, {"a.json": "1"}, "46,524", "pass"),
    ("answer", {"a.json": "1"}, {"a.json": "1", "b.json": "2"}, "46,524", "wrong"),
])
def test_route(expect, before, after, reply, want):
    case = {"expect": expect, "open": "a.json", "prompt": "x"}
    assert ev.route(case, "x", before, after, reply, [])[0] == want


def test_import_route_needs_the_link_checked():
    case = {"expect": "import", "open": "a.json"}
    seen = [{"command": f"wt verify '{LINK}'", "output": ""}]
    assert ev.route(case, f"look: {LINK}", {"a.json": "1"}, {"a.json": "1"}, "ok", seen)[0] == "pass"
    assert ev.route(case, f"look: {LINK}", {"a.json": "1"}, {"a.json": "1"}, "ok", [])[0] == "wrong"


def test_grade_links_must_be_verified_and_saved(tmp_path):
    (tmp_path / "builds").mkdir()
    (tmp_path / "builds" / "b.json").write_text(json.dumps({"link": LINK}))
    case = {"expect": "create", "open": None, "prompt": "new build"}
    run = {"finished": True, "errors": [], "reply": f"Here: {LINK}",
           "commands": [{"command": "wt gear", "output": f"VERIFIED OK\n{LINK}"}]}
    g = ev.grade(case, "new build", {}, {"b.json": "1"}, tmp_path, run)
    assert g["pass"], g
    run["commands"][0]["output"] = LINK                              # never printed VERIFIED OK
    g = ev.grade(case, "new build", {}, {"b.json": "1"}, tmp_path, run)
    assert g["unverified"] == [LINK] and not g["pass"]
    (tmp_path / "builds" / "b.json").write_text(json.dumps({"link": "other"}))
    run["commands"][0]["output"] = f"VERIFIED OK {LINK}"
    g = ev.grade(case, "new build", {}, {"b.json": "1"}, tmp_path, run)
    assert g["unsaved"] == [LINK] and not g["checks"]["links_saved"]


def test_scratch_copy_runs_this_wt_on_its_own_builds(tmp_path, links):
    """The agent's `wt` is this checkout's, on the copy's builds/; the app shows
    the case's open build, and the hook note names it."""
    case = {"id": "c", "builds": {"storm.json": "shaman_105_stormdrain"}, "open": "storm.json"}
    ws, env = ev.make_workspace(tmp_path, case, links)
    assert (ws / "AGENTS.md").exists() and (ws / ".agents/skills/build/SKILL.md").exists()
    assert "hooks" not in json.loads((ws / ".claude/settings.json").read_text())
    app = ev.App(ws, env, "storm.json")
    try:
        note = ev.hook_note(ws, env)
        out = subprocess.run(["uv", "run", "wt", "current"], cwd=ws, env=env, capture_output=True, text=True)
    finally:
        app.stop()
    assert "builds/storm.json" in note and "open in the build editor" in note
    assert "Stormdrain" in out.stdout
    assert list(ev.snapshot(ws)) == ["storm.json"]


def test_regrade_applies_new_rules_to_a_finished_run(tmp_path):
    reply = "Which level? Up to 121. Say \"use the defaults\"."
    (tmp_path / "new-poison-mage.jsonl").write_text(
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": reply}}))
    checks = {"finished": True, "route": False, "links_verified": True, "links_saved": True,
              "numbers_grounded": False}
    (tmp_path / "summary.json").write_text(json.dumps({
        "agent": "codex", "passed": 0, "total": 1, "checks": dict.fromkeys(checks, 0),
        "cases": [{"id": "new-poison-mage", "pass": False, "checks": checks, "route": "wrong",
                   "why": "didn't create (no matching change)", "ungrounded": ["121"]}]}))
    s = ev.regrade(tmp_path)
    assert s["passed"] == 1 and s["cases"][0]["route"] == "asked" and s["cases"][0]["ungrounded"] == []
