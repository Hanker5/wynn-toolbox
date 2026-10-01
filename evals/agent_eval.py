"""Run player requests through an AI agent and check it kept AGENTS.md's rules.

    uv run python evals/agent_eval.py --agent codex-oss:qwen3:8b [--cases ID,ID] [--timeout S]
    uv run python evals/agent_eval.py --agent claude
    uv run python evals/agent_eval.py --agent codex

Each case (evals/cases.json) runs in its own scratch copy of the toolbox: the
agent instructions, the build skill, the knowledge files, a `wt` that runs this
checkout, and a builds/ folder with the case's builds, shown in a real `wt
serve` as the open build. The agent gets the request with the note the prompt
hook would add, runs without a terminal, and every command it ran is recorded.
Nothing touches this checkout's builds/ (`wt` finds builds/ in the folder it
runs in) or the network (`WYNN_TOOLBOX_OFFLINE`).

Checks, per case (AGENTS.md rule in brackets):
  route    the right first move: a new build stays new, "this build" changes
           that file, a variant leaves it alone [10]. Asking a question instead
           is allowed, unless the case says the request was complete (`finish`).
  links    every WynnBuilder link in the reply printed VERIFIED OK in some `wt`
           output [2], and is the link of a build file it saved [8].
  numbers  every number in the reply (100 and up, or with decimals) appears in
           some command output or in the request [1].
Results go to evals/results/<agent>-<time>/ (transcripts and summary.json).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CASES = Path(__file__).with_name("cases.json")
RESULTS = Path(__file__).with_name("results")
COPY = ["AGENTS.md", "CLAUDE.md", "GEMINI.md", ".agents", "knowledge", "examples", ".claude/skills"]
LINK = re.compile(r"https://wynnbuilder\.github\.io/builder/#[A-Za-z0-9+\-_]+")
NUMBER = re.compile(r"(?<![\w#/.\-])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{3,})(?![\w/])")
NOT_BUILDS = {"inventory.json", "settings.json"}


# ------------------------------------------------------------ the scratch copy
def wt_path():
    exe = REPO / ".venv" / ("Scripts/wt.exe" if os.name == "nt" else "bin/wt")
    if not exe.exists():
        raise SystemExit(f"no {exe}: run `uv sync` first")
    return exe


def make_workspace(root, case, links):
    """A scratch toolbox for one case. Returns (folder, environment)."""
    ws = Path(root) / case["id"]
    for rel in COPY:
        src = REPO / rel
        if src.is_dir():
            shutil.copytree(src, ws / rel)
        elif src.exists():
            (ws / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, ws / rel)
    # The project's permissions, without the prompt hook (the harness adds its note
    # to the request; the hook's `uv run` has no project to run in here).
    settings = json.loads((REPO / ".claude/settings.json").read_text())
    settings.pop("hooks", None)
    (ws / ".claude/settings.json").write_text(json.dumps(settings, indent=1))
    bin_dir = ws / "bin"
    bin_dir.mkdir()
    (bin_dir / "wt").write_text(f'#!/bin/sh\nexec "{wt_path()}" "$@"\n')
    # `uv run wt ...` as AGENTS.md also allows: the same wt.
    (bin_dir / "uv").write_text('#!/bin/sh\nif [ "$1" = run ]; then shift; [ "$1" = --quiet ] && shift; '
                                '[ "$1" = wt ] && shift && exec wt "$@"; fi\n'
                                'echo "uv: only \\"uv run wt\\" works in this copy" >&2; exit 2\n')
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
           "WYNN_TOOLBOX_OFFLINE": "1", "WYNN_TOOLBOX": "1"}
    (ws / "builds").mkdir()
    for file, name in (case.get("builds") or {}).items():
        out = subprocess.run(["wt", "import", links[name]["hash"], f"builds/{file}", "--no-show", "--force"],
                             cwd=ws, env=env, capture_output=True, text=True)
        if out.returncode not in (0, 1) or not (ws / "builds" / file).exists():
            raise RuntimeError(f"couldn't set up {file}: {out.stdout}{out.stderr}")
    return ws, env


class App:
    """`wt serve --no-browser` for the scratch copy, showing the case's open build."""

    def __init__(self, ws, env, open_file):
        self.proc = subprocess.Popen(["wt", "serve", "--no-browser"], cwd=ws, env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        state = ws / "builds" / ".server.json"
        for _ in range(100):
            if state.exists():
                break
            time.sleep(0.2)
        else:
            self.stop()
            raise RuntimeError("wt serve didn't start")
        s = json.loads(state.read_text())
        body = {"view": "editor" if open_file else "solver", "file": open_file, "dirty": False}
        req = urllib.request.Request(f"http://127.0.0.1:{s['port']}/api/view", method="PUT",
                                     data=json.dumps(body).encode(),
                                     headers={"x-wt-token": s["token"], "content-type": "application/json"})
        for _ in range(50):                  # the state file comes before the port opens
            try:
                urllib.request.urlopen(req, timeout=10).read()
                return
            except OSError:
                time.sleep(0.2)
        self.stop()
        raise RuntimeError("wt serve didn't answer")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def hook_note(ws, env):
    """What the prompt hook would tell the agent about the open build."""
    out = subprocess.run(["wt", "current", "--hook", "UserPromptSubmit"], cwd=ws, env=env,
                         capture_output=True, text=True, timeout=60)
    try:
        return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"] or ""
    except (ValueError, KeyError, TypeError):
        return ""


def snapshot(ws):
    """{build file: content hash}, builds only."""
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ws / "builds").glob("*.json") if p.name not in NOT_BUILDS and not p.name.startswith(".")}


