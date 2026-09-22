"""Update checker: what's installed, what GitHub has, and the updater it starts."""
import io
import json
import subprocess
import urllib.error

import pytest
from fastapi.testclient import TestClient

from wynntools import settings, updates
from wynntools.cli import main
from wynntools.web.server import create_app

OLD, NEW, MID = "1" * 40, "3" * 40, "2" * 40
PORT, TOKEN = 8765, "test-token"


def install(root, commit=OLD, **extra):
    (root / updates.MARKER).write_text(json.dumps(
        {"repo": "someone/wynn-toolbox", "branch": "main", "commit": commit, **extra}))


def gh_commit(sha, msg):
    return {"sha": sha, "commit": {"message": msg + "\n\nbody", "committer": {"date": "2026-09-01T10:00:00Z"}}}


class FakeGitHub:
    """Answers the two API calls the checker makes; records the URLs asked for."""

    def __init__(self, ahead=(), head=NEW, error=None, compare_error=None):
        self.ahead, self.head, self.error, self.compare_error = list(ahead), head, error, compare_error
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error
        if "/compare/" in url:
            if self.compare_error:
                raise self.compare_error
            return {"ahead_by": len(self.ahead), "commits": self.ahead}
        return gh_commit(self.head, "Latest thing")


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


# ------------------------------------------------------------------ install_info
def test_install_info(tmp_path):
    assert updates.install_info(tmp_path)["kind"] == "unknown"
    (tmp_path / updates.MARKER).write_text("")            # installs from before this change
    info = updates.install_info(tmp_path)
    assert info == {"kind": "install", "commit": None, "repo": updates.REPO, "branch": "main"}
    install(tmp_path)
    assert updates.install_info(tmp_path) == {"kind": "install", "commit": OLD,
                                              "repo": "someone/wynn-toolbox", "branch": "main"}
    # Nonsense in the marker never reaches a URL.
    (tmp_path / updates.MARKER).write_text(json.dumps(
        {"repo": "../../evil?x=", "branch": "a b", "commit": "not-a-sha"}))
    assert updates.install_info(tmp_path) == {"kind": "install", "commit": None,
                                              "repo": updates.REPO, "branch": "main"}


def test_install_info_git_clone(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin",
                    "git@github.com:someone/fork.git"], check=True)
    info = updates.install_info(tmp_path)
    assert info["kind"] == "git" and len(info["commit"]) == 40 and info["repo"] == "someone/fork"


# ------------------------------------------------------------------ check
def test_update_available(tmp_path):
    install(tmp_path)
    gh = FakeGitHub(ahead=[gh_commit(MID, "Older fix"), gh_commit(NEW, "Newest feature")])
    r = updates.check(tmp_path, fetch=gh)
    assert r["available"] and r["latest"] == NEW and r["ahead_by"] == 2 and r["error"] is None
    assert [c["message"] for c in r["commits"]] == ["Newest feature", "Older fix"]   # newest first
    assert r["can_update"] and r["current"] == OLD
    assert gh.urls == [f"{updates.API}/repos/someone/wynn-toolbox/compare/{OLD}...main"]


def test_up_to_date(tmp_path):
    install(tmp_path, commit=NEW)
    r = updates.check(tmp_path, fetch=FakeGitHub())
    assert not r["available"] and r["latest"] == NEW and r["ahead_by"] == 0


def test_unknown_version_offers_the_latest(tmp_path):
    (tmp_path / updates.MARKER).write_text("")
    r = updates.check(tmp_path, fetch=FakeGitHub())
    assert r["available"] and r["latest"] == NEW and r["ahead_by"] is None
    assert r["commits"][0]["message"] == "Latest thing"


def test_commit_github_does_not_know(tmp_path):
    """A commit that is gone from the repo (force-push): compare with the head instead."""
    install(tmp_path)
    r = updates.check(tmp_path, fetch=FakeGitHub(compare_error=http_error(404)))
    assert r["available"] and r["latest"] == NEW and r["ahead_by"] is None


