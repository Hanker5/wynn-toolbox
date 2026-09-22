"""How `wt` on the command line talks to a running `wt serve`: small files in builds/.

Files, not HTTP, because AI sandboxes block network access, localhost
included (Codex's default sandbox refuses the connection), while writing
inside the project is allowed:

    .server.json   the running server (port, token, pid); touched every few
                   seconds while it runs, removed when it stops
    .view.json     what the page shows: {view, file, dirty, doc, at}
    .show.json     a request to open a build: {file, seq, at}
    .progress/     run-<pid>.json, one per long-running `wt` command while it
                   runs: {label, command, fraction, expect, detail, started, at};
                   history.json, how long each command took the last few times

Only the standard library is used, so the per-prompt hooks stay fast.
"""
import contextlib
import json
import math
import os
import tempfile
import threading
import time
from pathlib import Path

STATE_FILE = ".server.json"
VIEW_FILE = ".view.json"
SHOW_FILE = ".show.json"
FILES = (STATE_FILE, VIEW_FILE, SHOW_FILE)
PROGRESS_DIR = ".progress"
HISTORY_FILE = "history.json"     # inside PROGRESS_DIR; not a run, so never a bar
RUN_GLOB = "run-*.json"
SHOW_TTL = 15          # seconds; an older request (no page open at the time) is ignored
HEARTBEAT = 5          # seconds between the server's touches of .server.json
STALE = 20             # seconds without a touch: the server is gone (crashed or killed)
PROGRESS_DELAY = 1.0   # seconds a command runs before the page shows it
PROGRESS_BEAT = 2.0    # seconds between rewrites of a command's progress file
PROGRESS_STALE = 10    # seconds without a rewrite: that command is gone (killed)
HISTORY_KEEP = 5       # runs remembered per command, to estimate the next one
# What a command takes the first time, before there is any history for it. Only
# commands that can't measure their own progress ever use these.
EXPECT = {"gear": 20, "upgrades": 60, "fetch": 25, "craft": 20}
EXPECT_OTHER = 15


def estimate(elapsed, expect):
    """A fraction for a command that can't measure itself: it rises steadily to
    90% over the time this command usually takes, then creeps towards 99%, so
    the bar keeps moving without ever claiming to be finished."""
    expect = expect if expect and expect > 0 else EXPECT_OTHER
    if elapsed < expect:
        return 0.9 * elapsed / expect
    return 0.9 + 0.09 * (1 - math.exp(-(elapsed - expect) / expect))


def history(builds_dir):
    d = read_json(Path(builds_dir) / PROGRESS_DIR / HISTORY_FILE)
    return d if isinstance(d, dict) else {}