# ------------------------------------------------------------ agents
def agent_command(agent, ws, prompt, context=None):
    if agent == "claude":
        # What a player would approve in the app: wt, and spec files in a scratch folder.
        return ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
                "--permission-mode", "acceptEdits", "--add-dir", tempfile.gettempdir(),
                "--allowedTools", "Bash(wt *)", "Bash(uv run wt *)", "Bash(mkdir *)", "Read", "Write", "Edit"]
    if agent == "codex" or agent.startswith("codex-oss:"):
        cmd = ["codex", "exec", "--json", "-s", "workspace-write", "--skip-git-repo-check", "--ephemeral",
               "-C", str(ws), "-c", "shell_environment_policy.inherit=all"]
        if agent.startswith("codex-oss:"):
            cmd += ["--oss", "--local-provider", "ollama", "-m", agent.split(":", 1)[1]]
            if context:
                cmd += ["-c", f"model_context_window={context}"]
        return cmd + [prompt]
    if agent.startswith("wt-agent:"):
        cmd = ["wt", "agent", "--model", agent.split(":", 1)[1], "--json", "-p", prompt]
        return cmd + (["--ctx", str(context)] if context else [])
    raise SystemExit(f"unknown agent {agent!r}: claude, codex, codex-oss:<ollama model> or "
                     f"wt-agent:<ollama model>")


def parse_codex(lines):
    commands, messages, errors = [], [], []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        item = e.get("item") if isinstance(e.get("item"), dict) else {}
        if e.get("type") == "item.completed":
            if item.get("type") == "command_execution":
                commands.append({"command": item.get("command", ""), "output": item.get("aggregated_output", ""),
                                 "exit": item.get("exit_code")})
            elif item.get("type") == "agent_message":
                messages.append(item.get("text", ""))
            elif item.get("type") == "error":
                errors.append(item.get("message", ""))
        elif e.get("type") in ("error", "turn.failed"):
            errors.append(json.dumps(e)[:500])
    return {"commands": commands, "reply": messages[-1] if messages else "", "errors": errors}


def parse_claude(lines):
    uses, outputs, reply, errors = {}, {}, "", []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        msg = e.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if e.get("type") == "assistant" and isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    inp = c.get("input") or {}
                    uses[c["id"]] = inp.get("command") or f"{c.get('name')} {json.dumps(inp)[:200]}"
        elif e.get("type") == "user" and isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    body = c.get("content")
                    if isinstance(body, list):
                        body = "\n".join(x.get("text", "") for x in body if isinstance(x, dict))
                    outputs[c.get("tool_use_id")] = str(body or "")
        elif e.get("type") == "result":
            reply = e.get("result") or ""
            if e.get("is_error"):
                errors.append(reply[:500])
    commands = [{"command": cmd, "output": outputs.get(k, ""), "exit": None} for k, cmd in uses.items()]
    return {"commands": commands, "reply": reply, "errors": errors}


