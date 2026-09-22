import sys

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from wynntools.web.server import COOKIE, create_app

PORT, TOKEN = 8765, "test-token"
GOOD_ORIGIN = f"http://127.0.0.1:{PORT}"
WS_URL = f"ws://127.0.0.1:{PORT}/ws/terminal"      # full URL, so the Host header is right
AUTH = {"cookie": f"{COOKIE}={TOKEN}"}
# These tests type POSIX shell syntax; test_powershell_round_trip covers Windows.
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="uses sh syntax")


@pytest.fixture()
def app(tmp_path):
    return create_app(tmp_path, PORT, token=TOKEN, terminal_cwd=tmp_path)


def read_until(ws, marker, limit=400):
    out = ""
    for _ in range(limit):
        out += ws.receive_bytes().decode(errors="replace")
        if marker in out:
            return out
    raise AssertionError(f"{marker!r} never appeared; got {out[-300:]!r}")


def test_other_sites_cannot_open_the_shell(app):
    """Cross-site websocket hijacking: right cookie, wrong Origin -> refused."""
    with TestClient(app, base_url=GOOD_ORIGIN) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(WS_URL, headers={**AUTH, "origin": "http://evil.example"}) as ws:
                ws.receive_bytes()


def test_token_required_for_shell(app):
    with TestClient(app, base_url=GOOD_ORIGIN) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(WS_URL, headers={"origin": GOOD_ORIGIN}) as ws:
                ws.receive_bytes()


@posix_only
def test_shell_round_trip_and_run_allowlist(app):
    with TestClient(app, base_url=GOOD_ORIGIN) as c:
        with c.websocket_connect(WS_URL, headers={**AUTH, "origin": GOOD_ORIGIN}) as ws:
            ws.receive_bytes()                                   # scrollback replay
            ws.send_json({"type": "run", "cmd": "echo SHOULD-NOT-RUN"})   # not an AI CLI
            ws.send_json({"type": "input", "data": "echo wt-$((40+2))-done\r"})
            out = read_until(ws, "wt-42-done")
            assert "SHOULD-NOT-RUN" not in out


@posix_only
def test_shell_survives_page_reload(app):
    """Reattaching replays scrollback from the same shell instead of a new one."""
    with TestClient(app, base_url=GOOD_ORIGIN) as c:
        with c.websocket_connect(WS_URL, headers={**AUTH, "origin": GOOD_ORIGIN}) as ws:
            ws.receive_bytes()
            ws.send_json({"type": "input", "data": "export WT_MARK=kept-$((1+1))\r"})
            ws.send_json({"type": "input", "data": "echo marker-$((2+3))\r"})
            read_until(ws, "marker-5")
        pid = app.state.terminal.pid
        with c.websocket_connect(WS_URL, headers={**AUTH, "origin": GOOD_ORIGIN}) as ws:
            assert "marker-5" in ws.receive_bytes().decode(errors="replace")
            ws.send_json({"type": "input", "data": "echo $WT_MARK\r"})
            read_until(ws, "kept-2")
        assert app.state.terminal.pid == pid


@posix_only
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
def test_shell_does_not_inherit_the_apps_files(app):
    """Found by the player: updating closed the app but never installed. The
    shell inherited the app window's connection to the server (Chromium opens
    it without close-on-exec), so the server never finished shutting down and
    the updater waited forever for the app to exit."""
    import os
    r, w = os.pipe()
    os.set_inheritable(w, True)                 # like Chromium's sockets
    try:
        with TestClient(app, base_url=GOOD_ORIGIN) as c:
            with c.websocket_connect(WS_URL, headers={**AUTH, "origin": GOOD_ORIGIN}) as ws:
                ws.receive_bytes()
                ws.send_json({"type": "input", "data": "ls /proc/$$/fd; echo fds-$((1+1))-done\r"})
                out = read_until(ws, "fds-2-done")
                fds = {int(x) for x in os.listdir(f"/proc/{app.state.terminal.pid}/fd")}
        assert w not in fds, out
        assert fds <= {0, 1, 2, 255}                # 255: bash's own copy of the tty
    finally:
        os.close(r); os.close(w)


# ------------------------------------------------------------ chosen AI
@pytest.fixture()
def fake_ai(tmp_path, monkeypatch):
    """A fake 'claude' that prints a marker, first on PATH, plus a harmless installer."""
    import os
    from wynntools.web import terminal
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "wt-fake-ai"
    exe.write_text("#!/bin/sh\necho FAKE-AI-$((6*7))-STARTED\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    fake = {**terminal.AI_CLIS[0], "cmd": "wt-fake-ai",
            "install": {"posix": "echo INSTALL-$((2+2))-RAN", "windows": "echo INSTALL-4-RAN"}}
    monkeypatch.setattr(terminal, "AI_CLIS", [fake, *terminal.AI_CLIS[1:]])
    return fake


def count_in_scrollback(app, marker):
    return bytes(app.state.terminal.scrollback).decode(errors="replace").count(marker)


