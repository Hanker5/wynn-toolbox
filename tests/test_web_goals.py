"""The web app's endpoints for the new features."""
import pytest
from fastapi.testclient import TestClient

from wynntools.web.server import create_app

PORT, TOKEN = 8765, "test-token"


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(tmp_path, PORT, token=TOKEN), base_url=f"http://127.0.0.1:{PORT}",
                      headers={"x-wt-token": TOKEN})


def test_damage_scenario(client, links):
    client.post("/api/import", json={"link": links["shaman_105_stormdrain"]["hash"], "file": "s.json"})
    doc = client.get("/api/builds/s.json").json()
    r = client.post("/api/damage", json={"doc": doc, "specials": {"weapon": ["Curse", 7]}}).json()
    base = doc["status"]["damage"]["typical"]["spells"][2]["summary"]
    assert r["typical"]["spells"][2]["summary"] == pytest.approx(base * 1.25, rel=1e-3)
    assert client.post("/api/damage", json={"doc": doc, "specials": {"weapon": ["Nope", 1]}}).status_code == 422
    meta = client.get("/api/meta").json()
    assert [s["weapon"] for s in meta["specials"]][0] == "Quake"