def run_agent(agent, ws, prompt, env, timeout, context=None):
    t0 = time.time()
    try:
        out = subprocess.run(agent_command(agent, ws, prompt, context), cwd=ws, env=env,
                             stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        raw, finished, rc = out.stdout, True, out.returncode
        stderr = out.stderr[-3000:]
    except subprocess.TimeoutExpired as e:
        raw = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        finished, rc, stderr = False, None, f"timed out after {timeout}s"
    parsed = (parse_claude if agent == "claude" else parse_codex)(raw.splitlines())
    return {**parsed, "finished": finished, "returncode": rc, "stderr": stderr,
            "seconds": round(time.time() - t0), "raw": raw}


# ------------------------------------------------------------ grading
def _plain(text):
    return (text or "").replace(",", "")


def ungrounded_numbers(reply, sources):
    """Numbers in the reply (100 and up, or with decimals) found in no source text.
    Links and `code` are left out: file names and commands aren't build numbers."""
    text = LINK.sub(" ", reply or "")
    text = re.sub(r"`[^`]*`", " ", text)
    haystack = _plain("\n".join(sources))
    out = []
    for m in NUMBER.finditer(text):
        n = _plain(m.group(1))
        if (float(n) >= 100 or "." in n) and n not in haystack and n not in out:
            out.append(n)
    return out


ASKS = re.compile(r"\?|\b(tell me|let me know|which (one|do you|would you|you want)|pick one|choose one|"
                  r"say which|your call)\b", re.I)


def asks(reply):
    """Whether a reply asks the player something (a question, or "tell me which")."""
    return bool(ASKS.search(reply or ""))


def route(case, request, before, after, reply, commands):
    """("pass" | "asked" | "wrong", why)."""
    open_file = case.get("open")
    changed_open = bool(open_file) and before.get(open_file) != after.get(open_file)
    new = sorted(set(after) - set(before))
    new_top = [f for f in new if "--" not in f]
    expect = case["expect"]
    if expect in ("create", "variant", "import", "answer") and changed_open:
        return "wrong", f"changed the open build {open_file}"
    if expect == "answer" and new:
        return "wrong", f"made {', '.join(new)} for a question"
    if expect == "edit" and new_top and not changed_open:
        return "wrong", f"made {', '.join(new_top)} instead of changing {open_file}"
    given = [x.split("#")[1] for x in LINK.findall(request)]
    # Candidates of the open build (x--y.json) are how the app proposes changes to it
    # (Improve/Fix, trade-offs): an edit the player then chooses from.
    proposed = bool(open_file) and any(f.startswith(Path(open_file).stem + "--") for f in new)
    done = {"create": bool(new_top), "edit": changed_open or proposed, "variant": bool(new), "answer": True,
            "import": any(h in c["command"] for c in commands for h in given)}[expect]
    if done:
        return "pass", ""
    if asks(reply):                        # nothing changed, and it asked the player something
        return "asked", "asked a question instead"
    return "wrong", f"didn't {expect} (no matching change)"


def instructions(ws):
    """The agent's instruction and knowledge files: facts from these (the level cap,
    a preset's example minimums) aren't numbers the agent made up."""
    out = []
    for rel in ("AGENTS.md", ".agents/skills/build/SKILL.md", "knowledge/goals.md", "knowledge/mechanics.md"):
        try:
            out.append((Path(ws) / rel).read_text(encoding="utf-8"))
        except OSError:
            pass
    return out


def grade(case, prompt, before, after, ws, run):
    outputs = [c["output"] for c in run["commands"]]
    verified = [o for o in outputs if "VERIFIED OK" in o]
    saved = set()
    for name in after:
        try:
            saved.add(json.loads((ws / "builds" / name).read_text())["link"].split("#")[1])
        except (OSError, ValueError, KeyError, IndexError):
            pass
    links = LINK.findall(run["reply"])
    unverified = [x for x in links if not any(x.split("#")[1] in o for o in verified)]
    unsaved = [x for x in links if x.split("#")[1] not in saved]
    numbers = ungrounded_numbers(run["reply"], outputs + [prompt] + instructions(ws))
    how, why = route(case, prompt, before, after, run["reply"], run["commands"])
    checks = {
        "finished": run["finished"] and not run["errors"] and bool(run["reply"].strip()),
        "route": how == "pass" or (how == "asked" and not case.get("finish")),
        "links_verified": not unverified,
        "links_saved": not unsaved,
        "numbers_grounded": not numbers,
    }
    return {"pass": all(checks.values()), "checks": checks, "route": how, "why": why,
            "unverified": unverified, "unsaved": unsaved, "ungrounded": numbers,
            "new_files": sorted(set(after) - set(before)),
            "wt_commands": [c["command"] for c in run["commands"]]}


# ------------------------------------------------------------ running
def expand(prompt, links):
    return re.sub(r"\{link:(\w+)\}", lambda m: "https://wynnbuilder.github.io/builder/#" + links[m.group(1)]["hash"],
                  prompt)


def regrade(out_dir):
    """Grade a finished run again from its transcripts, after the checks changed:
    the question rule and the number check. (The link checks need the scratch
    copy's build files, gone after the run: they stay as they were.)"""
    out_dir = Path(out_dir)
    summary = json.loads((out_dir / "summary.json").read_text())
    links = {k: v for k, v in json.loads((REPO / "tests/fixtures/links.json").read_text()).items()
             if not k.startswith("_")}
    cases = {c["id"]: c for c in json.loads(CASES.read_text())["cases"]}
    parse = parse_claude if summary["agent"] == "claude" else parse_codex
    for r in summary["cases"]:
        case = cases[r["id"]]
        run = parse((out_dir / f"{r['id']}.jsonl").read_text().splitlines())
        request = expand(case["prompt"], links)
        r["ungrounded"] = ungrounded_numbers(run["reply"], [c["output"] for c in run["commands"]]
                                             + [request] + instructions(REPO))
        r["checks"]["numbers_grounded"] = not r["ungrounded"]
        if r["route"] == "wrong" and r["why"].startswith("didn't"):   # nothing forbidden changed
            before = {f: "" for f in case.get("builds") or {}}
            after = {**before, **{f: "new" for f in r.get("new_files") or []}}
            r["route"], r["why"] = route(case, request, before, after, run["reply"], run["commands"])
        r["checks"]["route"] = r["route"] == "pass" or (r["route"] == "asked" and not case.get("finish"))
        r["pass"] = all(r["checks"].values())
    summary["passed"] = sum(r["pass"] for r in summary["cases"])
    summary["checks"] = {k: sum(r["checks"][k] for r in summary["cases"]) for k in summary["checks"]}
    summary["regraded"] = time.strftime("%Y%m%d-%H%M%S")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def write_summary(out_dir, a, stamp, results):
    summary = {"agent": a.agent, "context": a.context, "when": stamp, "cases": results,
               "passed": sum(r["pass"] for r in results), "total": len(results),
               "checks": {k: sum(r["checks"][k] for r in results) for k in (results[0]["checks"] if results else {})}}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--regrade", metavar="RESULTS_DIR", help="grade a finished run again, then exit")
    p.add_argument("--agent",
                   help="claude, codex, codex-oss:<ollama model> or wt-agent:<ollama model>")
    p.add_argument("--cases", help="comma-separated case ids (default: all)")
    p.add_argument("--timeout", type=int, default=1200, help="seconds per case")
    p.add_argument("--context", type=int, help="local models: the context window, in tokens")
    p.add_argument("--keep", action="store_true", help="keep the scratch copies")
    a = p.parse_args(argv)
    if a.regrade:
        s = regrade(a.regrade)
        print(f"{s['agent']}: {s['passed']}/{len(s['cases'])} cases passed (regraded)")
        for k, v in s["checks"].items():
            print(f"  {k:<17}{v}/{len(s['cases'])}")
        return 0
    if not a.agent:
        p.error("--agent is required")
    links = {k: v for k, v in json.loads((REPO / "tests/fixtures/links.json").read_text()).items()
             if not k.startswith("_")}
    cases = json.loads(CASES.read_text())["cases"]
    if a.cases:
        want = a.cases.split(",")
        cases = [c for c in cases if c["id"] in want]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = RESULTS / f"{re.sub(r'[^A-Za-z0-9.-]+', '_', a.agent)}-{stamp}"
    out_dir.mkdir(parents=True)
    root = Path(tempfile.mkdtemp(prefix="wt-eval-"))
    results = []
    try:
        for case in cases:
            ws, env = make_workspace(root, case, links)
            app = App(ws, env, case.get("open"))
            try:
                note = hook_note(ws, env)
                request = expand(case["prompt"], links)
                prompt = f"{note}\n\n{request}" if note else request
                before = snapshot(ws)
                print(f"{case['id']}: running ...", flush=True)
                run = run_agent(a.agent, ws, prompt, env, a.timeout, a.context)
                after = snapshot(ws)
            finally:
                app.stop()
            g = grade(case, request, before, after, ws, run)
            (out_dir / f"{case['id']}.jsonl").write_text(run["raw"])
            results.append({"id": case["id"], "seconds": run["seconds"], **g, "reply": run["reply"],
                            "errors": run["errors"], "stderr": run["stderr"]})
            write_summary(out_dir, a, stamp, results)        # after every case: a stopped run keeps its results
            mark = "PASS" if g["pass"] else "FAIL"
            failed = [k for k, v in g["checks"].items() if not v]
            print(f"  {mark} in {run['seconds']}s" + (f": {', '.join(failed)}" if failed else "")
                  + (f" ({g['why']})" if g["why"] else ""), flush=True)
    finally:
        if not a.keep:
            shutil.rmtree(root, ignore_errors=True)
    summary = write_summary(out_dir, a, stamp, results)
    print(f"\n{a.agent}: {summary['passed']}/{summary['total']} cases passed")
    for k, v in summary["checks"].items():
        print(f"  {k:<17}{v}/{summary['total']}")
    print(f"details: {out_dir}" + (f" (scratch copies kept in {root})" if a.keep else ""))
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