@pytest.mark.parametrize("error, says", [
    (urllib.error.URLError("no network"), "offline"),
    (http_error(403), "rate limit"),
    (http_error(500), "500"),
    (ValueError("bad json"), "unexpected"),
])
def test_network_problems_never_raise(tmp_path, error, says):
    install(tmp_path)
    r = updates.check(tmp_path, cache_dir=tmp_path, fetch=FakeGitHub(error=error))
    assert not r["available"] and says in r["error"]
    assert not (tmp_path / updates.CACHE_FILE).exists()        # errors aren't cached


def test_a_bad_sha_from_github_is_refused(tmp_path):
    (tmp_path / updates.MARKER).write_text("")
    r = updates.check(tmp_path, fetch=FakeGitHub(head="main; rm -rf ~"))
    assert not r["available"] and r["latest"] is None and r["error"]


def test_cache(tmp_path):
    install(tmp_path)
    gh = FakeGitHub(ahead=[gh_commit(NEW, "New")])
    t = [1000.0]
    now = lambda: t[0]  # noqa: E731
    first = updates.check(tmp_path, cache_dir=tmp_path, fetch=gh, now=now)
    t[0] += 60
    assert updates.check(tmp_path, cache_dir=tmp_path, fetch=gh, now=now) == first
    assert len(gh.urls) == 1
    updates.check(tmp_path, cache_dir=tmp_path, fetch=gh, now=now, force=True)
    assert len(gh.urls) == 2
    t[0] += updates.CACHE_TTL + 1
    updates.check(tmp_path, cache_dir=tmp_path, fetch=gh, now=now)
    assert len(gh.urls) == 3
    install(tmp_path, commit=NEW)                               # updated: the old answer is void
    assert updates.check(tmp_path, cache_dir=tmp_path, fetch=FakeGitHub(), now=now)["available"] is False


# ------------------------------------------------------------------ installing
def test_update_command_unix(tmp_path):
    install(tmp_path)
    argv, env, kw = updates.update_command(tmp_path, tmp_path / "builds", NEW, 4242, "--browser",
                                           platform="linux")
    assert argv[:2] == ["sh", "-c"] and kw["start_new_session"]
    assert env["WT_PID"] == "4242" and env["WYNN_TOOLBOX_COMMIT"] == NEW
    assert env["WT_INSTALLER"] == f"{updates.RAW}/someone/wynn-toolbox/{NEW}/install/install.sh"
    assert env["WYNN_TOOLBOX_DIR"] == str(tmp_path.resolve())
    assert env["WT_RELAUNCH"] == "1" and env["WT_SERVE_ARGS"] == "--browser"
    # Values travel in the environment, not in the script.
    assert NEW not in argv[2] and "4242" not in argv[2]
    _, env, _ = updates.update_command(tmp_path, tmp_path, NEW, 1, None, platform="linux")
    assert env["WT_RELAUNCH"] == ""


def test_update_command_windows(tmp_path):
    install(tmp_path)
    argv, env, kw = updates.update_command(tmp_path, tmp_path, NEW, 7, "", platform="win32")
    assert argv[0] == "powershell" and kw["creationflags"]
    assert env["WT_INSTALLER"].endswith(f"/{NEW}/install/install.ps1")
    assert env["WT_RELAUNCH"] == "1" and env["WT_SERVE_ARGS"] == ""


def test_update_target_must_be_a_commit(tmp_path):
    install(tmp_path)
    with pytest.raises(ValueError):
        updates.update_command(tmp_path, tmp_path, "main", 1, "")


def test_unix_helper_runs_the_installer_and_records_the_result(tmp_path):
    """Run the real helper script with a fake installer (no network)."""
    installer = tmp_path / "install.sh"
    installer.write_text('echo "installing $WYNN_TOOLBOX_COMMIT into $WYNN_TOOLBOX_DIR"\n')
    install(tmp_path)
    argv, env, _ = updates.update_command(tmp_path, tmp_path, NEW, 0, None, platform="linux")
    env["WT_INSTALLER"] = f"file://{installer}"
    out = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=30)
    assert f"installing {NEW}" in out.stdout
    result = updates.take_result(tmp_path)
    assert result["ok"] is True and result["to"] == NEW and result["at"] > 0
    assert updates.take_result(tmp_path) is None               # reported once


