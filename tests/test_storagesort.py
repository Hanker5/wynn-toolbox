"""Sorting an ender chest: groups, rules, the sorted layout, and the clicks that reach it."""
import random

import pytest

from wynntools import storagesort as ss
from wynntools.inventory import Inventory


def slot(n, name, kind="other", sig=None, count=1, **extra):
    out = {"slot": n, "name": name, "kind": kind, "sig": sig or f"sig-{name}-{n}", **extra}
    if count != 1:
        out["count"] = count
    return out


def chest(pages, place="account", inventory=()):
    """An inventory with one chest ({page: [slots]}) and character c1's inventory."""
    places = {place: {"pages": {str(p): {"updated": "", "slots": list(s)} for p, s in pages.items()}},
              "inventory:c1": {"pages": {"1": {"updated": "", "slots": list(inventory)}}}}
    return Inventory(places=places, characters={"c1": {"name": "", "seen": "2026-10-01T10:00:00"}})


def test_groups_come_from_the_data_and_from_names(gd):
    ingredient = "Ancient Spring Water"                  # in WynnBuilder's ingredient list
    want = {
        ("Galleon", "item"): "armor:boots", ("Spring", "item"): "weapon:archer",
        ("Thunder Powder II", "other"): "powder", (ingredient, "other"): "ingredient",
        ("Copper Ingot", "other"): "material", ("Potions of Healing [10/30]", "other"): "consumable",
        ("Emerald Pouch [Tier 7]", "other"): "emerald", ("Broken Ice Barrows Key", "other"): "key",
        ("Corrupted Arakadicus' Eye", "other"): "key", ("Corrupted Potato", "other"): "misc",
        ("Nii Rune", "other"): "rune", ("Golden Pickaxe T5", "other"): "tool",
        ("Wyvern Reins", "other"): "mount", ("Unidentified Helmet", "other"): "unidentified",
        ("Snake Symbol", "other"): "misc",
    }
    got = {k: ss.describe(gd, {"name": k[0], "kind": k[1]})["group"] for k in want}
    assert got == want
    tome = next(iter(gd.tome_by_name))
    assert ss.describe(gd, {"name": tome, "kind": "tome"})["group"] == "tome"
    assert ss.describe(gd, {"name": "Aspect of X", "kind": "aspect", "cls": "Mage", "tier": 2})["class"] == "Mage"


def test_rule_typos_are_refused():
    errors = ss.validate_rules({"acount": {}, "account": {"groups": [
        {"name": "Mythics", "match": {"teir": "Mythic"}},
        {"name": "Mage", "match": {"class": "Wizard"}},
        {"name": "Bad", "match": {"name": "(unclosed"}},
        {"name": "Empty"},
        {"name": "Odd", "match": {"tier": "mythic"}, "page": 1}]}})
    text = "\n".join(errors)
    for bit in ("unknown chest 'acount'", "unknown match key 'teir'", "unknown class 'Wizard'",
                "name must be a pattern", "'Empty': needs a \"match\"", "unknown key 'page'"):
        assert bit in text
    assert "mythic" not in text.replace("'Mythics'", "")              # choices ignore case
    assert ss.validate_rules({"character": {"groups": [{"name": "Lows", "match": {"level": [1, 50]}}],
                                            "keep_pages": [1]}}) == []


def test_rules_come_first_then_the_default_order(gd):
    inv = chest({1: [slot(0, "Copper Ingot"), slot(1, "Galleon", "item"), slot(2, "Spring", "item"),
                     slot(3, "Nii Rune")]})
    rules = {"groups": [{"name": "Runes first", "match": {"name": "Rune$"}}]}
    layout = ss.target_layout(gd, inv, "account", rules)
    order = [layout.things[k].entry["name"] for k, _ in sorted(layout.dest.items(), key=lambda kv: kv[1])]
    assert order == ["Nii Rune", "Spring", "Galleon", "Copper Ingot"]
    # each group starts a new row
    assert sorted(layout.dest.values()) == [(1, 0), (1, 9), (1, 18), (1, 27)]
    assert layout.page_groups() == {1: ["Runes first", "Archer weapons", "Boots", "Crafting materials"]}


def test_kept_pages_stay_as_they_are(gd):
    inv = chest({1: [slot(5, "Nii Rune")], 2: [slot(0, "Copper Ingot")], 3: [slot(7, "Snake Symbol")]})
    layout = ss.target_layout(gd, inv, "account", {"keep_pages": [1]})
    assert layout.kept == [1] and layout.pages == [2, 3]
    assert (1, 5) not in layout.dest
    assert set(layout.dest.values()) <= {(p, s) for p in (2, 3) for s in range(45)}


