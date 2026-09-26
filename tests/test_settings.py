import json
import threading

import pytest
from fastapi.testclient import TestClient

from wynntools import settings
from wynntools.cli import main
from wynntools.web import server
from wynntools.web.server import STATE_FILE, create_app, free_port, running_instance

PORT, TOKEN = 8765, "test-token"


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path, PORT, token=TOKEN)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", headers={"x-wt-token": TOKEN})


DEFAULTS = {"ai": None, "check_updates": True, "ignored_update": None, "window": None,
            "sidebar": None}


def test_defaults_and_round_trip(tmp_path):
    f = tmp_path / "settings.json"
    assert settings.load(f) == DEFAULTS                  # no file: wizard not run yet
    assert settings.save({"ai": "codex"}, f) == {**DEFAULTS, "ai": "codex"}
    assert settings.load(f) == {**DEFAULTS, "ai": "codex"}
    assert settings.save({"ai": None}, f) == DEFAULTS


def test_update_and_window_settings(tmp_path):
    f = tmp_path / "settings.json"
    sha = "a" * 40
    geo = {"width": 1200, "height": 800, "x": None, "y": 40, "maximized": False}
    out = settings.save({"check_updates": False, "ignored_update": sha, "window": geo}, f)
    assert out == {**DEFAULTS, "check_updates": False, "ignored_update": sha, "window": geo}
    assert settings.load(f) == out
    for bad in ({"check_updates": "yes"}, {"ignored_update": "; rm -rf ~"},
                {"window": {"width": "big"}}, {"window": {"width": True}},
                {"window": {"colour": 1}}, {"window": [1, 2]}):
        with pytest.raises(ValueError):
            settings.save(bad, f)
    # A hand-edited bad value falls back to the default instead of breaking the app.
    f.write_text(json.dumps({"ai": "codex", "window": "huge", "check_updates": 0}))
    assert settings.load(f) == {**DEFAULTS, "ai": "codex"}


def test_sidebar_setting(tmp_path):
    f = tmp_path / "settings.json"
    layout = {"items": ["a.json", {"group": "Mage", "collapsed": True, "builds": ["b.json"]}]}
    assert settings.save({"sidebar": layout}, f)["sidebar"] == layout
    assert settings.save({"ai": "codex"}, f)["sidebar"] == layout      # other keys leave it alone
    for bad in ({"items": "a.json"}, ["a.json"], {"items": ["a.json", "a.json"]},
                {"items": ["../a.json"]}, {"items": ["notes.txt"]},
                {"items": [{"group": "", "collapsed": False, "builds": []}]},
                {"items": [{"group": "x.json", "collapsed": False, "builds": []}]},
                {"items": [{"group": "G", "collapsed": False, "builds": []},
                           {"group": "G", "collapsed": False, "builds": []}]},
                {"items": [{"group": "G", "collapsed": "no", "builds": []}]},
                {"items": ["a.json", {"group": "G", "collapsed": False, "builds": ["a.json"]}]}):
        with pytest.raises(ValueError):
            settings.save({"sidebar": bad}, f)
    f.write_text(json.dumps({"sidebar": {"items": [1]}}))               # hand-edited nonsense
    assert settings.load(f)["sidebar"] is None


def test_bad_values_rejected_and_bad_files_ignored(tmp_path):
    f = tmp_path / "settings.json"
    with pytest.raises(ValueError):
        settings.save({"ai": "rm -rf ~"}, f)
    with pytest.raises(ValueError):
        settings.save({"colour": "blue"}, f)
    f.write_text('{"ai": "not-a-cli", "other": 1}')     # hand-edited nonsense
    assert settings.load(f) == DEFAULTS
    f.write_text("not json")
    assert settings.load(f) == DEFAULTS


def test_settings_api(client, tmp_path):
    assert client.get("/api/settings").json() == DEFAULTS
    assert client.put("/api/settings", json={"ai": "gemini"}).json() == {**DEFAULTS, "ai": "gemini"}
    assert json.loads((tmp_path / "settings.json").read_text()) == {**DEFAULTS, "ai": "gemini"}
    assert client.put("/api/settings", json={"ai": "bash"}).status_code == 422
    assert client.put("/api/settings", json=["ai"]).status_code == 422
    assert client.get("/api/settings").json() == {**DEFAULTS, "ai": "gemini"}


def test_settings_and_state_files_are_not_builds(client, tmp_path):
    client.put("/api/settings", json={"ai": "shell"})
    (tmp_path / STATE_FILE).write_text("{}")
    assert client.get("/api/builds").json() == []
    assert client.put("/api/builds/settings.json", json={}).status_code == 400
    assert client.get("/api/builds/settings.json").status_code == 400


def test_wt_config(tmp_path, capsys):
    f = str(tmp_path / "s.json")
    with pytest.raises(SystemExit) as e:
        main(["config", "ai", "claude", "--file", f])
    assert e.value.code == 0 and settings.load(f)["ai"] == "claude"
    with pytest.raises(SystemExit) as e:
        main(["config", "ai", "nope", "--file", f])
    assert e.value.code != 0 and settings.load(f)["ai"] == "claude"
    with pytest.raises(SystemExit):
        main(["config", "ai", "none", "--file", f])
    assert settings.load(f)["ai"] is None
    with pytest.raises(SystemExit) as e:
        main(["config", "check_updates", "off", "--file", f])
    assert e.value.code == 0 and settings.load(f)["check_updates"] is False
    with pytest.raises(SystemExit) as e:
        main(["config", "check_updates", "maybe", "--file", f])
    assert e.value.code != 0 and settings.load(f)["check_updates"] is False
    with pytest.raises(SystemExit) as e:
        main(["config", "window", "x", "--file", f])       # not changeable from here
    assert e.value.code != 0


def test_second_launch_finds_the_running_server(tmp_path):
    """Double-clicking the shortcut reopens the running app instead of failing on the port."""
    import uvicorn
    assert running_instance(tmp_path) is None
    port = free_port(20000 + (hash(str(tmp_path)) % 20000))
    app = create_app(tmp_path, port, token=TOKEN)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    try:
        import time
        for _ in range(100):
            if srv.started:
                break
            time.sleep(0.05)
        (tmp_path / STATE_FILE).write_text(json.dumps({"port": port, "token": TOKEN}))
        assert running_instance(tmp_path) == f"http://127.0.0.1:{port}/?token={TOKEN}"
        (tmp_path / STATE_FILE).write_text(json.dumps({"port": port, "token": "stale"}))
        assert running_instance(tmp_path) is None            # a different run's token
        assert free_port(port) != port                        # busy port is skipped
    finally:
        srv.should_exit = True
        t.join(5)
    (tmp_path / STATE_FILE).write_text(json.dumps({"port": port, "token": TOKEN}))
    assert running_instance(tmp_path) is None                # server gone: stale file ignored


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="TIME_WAIT reuse is POSIX")
def test_quick_restart_keeps_its_port():
    """Found by restarting the app by hand: the old port was still in TIME_WAIT,
    so the new run moved to the next port (and lost the page's saved layout)."""
    import socket
    port = free_port(21000)
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port)); srv.listen()
    cli = socket.create_connection(("127.0.0.1", port))
    conn, _ = srv.accept()
    conn.close(); srv.close()                      # server closes first -> TIME_WAIT
    cli.close()
    assert free_port(port) == port
