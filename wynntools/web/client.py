"""How `wt` on the command line talks to a running `wt serve`: small files in builds/.

Files, not HTTP, because AI sandboxes block network access, localhost
included (Codex's default sandbox refuses the connection), while writing
inside the project is allowed:

    .server.json   the running server (port, token, pid); touched every few
                   seconds while it runs, removed when it stops
    .view.json     what the page shows: {view, file, dirty, doc, at}
    .show.json     a request to open a build: {file, seq, at}

Only the standard library is used, so the per-prompt hooks stay fast.
"""
import json
import os
import tempfile
import time
from pathlib import Path

STATE_FILE = ".server.json"
VIEW_FILE = ".view.json"
SHOW_FILE = ".show.json"
FILES = (STATE_FILE, VIEW_FILE, SHOW_FILE)
SHOW_TTL = 15          # seconds; an older request (no page open at the time) is ignored
HEARTBEAT = 5          # seconds between the server's touches of .server.json
STALE = 20             # seconds without a touch: the server is gone (crashed or killed)


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
