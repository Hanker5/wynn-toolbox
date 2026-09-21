"""A persistent shell on a pseudo-terminal, shared with the web page.

One session lives for the whole server run, so reloading the page (or closing
the panel) does not kill an AI CLI the player has logged into. Output is kept in
a scrollback buffer and replayed when the page reattaches.

POSIX uses the standard pty module; Windows uses ConPTY through pywinpty, with
PowerShell as the shell.
"""
import asyncio
import os
import shutil
import sys
import threading
import time
import warnings
from pathlib import Path

SCROLLBACK = 256 * 1024
WINDOWS = sys.platform == "win32"

# The AI assistants the setup wizard offers. Install commands are the vendors'
# own (checked 2026-09 against their docs); the server types them into the
# terminal itself, so the page can only pick one by key, never send a command.
AI_CLIS = [
    {"key": "claude", "cmd": "claude", "label": "Claude Code", "vendor": "Anthropic",
     "account": "Needs a Claude Pro, Max, Team or Console account (the free plan doesn't include it).",
     "login": "The first time it starts, it opens a sign-in page in your browser.",
     "install": {"posix": "curl -fsSL https://claude.ai/install.sh | bash",
                 "windows": "irm https://claude.ai/install.ps1 | iex"},
     "needs_node": False, "docs": "https://code.claude.com/docs/en/setup"},
    {"key": "codex", "cmd": "codex", "label": "Codex", "vendor": "OpenAI",
     "account": "Needs a ChatGPT Plus, Pro, Business, Edu or Enterprise plan, or an OpenAI API key.",
     "login": "The first time it starts, choose \u201cSign in with ChatGPT\u201d.",
     "install": {"posix": "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
                 "windows": "irm https://chatgpt.com/codex/install.ps1 | iex"},
     "needs_node": False, "docs": "https://github.com/openai/codex"},
    {"key": "gemini", "cmd": "gemini", "label": "Gemini CLI", "vendor": "Google",
     "account": "Sign in with a Google account, or use a Gemini API key.",
     "login": "The first time it starts, choose \u201cSign in with Google\u201d.",
     # --prefix keeps it in ~/.local, so no sudo is needed for a system Node.
     "install": {"posix": "npm install -g --prefix ~/.local @google/gemini-cli",
                 "windows": "npm install -g @google/gemini-cli"},
     "needs_node": True, "docs": "https://github.com/google-gemini/gemini-cli"},
]
NODE_DOCS = "https://nodejs.org/en/download"


def _extra_dirs():
    """Where the CLIs above (and Node) install themselves. Appended to PATH so a
    CLI installed after the app started is found without a restart."""
    home = Path.home()
    if WINDOWS:
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        return [home / ".local" / "bin", local / "Programs" / "OpenAI" / "Codex" / "bin",
                roaming / "npm", Path(os.environ.get("ProgramFiles") or r"C:\Program Files") / "nodejs"]
    return [home / ".local" / "bin", home / ".claude" / "local", Path("/opt/homebrew/bin"),
            Path("/home/linuxbrew/.linuxbrew/bin"), Path("/usr/local/bin")]


def shell_path():
    """The PATH the terminal's shell gets: the server's own, then the install dirs."""
    parts = (os.environ.get("PATH") or "").split(os.pathsep)
    parts += [str(d) for d in _extra_dirs() if str(d) not in parts]
    return os.pathsep.join(p for p in parts if p)


def find_cli(cmd):
    return shutil.which(cmd, path=shell_path())


def cli(key):
    return next((c for c in AI_CLIS if c["key"] == key), None)


def launch_command(key):
    """What to type to start CLI `key`, or None if it isn't installed. The bare
    name is enough: the shell's PATH includes the install dirs even if they
    were created after it started."""
    c = cli(key)
    return c["cmd"] if c and find_cli(c["cmd"]) else None


def install_command(key):
    c = cli(key)
    return c and c["install"]["windows" if WINDOWS else "posix"]


def node_install_command():
    if WINDOWS:
        return "winget install OpenJS.NodeJS.LTS"
    if find_cli("brew"):
        return "brew install node"
    return None                                   # distro packages vary; link to the docs


def available_clis():
    return {
        "os": "windows" if WINDOWS else ("macos" if sys.platform == "darwin" else "linux"),
        "clis": [{k: c[k] for k in ("key", "cmd", "label", "vendor", "account", "login",
                                    "needs_node", "docs")}
                 | {"installed": find_cli(c["cmd"]) is not None,
                    "install": install_command(c["key"])}
                 for c in AI_CLIS],
        "node": {"installed": find_cli("npm") is not None, "install": node_install_command(),
                 "docs": NODE_DOCS},
    }


