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
    import_export(inv, gd, export("character", page(1, steal(5)), [], me="aaaabbbb"))
    assert sorted(inv.places) == ["character:aaaabbbb", f"character:{ME}", "inventory:aaaabbbb", f"inventory:{ME}"]
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
