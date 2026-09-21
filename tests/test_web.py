import time

import pytest
from fastapi.testclient import TestClient

from wynntools.web.server import create_app

PORT = 8765
TOKEN = "test-token"


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path, PORT, token=TOKEN)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", headers={"x-wt-token": TOKEN})


def test_token_required(tmp_path):
    app = create_app(tmp_path, PORT, token=TOKEN)
    anon = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    assert anon.get("/api/meta").status_code == 401
    assert anon.get("/api/meta", headers={"x-wt-token": "wrong"}).status_code == 401


def test_foreign_host_rejected(tmp_path):
    """Blocks DNS-rebinding: a page on evil.example can't talk to the app."""
    app = create_app(tmp_path, PORT, token=TOKEN)
    c = TestClient(app, base_url=f"http://evil.example:{PORT}", headers={"x-wt-token": TOKEN})
    assert c.get("/api/meta").status_code == 403


def test_token_in_url_sets_cookie(tmp_path):
    app = create_app(tmp_path, PORT, token=TOKEN)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    assert c.get(f"/?token={TOKEN}").status_code == 200
    assert c.get("/api/meta").status_code == 200          # now via cookie


def test_import_edit_and_conflict(client, links):
    r = client.post("/api/import", json={"link": links["shaman_105_stormdrain"]["hash"],
                                         "file": "hank.json", "name": "Hank"})
    assert r.status_code == 200
    doc = client.get("/api/builds/hank.json").json()
    assert doc["status"]["verified"]
    # someone else (the AI) saves first...
    doc2 = {**doc, "notes": "edited by the AI"}
    time.sleep(0.01)
    assert client.put("/api/builds/hank.json", json=doc2).status_code == 200
    # ...so a save based on the old version is refused
    stale = {**doc, "notes": "edited in the browser"}
    assert client.put("/api/builds/hank.json", json=stale).status_code == 409


def test_check_flags_problems_without_saving(client, links):
    client.post("/api/import", json={"link": links["shaman_105_stormdrain"]["hash"], "file": "h.json"})
    doc = client.get("/api/builds/h.json").json()
    doc["equipment"][3] = "Gaea-Hewn Boots"
    doc["equipment"][0] = "Phoenix Prince's Crown"
    doc["equipment"][8] = "The Watched"
    out = client.post("/api/check", json=doc).json()
    assert not out["status"]["verified"]
    assert client.get("/api/builds/h.json").json()["status"]["verified"]   # file untouched
    doc["equipment"][2] = "Not A Real Item"
    assert client.post("/api/check", json=doc).status_code == 422


def test_paths_confined_to_builds_dir(client):
    assert client.get("/api/builds/..%2Fpyproject.json").status_code in (400, 404)
    assert client.put("/api/builds/x.txt", json={}).status_code == 400


def test_solve_job_writes_build(client):
    spec = {"class": "Mage", "level": 105, "objective": {"poison": 1},
            "floors": {"hp": 15000, "mr": 20, "mana": 113}, "require_major": ["PLAGUE"],
            "force": {"weapon": "Gaia"}}
    job = client.post("/api/solve", json={"spec": spec, "file": "gaia.json", "name": "Gaia",
                                          "tree_preset": "mage-poison-lightbender"}).json()["job"]
    for _ in range(600):
        with client.stream("GET", f"/api/jobs/{job}/events") as s:
            last = [line for line in s.iter_lines() if line.startswith("data:")][-1]
        if '"state": "done"' in last or '"state": "failed"' in last:
            break
        time.sleep(0.1)
    assert '"state": "done"' in last
    doc = client.get("/api/builds/gaia.json").json()
    assert doc["status"]["verified"] and doc["status"]["totals"]["poison"] >= 84300
    assert len(doc["tree"]) > 20


def test_items_autocomplete(client):
    hits = client.get("/api/items", params={"slot": "weapon", "cls": "Shaman", "q": "storm"}).json()
    assert any(h["name"] == "Stormdrain" for h in hits)


def test_craft_suggest_and_item_lookup(client):
    res = client.post("/api/craft-suggest", json={"slot": "ring1", "level": 105,
                                                  "objective": {"eSteal": 1}, "top": 2}).json()
    assert res and res[0]["craft"]["ingredients"] and not res[0]["craft"]["problems"]
    it = client.get("/api/item", params={"name": res[0]["name"]}).json()
    assert it["craft"]["recipe"] == "Ring-103-105"
    assert client.post("/api/craft-suggest", json={"slot": "weapon", "level": 105,
                                                   "objective": {"eSteal": 1}}).status_code == 422
