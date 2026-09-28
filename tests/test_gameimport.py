from wynntools.gameimport import clean, import_slots, read_rolls
from wynntools.inventory import Inventory

PAD = "\U000cffff"     # Wynncraft's custom-font spacing, as the chest-export mod sends it

# Heroism's identifications, as copied from a real in-game tooltip.
HEROISM_LORE = [
    f"{PAD}Heroism", "+3,500 Health", "+50 +50 +50", f"Combat Level{PAD}96",
    f"Defence{PAD}+10", f"Agility{PAD}+10",
    f"Life Steal{PAD}+161/3s", f"Reflection{PAD}+28%", f"Thorns{PAD}+14%", f"Health{PAD}+950",
    f"Health Regen{PAD}-124%", f"Health Regen{PAD}-14", f"Walk Speed{PAD}+18%", f"Sprint{PAD}+4%",
]


def test_clean_strips_formatting_and_wynncraft_spacing():
    assert clean("\U000cf000§dHeroism\U000cf000") == "Heroism"
    assert clean("Broken IceÀÀÀBarrows Key") == "Broken Ice Barrows Key"     # as a real export names it


def test_reads_real_rolls_from_the_tooltip(gd):
    assert read_rolls(gd.item("Heroism"), HEROISM_LORE) == {
        "ls": 161, "ref": 28, "thorns": 14, "hpBonus": 950, "hprPct": -124, "hprRaw": -14,
        "spd": 18, "sprint": 4}          # skill points and base health never roll


def test_spell_cost_is_matched_by_the_one_the_item_has(gd):
    # Flaming Soul's only spell cost is spRaw1; the tooltip names the spell instead.
    assert read_rolls(gd.item("Flaming Soul"), [f"Totem Cost{PAD}-8"]) == {"spRaw1": -8}


def test_import_saves_rolls_and_updates_them_on_a_later_export(gd):
    inv = Inventory(items={"Heroism": {}})
    r = import_slots(inv, gd, [{"name": "Heroism", "lore": HEROISM_LORE},
                               {"name": "Heroism", "lore": [f"Walk Speed{PAD}+7%"]}])
    assert r["imported"] == {"items": 0, "tomes": 0, "aspects": 0, "rolls": 1}
    assert inv.rolls("Heroism")["spd"] == 18                     # the first copy wins
    import_slots(inv, gd, [{"name": "Heroism", "lore": [f"Walk Speed{PAD}+20%"]}])
    assert inv.rolls("Heroism") == {"spd": 20}


# ---------------------------------------------------------------- format 2: pages and places

from wynntools.gameimport import import_export, page_of  # noqa: E402

ME = "a1b2c3d4"
NEXT = "§f§lPage {}§a >§2>§a>§2>§a>"          # the arrows as Wynncraft names them
PREV = "§f§lPage {}§a <§2<§a<§2<§a<"


def steal(n):
    return {"name": "Galleon", "lore": [f"Stealing{PAD}+{n}%"]}


def page(n, *items, last=12):
    """An ender chest page's storage slots: items from slot 0, arrows as the game shows them."""
    slots = [{"slot": k, **it} for k, it in enumerate(items)]
    if n > 1:
        slots.append({"slot": 51, "name": PREV.format(n - 1)})
    if n < last:
        slots.append({"slot": 52, "name": NEXT.format(n + 1)})
    return slots


def export(kind, storage=(), inventory=(), me=ME, **kw):
    return {"version": 2, "kind": kind, "character": {"id": me}, "storage": list(storage),
            "inventory": list(inventory), **kw}


def test_page_is_read_from_the_arrows():
    assert page_of(page(1)) == 1 and page_of(page(5)) == 5 and page_of(page(12)) == 12
    assert page_of([]) == 1                                       # a chest with one page
    assert page_of([{"slot": 51, "name": PREV.format(2)}, {"slot": 52, "name": NEXT.format(9)}]) is None


def test_an_export_records_each_copy_and_where_it_is(gd):
    inv = Inventory()
    r = import_export(inv, gd, export("account", page(3, steal(14), {}, steal(9), steal(9),
                                                     {"name": "Liquid Emerald", "count": 64})))
    assert r["imported"]["items"] == 3 and "Account ender chest p3" in r["message"]
    copies = inv.copies("Galleon")
    assert [(c.place, c.page, c.slot) for c in copies] == [("account", 3, 0), ("account", 3, 2), ("account", 3, 3)]
    assert len({c.fp for c in copies}) == 2               # the two +9% copies are identical
    assert inv.counts() == {"Galleon": 3} and inv.rolls("Galleon", copies[1].fp) == {"eSteal": 9}
    assert inv.where("account", 3, 2) == "Account ender chest · page 3 · row 1, column 3"
    assert [h["where"] for h in inv.find("emerald")] == ["Account ender chest · page 3 · row 1, column 5"]
    assert not inv.owns("Liquid Emerald")                 # other things are shown, not gear


