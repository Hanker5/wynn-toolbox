"""A small agent for a model running on this computer (Ollama): `wt agent`.

General coding agents bring tens of thousands of tokens of their own
instructions, which leaves a small local model almost no room for a build
search's output. This one gives the model AGENTS.md and the build skill, and two
tools: run a `wt` command (in the toolbox folder, nothing else), and read a
text file inside it. Before each request it adds the note the prompt hooks add
(which build the player has open).

    wt agent [--model qwen3:8b]            talk to it in the terminal
    wt agent -p "REQUEST" [--json]         one request, then exit (--json: events
                                           as JSON lines, the shape `codex exec
                                           --json` prints; evals/agent_eval.py)

Not offered in the app yet: docs/PLAN.md item 4 measures local models first.
"""
import json
import os
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path

DEFAULT_MODEL = "qwen3:8b"
DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
MAX_OUTPUT = 12000            # characters of a command's output the model sees (head and tail)
MAX_STEPS = 30                # tool calls per request
REFUSED = {"serve", "update", "mod", "config", "agent"}   # the app's business, not the agent's

NOTES = """
# Running here
You run on the player's own computer. Your tools:
- `wt`: run one wt command (for example `wt gear spec.json --tree mage-riftwalker --save builds/x.json`).
  Write spec files with `wt` only where a command takes JSON: put the spec's JSON in a
  file through the `write_spec` tool, then pass that path.
- `read_file`: read a text file in the toolbox folder (builds/, knowledge/, examples/).
- `write_spec`: write a search spec (JSON) to a scratch file and get its path.
Answer from the output of these tools only. Keep answers short and plain.
"""

TOOLS = [
    {"type": "function", "function": {
        "name": "wt", "description": "Run one wt command in the toolbox folder and return its output.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "the whole command, starting with wt"}},
            "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a text file inside the toolbox folder.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "a path relative to the toolbox folder"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_spec", "description": "Write a gear-search spec (JSON) to a scratch file; returns its path.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "a short file name, e.g. stealing-shaman"},
            "spec": {"type": "string", "description": "the spec as JSON text"}},
            "required": ["name", "spec"]}}},
]


def system_prompt(root):
    parts = []
    for rel in ("AGENTS.md", ".agents/skills/build/SKILL.md"):
        p = Path(root) / rel
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
    return "\n\n".join(parts) + "\n" + NOTES


def clip(text, limit=MAX_OUTPUT):
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[... {len(text) - limit} characters left out ...]\n{text[-half:]}"


