import time

import pytest
from fastapi.testclient import TestClient

from wynntools import updates
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
                                          "tree_preset": "mage-light-bender"}).json()["job"]
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
    assert res[0]["sources"]["Stolen Pearls"][0]["mob"] == "Tribal Exile"
    it = client.get("/api/item", params={"name": res[0]["name"]}).json()
    assert it["craft"]["recipe"] == "Ring-103-105"
    assert client.post("/api/craft-suggest", json={"slot": "weapon", "level": 105,
                                                   "objective": {"eSteal": 1}}).status_code == 422


def test_new_link_beats_stale_cookie(tmp_path):
    """Regression: after a restart the old session's cookie locked the user out
    even when they opened the new link."""
    app = create_app(tmp_path, PORT, token=TOKEN)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    c.cookies.set("wt_token", "token-from-previous-run")
    r = c.get(f"/?token={TOKEN}")
    assert r.status_code == 200
    assert r.cookies.get("wt_token") == TOKEN             # stale cookie replaced
    assert c.get("/api/meta").status_code == 200


def test_expired_link_gets_a_readable_page(tmp_path):
    app = create_app(tmp_path, PORT, token=TOKEN)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    r = c.get("/?token=old")
    assert r.status_code == 401 and "expired" in r.text and "wt serve" in r.text
    assert c.get("/api/meta").json()["detail"].startswith("missing or wrong token")


def test_inventory_api_and_reserved_file(client):
    assert client.post("/api/inventory", json={"action": "add", "name": "Galleon"}).status_code == 200
    assert client.post("/api/inventory", json={"action": "add", "name": "Galleon",
                                               "rolls": {"eSteal": 10}}).json()["items"]["Galleon"] == {"rolls": {"eSteal": 10}}
    assert client.post("/api/inventory", json={"action": "add", "name": "Not An Item"}).status_code == 422
    assert client.get("/api/builds").json() == []                 # inventory.json is not a build
    assert client.put("/api/builds/inventory.json", json={}).status_code == 400


def test_update_check_cache_is_not_a_build(client, tmp_path):
    """Regression: the update checker's own cache files (not build-shaped JSON)
    showed up in the builds list as unreadable builds."""
    (tmp_path / updates.CACHE_FILE).write_text('{"key": "x", "result": {}}')
    (tmp_path / updates.RESULT_FILE).write_text('{"ok": true, "to": "abc", "at": 1}')
    assert client.get("/api/builds").json() == []
    assert client.put(f"/api/builds/{updates.CACHE_FILE}", json={}).status_code == 400


def test_gear_search_spec_is_not_a_build(client, tmp_path):
    """Regression: a `wt gear`/`wt upgrades` spec.json left in builds/ by mistake
    (no `equipment` key) showed up in the builds list as unreadable."""
    (tmp_path / "poison-mage-spec.json").write_text(
        '{"class": "Mage", "level": 105, "objective": {"poison": 1}}')
    assert client.get("/api/builds").json() == []


def test_upgrades_job(client):
    for n in ["Slimy Shako", "Contagion", "Caterpillar", "Cytotoxic Striders", "Coral Ring",
              "Summa", "Contrast", "Gaia"]:
        client.post("/api/inventory", json={"action": "add", "name": n})
    spec = {"class": "Mage", "level": 105, "objective": {"poison": 1},
            "floors": {"hp": 15000, "mr": 20, "mana": 113}, "require_major": ["PLAGUE"]}
    job = client.post("/api/upgrades", json={"spec": spec, "top": 5}).json()["job"]
    for _ in range(300):
        with client.stream("GET", f"/api/jobs/{job}/events") as s:
            last = [line for line in s.iter_lines() if line.startswith("data:")][-1]
        if '"state": "done"' in last or '"state": "failed"' in last:
            break
        time.sleep(0.1)
    import json as _json
    result = _json.loads(last[5:])["result"]
    ranked = [u["item"] for u in result["upgrades"]]
    # without a forced weapon, owning Sequoia beats any bracelet; Dying Lobelia fills the gap
    assert ranked[0] == "Sequoia" and "Dying Lobelia" in ranked


