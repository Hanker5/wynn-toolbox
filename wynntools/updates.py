"""Is there a newer Wynn Toolbox on GitHub, and install it.

Any new commit on the branch the app was installed from counts as an update.
The installer records the commit it installed in `.wynn-toolbox-install`
(JSON: repo, branch, commit, installed_at); a git clone uses `git rev-parse
HEAD`. Older installs left that file empty: their version is unknown, and the
update is offered so the next install records it.

Checks use GitHub's public API (60 requests an hour without a login), so a
result is cached in builds/.update.json for a few hours. Nothing here raises
on a network problem: the result carries an `error` instead.

Installing runs the installer from the new commit in a detached helper, after
the app has exited (Windows locks a running program's files), then starts the
app again. Its output goes to builds/update.log, and the outcome to
builds/.update-result.json for the next start to report.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = ".wynn-toolbox-install"
REPO = "Hanker5/wynn-toolbox"
BRANCH = "main"
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
CACHE_FILE = ".update.json"
RESULT_FILE = ".update-result.json"
LOG_FILE = "update.log"
CACHE_TTL = 6 * 3600
MAX_COMMITS = 10
SHA = re.compile(r"[0-9a-f]{40}")
NAME = re.compile(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)?")


# ------------------------------------------------------------------ what's installed
def _git(root, *args):
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                           timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def install_info(root=ROOT):
    """{kind: install|git|unknown, commit, repo, branch}. commit is None when unknown."""
    root = Path(root)
    marker = root / MARKER
    if marker.exists():
        try:
            data = json.loads(marker.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        repo, branch, commit = data.get("repo"), data.get("branch"), data.get("commit")
        return {"kind": "install",
                "commit": commit if isinstance(commit, str) and SHA.fullmatch(commit) else None,
                "repo": repo if isinstance(repo, str) and NAME.fullmatch(repo) else REPO,
                "branch": branch if isinstance(branch, str) and NAME.fullmatch(branch) else BRANCH}
    if (root / ".git").exists():
        commit = _git(root, "rev-parse", "HEAD")
        repo = REPO
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(\.git)?$", _git(root, "remote", "get-url",
                                                                        "origin") or "")
        if m and NAME.fullmatch(m.group(1)):
            repo = m.group(1)
        return {"kind": "git", "commit": commit if commit and SHA.fullmatch(commit) else None,
                "repo": repo, "branch": BRANCH}
    return {"kind": "unknown", "commit": None, "repo": REPO, "branch": BRANCH}


# ------------------------------------------------------------------ what's on GitHub
def _get_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "wynn-toolbox"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())


def _commit(c):
    msg = ((c.get("commit") or {}).get("message") or "").strip().splitlines()
    date = ((c.get("commit") or {}).get("committer") or {}).get("date")
    return {"sha": c.get("sha"), "message": msg[0] if msg else "", "date": date}


def _latest(info, fetch):
    head = fetch(f"{API}/repos/{info['repo']}/commits/{info['branch']}")
    return head["sha"], _commit(head)


def check(root=ROOT, cache_dir=None, force=False, fetch=None, now=time.time):
    """Compare the installed commit with the branch on GitHub.

    Returns {available, kind, can_update, current, latest, ahead_by, commits,
    repo, branch, checked_at, error}. `commits` is newest first, at most
    MAX_COMMITS; ahead_by is None when the installed version is unknown."""
    fetch = fetch or _get_json
    info = install_info(root)
    key = f"{info['repo']}@{info['branch']}:{info['commit']}"
    cache = Path(cache_dir) / CACHE_FILE if cache_dir else None
    if cache and not force:
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("key") == key and now() - cached["result"]["checked_at"] < CACHE_TTL:
                return cached["result"]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass

    out = {"available": False, "kind": info["kind"], "can_update": info["kind"] != "git",
           "current": info["commit"], "latest": None, "ahead_by": 0, "commits": [],
           "repo": info["repo"], "branch": info["branch"], "checked_at": now(), "error": None}
    try:
        if info["commit"]:
            try:
                cmp = fetch(f"{API}/repos/{info['repo']}/compare/"
                            f"{info['commit']}...{info['branch']}")
            except urllib.error.HTTPError as e:
                if e.code not in (404, 422):         # 404: GitHub doesn't know our commit
                    raise
                cmp = None
            if cmp is not None:
                ahead = int(cmp.get("ahead_by") or 0)
                commits = [_commit(c) for c in cmp.get("commits") or []][::-1]
                out.update(ahead_by=ahead, commits=commits[:MAX_COMMITS],
                           available=ahead > 0,
                           latest=commits[0]["sha"] if ahead and commits else info["commit"])
            else:
                latest, head = _latest(info, fetch)
                out.update(latest=latest, available=latest != info["commit"], ahead_by=None,
                           commits=[head])
        else:
            latest, head = _latest(info, fetch)
            out.update(latest=latest, available=True, ahead_by=None, commits=[head])
    except urllib.error.HTTPError as e:
        out["error"] = ("GitHub's rate limit was reached; try again in an hour"
                        if e.code in (403, 429) else f"GitHub answered {e.code}")
    except (urllib.error.URLError, OSError, TimeoutError):
        out["error"] = "couldn't reach GitHub (offline?)"
    except (ValueError, KeyError, TypeError, IndexError):
        out["error"] = "unexpected answer from GitHub"
    if out["latest"] and not SHA.fullmatch(out["latest"]):
        out.update(latest=None, available=False, error="unexpected answer from GitHub")

    if cache and out["error"] is None:
        try:
            cache.write_text(json.dumps({"key": key, "result": out}), encoding="utf-8")
        except OSError:
            pass
    return out


# ------------------------------------------------------------------ installing
UNIX_HELPER = r"""
while [ "$WT_PID" != 0 ] && kill -0 "$WT_PID" 2>/dev/null; do sleep 0.5; done
echo "== $(date): updating to $WYNN_TOOLBOX_COMMIT"
if curl -fsSL "$WT_INSTALLER" | sh; then ok=true; else ok=false; fi
printf '{"ok": %s, "to": "%s", "at": %s}\n' "$ok" "$WYNN_TOOLBOX_COMMIT" "$(date +%s)" \
  > "$WT_RESULT"
