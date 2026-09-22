"""How `wt` on the command line talks to a running `wt serve`: small files in builds/.

Files, not HTTP, because AI sandboxes block network access, localhost
included (Codex's default sandbox refuses the connection), while writing
inside the project is allowed:

    .server.json   the running server (port, token, pid); touched every few
                   seconds while it runs, removed when it stops
    .view.json     what the page shows: {view, file, dirty, doc, at}
    .show.json     a request to open a build: {file, seq, at}
    .progress/     one file per long-running `wt` command, while it runs:
                   {label, command, fraction, detail, started, at}

Only the standard library is used, so the per-prompt hooks stay fast.
"""
import contextlib
import json
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
SHOW_TTL = 15          # seconds; an older request (no page open at the time) is ignored
HEARTBEAT = 5          # seconds between the server's touches of .server.json
STALE = 20             # seconds without a touch: the server is gone (crashed or killed)
PROGRESS_DELAY = 1.0   # seconds a command runs before the page shows it
PROGRESS_BEAT = 2.0    # seconds between rewrites of a command's progress file
PROGRESS_STALE = 10    # seconds without a rewrite: that command is gone (killed)


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
    for p in (Path(builds_dir) / PROGRESS_DIR).glob("*.json"):
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

    def __init__(self, builds_dir, label, command="", delay=PROGRESS_DELAY, beat=PROGRESS_BEAT):
        self.path = Path(builds_dir) / PROGRESS_DIR / f"{os.getpid()}.json"
        self.on = running(builds_dir)
        self.delay, self.beat = delay, beat
        self.state = {"label": label, "command": command, "fraction": None, "detail": None,
                      "started": time.time(), "at": None}
        self.dirty = False
        self.stop = threading.Event()
        self.thread = None

    def update(self, fraction=None, detail=None):
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
        return False


def running_tools(builds_dir, stale=PROGRESS_STALE):
    """The `wt` commands running now, oldest first. Removes files of commands
    that stopped writing (killed before they could clean up)."""
    out, now = [], time.time()
    for p in (Path(builds_dir) / PROGRESS_DIR).glob("*.json"):
        d = read_json(p)
        if not isinstance(d, dict) or now - (d.get("at") or 0) > stale:
            with contextlib.suppress(OSError):
                p.unlink(missing_ok=True)
            continue
        out.append({"id": p.stem, "label": str(d.get("label") or "wt"),
                    "command": str(d.get("command") or ""), "fraction": d.get("fraction"),
                    "detail": d.get("detail"),
                    "elapsed": round(now - (d.get("started") or now), 1)})
    return sorted(out, key=lambda x: -x["elapsed"])