def test_build_status_has_damage_and_spell_list(client, links):
    client.post("/api/import", json={"link": links["mage_105_gaia_lightbender"]["hash"],
                                     "file": "gaia.json", "name": "Gaia"})
    dmg = client.get("/api/builds/gaia.json").json()["status"]["damage"]
    ophanim = {s["name"]: s for s in dmg["perfect"]["spells"]}["Ophanim"]
    assert ophanim["summary"] == 19482.73 and ophanim["cost"] == 65.0
    assert dmg["typical"]["defense"]["ehp"] < dmg["perfect"]["defense"]["ehp"]
    names = [s["name"] for s in client.get("/api/spells?cls=Mage&preset=mage-light-bender").json()]
    assert names[0] == "Wand Melee" and "Ophanim" in names
    assert [s["name"] for s in client.get("/api/spells?cls=Mage").json()] == ["Wand Melee"]


def test_damage_minimum_needs_a_preset(client):
    spec = {"class": "Mage", "level": 105, "objective": {"poison": 1},
            "floors": {"damage": {"Ophanim": 10000}}, "force": {"weapon": "Gaia"}}
    r = client.post("/api/solve", json={"spec": spec, "file": "x.json"})
    assert r.status_code == 422 and "preset" in r.json()["detail"]
    r = client.post("/api/solve", json={"spec": spec, "file": "x.json",
                                        "tree_preset": "mage-light-bender"})
    assert r.status_code == 200
    client.post(f"/api/jobs/{r.json()['job']}/cancel")


def test_compare_two_builds(client, links):
    for f, k in (("a.json", "mage_105_gaia_lightbender"), ("b.json", "mage_105_sequoia")):
        client.post("/api/import", json={"link": links[k]["hash"], "file": f, "name": k})
    r = client.get("/api/compare", params={"a": "a.json", "b": "b.json", "roll": "perfect"}).json()
    weapon = next(g for g in r["gear"] if g["key"] == "weapon")
    assert (weapon["a"], weapon["b"], weapon["same"]) == ("Gaia", "Sequoia", False)
    poison = next(s for s in r["stats"] if s["key"] == "poison")
    assert poison["a"] == 108300 and poison["diff"] == poison["b"] - poison["a"]
    assert r["same_class"] and any(d["key"] == "Ophanim" for d in r["damage"])
    assert client.get("/api/compare", params={"a": "a.json", "b": "nope.json"}).status_code == 404


def test_exact_solve_job(client):
    spec = {"class": "Mage", "level": 105, "objective": {"poison": 1},
            "floors": {"hp": 15000, "mr": 20, "mana": 113}, "require_major": ["PLAGUE"],
            "force": {"weapon": "Gaia"}}
    job = client.post("/api/solve", json={"spec": spec, "file": "exact.json", "exact": True}).json()["job"]
    for _ in range(600):
        with client.stream("GET", f"/api/jobs/{job}/events") as s:
            last = [line for line in s.iter_lines() if line.startswith("data:")][-1]
        if '"state": "done"' in last or '"state": "failed"' in last:
            break
        time.sleep(0.1)
    assert '"state": "done"' in last
    assert client.get("/api/builds/exact.json").json()["status"]["totals"]["poison"] == 84300
    # a damage minimum falls back to the shortlist search
    r = client.post("/api/solve", json={"spec": {**spec, "floors": {"damage": {"Ophanim": 1}}},
                                        "file": "x.json", "tree_preset": "mage-light-bender"})
    assert r.status_code == 200
    client.post(f"/api/jobs/{r.json()['job']}/cancel")