@posix_only
def test_saved_ai_starts_once_per_shell(app, tmp_path, fake_ai):
    (tmp_path / "settings.json").write_text('{"ai": "claude"}')
    with TestClient(app, base_url=GOOD_ORIGIN) as c:
        with c.websocket_connect(WS_URL, headers={**AUTH, "origin": GOOD_ORIGIN}) as ws:
            read_until(ws, "FAKE-AI-42-STARTED")
            ws.send_json({"type": "start"})                 # the wizard's Start: already running
            ws.send_json({"type": "input", "data": "echo sync-$((1+1))\r"})
            read_until(ws, "sync-2")
        with c.websocket_connect(WS_URL, headers={**AUTH, "origin": GOOD_ORIGIN}) as ws:
            ws.receive_bytes()                                # page reload: reattach only
            ws.send_json({"type": "input", "data": "echo again-$((2+1))\r"})
            read_until(ws, "again-3")
        assert count_in_scrollback(app, "FAKE-AI-42-STARTED") == 1
        with c.websocket_connect(WS_URL, headers={**AUTH, "origin": GOOD_ORIGIN}) as ws:
            ws.receive_bytes()
            ws.send_json({"type": "restart"})                 # fresh shell: starts again
            read_until(ws, "FAKE-AI-42-STARTED")


@posix_only
def test_no_ai_chosen_or_shell_starts_nothing(app, tmp_path, fake_ai):
    for setting in (None, '{"ai": "shell"}'):
        if setting:
            (tmp_path / "settings.json").write_text(setting)
        with TestClient(app, base_url=GOOD_ORIGIN) as c:
            with c.websocket_connect(WS_URL, headers={**AUTH, "origin": GOOD_ORIGIN}) as ws:
                ws.receive_bytes()
                ws.send_json({"type": "input", "data": "echo idle-$((3+3))\r"})
                read_until(ws, "idle-6")
        assert count_in_scrollback(app, "FAKE-AI") == 0
        app.state.terminal.close()


@posix_only
def test_run_and_install_by_key_only(app, fake_ai):
    with TestClient(app, base_url=GOOD_ORIGIN) as c:
        with c.websocket_connect(WS_URL, headers={**AUTH, "origin": GOOD_ORIGIN}) as ws:
            ws.receive_bytes()
            ws.send_json({"type": "install", "cmd": "echo SHOULD-NOT-RUN"})
            ws.send_json({"type": "run", "cmd": "echo SHOULD-NOT-RUN"})
            ws.send_json({"type": "install", "cmd": "claude"})
            read_until(ws, "INSTALL-4-RAN")
            ws.send_json({"type": "run", "cmd": "claude"})
            out = read_until(ws, "FAKE-AI-42-STARTED")
            assert "SHOULD-NOT-RUN" not in out


@posix_only
def test_clis_report_install_state(app, fake_ai):
    with TestClient(app, base_url=GOOD_ORIGIN, headers={"x-wt-token": TOKEN}) as c:
        info = c.get("/api/terminal/clis").json()
    first = info["clis"][0]
    assert first["installed"] and "INSTALL-" in first["install"] and not info["running"]
    assert {"installed", "install", "docs"} <= set(info["node"])


@posix_only
def test_find_cli_looks_in_install_dirs(tmp_path, monkeypatch):
    """A CLI installed to ~/.local/bin after the app started is found even if the
    server's PATH doesn't include it."""
    from wynntools.web import terminal
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert terminal.find_cli("wt-late-cli") is None
    (tmp_path / ".local" / "bin").mkdir(parents=True)
    exe = tmp_path / ".local" / "bin" / "wt-late-cli"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    assert terminal.find_cli("wt-late-cli") == str(exe)
    assert str(tmp_path / ".local" / "bin") in terminal.shell_path()


def test_codex_keeps_its_conversation_in_terminal_scrollback(monkeypatch):
    """Only Codex opts out of its alternate terminal screen for the web PTY."""
    from wynntools.web import terminal
    monkeypatch.setattr(terminal, "find_cli", lambda cmd: f"/mock/bin/{cmd}")
    assert terminal.launch_command("codex") == "codex --no-alt-screen"
    assert terminal.launch_command("claude") == "claude"
    assert terminal.launch_command("gemini") == "gemini"


def test_codex_installs_via_npm_on_windows_only(monkeypatch):
    """Regression: OpenAI's own install.ps1 can crash on Windows PowerShell 5.1 with
    "The property 'OSArchitecture' cannot be found on this object" (openai/codex#20782).
    Windows installs Codex through npm instead, which needs Node; POSIX's installer is
    self-contained and unaffected, so it shouldn't need Node."""
    from wynntools.web import terminal
    monkeypatch.setattr(terminal, "WINDOWS", True)
    info = terminal.available_clis()
    codex = next(c for c in info["clis"] if c["key"] == "codex")
    assert codex["install"] == "npm install -g @openai/codex" and codex["needs_node"] is True

    monkeypatch.setattr(terminal, "WINDOWS", False)
    info = terminal.available_clis()
    codex = next(c for c in info["clis"] if c["key"] == "codex")
    assert "install.sh" in codex["install"] and codex["needs_node"] is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ConPTY backend")
def test_powershell_round_trip(app):
    with TestClient(app, base_url=GOOD_ORIGIN) as c:
        with c.websocket_connect(WS_URL, headers={**AUTH, "origin": GOOD_ORIGIN}) as ws:
            ws.receive_bytes()
            ws.send_json({"type": "input", "data": "Write-Output ('wt-' + (40+2) + '-done')\r"})
            read_until(ws, "wt-42-done")
            ws.send_json({"type": "resize", "cols": 120, "rows": 40})
            ws.send_json({"type": "restart"})
            ws.send_json({"type": "input", "data": "Write-Output ('again-' + (1+2))\r"})
            read_until(ws, "again-3")