def expected(builds_dir, key):
    """How long `wt <key>` usually takes: the middle of its last few runs."""
    runs = sorted(x for x in history(builds_dir).get(key, []) if isinstance(x, (int, float)))
    return runs[len(runs) // 2] if runs else EXPECT.get(key, EXPECT_OTHER)


def remember(builds_dir, key, seconds):
    """Add one run to the history the next estimate is made from."""
    d = history(builds_dir)
    d[key] = ([x for x in d.get(key, []) if isinstance(x, (int, float))] +
              [round(seconds, 1)])[-HISTORY_KEEP:]
    with contextlib.suppress(OSError):
        path = Path(builds_dir) / PROGRESS_DIR
        path.mkdir(exist_ok=True)
        write_json(path / HISTORY_FILE, d)


def write_json(path, data):
    """Atomic, so a reader never sees half a file."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def running(builds_dir):
    """True if a `wt serve` for this builds folder is running: its state file
    was touched recently. (Not a process-id check: sandboxes such as Codex's
    run in their own process namespace and can't see the server.)"""
    try:
        return time.time() - (Path(builds_dir) / STATE_FILE).stat().st_mtime < STALE
    except OSError:
        return False


def view(builds_dir):
    """What the page last reported, or None if the app isn't running.
    {"at": None} means the app runs but no page has opened it yet."""
    if not running(builds_dir):
        return None
    v = read_json(Path(builds_dir) / VIEW_FILE)
    return v if isinstance(v, dict) else {"view": "empty", "file": None, "dirty": False,
                                           "doc": None, "at": None}


def request_show(builds_dir, file):
    """Ask the open page to open build `file` (a name directly inside builds/)."""
    write_json(Path(builds_dir) / SHOW_FILE, {"file": file, "seq": time.time_ns(), "at": time.time()})


def cleanup(builds_dir):
    for name in FILES:
        (Path(builds_dir) / name).unlink(missing_ok=True)
    for p in (Path(builds_dir) / PROGRESS_DIR).glob(RUN_GLOB):
        p.unlink(missing_ok=True)


_active = None


def report(fraction=None, detail=None):
    """Progress of the running `wt` command, for the page: `fraction` 0-1 (None:
    unknown) and a short `detail`. Does nothing unless a ToolProgress is open."""
    if _active is not None:
        _active.update(fraction, detail)


class ToolProgress:
    """While open, builds/.progress/<pid>.json tells the app this command runs.

    Written only once the command has run PROGRESS_DELAY seconds (quick commands
    never show), then rewritten every PROGRESS_BEAT seconds so a killed command
    goes stale, and on each report() (at most four times a second). Removed on
    exit. Does nothing when the app isn't running. Never raises.
    """

    def __init__(self, builds_dir, label, command="", key=None, delay=PROGRESS_DELAY,
                 beat=PROGRESS_BEAT):
        self.builds_dir = Path(builds_dir)
        self.path = self.builds_dir / PROGRESS_DIR / f"run-{os.getpid()}.json"
        self.on = running(builds_dir)
        self.key = key or "other"
        self.delay, self.beat = delay, beat
        self.measured = False              # did the command report a real fraction?
        self.state = {"label": label, "command": command, "fraction": None,
                      "expect": expected(builds_dir, self.key), "detail": None,
                      "started": time.time(), "at": None}
        self.dirty = False
        self.stop = threading.Event()
        self.thread = None

    def update(self, fraction=None, detail=None):
        if fraction is not None:
            self.measured = True
        self.state["fraction"] = None if fraction is None else max(0.0, min(1.0, float(fraction)))
        self.state["detail"] = detail
        self.dirty = True

    def _write(self):
        self.state["at"] = time.time()
        self.dirty = False
        try:
            self.path.parent.mkdir(exist_ok=True)
            write_json(self.path, self.state)
        except OSError:
            pass

    def _run(self):
        if self.stop.wait(self.delay):
            return
        self._write()
        while not self.stop.wait(0.25):
            if self.dirty or time.time() - self.state["at"] >= self.beat:
                self._write()

    def __enter__(self):
        global _active
        _active = self
        if self.on:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        return self

    def __exit__(self, *exc):
        global _active
        _active = None
        if self.thread:
            self.stop.set()
            self.thread.join()
            self.path.unlink(missing_ok=True)
        # Only commands that couldn't measure themselves need an estimate, so
        # only their times are worth remembering. Recorded even with the app
        # closed, so the first bar the player sees is already a good guess.
        elapsed = time.time() - self.state["started"]
        if elapsed >= self.delay and not self.measured:
            remember(self.builds_dir, self.key, elapsed)
        return False


def running_tools(builds_dir, stale=PROGRESS_STALE):
    """The `wt` commands running now, oldest first, each with a fraction to draw:
    the command's own where it can measure itself, an estimate from how long it
    usually takes where it can't. Removes files of commands that stopped writing
    (killed before they could clean up)."""
    out, now = [], time.time()
    for p in (Path(builds_dir) / PROGRESS_DIR).glob(RUN_GLOB):
        d = read_json(p)
        if not isinstance(d, dict) or now - (d.get("at") or 0) > stale:
            with contextlib.suppress(OSError):
                p.unlink(missing_ok=True)
            continue
        elapsed = now - (d.get("started") or now)
        fraction = d.get("fraction")
        out.append({"id": p.stem, "label": str(d.get("label") or "wt"),
                    "command": str(d.get("command") or ""), "detail": d.get("detail"),
                    "fraction": fraction if isinstance(fraction, (int, float))
                    else estimate(elapsed, d.get("expect")),
                    "estimated": not isinstance(fraction, (int, float)),
                    "elapsed": round(elapsed, 1)})
    return sorted(out, key=lambda x: -x["elapsed"])