class Tools:
    def __init__(self, root, env=None, scratch=None):
        self.root = Path(root).resolve()
        self.env = env or os.environ.copy()
        self.scratch = Path(scratch or self.root / ".agent")

    def wt(self, command):
        try:
            args = shlex.split(command)
        except ValueError as e:
            return f"can't read that command: {e}"
        if args[:2] == ["uv", "run"]:
            args = [a for a in args[2:] if a != "--quiet"]
        if not args:
            return "give a wt command, e.g. wt current"
        if args[0] != "wt":                  # "damage builds/x.json": the tool is wt
            args = ["wt", *args]
        if len(args) > 1 and args[1] in REFUSED:
            return f"`wt {args[1]}` is the player's to run, not yours"
        try:
            out = subprocess.run(args, cwd=self.root, env=self.env, capture_output=True, text=True,
                                 timeout=1800, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return "the command ran over 30 minutes and was stopped"
        except OSError as e:
            return f"couldn't run wt: {e}"
        text = (out.stdout + ("\n" + out.stderr if out.stderr.strip() else "")).strip()
        return clip(text + (f"\n(exit code {out.returncode})" if out.returncode else ""))

    def read_file(self, path):
        p = (self.root / path).resolve()
        if self.root not in p.parents and p != self.root:
            return "only files inside the toolbox folder can be read"
        try:
            return clip(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            return f"can't read {path}: {e}"

    def write_spec(self, name, spec):
        try:
            data = json.loads(spec) if isinstance(spec, str) else spec
        except ValueError as e:
            return f"that isn't valid JSON: {e}"
        self.scratch.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in str(name))[:60] or "spec"
        path = self.scratch / f"{safe}.json"
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        return str(path.relative_to(self.root))

    def call(self, name, args):
        if not isinstance(args, dict):
            try:
                args = json.loads(args)
            except (TypeError, ValueError):
                args = {}
        fn = {"wt": lambda: self.wt(args.get("command", "")),
              "read_file": lambda: self.read_file(args.get("path", "")),
              "write_spec": lambda: self.write_spec(args.get("name", "spec"), args.get("spec", "{}"))}.get(name)
        return fn() if fn else f"no tool named {name}"


def chat(host, model, messages, ctx=None, think=None, timeout=1800):
    body = {"model": model, "messages": messages, "tools": TOOLS, "stream": False}
    if ctx:
        body["options"] = {"num_ctx": ctx}
    if think is not None:
        body["think"] = think
    req = urllib.request.Request(f"{host.rstrip('/')}/api/chat", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class Agent:
    def __init__(self, root, model=DEFAULT_MODEL, host=DEFAULT_HOST, ctx=None, think=None, env=None,
                 emit=None):
        self.tools = Tools(root, env)
        self.model, self.host, self.ctx, self.think = model, host, ctx, think
        self.messages = [{"role": "system", "content": system_prompt(root)}]
        self.emit = emit or (lambda event: None)
        self.n = 0

    def _item(self, kind, **fields):
        self.n += 1
        self.emit({"type": "item.completed", "item": {"id": f"item_{self.n}", "type": kind, **fields}})

    def _make_room(self, used):
        """Near the context limit, drop the oldest command outputs (not the instructions)."""
        if not self.ctx or used < self.ctx * 0.8:
            return
        for m in self.messages[1:-4]:
            if m["role"] == "tool" and not m.get("dropped"):
                m["content"], m["dropped"] = "[output left out to save room; run the command again if needed]", True
                return

    def ask(self, text):
        """Answer one request: returns the reply text."""
        self.messages.append({"role": "user", "content": text})
        for _ in range(MAX_STEPS):
            r = chat(self.host, self.model, [{k: v for k, v in m.items() if k != "dropped"}
                                              for m in self.messages], self.ctx, self.think)
            msg = r.get("message") or {}
            self._make_room((r.get("prompt_eval_count") or 0) + (r.get("eval_count") or 0))
            calls = msg.get("tool_calls") or []
            self.messages.append({"role": "assistant", "content": msg.get("content") or "",
                                  **({"tool_calls": calls} if calls else {})})
            if not calls:
                reply = (msg.get("content") or "").strip()
                self._item("agent_message", text=reply)
                return reply
            for c in calls:
                fn = c.get("function") or {}
                out = self.tools.call(fn.get("name"), fn.get("arguments") or {})
                args = fn.get("arguments") or {}
                shown = args.get("command") if fn.get("name") == "wt" else f"{fn.get('name')} {json.dumps(args)}"
                self._item("command_execution", command=shown, aggregated_output=out, exit_code=None)
                self.messages.append({"role": "tool", "content": out, "tool_name": fn.get("name")})
        reply = f"(stopped after {MAX_STEPS} steps without an answer)"
        self._item("agent_message", text=reply)
        return reply


def hook_note(root, env=None):
    out = subprocess.run(["wt", "current", "--hook", "UserPromptSubmit"], cwd=root, env=env,
                         capture_output=True, text=True, timeout=60)
    try:
        return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"] or ""
    except (ValueError, KeyError, TypeError):
        return ""


def main(a):
    root = Path.cwd()
    if a.json:
        def emit(event):
            print(json.dumps(event), flush=True)
    else:
        def emit(event):
            item = event.get("item") or {}
            if item.get("type") == "command_execution":
                print(f"$ {item['command']}", file=sys.stderr, flush=True)
    agent = Agent(root, a.model, a.host, a.ctx, think=False if a.no_think else None, emit=emit)

    def one(text):
        note = hook_note(root)
        try:
            return agent.ask(f"{note}\n\n{text}" if note else text)
        except OSError as e:
            raise SystemExit(f"can't reach the model at {a.host} ({e}); is Ollama running "
                             f"(`ollama serve`) with {a.model} pulled?")
    if a.prompt is not None:
        reply = one(a.prompt)
        if not a.json:
            print(reply)
        return 0
    print(f"WynnGPT with {a.model} on this computer. Ask for a build; Ctrl+D to quit.")
    while True:
        try:
            text = input("\n> ").strip()
        except EOFError:
            print()
            return 0
        if text:
            print("\n" + one(text))