# ---------------------------------------------------------------- backends
class _PosixPty:
    def __init__(self, on_data):
        self.on_data = on_data
        self.pid = self.fd = None

    def start(self, cwd, env):
        import pty
        # Everything the child needs is prepared before forking: the server is
        # multi-threaded, so the child should only chdir and exec (no allocation
        # or locking that another thread might have held at fork time).
        shell = shutil.which(os.environ.get("SHELL") or "bash") or "/bin/sh"
        argv = [shell]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)   # see comment above
            pid, fd = pty.fork()
        if pid == 0:                                  # child: becomes the shell
            try:
                os.chdir(cwd)
                os.execve(shell, argv, env)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        os.set_blocking(fd, False)
        asyncio.get_running_loop().add_reader(fd, self._readable)

    def _readable(self):
        try:
            data = os.read(self.fd, 65536)
        except OSError:
            data = b""
        if not data:
            asyncio.get_running_loop().remove_reader(self.fd)
        self.on_data(data)

    def alive(self):
        if self.pid is None:
            return False
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            return False
        return pid == 0

    def write(self, data):
        os.write(self.fd, data)

    def resize(self, cols, rows):
        import fcntl
        import struct
        import termios
        if self.fd is not None:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def close(self):
        import signal
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


class _WinPty:
    """ConPTY via pywinpty. Its reads block, and the Proactor event loop has no
    add_reader, so a thread reads and hands output to the loop."""

    def __init__(self, on_data):
        self.on_data = on_data
        self.proc = None

    @property
    def pid(self):
        return self.proc.pid if self.proc else None

    def start(self, cwd, env):
        from winpty import PtyProcess
        shell = shutil.which("powershell.exe") or "powershell.exe"
        self.proc = PtyProcess.spawn([shell, "-NoLogo"], cwd=cwd, env=env, dimensions=(30, 100))
        loop = asyncio.get_running_loop()
        proc = self.proc

        def emit(data):                              # on the loop; drop output of a closed shell
            if self.proc is proc:
                self.on_data(data)

        def pump():
            while True:
                try:
                    text = proc.read(65536)          # "" for pywinpty's internal no-op packets
                except (EOFError, OSError):          # pty closed: the shell exited
                    loop.call_soon_threadsafe(emit, b"")
                    return
                if text:
                    loop.call_soon_threadsafe(emit, text.encode("utf-8", "replace"))
        threading.Thread(target=pump, daemon=True).start()

    def alive(self):
        return bool(self.proc and self.proc.isalive())

    def write(self, data):
        self.proc.write(data.decode("utf-8", "replace"))

    def resize(self, cols, rows):
        if self.proc:
            self.proc.setwinsize(rows, cols)

    def close(self):
        if self.proc:
            try:
                self.proc.terminate(force=True)
            except Exception:                      # already gone
                pass
            self.proc = None


# ---------------------------------------------------------------- session
class TerminalSession:
    def __init__(self, cwd):
        self.cwd = str(cwd)
        self.proc = None
        self.scrollback = bytearray()
        self.listener = None          # asyncio.Queue of the attached page, if any
        self.started = self.last_output = 0.0
        self.launched = False         # the chosen AI was started in this shell

    @property
    def pid(self):
        return self.proc.pid if self.proc else None

    # ---------------------------------------------------------------- lifecycle
    def alive(self):
        return bool(self.proc and self.proc.alive())

    def spawn(self):
        env = {**os.environ, "TERM": "xterm-256color", "WYNN_TOOLBOX": "1", "PATH": shell_path()}
        self.proc = (_WinPty if WINDOWS else _PosixPty)(self._on_output)
        self.scrollback.clear()
        self.started = self.last_output = time.time()
        self.launched = False
        self.proc.start(self.cwd, env)

    def ensure(self):
        if not self.alive():
            self.close()
            self.spawn()

    def close(self):
        if self.proc is not None:
            self.proc.close()
            self.proc = None

    # ---------------------------------------------------------------- io
    def _on_output(self, data):
        if not data:                                  # shell exited
            data = b"\r\n\x1b[2m[shell exited; press any key for a new one]\x1b[0m\r\n"
        self.last_output = time.time()
        self.scrollback += data
        del self.scrollback[:-SCROLLBACK]
        if self.listener is not None:
            self.listener.put_nowait(data)

    def write(self, text):
        self.ensure()
        self.proc.write(text.encode())

    def resize(self, cols, rows):
        if self.proc is not None:
            self.proc.resize(cols, rows)

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