def test_a_later_export_replaces_the_page(gd):
    inv = Inventory()
    import_export(inv, gd, export("account", page(2, steal(14))))
    r = import_export(inv, gd, export("account", page(2)))              # moved out
    assert r["imported"]["removed"] == 1 and not inv.owns("Galleon")
    import_export(inv, gd, export("account", page(4, steal(14))))       # ... to page 4
    assert [(c.page, c.slot) for c in inv.copies("Galleon")] == [(4, 0)]


def test_characters_keep_their_own_ender_chest_and_inventory(gd):
    inv = Inventory()
    import_export(inv, gd, export("character", page(1, steal(14)), [{"slot": 0, "name": "Spring"}]))
    import_export(inv, gd, export("character", page(1, steal(5)), [], me="zzzz0000"))
    assert sorted(inv.places) == [f"character:{ME}", "character:zzzz0000", f"inventory:{ME}", "inventory:zzzz0000"]
    assert inv.characters[ME]["class"] == "Archer"                      # guessed from the bow it carries
    assert inv.where(f"inventory:{ME}", 1, 0) == f"Archer {ME} · inventory · hotbar 1"
    import_export(inv, gd, export("inventory", inventory=[]))
    assert not inv.owns("Spring") and inv.counts() == {"Galleon": 2}


def test_new_copies_claim_the_ones_added_by_hand(gd):
    inv = Inventory(items=[{"name": "Galleon", "rolls": {"eSteal": 14}}, {"name": "Galleon", "rolls": {"eSteal": 3}},
                           {"name": "Heroism"}], tomes=["Tome of Scavenging Expertise III"])
    r = import_export(inv, gd, export("account", page(1, steal(14), {"name": "Heroism", "lore": HEROISM_LORE},
                                                     {"name": "Tome of Scavenging Expertise III"})))
    assert r["imported"]["claimed"] == 3
    assert inv.items == [{"name": "Galleon", "rolls": {"eSteal": 3}}]   # a different copy stays
    assert inv.counts() == {"Galleon": 2, "Heroism": 1} and inv.tome_counts() == {"Tome of Scavenging Expertise III": 1}
    import_export(inv, gd, export("account", page(1, steal(14))))       # re-exporting claims nothing more
    assert inv.items == [{"name": "Galleon", "rolls": {"eSteal": 3}}]


def test_a_complete_walk_drops_pages_the_player_no_longer_has(gd):
    inv = Inventory()
    walk = [{"kind": "account", "storage": page(n, steal(n), last=3)} for n in (1, 2, 3)]
    import_export(inv, gd, export("ender_all", pages=walk, complete=True))
    assert sorted(inv.places["account"]["pages"]) == ["1", "2", "3"]
    partial = [{"kind": "account", "storage": page(1, last=2)}]
    import_export(inv, gd, export("ender_all", pages=partial, complete=False))
    assert sorted(inv.places["account"]["pages"]) == ["1", "2", "3"]    # a partial walk drops nothing
    import_export(inv, gd, export("ender_all", pages=walk[:1] + [{"kind": "account", "storage": page(2, last=2)}],
                                  complete=True))
    assert sorted(inv.places["account"]["pages"]) == ["1", "2"]


def test_unreadable_page_and_unknown_containers_import_nothing_from_storage(gd):
    inv = Inventory()
    odd = [steal(1) | {"slot": 0}, {"slot": 51, "name": PREV.format(2)}, {"slot": 52, "name": NEXT.format(9)}]
    r = import_export(inv, gd, export("account", odd))
    assert r["warnings"] and "account" not in inv.places
    import_export(inv, gd, export("unknown", page(1, steal(4))))
    assert not inv.owns("Galleon")


