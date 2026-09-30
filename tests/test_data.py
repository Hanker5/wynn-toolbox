import json
import locale

from wynntools import data


def test_load_reads_utf8_regardless_of_system_locale(tmp_path, monkeypatch):
    """Regression: `load` used to call `.read_text()` with no encoding, which
    reads the OS default codec (cp1252 on Windows) instead of UTF-8. Real
    WynnBuilder data has multi-byte UTF-8 names, so this crashed `wt serve`
    on Windows with `UnicodeDecodeError: 'charmap' codec can't decode byte
    0x81` while working fine on Linux, where the default locale is UTF-8."""
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "cp1252")
    version_dir = tmp_path / data.VERSIONS[data.latest()]
    version_dir.mkdir(parents=True)
    payload = {"name": "Réalm \u0081 Crest"}   # \xc2\x81 in utf-8: undefined in cp1252
    (version_dir / "encoding.json").write_bytes(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    data.load.cache_clear()
    try:
        assert data.load("encoding") == payload
    finally:
        data.load.cache_clear()


# ---------------------------------------------------------------- game versions

import shutil

import pytest

from wynntools.codec import decode, encode, link_hash
from wynntools.diagnose import diagnose_link

LOAD_ITEM_JS = """
const wynn_version_names = [
    '2.0.1.1',
    '2.2.4.0'
];
const WYNN_VERSION_LATEST = wynn_version_names.length - 1;
"""


@pytest.fixture
def versions(tmp_path, monkeypatch):
    """A private data cache (a copy of the current version's files) and a version
    list restored afterwards: VERSIONS is shared by every module that imports it."""
    real = data.CACHE_DIR / data.VERSIONS[-1]
    saved = list(data.VERSIONS)
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)
    data._asked.clear()
    data.load.cache_clear()

    def add_version(name):
        shutil.copytree(real, tmp_path / name)
        return name
    yield add_version
    data.VERSIONS[:] = saved
    data._asked.clear()
    data.load.cache_clear()


def _served(names):
    js = "const wynn_version_names = [\n" + ",\n".join(f"    '{n}'" for n in names) + "\n];"
    return lambda url, timeout: js.encode()


def _next_version_link(gd, links, add_version):
    """A session link re-encoded as if WynnBuilder had one more version."""
    build = decode(next(iter(links.values()))["hash"], gd)
    name = add_version("9.9.9.9")
    data.VERSIONS.append(name)
    build.version = data.latest()
    link = encode(build, data.GameData())
    data.VERSIONS.pop()
    data.load.cache_clear()
    return link, name


def test_parse_versions_reads_wynnbuilders_list():
    assert data.parse_versions(LOAD_ITEM_JS) == ["2.0.1.1", "2.2.4.0"]
    with pytest.raises(ValueError):
        data.parse_versions("const nothing = 1;")


def test_version_list_only_grows_and_keeps_every_index(versions):
    known = list(data.VERSIONS)
    assert data._adopt(known[:-1]) == []                   # shorter: ignored
    assert data._adopt(["0.0.0.1", *known[1:], "x"]) == []  # would move indices: ignored
    assert data._adopt([*known, "9.9.9.9"]) == ["9.9.9.9"]
    assert data.latest() == len(known)


def test_link_from_a_newer_version_is_explained_offline(gd, links, versions):
    """Regression: a link made after a patch carried a version number past the
    built-in list, raised IndexError, and was reported as "it isn't a
    WynnBuilder build link"."""
    link, _ = _next_version_link(gd, links, versions)
    with pytest.raises(data.UnknownVersion, match="newer WynnBuilder version"):
        decode(link_hash(link), gd)
    r = diagnose_link(link, gd)
    assert not r["ok"]
    assert [f["code"] for f in r["findings"]] == ["new_version"]
    assert "isn't a WynnBuilder build link" not in r["findings"][0]["message"]


def test_link_from_a_newer_version_reads_once_the_list_grows(gd, links, versions, monkeypatch):
    link, name = _next_version_link(gd, links, versions)
    monkeypatch.delenv("WYNN_TOOLBOX_OFFLINE")
    monkeypatch.setattr(data, "_download", _served([*data.VERSIONS, name]))
    b = decode(link_hash(link), gd)
    assert data.VERSIONS[-1] == name and b.version == data.latest()
    assert encode(b, gd.for_version(b.version)) == link_hash(link)
    r = diagnose_link(link, gd)
    assert r["ok"], r["findings"]
    assert data.GameData().version == b.version       # new data is the default from now on
    assert data.load_saved_versions() == []           # saved for the next run ...
    data.VERSIONS.pop()
    assert data.load_saved_versions() == [name]       # ... which adopts it


def test_routine_check_runs_at_most_every_few_hours(versions, monkeypatch):
    monkeypatch.delenv("WYNN_TOOLBOX_OFFLINE")
    calls = []

    def serve(url, timeout):
        calls.append(url)
        return _served([*data.VERSIONS, "9.9.9.9"])(url, timeout)
    monkeypatch.setattr(data, "_download", serve)
    assert data.check_versions() == ["9.9.9.9"]
    assert data.check_versions() == []
    assert len(calls) == 1


def test_failed_check_is_retried_sooner_and_never_raises(versions, monkeypatch):
    monkeypatch.delenv("WYNN_TOOLBOX_OFFLINE")

    def offline(url, timeout):
        raise OSError("no network")
    monkeypatch.setattr(data, "_download", offline)
    assert data.check_versions() == []
    saved = data._saved_versions()
    assert saved["ok"] is False
    monkeypatch.setattr(data.time, "time", lambda: saved["checked"] + data.RETRY_AFTER + 1)
    monkeypatch.setattr(data, "_download", _served([*data.VERSIONS, "9.9.9.9"]))
    assert data.check_versions() == ["9.9.9.9"]


def test_offline_setting_skips_every_check(versions, monkeypatch):
    def fail(url, timeout):
        raise AssertionError("no download expected")
    monkeypatch.setattr(data, "_download", fail)
    assert data.check_versions() == []
    assert data.ensure_version(data.latest() + 1) is False


def test_app_imports_a_newer_link_and_switches_to_its_data(gd, links, versions, monkeypatch,
                                                            tmp_path):
    from fastapi.testclient import TestClient

    from wynntools.web.server import create_app
    app = create_app(tmp_path / "builds", 8765, token="t")
    c = TestClient(app, base_url="http://127.0.0.1:8765", headers={"x-wt-token": "t"})
    before = c.get("/api/meta").json()["version"]
    link, name = _next_version_link(gd, links, versions)
    monkeypatch.delenv("WYNN_TOOLBOX_OFFLINE")
    monkeypatch.setattr(data, "_download", _served([*data.VERSIONS, name]))
    r = c.post("/api/import", json={"link": link, "file": "new.json", "name": "New"})
    assert r.status_code == 200, r.text
    assert (before, c.get("/api/meta").json()["version"]) == (data.VERSIONS[-2], name)
    assert c.get("/api/builds/new.json").json()["status"]["verified"]
