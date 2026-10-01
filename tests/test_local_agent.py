"""`wt agent`: the small agent for a model on this computer. Its tools only run
wt and read inside the toolbox folder; the loop runs tools until the model answers."""
import json

from wynntools import local_agent as la


def test_tools_run_only_wt_and_read_only_inside(tmp_path, monkeypatch):
    t = la.Tools(tmp_path)
    assert "the player's to run" in t.wt("wt serve")
    (tmp_path / "builds").mkdir()
    (tmp_path / "builds" / "a.json").write_text('{"name": "A"}')
    assert t.read_file("builds/a.json") == '{"name": "A"}'
    assert "only files inside" in t.read_file("../../etc/passwd")
    path = t.write_spec("stealing shaman!", '{"class": "Shaman", "level": 105}')
    assert path == ".agent/stealing-shaman-.json"
    assert json.loads((tmp_path / path).read_text())["class"] == "Shaman"
    assert "isn't valid JSON" in t.write_spec("x", "{nope")
    seen = []
    monkeypatch.setattr(la.subprocess, "run", lambda args, **kw: seen.append(args) or
                        type("R", (), {"stdout": "VERIFIED OK", "stderr": "", "returncode": 0})())
    assert t.wt("uv run --quiet wt verify 'x y'") == "VERIFIED OK" and seen == [["wt", "verify", "x y"]]
    t.wt("damage builds/a.json")                       # the tool is wt: the word itself is optional
    t.wt("rm -rf /")                                   # still only ever wt (its usage error)
    assert seen[1:] == [["wt", "damage", "builds/a.json"], ["wt", "rm", "-rf", "/"]]


def test_long_output_keeps_head_and_tail():
    text = "A" * 10000 + "B" * 10000
    out = la.clip(text, 1000)
    assert out.startswith("A" * 500) and out.endswith("B" * 500) and "left out" in out


def test_loop_runs_tools_until_the_model_answers(tmp_path, monkeypatch):
    (tmp_path / "AGENTS.md").write_text("RULES")
    replies = iter([
        {"message": {"content": "", "tool_calls": [{"function": {"name": "read_file",
                                                                 "arguments": {"path": "AGENTS.md"}}}]},
         "prompt_eval_count": 10},
        {"message": {"content": "The rules say RULES."}, "prompt_eval_count": 20},
    ])
    sent = []

    def fake_chat(host, model, messages, ctx=None, think=None, timeout=0):
        sent.append(messages)
        return next(replies)
    monkeypatch.setattr(la, "chat", fake_chat)
    events = []
    agent = la.Agent(tmp_path, emit=events.append)
    assert agent.ask("what are the rules?") == "The rules say RULES."
    assert sent[0][0]["role"] == "system" and "RULES" in sent[0][0]["content"]
    assert sent[1][-1] == {"role": "tool", "content": "RULES", "tool_name": "read_file"}
    kinds = [e["item"]["type"] for e in events]
    assert kinds == ["command_execution", "agent_message"]


def test_old_outputs_make_room_near_the_limit(tmp_path):
    agent = la.Agent(tmp_path, ctx=1000)
    agent.messages += [{"role": "tool", "content": "big"}] + [{"role": "user", "content": "x"}] * 4
    agent._make_room(900)
    assert agent.messages[1]["content"].startswith("[output left out")
