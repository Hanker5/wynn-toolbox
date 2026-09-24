"""The web app's endpoints and `wt` commands for the new search features."""
import json

import pytest
from fastapi.testclient import TestClient

from wynntools import buildfile
from wynntools.cli import main
from wynntools.codec import decode
from wynntools.web.server import create_app

PORT, TOKEN = 8765, "test-token"


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(tmp_path, PORT, token=TOKEN), base_url=f"http://127.0.0.1:{PORT}",
                      headers={"x-wt-token": TOKEN})


def wait(client, job):
    for _ in range(1200):
        with client.stream("GET", f"/api/jobs/{job}/events") as s:
            for line in s.iter_lines():
                if line.startswith("data:"):
                    j = json.loads(line[5:])
                    if j["state"] != "running":
                        return j
    raise AssertionError("job never finished")


def test_solve_failure_comes_with_an_explanation(client):
    spec = {"class": "Mage", "level": 105, "objective": {"poison": 1}, "floors": {"hp": 60000}}
    j = wait(client, client.post("/api/solve", json={"spec": spec, "file": "x.json"}).json()["job"])
    assert j["state"] == "failed" and j["explanation"]["conflict"] == ["Health at least 60,000"]


def test_solve_with_new_floors_saves_a_candidate(client, tmp_path, gd, links):
    client.post("/api/import", json={"link": links["shaman_105_stormdrain"]["hash"], "file": "main.json"})
    spec = {"class": "Shaman", "level": 105, "objective": {"hp": 1}, "force": {"weapon": "Stormdrain"},
            "floors": {"min_eledef": 0, "int": 100}}
    r = client.post("/api/solve", json={"spec": spec, "file": "main--safe.json", "name": "safe",
                                        "parent": "main.json"}).json()
    assert r["search"] == "exact"
    assert wait(client, r["job"])["state"] == "done"
    doc = client.get("/api/builds/main--safe.json").json()
    st = doc["status"]
    assert doc["parent"] == "main.json" and st["verified"]
    assert st["sp_final"]["int"] == 100 and st["sp_manual"]["int"]
    assert min(st["totals"][k] for k in ("eDef", "tDef", "wDef", "fDef", "aDef")) >= 0
    listing = {b["file"]: b for b in client.get("/api/builds").json()}
    assert listing["main--safe.json"]["parent"] == "main.json"


def test_damage_scenario(client, links):
    client.post("/api/import", json={"link": links["shaman_105_stormdrain"]["hash"], "file": "s.json"})
    doc = client.get("/api/builds/s.json").json()
    r = client.post("/api/damage", json={"doc": doc, "specials": {"weapon": ["Curse", 7]}}).json()
    base = doc["status"]["damage"]["typical"]["spells"][2]["summary"]
    assert r["typical"]["spells"][2]["summary"] == pytest.approx(base * 1.25, rel=1e-3)
    assert client.post("/api/damage", json={"doc": doc, "specials": {"weapon": ["Nope", 1]}}).status_code == 422
    meta = client.get("/api/meta").json()
    assert [s["weapon"] for s in meta["specials"]][0] == "Quake"


def test_locks_are_editable(client, links):
    client.post("/api/import", json={"link": links["shaman_105_stormdrain"]["hash"], "file": "l.json"})
    doc = client.get("/api/builds/l.json").json()
    out = client.put("/api/builds/l.json", json={**doc, "locked": ["weapon", "helmet"]}).json()
    assert out["locked"] == ["weapon", "helmet"]


def test_wt_own_unavailable_and_gear_leave_it_out(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inv = str(tmp_path / "inv.json")
    with pytest.raises(SystemExit):
        main(["own", "unavailable", "Leo", "--reason", "too expensive", "--inventory", inv])
    assert json.loads((tmp_path / "inv.json").read_text())["unavailable"] == {"Leo": "too expensive"}
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({"class": "Shaman", "level": 105, "objective": {"hp": 1},
                                "force": {"weapon": "Stormdrain"}}))
    with pytest.raises(SystemExit):
        main(["gear", str(spec), "--inventory", inv, "--quiet"])
    out = capsys.readouterr().out
    assert "leaving out 1 item marked unavailable" in out and "chestplate Leo" not in out


def test_wt_gear_explains_and_respects_locks(tmp_path, gd, links, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({"class": "Shaman", "level": 105, "objective": {"hp": 1},
                                "force": {"weapon": "Sunstar"}, "floors": {"def": 120, "int": 120}}))
    with pytest.raises(SystemExit) as e:
        main(["gear", str(spec), "--quiet"])
    out = capsys.readouterr().out
    assert e.value.code == 1 and "These can't all hold at once" in out and "Sunstar alone needs 115" in out
    doc = buildfile.from_build(decode(links["shaman_105_stormdrain"]["hash"], gd), gd)
    f = tmp_path / "b.json"
    buildfile.write(f, {"name": "b", **doc, "locked": ["helmet"], "spec": {"objective": {"hp": 1}}})
    with pytest.raises(SystemExit, match="helmet is locked"):
        main(["gear", "--edit", str(f), "--change", "helmet", "--no-show"])