def test_a_full_chest_packs_groups_together(gd):
    names = ["Copper Ingot", "Nii Rune", "Snake Symbol", "Wyvern Reins", "Golden Pickaxe T5"]
    inv = chest({1: [slot(n, names[n % 4]) for n in range(45)]})      # 12, 11, 11, 11: rows would need 8
    layout = ss.target_layout(gd, inv, "account")
    assert layout.packing == "dense" and len(layout.dest) == 45
    assert sorted(layout.dest.values()) == [(1, s) for s in range(45)]


def test_a_group_can_ask_for_its_own_page(gd):
    inv = chest({1: [slot(0, "Copper Ingot"), slot(1, "Nii Rune")], 2: []})
    rules = {"groups": [{"name": "Runes", "match": {"group": "rune"}},
                        {"name": "Mats", "match": {"group": "material"}, "new_page": True}]}
    layout = ss.target_layout(gd, inv, "account", rules)
    assert layout.page_groups() == {1: ["Runes"], 2: ["Mats"]}


def test_missing_pages_and_old_exports_stop_the_mod_but_still_preview(gd):
    inv = chest({1: [slot(3, "Nii Rune")], 3: [slot(0, "Copper Ingot")]})
    for p in inv.places["account"]["pages"].values():
        for s in p["slots"]:
            del s["sig"]
    pl = ss.plan(gd, inv, "account")
    assert not pl["ready"] and pl["moves"] == 2
    assert any("pages 2 haven't been exported" in p for p in pl["problems"])
    assert any("older chest-export mod" in p for p in pl["problems"])


def test_needs_two_free_inventory_slots(gd):
    full = [slot(n, f"junk{n}") for n in range(13, 35)]
    inv = chest({1: [slot(3, "Nii Rune"), slot(0, "Copper Ingot")]}, inventory=full)
    pl = ss.plan(gd, inv, "account")
    assert pl["buffer"] == [] and pl["reserve"] == 35 and not pl["ready"]
    assert any("empty at least 2 slots" in p for p in pl["problems"])


def test_a_sorted_chest_needs_nothing(gd):
    inv = chest({1: [slot(0, "Spring", "item"), slot(9, "Galleon", "item")]})
    pl = ss.plan(gd, inv, "account")
    assert pl["moves"] == 0 and pl["steps"] == [] and not pl["ready"] and pl["problems"] == []


NAMES = ["Copper Ingot", "Nii Rune", "Snake Symbol", "Wyvern Reins", "Golden Pickaxe T5", "Galleon",
         "Spring", "Thunder Powder II", "Potions of Healing [10/30]", "Broken Ice Barrows Key",
         "Unidentified Helmet", "Emerald Pouch [Tier 7]"]


def _random_chest(rng, pages, fill):
    out = {}
    for p in range(1, pages + 1):
        slots = []
        for s in range(45):
            if rng.random() < fill:
                name = rng.choice(NAMES)
                kind = "item" if name in ("Galleon", "Spring") else "other"
                # a few stacks alike (same sig) with different counts: they would merge if clicked together
                sig = f"{name}#{rng.randrange(3)}" if kind == "other" else f"{name}#{p}.{s}"
                slots.append(slot(s, name, kind, sig=sig, count=rng.randint(1, 3) if kind == "other" else 1))
        out[p] = slots
    return out


@pytest.mark.parametrize("seed", range(30))
def test_every_plan_reaches_the_sorted_chest_without_losing_anything(gd, seed):
    rng = random.Random(seed)
    pages = rng.randint(1, 6)
    inv = chest(_random_chest(rng, pages, rng.choice([0.2, 0.6, 0.95])))
    buffer = rng.sample(list(ss.BUFFER_SLOTS), rng.randint(2, 20))
    keep = [rng.randint(1, pages)] if pages > 1 and rng.random() < 0.3 else []
    rules = {"keep_pages": keep, "groups": [{"name": "Rings and runes", "match": {"name": "Rune|Pickaxe"}}]}
    pl = ss.plan(gd, inv, "account", rules, start_page=rng.randint(1, pages), buffer=sorted(buffer))
    layout = ss.target_layout(gd, inv, "account", rules)

    start = {p: {n: [e["sig"], e.get("count", 1), e["name"]] for n, e in slots.items()}
             for p, slots in ss.chest_pages(inv, "account").items()}
    first = next((s["page"] for s in pl["steps"] if s["op"] == "page"), 1)
    end, carried = ss.simulate(start, {}, pl["steps"], first)

    assert carried == {}                                         # nothing left in the inventory
    assert pl["reserve"] not in {s["slot"] for s in pl["steps"] if s["op"] == "click" and s["area"] == "inv"}

    def stacks(pages):
        return sorted(tuple(v[:2]) for slots in pages.values() for v in slots.values())
    assert stacks(end) == stacks(start)                          # nothing lost or doubled
    for page in keep:
        assert end.get(page, {}) == start.get(page, {})          # kept pages untouched
    want = {to: layout.things[now].sig for now, to in layout.dest.items()}
    got = {(p, s): v[0] for p, slots in end.items() for s, v in slots.items() if p not in keep}
    assert got == want                                           # every slot holds what it should
    assert pl["ready"] == (pl["moves"] > 0)


