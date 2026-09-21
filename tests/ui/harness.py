"""Run the web app in a background thread for browser tests and screenshots."""
import shutil
import socket
import threading
import time

import uvicorn

from wynntools.web.server import create_app

TOKEN = "ui-test-token"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AppServer:
    """Context manager: serves the app from `builds_dir` on a free localhost port."""

    def __init__(self, builds_dir, seed_from=None, terminal_cwd=None):
        self.builds_dir = builds_dir
        if seed_from:
            for f in seed_from:
                shutil.copy(f, builds_dir)
        self.port = free_port()
        self.app = create_app(builds_dir, self.port, token=TOKEN, terminal_cwd=terminal_cwd)
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
