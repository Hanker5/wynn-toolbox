"""Run the web app in a background thread for browser tests and screenshots."""
import json
import shutil
import socket
import threading
import time
from pathlib import Path

import uvicorn

from wynntools.web.server import create_app

TOKEN = "ui-test-token"
LATEST = "c0ffee" + "0" * 34


def up_to_date(*_a, **_k):
    """The update check without GitHub: nothing new."""
    return {"available": False, "kind": "install", "can_update": True, "current": LATEST,
            "latest": LATEST, "ahead_by": 0, "commits": [], "repo": "x/y", "branch": "main",
            "checked_at": 0, "error": None}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AppServer:
    """Context manager: serves the app from `builds_dir` on a free localhost port."""

    def __init__(self, builds_dir, seed_from=None, terminal_cwd=None, ai="shell",
                 update_check=up_to_date):
        """`ai` is the saved AI choice; the default ("shell") skips the setup
        wizard, and None leaves settings.json out so the wizard opens.
        `update_check` answers the update checker (default: up to date)."""
        self.builds_dir = builds_dir
        if seed_from:
            for f in seed_from:
                shutil.copy(f, builds_dir)
        if ai is not None:
            settings_file = Path(builds_dir) / "settings.json"
            if not settings_file.exists():
                settings_file.write_text(json.dumps({"ai": ai}))
        self.port = free_port()
        self.app = create_app(builds_dir, self.port, token=TOKEN, terminal_cwd=terminal_cwd,
                              update_check=update_check)
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port,
                                                    log_level="warning", ws="websockets"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/?token={TOKEN}"

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 20
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("web app did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10)