def test_page_reports_its_view_for_the_ai(client, links):
    """`wt current` resolves "this build" from what the page last reported."""
    client.post("/api/import", json={"link": links["shaman_105_stormdrain"]["hash"], "file": "h.json"})
    assert client.get("/api/view").json()["at"] is None           # no page yet
    doc = client.get("/api/builds/h.json").json()
    doc["notes"] = "unsaved"
    assert client.put("/api/view", json={"view": "editor", "file": "h.json", "dirty": True,
                                         "doc": {**doc, "status": "junk"}}).status_code == 200
    v = client.get("/api/view").json()
    assert v["file"] == "h.json" and v["dirty"] and v["doc"]["notes"] == "unsaved"
    assert "status" not in v["doc"]                                # only editable fields kept
    client.put("/api/view", json={"view": "editor", "file": "h.json", "dirty": False, "doc": doc})
    assert client.get("/api/view").json()["doc"] is None           # saved: the file is the truth
    assert client.put("/api/view", json={"view": "nope"}).status_code == 422
    assert client.put("/api/view", json={"view": "editor", "file": "../x.json"}).status_code == 400


def test_show_request_needs_an_existing_build(client, links):
    assert client.post("/api/show", json={"file": "missing.json"}).status_code == 404
    assert client.post("/api/show", json={"file": "inventory.json"}).status_code == 400
    client.post("/api/import", json={"link": links["shaman_105_stormdrain"]["hash"], "file": "h.json"})
    assert client.post("/api/show", json={"file": "h.json"}).json() == {"ok": True, "file": "h.json"}


def test_unknown_tree_preset_is_a_clear_error(client):
    """A removed preset (e.g. mage-poison-lightbender) must not crash the search."""
    spec = {"class": "Mage", "level": 105, "objective": {"poison": 1}}
    r = client.post("/api/solve", json={"spec": spec, "file": "x.json",
                                        "tree_preset": "mage-poison-lightbender"})
    assert r.status_code == 422 and "unknown tree preset" in r.json()["detail"]
    r = client.post("/api/upgrades", json={"spec": {**spec, "floors": {"damage": {"Ophanim": 1}}},
                                           "tree_preset": "mage-poison-lightbender"})
    assert r.status_code == 422 and "unknown tree preset" in r.json()["detail"]


def test_delete_moves_a_build_to_the_trash_and_undo_restores_it(client, links, tmp_path):
    client.post("/api/import", json={"link": links["shaman_105_stormdrain"]["hash"], "file": "hank.json"})
    r = client.delete("/api/builds/hank.json")
    assert r.status_code == 200 and r.json()["file"] == "hank.json"
    trash = r.json()["trash"]
    assert not (tmp_path / "hank.json").exists() and (tmp_path / ".trash" / trash).exists()
    assert [b["file"] for b in client.get("/api/builds").json()] == []     # not listed
    assert client.delete("/api/builds/hank.json").status_code == 404
    assert client.delete("/api/builds/inventory.json").status_code == 400  # not a build
    # a second delete of the same name never overwrites the first
    client.post("/api/import", json={"link": links["shaman_105_stormdrain"]["hash"], "file": "hank.json"})
    assert client.delete("/api/builds/hank.json").json()["trash"] != trash
    assert len(list((tmp_path / ".trash").glob("hank-*.json"))) == 2
    # undo
    r = client.post("/api/trash/restore", json={"trash": trash, "file": "hank.json"})
    assert r.status_code == 200 and (tmp_path / "hank.json").exists()
    assert client.get("/api/builds/hank.json").json()["status"]["verified"]
    assert client.post("/api/trash/restore", json={"trash": trash, "file": "hank.json"}).status_code == 404
    assert client.post("/api/trash/restore", json={"trash": "../hank.json", "file": "x.json"}).status_code == 404


def test_page_never_runs_a_cached_old_script(client):
    """Found by the player: after an update the app window kept running the old
    app.js from its disk cache (no Delete button), because nothing told it to
    re-check. Script URLs now carry a content hash and the page isn't cached."""
    import hashlib
    import re

    from wynntools.web.server import STATIC
    r = client.get("/")
    assert r.headers["cache-control"] == "no-store"
    refs = re.findall(r'(?:src|href)="/static/([^"]+)"', r.text)
    assert refs and all("?v=" in x for x in refs)
    for ref in refs:
        name, v = ref.split("?v=")
        assert v == hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12]
    s = client.get("/static/" + refs[0])
    assert s.status_code == 200 and s.headers["cache-control"] == "no-cache"