if [ -n "$WT_RELAUNCH" ]; then
  cd "$WYNN_TOOLBOX_DIR" && nohup "$WYNN_TOOLBOX_DIR/.venv/bin/wt" serve $WT_SERVE_ARGS \
    >> "$WT_APPLOG" 2>&1 &
fi
"""

WINDOWS_HELPER = r"""
Start-Transcript -Path $env:WT_LOG -Append | Out-Null
if ($env:WT_PID -ne '0') { Wait-Process -Id $env:WT_PID -ErrorAction SilentlyContinue }
Write-Host "Updating Wynn Toolbox to $env:WYNN_TOOLBOX_COMMIT ..."
$ok = $true
try { Invoke-RestMethod $env:WT_INSTALLER | Invoke-Expression }
catch { $ok = $false; Write-Host ($_ | Out-String) -ForegroundColor Red }
$okText = if ($ok) { 'true' } else { 'false' }
$at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
Set-Content -Path $env:WT_RESULT -Encoding ASCII -Value ('{"ok": ' + $okText + ', "to": "' + $env:WYNN_TOOLBOX_COMMIT + '", "at": ' + $at + '}')
Stop-Transcript | Out-Null
if ($env:WT_RELAUNCH) {
    $launchArgs = @('serve') + @($env:WT_SERVE_ARGS -split ' ' | Where-Object { $_ })
    Start-Process -FilePath (Join-Path $env:WYNN_TOOLBOX_DIR '.venv\Scripts\wynn-toolbox-app.exe') `
        -ArgumentList $launchArgs -WorkingDirectory $env:WYNN_TOOLBOX_DIR
}
if (-not $ok) { Read-Host 'The update failed (see above). Press Enter to close' }
"""


def update_command(root, builds_dir, target, pid, relaunch, platform=sys.platform):
    """(argv, env, popen_kwargs) for the detached updater. Values travel in
    environment variables, never inside the script text."""
    info = install_info(root)
    if not (isinstance(target, str) and SHA.fullmatch(target)):
        raise ValueError("the update target must be a full commit id")
    builds_dir = Path(builds_dir).resolve()
    windows = platform == "win32"
    script = "install.ps1" if windows else "install.sh"
    env = {**os.environ,
           "WT_PID": str(int(pid)),
           "WT_INSTALLER": f"{RAW}/{info['repo']}/{target}/install/{script}",
           "WT_RESULT": str(builds_dir / RESULT_FILE),
           "WT_LOG": str(builds_dir / LOG_FILE),
           "WT_APPLOG": str(builds_dir / "app.log"),
           "WT_RELAUNCH": "1" if relaunch is not None else "",
           "WT_SERVE_ARGS": relaunch or "",
           "WYNN_TOOLBOX_DIR": str(Path(root).resolve()),
           "WYNN_TOOLBOX_REPO": info["repo"],
           "WYNN_TOOLBOX_BRANCH": info["branch"],
           "WYNN_TOOLBOX_COMMIT": target}
    if windows:
        argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                WINDOWS_HELPER]
        # Its own console window, so the player can watch the installer.
        kwargs = {"creationflags": 0x00000010 | 0x00000200}   # NEW_CONSOLE | NEW_PROCESS_GROUP
    else:
        argv = ["sh", "-c", UNIX_HELPER]
        kwargs = {"start_new_session": True, "stdin": subprocess.DEVNULL}
    return argv, env, kwargs


def start_update(root, builds_dir, target, pid=None, relaunch="", popen=subprocess.Popen):
    """Start the updater; it waits for process `pid` (default: this one) to
    exit. `relaunch` is the extra `wt serve` arguments to restart with, or None
    to not restart. Raises ValueError for a git clone (use git pull)."""
    if install_info(root)["kind"] == "git":
        raise ValueError("this is a git clone; update it with `git pull`")
    argv, env, kwargs = update_command(root, builds_dir, target, pid or os.getpid(), relaunch)
    if sys.platform == "win32":          # shows in its own console; the transcript logs it
        popen(argv, env=env, close_fds=True, **kwargs)
        return
    with open(Path(builds_dir) / LOG_FILE, "a", encoding="utf-8") as log:
        popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT, close_fds=True, **kwargs)


def take_result(builds_dir):
    """The last update's outcome ({ok, to, at}), once; None if there is none."""
    path = Path(builds_dir) / RESULT_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    path.unlink(missing_ok=True)
    return data if isinstance(data, dict) else None
