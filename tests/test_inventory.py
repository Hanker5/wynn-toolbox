import dataclasses

from wynntools.gear_solver import Spec, solve_gear, upgrades
from wynntools.inventory import Inventory, load, save, with_rolls
from wynntools.verify import stat

SPEC = Spec(cls="Mage", level=105, objective={"poison": 1},
            floors={"hp": 15000, "mr": 20, "mana": 113}, require_major=["PLAGUE"])
GAIA_BUILD = ["Slimy Shako", "Contagion", "Caterpillar", "Cytotoxic Striders", "Coral Ring",
              "Summa", "Dying Lobelia", "Contrast", "Gaia"]


def test_real_rolls_override_base_and_perfect(gd):
    seq = with_rolls(gd.item("Sequoia"), {"poison": 20640})     # her actual 86% Sequoia
    assert stat(seq, "poison") == 20640
    assert stat(seq, "poison", "max") == 20640                  # real rolls don't change
    assert stat(gd.item("Sequoia"), "poison", "max") == 31200


def test_owned_only_uses_only_owned_items(gd):
    inv = Inventory(items={n: {} for n in GAIA_BUILD + ["Sequoia", "Bismuthinite"]})
    r = solve_gear(dataclasses.replace(SPEC, only=inv.names(), inventory=inv), gd)
    assert set(r.equipment) <= inv.names()
    assert r.score >= 84300          # owning Sequoia too, it finds 88,300 from owned items


def test_upgrade_list_finds_the_missing_piece(gd):
    """Own the Gaia build minus Dying Lobelia: the top upgrade should restore it (or better)."""
    owned = [n for n in GAIA_BUILD if n != "Dying Lobelia"] + ["Sequoia"]
    inv = Inventory(items={n: {} for n in owned})
    base, ups = upgrades(SPEC, gd, inv, per_slot=4, top=5)
    assert base is not None and ups
    assert ups[0].gain > 0 and ups[0].result.score >= 84300
    assert all(u.item not in inv.names() for u in ups)


def test_inventory_file_round_trip(tmp_path):
    inv = Inventory(items={"Galleon": {"rolls": {"eSteal": 14}}}, tomes=["Tome of Scavenging Expertise III"])
    save(inv, tmp_path / "inventory.json")
    back = load(tmp_path / "inventory.json")
    assert back.rolls("Galleon") == {"eSteal": 14} and back.owns("Galleon")


def test_missing_slots_are_allowed_when_searching_owned_items(gd):
    inv = Inventory(items={n: {} for n in GAIA_BUILD if n != "Dying Lobelia"})
    r = solve_gear(dataclasses.replace(SPEC, only=inv.names(), inventory=inv), gd)
    assert r is not None and r.equipment[6] is None          # no bracelet owned
