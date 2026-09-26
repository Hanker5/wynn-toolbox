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
