"""Installing the chest-export mod into a Minecraft folder from the app."""
import json
from pathlib import Path

import pytest

from wynntools import modinstall
from wynntools.modinstall import InstallError, candidates, install, status


def game(tmp_path, *parts, fabric=True):
    """A Minecraft folder like a launcher's: mods (with Fabric API), config, options.txt."""
    folder = tmp_path.joinpath(*parts)
    (folder / "mods").mkdir(parents=True)
    (folder / "options.txt").write_text("")
    if fabric:
        (folder / "mods" / "fabric-api-0.141.6+1.21.11.jar").write_bytes(b"jar")
    return folder


def test_install_copies_the_mod_replaces_old_ones_and_points_it_at_the_app(tmp_path):
    folder, builds = game(tmp_path, "mc"), tmp_path / "wynn" / "builds"
    builds.mkdir(parents=True)
    (folder / "mods" / "wynngpt-chest-export-1.0.0.jar").write_bytes(b"old")
    (folder / "config").mkdir()
    (folder / "config" / "wynngpt-chest-export.json").write_text('{"builds_path": "/elsewhere", "capture": true}')
    got = install(folder / "mods", builds)                           # the mods folder works too
    jar = modinstall.bundled_jar()
    assert got["jar"] == str(folder.resolve() / "mods" / jar.name) and got["removed"] == ["wynngpt-chest-export-1.0.0.jar"]
    assert (folder / "mods" / jar.name).read_bytes() == jar.read_bytes()
    config = json.loads((folder / "config" / "wynngpt-chest-export.json").read_text())
    assert config == {"builds_path": str(builds.resolve()), "capture": True}   # the player's other settings stay
    assert got["warnings"] == []
    assert status(folder, builds) == {"folder": str(folder.resolve()), "installed": [jar.name], "current": True,
                                      "configured": True}
    assert install(folder, builds)["removed"] == []                  # installing again changes nothing


def test_install_says_what_is_wrong(tmp_path):
    with pytest.raises(InstallError, match="no folder"):
        install(tmp_path / "missing", tmp_path)
    (tmp_path / "Documents").mkdir()
    with pytest.raises(InstallError, match="doesn't look like a Minecraft folder"):
        install(tmp_path / "Documents", tmp_path)
    with pytest.raises(InstallError, match="type the path"):
        install("  ", tmp_path)
    bare = game(tmp_path, "bare", fabric=False)
    assert any("Fabric API" in w for w in install(bare, tmp_path)["warnings"])
    flat = game(tmp_path, ".var", "app", "org.prismlauncher.PrismLauncher", "data", "PrismLauncher", "instances", "W", ".minecraft")
    note = next(w for w in install(flat, tmp_path)["warnings"] if "Flatpak" in w)
    assert f"--filesystem={tmp_path.resolve()}:ro org.prismlauncher.PrismLauncher" in note


def test_candidates_finds_launcher_instances(tmp_path):
    game(tmp_path, ".local", "share", "PrismLauncher", "instances", "Wynncraft", ".minecraft")
    game(tmp_path, ".minecraft", fabric=False)
    found = candidates(tmp_path)
    assert [(c["launcher"], c["fabric_api"]) for c in found] == [("Prism Launcher", True), ("Minecraft launcher", False)]
    assert Path(found[0]["path"]).parts[-3:] == ("instances", "Wynncraft", ".minecraft")


def test_the_app_installs_it_and_remembers_the_folder(tmp_path):
    from fastapi.testclient import TestClient
    from wynntools.web.server import create_app
    folder, builds = game(tmp_path, "mc"), tmp_path / "builds"
    builds.mkdir()
    c = TestClient(create_app(builds, 8765, token="t"), base_url="http://127.0.0.1:8765", headers={"x-wt-token": "t"})
    assert c.post("/api/mod/install", json={"folder": str(tmp_path / "nope")}).status_code == 422
    got = c.post("/api/mod/install", json={"folder": str(folder)}).json()
    assert got["builds_path"] == str(builds.resolve())
    st = c.get("/api/mod").json()
    assert st["folder"] == str(folder.resolve()) and st["status"]["current"] and st["status"]["configured"]


def test_wt_mod_install(tmp_path, monkeypatch, capsys):
    from wynntools import cli
    folder = game(tmp_path, "mc")
    (tmp_path / "builds").mkdir()
    monkeypatch.setattr(cli, "BUILDS", tmp_path / "builds")
    def run(*argv):
        try:
            return cli.main(list(argv)) or 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 1
    assert run("mod", "install", str(folder)) == 0
    assert "Restart Minecraft" in capsys.readouterr().out
    assert run("mod", "status") == 0                                # remembered, current and set up
