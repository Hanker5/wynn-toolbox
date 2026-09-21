from wynntools.codec import Build, decode, encode
from wynntools.craft_solver import CraftSpec, suggest_crafts
from wynntools.crafting import NO_INGREDIENT, Craft, craft_item, encode_craft_hash
from wynntools.verify import check_link, stat

EMPTY = [NO_INGREDIENT] * 6


def test_empty_ring_matches_wynnbuilder(gd):
    """Hash and durability produced by WynnBuilder's own encodeCraft/Craft (via QuickJS)."""
    it = craft_item(Craft("Ring-103-105", EMPTY, (3, 3)), gd.crafts)
    assert it["name"] == "CR-40w3w3w3w3w3w3d81"
    assert it["durability"] == [735, 738] and not it["problems"]


def test_crafted_item_in_build_link(gd, links):
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    ring = encode_craft_hash(Craft("Ring-103-105", ["Stolen Pearls"] * 4 + ["Doom Stone"] * 2), gd.crafts)
    b.equipment[5] = ring
    h = encode(b, gd)
    assert decode(h, gd).equipment[5] == ring
    ok, rep = check_link(h, gd)
    assert ok, rep["problems"]
    assert rep["summary"]["totals"]["eSteal"] > check_link(links["shaman_105_stormdrain"]["hash"], gd)[1]["summary"]["totals"]["eSteal"]


def test_profession_and_level_rules(gd):
    cd = gd.crafts
    # Filched Purse (Stealing) is an Alchemism/Scribing ingredient, not usable in jewellery
    it = craft_item(Craft("Ring-103-105", ["Filched Purse"] + EMPTY[1:]), cd)
    assert any("cannot be used for Jeweling" in p for p in it["problems"])
    it = craft_item(Craft("Ring-1-3", ["Stolen Pearls"] + EMPTY[1:]), cd)
    assert any("too high level" in p for p in it["problems"])


def test_suggested_crafts_are_valid_and_strong(gd):
    res = suggest_crafts(CraftSpec("ring", 105, {"eSteal": 1}), gd.crafts, top=3)
    assert res and all(not it["problems"] for _, it in res)
    assert stat(res[0][1], "eSteal") >= 22          # vs 8 for the best normal ring
    assert res == suggest_crafts(CraftSpec("ring", 105, {"eSteal": 1}), gd.crafts, top=3)


def test_ingredient_sources_merge_mobs_and_spots(gd):
    from wynntools.crafting import ingredient_sources, source_line
    cd = gd.crafts
    src = ingredient_sources(cd.ing_by_name["Stolen Pearls"])
    assert [e["mob"] for e in src] == ["Tribal Exile", "Rymek Citizen"]   # listed 2x and 3x
    assert src[0]["spots"] == [[1488, 113, -1513, 7]]                     # single spot, deduped
    assert len(src[1]["spots"]) == 9                                      # 10 listed, one repeat
    fake = {"droppedBy": [{"name": "A", "coords": None}, {"name": "B", "coords": False},
                          {"name": "A", "coords": [1, 2, 3, 4]}]}
    assert ingredient_sources(fake) == [{"mob": "A", "spots": [[1, 2, 3, 4]]},
                                        {"mob": "B", "spots": []}]
    assert "no mob listed" in source_line({"droppedBy": []})
    assert source_line(cd.ing_by_name["Stolen Pearls"]).startswith("Tribal Exile (1488, -1513), Rymek Citizen (1265, -1280) +8 spots")
    assert "powder" in source_line(cd.ing_by_name["Fire Powder VI"]).lower()
