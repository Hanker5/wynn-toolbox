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
    version_dir = tmp_path / data.VERSIONS[data.LATEST]
    version_dir.mkdir(parents=True)
    payload = {"name": "Réalm \u0081 Crest"}   # \xc2\x81 in utf-8: undefined in cp1252
    (version_dir / "encoding.json").write_bytes(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    data.load.cache_clear()
    try:
        assert data.load("encoding") == payload
    finally:
        data.load.cache_clear()
