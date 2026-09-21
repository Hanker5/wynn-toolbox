from wynntools import buildfile
from wynntools.codec import decode, encode


def test_build_file_round_trip(gd, links, tmp_path):
    """link -> build file -> disk -> build -> link is lossless for every session link."""
    for name, fx in links.items():
        doc = buildfile.refresh(buildfile.from_build(decode(fx["hash"], gd), gd), gd)
        path = tmp_path / f"{name}.json"
        buildfile.write(path, doc)
        back = buildfile.to_build(buildfile.read(path), gd)
        assert encode(back, gd) == fx["hash"], name
        assert doc["status"]["verified"], name


def test_hand_edit_is_rechecked(gd, links):
    """Swapping in an item the build can't support is caught on refresh."""
    doc = buildfile.from_build(decode(links["shaman_105_stormdrain"]["hash"], gd), gd)
    doc["equipment"][3] = "Gaea-Hewn Boots"
    doc["equipment"][0] = "Phoenix Prince's Crown"
    doc["equipment"][8] = "The Watched"
    out = buildfile.refresh(doc, gd)
    assert not out["status"]["verified"]
    assert any("skill points" in p for p in out["status"]["problems"])
