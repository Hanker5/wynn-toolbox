"""A persistent shell on a pseudo-terminal, shared with the web page.

One session lives for the whole server run, so reloading the page (or closing
the panel) does not kill an AI CLI the player has logged into. Output is kept in
a scrollback buffer and replayed when the page reattaches.
"""
import asyncio
import fcntl
import os
import pty
import shutil
import signal
import struct
import termios
import time

SCROLLBACK = 256 * 1024

# Only "Is it installed?" is checked; install steps live on each project's page.
AI_CLIS = [
    {"cmd": "claude", "label": "Claude Code", "docs": "https://github.com/anthropics/claude-code"},
    {"cmd": "codex", "label": "Codex", "docs": "https://github.com/openai/codex"},
    {"cmd": "gemini", "label": "Gemini CLI", "docs": "https://github.com/google-gemini/gemini-cli"},
]


def available_clis():
    return [{**c, "installed": shutil.which(c["cmd"]) is not None} for c in AI_CLIS]


class TerminalSession:
    def __init__(self, cwd):
        self.cwd = str(cwd)
        self.pid = self.fd = None
        self.scrollback = bytearray()
        self.listener = None          # asyncio.Queue of the attached page, if any
        self.started = self.last_output = 0.0

    # ---------------------------------------------------------------- lifecycle
    def alive(self):
        if self.pid is None:
            return False
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            return False
        return pid == 0

    def spawn(self):
        shell = os.environ.get("SHELL") or "/bin/bash"
        pid, fd = pty.fork()
        if pid == 0:                                  # child: becomes the shell
            os.chdir(self.cwd)
            env = {**os.environ, "TERM": "xterm-256color", "WYNN_TOOLBOX": "1"}
            os.execvpe(shell, [shell], env)
        self.pid, self.fd = pid, fd
        os.set_blocking(fd, False)
        self.started = self.last_output = time.time()
        self.scrollback.clear()
        asyncio.get_running_loop().add_reader(fd, self._on_output)

    def ensure(self):
        if not self.alive():
            self.close()
            self.spawn()

    def close(self):
        if self.fd is not None:
            try:
                asyncio.get_running_loop().remove_reader(self.fd)
            except RuntimeError:
                pass
            os.close(self.fd)
            self.fd = None
        if self.pid is not None:
            for sig in (signal.SIGHUP, signal.SIGKILL):
                try:
                    os.killpg(self.pid, sig)
                except ProcessLookupError:
                    break
            try:
                os.waitpid(self.pid, 0)
            except ChildProcessError:
                pass
            self.pid = None

    # ---------------------------------------------------------------- io
    def _on_output(self):
        try:
            data = os.read(self.fd, 65536)
        except OSError:
            data = b""
        if not data:                                  # shell exited
            asyncio.get_running_loop().remove_reader(self.fd)
            data = b"\r\n\x1b[2m[shell exited; press any key for a new one]\x1b[0m\r\n"
        self.last_output = time.time()
        self.scrollback += data
        del self.scrollback[:-SCROLLBACK]
        if self.listener is not None:
            self.listener.put_nowait(data)

    def write(self, text):
        self.ensure()
        os.write(self.fd, text.encode())

    def resize(self, cols, rows):
        if self.fd is not None:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    async def run(self, command):
        """Type a command once the shell has finished starting up.

        Text typed into a brand-new shell can be discarded by startup programs
        that reset the terminal (Bazzite's MOTD banner did exactly this), so wait
        until the shell has been running a moment and has gone quiet.
        """
        self.ensure()
        deadline = time.time() + 6
        while time.time() < deadline:
            now = time.time()
            if now - self.started > 0.8 and now - self.last_output > 0.3:
                break
            await asyncio.sleep(0.05)
        self.write(command + "\r")

    def attach(self):
        """Attach a page; any previously attached page stops receiving output."""
        self.listener = asyncio.Queue()
        return self.listener

    def detach(self, queue):
        if self.listener is queue:
            self.listener = None