def test_the_real_shape_of_a_plan(gd):
    inv = chest({1: [slot(0, "Copper Ingot"), slot(1, "Spring", "item")], 2: [slot(0, "Galleon", "item")]})
    pl = ss.plan(gd, inv, "account", start_page=2)
    assert pl["ready"] and pl["layout"] == {"1": ["Archer weapons", "Boots", "Crafting materials"]}
    assert pl["steps"][0]["op"] == "page" and pl["steps"][0]["page"] == 2
    assert pl["steps"][0]["expect"] == [[0, "sig-Galleon-0", 1, "Galleon"]]
    click = pl["steps"][1]
    assert click == {"op": "click", "area": "chest", "slot": 0,
                     "slot_has": ["sig-Galleon-0", 1, "Galleon"], "cursor_has": None}
    assert [e["name"] for e in pl["sorted"]["1"]] == ["Spring", "Galleon", "Copper Ingot"]


def _walk(storage, inventory=()):
    """What the mod's Sort button sends: a walk through one chest."""
    return {"version": 2, "kind": "ender_all", "complete": ["account"], "character": {"id": "c1"},
            "storage": [], "inventory": list(inventory),
            "pages": [{"kind": "account", "page": 1, "storage": list(storage)}]}


def test_the_mod_gets_a_plan_from_the_export_it_sends(tmp_path):
    from fastapi.testclient import TestClient
    from wynntools.web.server import create_app
    client = TestClient(create_app(tmp_path, 8765, token="t"), base_url="http://127.0.0.1:8765",
                        headers={"x-wt-token": "t"})
    storage = [{"slot": 0, "name": "Copper Ingot", "count": 3, "sig": "a1", "lore": []},
               {"slot": 1, "name": "Spring", "sig": "b2", "lore": []}]
    r = client.post("/api/inventory/sort", json=_walk(storage)).json()
    plan = r["plan"]
    assert plan["place"] == "account" and plan["ready"] and plan["moves"] == 2
    assert plan["steps"][0] == {"op": "page", "page": 1, "expect": [[0, "a1", 3, "Copper Ingot"],
                                                                    [1, "b2", 1, "Spring"]]}
    assert r["message"].startswith("2 items to move")
    # the import was saved, with the mod's ids for each stack
    saved = client.get("/api/inventory").json()
    slots = next(p for p in saved["place_list"] if p["key"] == "account")["pages"]["1"]["slots"]
    assert {s["name"]: s["sig"] for s in slots} == {"Copper Ingot": "a1", "Spring": "b2"}
    # the app's preview leaves the clicks out
    preview = client.get("/api/inventory/sort-plan", params={"place": "account"}).json()
    assert "steps" not in preview and preview["layout"] == {"1": ["Archer weapons", "Crafting materials"]}
    assert client.get("/api/inventory/sort-plan", params={"place": "inventory:c1"}).status_code == 409
    # only a walk through one chest can be sorted from
    assert client.post("/api/inventory/sort", json={**_walk(storage), "complete": []}).status_code == 422


def test_sorting_rules_round_trip_through_the_inventory_file(tmp_path):
    from wynntools import inventory
    inv = inventory.Inventory(sorting={"account": {"groups": [{"name": "M", "match": {"tier": "Mythic"}}]}})
    inventory.save(inv, tmp_path / "inventory.json")
    assert inventory.load(tmp_path / "inventory.json").sorting == inv.sorting
    inventory.save(inventory.Inventory(), tmp_path / "plain.json")
    assert "sorting" not in (tmp_path / "plain.json").read_text()


def test_wt_chest_saves_checked_rules_and_plans(tmp_path, capsys, monkeypatch):
    import json
    from wynntools import cli, inventory
    path = tmp_path / "inventory.json"
    inventory.save(chest({1: [slot(0, "Copper Ingot"), slot(1, "Nii Rune")]}), path)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"groups": [{"name": "Runes", "match": {"grup": "rune"}}]}))
    with pytest.raises(SystemExit) as out:
        cli.main(["chest", "rules", "--place", "account", "--set", str(bad), "--inventory", str(path)])
    assert out.value.code == 1 and "unknown match key 'grup'" in capsys.readouterr().out
    assert inventory.load(path).sorting == {}
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"groups": [{"name": "Runes", "match": {"group": "rune"}}]}))
    with pytest.raises(SystemExit):
        cli.main(["chest", "rules", "--place", "account", "--set", str(good), "--inventory", str(path)])
    assert inventory.load(path).sorting == {"account": {"groups": [{"name": "Runes", "match": {"group": "rune"}}]}}
    capsys.readouterr()
    with pytest.raises(SystemExit):
        cli.main(["chest", "plan", "--inventory", str(path)])
    text = capsys.readouterr().out
    assert "page  1 (2/45): Runes, Crafting materials" in text and "2 items move" in text
