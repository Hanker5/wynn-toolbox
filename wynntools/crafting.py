"""Crafted items: stats, validity and link encoding.

Port of js/craft.js (Craft.initCraftStats, encodeCraft, decodeCraft) and the
ingredient setup in js/load_ing.js. tests/test_differential.py checks it against
WynnBuilder's own JavaScript.

A crafted item is named by its hash, "CR-<base64>", the same way WynnBuilder
does, so it can sit in a build's equipment list next to normal item names.
"""
import math
from dataclasses import dataclass

from .bits import BitReader, BitWriter
from .data import LATEST, load
from .rules import ROLLED_IDS, SKILLS, js_round

NO_INGREDIENT = "No Ingredient"
RECIPE_TYPES = ["HELMET", "CHESTPLATE", "LEGGINGS", "BOOTS", "RELIK", "WAND", "SPEAR",
                "DAGGER", "BOW", "RING", "NECKLACE", "BRACELET", "POTION", "SCROLL", "FOOD"]
WEAPON_TYPES = {"wand", "bow", "dagger", "spear", "relik"}
ARMOR_TYPES = {"helmet", "chestplate", "leggings", "boots"}
ACCESSORY_TYPES = {"ring", "bracelet", "necklace"}
CONSUMABLE_TYPES = {"potion", "scroll", "food"}
GEAR_SKILLS = ["ARMOURING", "TAILORING", "WEAPONSMITHING", "WOODWORKING", "JEWELING"]
ALL_SKILLS = GEAR_SKILLS + ["COOKING", "ALCHEMISM", "SCRIBING"]

# js/craft.js CRAFTER_ENC
ATK_SPD = {"SLOW": 0, "NORMAL": 1, "FAST": 2}
ATK_SPD_BITLEN = 4
MAT_TIER_BITLEN = 3
ING_ID_BITLEN = 12
RECIPE_ID_BITLEN = 12
CRAFT_VERSION_BITLEN = 7
CRAFT_ENCODING_VERSION = 2
TIER_MULT = [0, 1, 1.25, 1.4]
# js/load_ing.js: powders usable as ingredients, (durability, requirement) per tier
POWDER_ING = [(-35, 0), (-52.5, 0), (-70, 10), (-91, 20), (-112, 28), (-133, 36), (-154, 44)]
POWDER_CLASSES = ["Earth", "Thunder", "Water", "Fire", "Air"]
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII"]
# ingFields: every rolled ID plus the five skill-point IDs
ING_FIELDS = ROLLED_IDS | set(SKILLS)


@dataclass
class Craft:
    recipe: str                 # e.g. "Ring-103-105"
    ingredients: list           # 6 ingredient names; NO_INGREDIENT for an empty slot
    mat_tiers: tuple = (3, 3)   # material tiers, 1-3 each
    atk_spd: str = "NORMAL"     # weapons only


class CraftData:
    """Ingredients and recipes, set up the way js/load_ing.js init_maps does."""

    def __init__(self, version=LATEST):
        ings = [dict(i) for i in load("ingreds", version)]
        extra = [{"name": NO_INGREDIENT, "displayName": NO_INGREDIENT, "tier": 0, "lvl": 0,
                  "skills": list(ALL_SKILLS), "ids": {},
                  "itemIDs": {"dura": 0, **{f"{s}Req": 0 for s in SKILLS}},
                  "consumableIDs": {"dura": 0, "charges": 0},
                  "posMods": {k: 0 for k in ("left", "right", "above", "under", "touching", "notTouching")},
                  "id": 4000}]
        for e in range(5):
            for t in range(7):
                dura, req = POWDER_ING[t]
                name = f"{POWDER_CLASSES[e]} Powder {ROMAN[t]}"
                item_ids = {"dura": dura, **{f"{s}Req": 0 for s in SKILLS}}
                item_ids[f"{SKILLS[e]}Req"] = req
                extra.append({"name": name, "displayName": name, "tier": 0, "lvl": 0,
                              "skills": list(GEAR_SKILLS), "ids": {}, "isPowder": True,
                              "pid": 7 * e + t, "itemIDs": item_ids,
                              "consumableIDs": {"dura": 0, "charges": 0},
                              "posMods": dict(extra[0]["posMods"]), "id": 4001 + 7 * e + t})
        for i in ings:
            i.setdefault("displayName", i["name"])
        self.ingredients = extra + ings
        self.ing_by_name = {i["displayName"]: i for i in self.ingredients}
        self.ing_by_id = {i["id"]: i for i in self.ingredients}
        self.recipes = load("recipes", version)["recipes"]
        self.recipe_by_name = {r["name"]: r for r in self.recipes}
        self.recipe_by_id = {r["id"]: r for r in self.recipes}

    def recipes_for(self, item_type):
        return [r for r in self.recipes if r["type"] == item_type.upper()]


