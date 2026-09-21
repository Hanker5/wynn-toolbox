import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from wynntools.web.server import COOKIE, create_app

PORT, TOKEN = 8765, "test-token"
GOOD_ORIGIN = f"http://127.0.0.1:{PORT}"
WS_URL = f"ws://127.0.0.1:{PORT}/ws/terminal"      # full URL, so the Host header is right
AUTH = {"cookie": f"{COOKIE}={TOKEN}"}


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


def test_shell_round_trip_and_run_allowlist(app):
    with TestClient(app, base_url=GOOD_ORIGIN) as c:
        with c.websocket_connect(WS_URL, headers={**AUTH, "origin": GOOD_ORIGIN}) as ws:
            ws.receive_bytes()                                   # scrollback replay
            ws.send_json({"type": "run", "cmd": "echo SHOULD-NOT-RUN"})   # not an AI CLI
            ws.send_json({"type": "input", "data": "echo wt-$((40+2))-done\r"})
            out = read_until(ws, "wt-42-done")
            assert "SHOULD-NOT-RUN" not in out


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
