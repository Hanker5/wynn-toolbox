"""Talk to a running `wt serve` from the command line.

The server writes its port and token to builds/.server.json (readable only by
this user), so `wt current` and `wt show` can reach it without the player
copying anything. Only the standard library is used: these commands must stay
fast, and must work when the app isn't running (they just say so).
"""
import json
import urllib.error
import urllib.request
from pathlib import Path

STATE_FILE = ".server.json"


class NotRunning(Exception):
    pass


def call(builds_dir, method, path, body=None, timeout=3):
    """JSON from the running app. Raises NotRunning if there is none, and
    ValueError with the server's message on an HTTP error."""
    try:
        state = json.loads((Path(builds_dir) / STATE_FILE).read_text())
        port, token = int(state["port"]), str(state["token"])
    except (OSError, ValueError, KeyError, TypeError):
        raise NotRunning()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"x-wt-token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise ValueError(detail or f"HTTP {e.code}")
    except (OSError, ValueError):                 # refused, timed out, stale state file
        raise NotRunning()