def ingredient_sources(ing):
    """Mobs that drop an ingredient, from WynnBuilder's `droppedBy`, merged by mob:
    [{"mob": name, "spots": [[x, y, z, radius], ...]}]. A mob listed without
    coordinates gets no spots. An empty list means the data names no mob (it may
    come from somewhere else, such as a merchant, quest or gathering)."""
    out = {}
    for d in ing.get("droppedBy") or []:
        entry = out.setdefault(d["name"], {"mob": d["name"], "spots": []})
        c = d.get("coords")
        spots = c if isinstance(c, list) and c and isinstance(c[0], list) else \
            [c] if isinstance(c, list) and c else []
        for s in spots:
            if s not in entry["spots"]:
                entry["spots"].append(s)
    return list(out.values())


def source_line(ing, max_mobs=3):
    """One human line: "Tribal Exile (1488, -1513), Rymek Citizen (1265, -1280) +9 spots"."""
    if ing.get("isPowder"):
        return "a powder (from mobs, or made at a Powder Master)"
    src = ingredient_sources(ing)
    if not src:
        return "no mob listed in WynnBuilder's data (merchant, quest or gathering?)"
    parts = []
    for e in src[:max_mobs]:
        if e["spots"]:
            x, _, z, *_ = e["spots"][0]
            n = len(e["spots"]) - 1
            more = f" +{n} spot{'s' if n > 1 else ''}" if n else ""
            parts.append(f"{e['mob']} ({x}, {z}){more}")
        else:
            parts.append(f"{e['mob']} (no location listed)")
    if len(src) > max_mobs:
        parts.append(f"{len(src) - max_mobs} more mob(s)")
    return ", ".join(parts)


# ------------------------------------------------------------------ stats

def _range(recipe, key):
    v = recipe.get(key)
    return [v["minimum"], v["maximum"]] if v else [0, 0]


def effectiveness(ings):
    """3x2 grid of ingredient effectiveness (%), flattened in slot order."""
    eff = [[100, 100], [100, 100], [100, 100]]
    for n, ing in enumerate(ings):
        i, j = n // 2, n % 2
        for key, value in ing["posMods"].items():
            if not value:
                continue
            if key == "above":
                for k in range(i - 1, -1, -1):
                    eff[k][j] += value
            elif key == "under":
                for k in range(i + 1, 3):
                    eff[k][j] += value
            elif key == "left":
                if j == 1:
                    eff[i][0] += value
            elif key == "right":
                if j == 0:
                    eff[i][1] += value
            elif key == "touching":
                for k in range(3):
                    for l in range(2):
                        if abs(k - i) + abs(l - j) == 1:
                            eff[k][l] += value
            elif key == "notTouching":
                for k in range(3):
                    for l in range(2):
                        if abs(k - i) > 1 or (abs(k - i) == 1 and abs(l - j) == 1):
                            eff[k][l] += value
    return [x for row in eff for x in row]


