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


def test_powders_and_aspects_survive_build_files(gd, links):
    from wynntools.codec import decode, encode
    from wynntools.buildfile import from_build, to_build
    b = decode(links["mage_105_gaia_lightbender"]["hash"], gd)
    b.powders = [[5], [], [], [19], [12, 26]]
    mage = {a["displayName"]: a for a in gd.aspects("Mage")}
    name = sorted(mage)[0]
    b.aspects = [None, (mage[name]["id"], 2), None, None, None]
    doc = from_build(b, gd)
    assert doc["aspects"][1] == [name, 2] and doc["powders"][4] == ["t6", "f6"]
    assert encode(to_build(doc, gd), gd) == encode(b, gd)


def test_bad_aspects_are_rejected(gd, links):
    import pytest
    from wynntools.codec import decode
    from wynntools.buildfile import from_build, to_build
    doc = from_build(decode(links["mage_105_gaia_lightbender"]["hash"], gd), gd)
    shaman = gd.aspects("Shaman")[0]["displayName"]
    with pytest.raises(KeyError, match="not a Mage aspect"):
        to_build({**doc, "aspects": [[shaman, 1], None, None, None, None]}, gd)
    mage = gd.aspects("Mage")[0]
    with pytest.raises(KeyError, match="tiers"):
        to_build({**doc, "aspects": [[mage["displayName"], 9], None, None, None, None]}, gd)


def test_armor_powders_count_in_totals(gd, links):
    from wynntools.codec import decode
    from wynntools.verify import summarize
    b = decode(links["mage_105_gaia_lightbender"]["hash"], gd)
    before = summarize(b, gd)["totals"]
    b.powders = [[5, 5], [], [], [], []]           # helmet: two earth T6
    after = summarize(b, gd)["totals"]
    assert after["hp"] - before["hp"] == 2 * 60
    assert after["eDef"] - before["eDef"] == 2 * 29 and after["aDef"] - before["aDef"] == -2 * 7