def test_git_clones_are_not_self_updated(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(ValueError, match="git pull"):
        updates.start_update(tmp_path, tmp_path, NEW, popen=lambda *a, **k: None)


# ------------------------------------------------------------------ web API
@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    install(root)
    gh = FakeGitHub(ahead=[gh_commit(NEW, "New")])
    monkeypatch.setattr(updates, "_get_json", gh)
    started = []
    monkeypatch.setattr(updates, "start_update", lambda *a, **k: started.append((a, k)))
    app = create_app(tmp_path / "builds", PORT, token=TOKEN, root=root)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", headers={"x-wt-token": TOKEN})
    return c, app, started, tmp_path / "builds"


def test_update_api(app_client):
    c, app, started, builds = app_client
    r = c.get("/api/update").json()
    assert r["available"] and r["latest"] == NEW and not r["ignored"]
    assert c.post("/api/update/ignore", json={"commit": NEW}).json() == {"ignored": NEW}
    assert c.get("/api/update").json()["ignored"]
    assert settings.load(builds / "settings.json")["ignored_update"] == NEW
    assert c.post("/api/update/ignore", json={"commit": "x; y"}).status_code == 422
    settings.save({"check_updates": False}, builds / "settings.json")
    assert c.get("/api/update").json() == {"available": False, "disabled": True}
    assert c.get("/api/update?force=true").json()["available"]      # "Check for updates" still works


def test_update_install_api(app_client):
    c, app, started, builds = app_client
    stopped = []
    app.state.mode, app.state.shutdown = "window", lambda: stopped.append(1)
    assert c.post("/api/update/install", json={"commit": NEW}).json() == {"started": True, "relaunch": True}
    (args, kw), = started
    assert args[2] == NEW and kw == {"relaunch": ""}
    app.state.mode = "none"                                          # `wt serve --no-browser`
    assert c.post("/api/update/install", json={"commit": NEW}).json()["relaunch"] is False


def test_update_api_needs_the_token(app_client):
    c, *_ = app_client
    assert c.get("/api/update", headers={"x-wt-token": "wrong"}).status_code == 401
    assert c.post("/api/update/install", json={"commit": NEW},
                  headers={"x-wt-token": "wrong"}).status_code == 401


def test_last_update_result_is_reported_once(tmp_path, monkeypatch):
    builds = tmp_path / "builds"
    builds.mkdir()
    (builds / updates.RESULT_FILE).write_text(json.dumps({"ok": False, "to": NEW, "at": 1}))
    monkeypatch.setattr(updates, "check", lambda *a, **k: {"available": False, "latest": None})
    app = create_app(builds, PORT, token=TOKEN, root=tmp_path)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", headers={"x-wt-token": TOKEN})
    assert c.get("/api/update").json()["last_update"] == {"ok": False, "to": NEW, "at": 1}
    assert c.get("/api/update").json()["last_update"] is None


def test_focus_without_a_window(app_client):
    c, *_ = app_client
    assert c.post("/api/window/focus").status_code == 409


# ------------------------------------------------------------------ CLI
def test_wt_update_check(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(updates, "check", lambda *a, **k: {
        "available": True, "error": None, "ahead_by": 2, "latest": NEW, "current": OLD,
        "branch": "main", "can_update": True,
        "commits": [{"message": "Newest feature"}, {"message": "Older fix"}]})
    with pytest.raises(SystemExit) as e:
        main(["update", "--check", "--builds", str(tmp_path)])
    out = capsys.readouterr().out
    assert e.value.code == 0 and "2 new changes" in out and "Newest feature" in out
    monkeypatch.setattr(updates, "check", lambda *a, **k: {
        "available": False, "error": None, "current": NEW, "branch": "main"})
    with pytest.raises(SystemExit):
        main(["update", "--check", "--builds", str(tmp_path)])
    assert "up to date" in capsys.readouterr().out