def craft_item(craft, cd):
    """Stats of a crafted item, shaped like a normal item dict.

    Rolled IDs are in item["rolls"][id] = (min, max); verify.stat reads them.
    Also returns craft problems (wrong profession, ingredient level too high,
    not enough durability) in item["problems"].
    """
    recipe = cd.recipe_by_name[craft.recipe]
    ings = [cd.ing_by_name[n] for n in craft.ingredients]
    typ = recipe["type"].lower()
    lvl = _range(recipe, "lvl")
    item = {"name": encode_craft_hash(craft, cd), "tier": "Crafted", "type": typ,
            "lvl": lvl[1], "lvlLow": lvl[0], "hp": 0, "hpLow": 0, "fixID": False,
            "craft": craft, "rolls": {}}
    item["displayName"] = item["name"]
    for s in SKILLS:
        item[f"{s}Req"] = 0
        item[s] = 0
    if typ in ARMOR_TYPES:
        item["category"] = "armor"
    elif typ in WEAPON_TYPES:
        item["category"] = "weapon"
    elif typ in ACCESSORY_TYPES:
        item["category"] = "accessory"
    else:
        item["category"] = "consumable"
    if typ in ARMOR_TYPES | WEAPON_TYPES:
        item["slots"] = 1 if lvl[0] < 30 else 2 if lvl[0] < 70 else 3

    amounts = [m["amount"] for m in recipe["materials"]]
    t0, t1 = craft.mat_tiers
    matmult = (TIER_MULT[t0] * amounts[0] + TIER_MULT[t1] * amounts[1]) / sum(amounts)
    low, high = _range(recipe, "healthOrDamage")
    durability = [js_round(d * matmult) for d in _range(recipe, "durability")]

    if item["category"] == "weapon":
        ratio = {"SLOW": 2.05 / 1.5, "NORMAL": 1, "FAST": 2.05 / 2.5}[craft.atk_spd]
        base_lo = math.floor(math.floor(low * matmult) * ratio)
        base_hi = math.floor(math.floor(high * matmult) * ratio)
        item["atkSpd"] = craft.atk_spd
        item["nDamBaseHigh"] = base_hi              # damage calc uses the high roll
        item["nDamLow"] = f"{math.floor(base_lo * 0.9)}-{math.floor(base_lo * 1.1)}"
        item["nDam"] = f"{math.floor(base_hi * 0.9)}-{math.floor(base_hi * 1.1)}"
    elif item["category"] == "armor":
        item["hp"] = math.floor(high * matmult)
        item["hpLow"] = math.floor(low * matmult)

    eff = effectiveness(ings)
    item["effectiveness"] = eff
    rolls = {}
    for n, ing in enumerate(ings):
        mult = eff[n] / 100          # JS uses (eff/100).toFixed(2); eff is an integer percent
        for key, value in ing["itemIDs"].items():
            if key != "dura" and item["category"] != "consumable":
                add = js_round(value) if ing.get("isPowder") else js_round(value * mult + 1e-9)
                item[key] = item.get(key, 0) + add
            else:
                durability = [d + value for d in durability]
        for key, rng in ing["ids"].items():
            if key not in ING_FIELDS or not rng.get("maximum"):
                continue
            a, b = sorted((math.floor(rng["minimum"] * mult), math.floor(rng["maximum"] * mult)))
            lo, hi = rolls.get(key, (0, 0))
            rolls[key] = (lo + a, hi + b)
    problems = []
    if any(d < 1 for d in durability):
        problems.append(f"needs {1 - min(durability)} more durability")
        durability = [max(0, math.floor(d)) for d in durability]
    else:
        durability = [math.floor(d) for d in durability]
    item["durability"] = durability
    for s in SKILLS:                      # skill points use the max roll
        item[s] = rolls.pop(s, (0, 0))[1]
    item["rolls"] = rolls
    for ing in ings:
        if recipe["skill"] not in ing["skills"]:
            problems.append(f"{ing['displayName']} cannot be used for {recipe['skill'].title()}")
        if (ing.get("lvl") or 0) > lvl[1]:
            problems.append(f"{ing['displayName']} is too high level for {lvl[0]}-{lvl[1]}")
    item["problems"] = problems
    return item


# ------------------------------------------------------------------ encoding

def write_craft(w, craft, cd):
    """Append a craft's bits (js encodeCraft), including its own padding."""
    start = len(w.bits)
    w.write(0, 1)                                     # 0 = current (non-legacy) format
    w.write(CRAFT_ENCODING_VERSION, CRAFT_VERSION_BITLEN)
    for name in craft.ingredients:
        w.write(cd.ing_by_name[name]["id"], ING_ID_BITLEN)
    recipe = cd.recipe_by_name[craft.recipe]
    w.write(recipe["id"], RECIPE_ID_BITLEN)
    for t in craft.mat_tiers:
        w.write(t - 1, MAT_TIER_BITLEN)
    if recipe["type"].lower() in WEAPON_TYPES:
        w.write(ATK_SPD[craft.atk_spd], ATK_SPD_BITLEN)
    # JS pads with 6 - (len % 6) bits, which is a full 6 when already aligned
    w.write(0, 6 - ((len(w.bits) - start) % 6))


def read_craft(r, cd):
    start = r.pos
    if r.read(1):
        raise NotImplementedError("legacy crafted-item hashes are not supported")
    r.read(CRAFT_VERSION_BITLEN)
    ings = [cd.ing_by_id[r.read(ING_ID_BITLEN)]["displayName"] for _ in range(6)]
    recipe = cd.recipe_by_id[r.read(RECIPE_ID_BITLEN)]
    tiers = tuple(r.read(MAT_TIER_BITLEN) + 1 for _ in range(2))
    atk = "NORMAL"          # unused for non-weapons (JS stores SLOW; it never matters)
    if recipe["type"].lower() in WEAPON_TYPES:
        atk = {v: k for k, v in ATK_SPD.items()}[r.read(ATK_SPD_BITLEN)]
    r.read(6 - ((r.pos - start) % 6))
    return Craft(recipe["name"], ings, tiers, atk)


def encode_craft_hash(craft, cd):
    w = BitWriter()
    write_craft(w, craft, cd)
    return "CR-" + w.to_b64()


def decode_craft_hash(name, cd):
    return read_craft(BitReader(name.removeprefix("CR-")), cd)
