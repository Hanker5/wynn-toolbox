"""Each AI CLI's project setup: the shared build skill, and the prompt hooks
that tell the agent which build the player has open."""
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
HOOKS = {  # config file -> (hook event, how to find the hook commands)
    ".claude/settings.json": ("UserPromptSubmit", "UserPromptSubmit"),
    ".codex/hooks.json": ("UserPromptSubmit", "UserPromptSubmit"),
    ".gemini/settings.json": ("BeforeAgent", "BeforeAgent"),
}


def test_build_skill_is_the_same_for_every_agent():
    claude = (ROOT / ".claude/skills/build/SKILL.md").read_text()
    agents = (ROOT / ".agents/skills/build/SKILL.md").read_text()
    assert claude == agents, "edit one build skill, then copy it over the other"


@pytest.mark.parametrize("path", sorted(HOOKS))
def test_prompt_hook_asks_wt_for_the_open_build(path):
    f = ROOT / path
    if not f.exists():
        pytest.skip(f"{path} not set up")
    event, key = HOOKS[path]
    commands = [h["command"] for group in json.loads(f.read_text())["hooks"][key]
                for h in group["hooks"]]
    assert f"wt current --hook {event}" in " ".join(commands)


def test_gemini_may_run_wt_without_asking():
    allowed = json.loads((ROOT / ".gemini/settings.json").read_text())["tools"]["allowed"]
    assert "run_shell_command(wt)" in allowed and "run_shell_command(uv run wt)" in allowed


def test_terminal_puts_the_toolbox_wt_first(monkeypatch):
    """So agents can run `wt` without `uv run`, which Codex's sandbox blocks."""
    from wynntools.web import terminal
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/bin"]))
    first = terminal.shell_path().split(os.pathsep)[0]
    assert terminal.toolbox_bin() and first == str(terminal.toolbox_bin())