def test_only_chests_walked_to_the_end_drop_pages(gd):
    inv = Inventory()
    both = [{"kind": k, "storage": page(n, steal(n), last=3)} for k in ("account", "character") for n in (1, 2, 3)]
    import_export(inv, gd, export("ender_all", pages=both, complete=["account", "character"]))
    short = [{"kind": k, "storage": page(n, last=2)} for k in ("account", "character") for n in (1, 2)]
    import_export(inv, gd, export("ender_all", pages=short, complete=["account"]))   # the character walk stopped
    assert sorted(inv.places["account"]["pages"]) == ["1", "2"]
    assert sorted(inv.places[f"character:{ME}"]["pages"]) == ["1", "2", "3"]


# ---------------------------------------------------------------- real exports (tests/fixtures/exports)

import json  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

EXPORTS = Path(__file__).parent / "fixtures" / "exports"
MOD = Path(__file__).parent.parent / "wynn-chest-export" / "src" / "client" / "java" / "com" / "hankryhays" / "wynngptchestexport"


def real(name):
    return json.loads((EXPORTS / name).read_text(encoding="utf-8"))


def java_string(source, constant):
    """A Java string constant's value (its \\uXXXX escapes decoded, surrogate pairs joined)."""
    parts = re.search(rf"{constant} = (.+?);", source).group(1)
    text = "".join(re.findall(r'"([^"]*)"', parts))
    return text.encode("latin-1").decode("unicode_escape").encode("utf-16", "surrogatepass").decode("utf-16")


def test_the_mod_recognises_real_ender_chest_titles():
    """The glyph strings the mod matches (StorageScreens.java) are in the titles the game sent."""
    source = (MOD / "StorageScreens.java").read_text(encoding="utf-8")
    bank = java_string(source, "BANK_TITLE")
    assert real("account-p1.json")["source"]["title"].endswith(bank + "")
    assert real("character-p3.json")["source"]["title"].endswith(bank + "")
    walker = (MOD / "PageWalker.java").read_text(encoding="utf-8")
    controls = {s["slot"]: clean(s["name"]) for s in real("account-p1.json")["storage"] if s["slot"] >= 45}
    assert controls[int(re.search(r"SWITCH_SLOT = (\d+);", walker).group(1))] == java_string(walker, "SWITCH_NAME")
    assert controls[46] == "Quick Actions" and "46" not in re.findall(r"_SLOT = (\d+);", walker)   # never clicked


def test_real_pages_are_read(gd):
    assert [page_of(real(f)["storage"]) for f in ("account-p1.json", "account-p7.json", "character-p3.json")] == [1, 7, 3]
    inv = Inventory()
    for f in ("account-p1.json", "account-p7.json", "character-p3.json", "inventory.json"):
        import_export(inv, gd, real(f))
    assert sorted(inv.places) == ["account", "character:a1b2c3d4", "inventory:a1b2c3d4"]
    assert sorted(inv.places["account"]["pages"]) == ["1", "7"]
    assert inv.places["character:a1b2c3d4"]["pages"]["3"]["slots"] == []      # an empty page
    heroism = inv.copies("Heroism")
    assert len(heroism) == 2 and len({c.fp for c in heroism}) == 2           # two copies, different rolls
    assert all(c.rolls.get("ls") for c in heroism)                           # read from the tooltips
    assert not any(s["slot"] >= 45 for key, _, s in inv.slots() if not key.startswith("inventory"))   # no arrows


def test_the_walker_clicks_only_real_arrows_and_the_switch():
    """The page walker's click rule (PageWalker.java), applied to real slots: on the last page
    bought, slot 52 is still named "Page 15 >>>>>" but offers to buy the page; it must never
    be clicked, and neither must Quick Actions (46)."""
    walker = (MOD / "PageWalker.java").read_text(encoding="utf-8")
    hint, purchase = java_string(walker, "ARROW_HINT"), java_string(walker, "PURCHASE")
    switch, switch_hint = java_string(walker, "SWITCH_NAME"), java_string(walker, "SWITCH_HINT")

    def clickable(export, slot):
        s = next(x for x in real(export)["storage"] if x["slot"] == slot)
        name, lore = clean(s["name"]), [clean(line) for line in s.get("lore") or []]
        if slot == 47:
            return name == switch and switch_hint in lore
        return bool(re.match(r"^Page \d+\s*[<>]", name)) and hint in lore and not any(purchase in x for x in lore)

    assert clickable("account-p7.json", 51) and clickable("account-p7.json", 52)
    assert clickable("account-p14-last.json", 51) and not clickable("account-p14-last.json", 52)
    assert clickable("account-p1.json", 47) and not clickable("account-p1.json", 46)
    assert page_of(real("account-p14-last.json")["storage"]) == 14
