"""WynnBuilder's damage and defence numbers: the builder page's right column.

A port of, in the order the builder page runs them:
  js/powders.js         calc_weapon_powder, applyArmorPowders
  js/builder/build.js   Build.initBuildStats (item, tome and set-bonus stats)
  js/builder/atree.js   atree_merge, atree_raw_stats, atree_make_interactives
                        (slider defaults only), atree_scaling, atree_collect_spells
  js/damage_calc.js     calculateSpellDamage
  js/builder/builder_graph.js  SpellDamageCalcNode, getDefenseStats
  js/display.js         getSpellCost and the averages in displaySpellDamage

Every function keeps WynnBuilder's evaluation order, including the quirks
(neutral conversion, rainbow raw, the relik's 0.6 class defence), which is the
order the Wynncraft developer guide "How Damage Is Calculated - Fruma Edition"
describes: base damage (melee) or base DPS (spells), conversions, elemental
additives, base modifiers (additive), master modifiers (multiplicative), then
the target's elemental defences (not modelled: they depend on the mob). One
deliberate difference from WynnBuilder: the Critical Damage Bonus ID multiplies
crit damage, as the guide says (WynnBuilder adds it). The live test
(tests/test_wynnbuilder_live.py) compares these numbers with the page itself.
Page toggles default to off (no potions, raid buffs, powder specials, radiance)
and ability sliders sit at their defaults, as when a link is first opened.
"""
import copy
import math

from .codec import POWDERABLE, SLOTS
from .rules import ATTACK_SPEED, ROLLED_IDS, SKILLS, base_hp, js_round, sp_to_pct
from .verify import build_skillpoints, stat
from .skillpoints import set_bonus_stats

ATTACK_SPEEDS = ["SUPER_SLOW", "VERY_SLOW", "SLOW", "NORMAL", "FAST", "VERY_FAST", "SUPER_FAST"]
ATTACK_SPEED_NAMES = ["Super Slow", "Very Slow", "Slow", "Normal", "Fast", "Very Fast", "Super Fast"]
ELEMENTS = ["n", "e", "t", "w", "f", "a"]          # neutral + skp_elements
DAMAGE_CLASSES = ["Neutral", "Earth", "Thunder", "Water", "Fire", "Air"]
SKILLPOINT_DAMAGE_MULT = [1, 1, 1, 0.867, 0.951]
SKILLPOINT_FINAL_MULT = [1, 1, 0.5 / sp_to_pct(150), 0.867, 0.951]
CLASS_DEFENSE = {"relik": 0.60, "bow": 0.70, "wand": 0.80, "dagger": 1.0, "spear": 1.0}
WEAPON_CLASS = {"wand": "Mage", "bow": "Archer", "dagger": "Assassin", "spear": "Warrior",
                "relik": "Shaman"}

STATIC_IDS = ["hp", "eDef", "tDef", "wDef", "fDef", "aDef", "str", "dex", "int", "def", "agi",
              "damMobs", "defMobs"]
MUST_IDS = [f"{e}{k}" for e in "etwfan" for k in
            ("MdPct", "MdRaw", "SdPct", "SdRaw", "DamPct", "DamRaw", "DamAddMin", "DamAddMax")] + \
    ["mdPct", "mdRaw", "sdPct", "sdRaw", "damPct", "damRaw", "damAddMin", "damAddMax",
     "rMdPct", "rMdRaw", "rSdPct", "rSdRaw", "rDamPct", "rDamRaw", "rDamAddMin", "rDamAddMax",
     "healPct", "critDamPct"]
MULT_MAPS = ("damMult", "defMult", "healMult", "manaMult")
NONSTACKING = ("Potion", "Vulnerability", "Mask")

# js/powders.js powderStats: (min, max, convert %, defPlus, defMinus), 7 tiers per element ETWFA
POWDER_STATS = [
    (4, 5, 17, 2, 1), (6, 7, 21, 5, 2), (7, 9, 25, 9, 3), (8, 9, 31, 14, 4), (9, 11, 38, 22, 7),
    (11, 12, 46, 29, 7), (12, 14, 52, 37, 12),
    (1, 8, 9, 2, 1), (1, 12, 11, 4, 1), (2, 14, 13, 8, 2), (2, 15, 17, 13, 3), (3, 17, 22, 20, 5),
    (4, 19, 28, 28, 6), (5, 21, 32, 36, 11),
    (3, 4, 13, 3, 1), (5, 6, 15, 6, 1), (6, 8, 17, 11, 3), (7, 8, 21, 16, 4), (8, 10, 26, 23, 6),
    (10, 13, 32, 32, 10), (11, 15, 38, 40, 15),
    (2, 5, 14, 3, 1), (4, 7, 16, 6, 1), (5, 9, 19, 10, 2), (6, 9, 24, 15, 3), (7, 11, 30, 22, 5),
    (9, 14, 37, 31, 9), (10, 16, 44, 39, 14),
    (2, 6, 11, 3, 1), (3, 9, 14, 6, 2), (4, 11, 17, 10, 3), (5, 11, 22, 16, 5), (7, 12, 28, 23, 7),
    (8, 15, 35, 30, 8), (9, 17, 42, 38, 13),
]
POWDER_ARMOR_HP = [5, 10, 20, 30, 45, 60, 75]
# js/powders.js powderSpecialStats, ETWFA: the weapon special (name, burst damage %
# and damage boost % per power 1-7) and the armor special (name, and the cap on
# its "% <element> Dmg Boost" slider in builder.js).
POWDER_SPECIALS = [
    {"weapon": "Quake", "damage": [240, 280, 320, 360, 400, 440, 480], "boost": None,
     "armor": "Rage", "cap": 300},
    {"weapon": "Chain Lightning", "damage": [200, 225, 250, 275, 300, 325, 350], "boost": None,
     "armor": "Kill Streak", "cap": 200},
    {"weapon": "Curse", "damage": None, "boost": [10, 12.5, 15, 17.5, 20, 22.5, 25],
     "armor": "Concentration", "cap": 120},
    {"weapon": "Courage", "damage": [110, 125, 140, 155, 170, 185, 200],
     "boost": [10, 12.5, 15, 17.5, 20, 22.5, 25], "armor": "Endurance", "cap": 120},
    {"weapon": "Wind Prison", "damage": None, "boost": [100, 125, 150, 175, 200, 225, 250],
     "armor": "Dodge", "cap": 120},
]
SPECIAL_BY_NAME = {sp["weapon"]: (i, sp) for i, sp in enumerate(POWDER_SPECIALS)}
# Shaman summons: the spells whose headline is a summon's DPS (their names in
# WynnBuilder's tree data). "Total summon DPS" adds these up.
SUMMON_SPELLS = ("Puppet Damage", "Crimson Effigy", "Hummingbird's Song", "Patchwork Abomination")
PUPPET_SPELL = "Puppet Damage"


def powder_special(powders):
    """(element index 0-4, power 1-7) of the special a weapon's or armor piece's
    powders give, or None. Per the developer guide: two or more tier IV+
    powders of one element give that element's special; with pairs of several
    elements, the element of the first qualifying powder wins; the power comes
    from the two powders' tiers (IV+IV = 1, IV+V = 2, V+V or IV+VI = 3, ...,
    VII+VII = 7, i.e. the tiers' sum minus 7). With three or more of the element
    the two highest tiers count (the guide only covers pairs)."""
    good = [p for p in powders if p % POWDER_TIERS + 1 >= 4]
    for p in good:
        e = p // POWDER_TIERS
        tiers = sorted((q % POWDER_TIERS + 1 for q in good if q // POWDER_TIERS == e), reverse=True)
        if len(tiers) >= 2:
            return e, tiers[0] + tiers[1] - 7
    return None


def build_specials(build, gd):
    """The powder specials a build's powders give: {"weapon": [name, power] or
    None, "armor": [{"slot", "name", "element", "power"}]}."""
    out = {"weapon": None, "armor": []}
    for slot_idx, pw in zip(POWDERABLE, build.powders):
        name = build.equipment[slot_idx]
        if not name or not pw:
            continue
        got = powder_special(list(pw)[:gd.item(name).get("slots") or 0])
        if got is None:
            continue
        e, power = got
        if slot_idx == 8:
            out["weapon"] = [POWDER_SPECIALS[e]["weapon"], power]
        else:
            out["armor"].append({"slot": SLOTS[slot_idx], "name": POWDER_SPECIALS[e]["armor"],
                                 "element": SKP_ELEMENTS[e], "power": power})
    return out


def check_specials(specials):
    """Raise ValueError unless `specials` is None or {"weapon": [name, power] or
    None, "armor": {"e"|"t"|"w"|"f"|"a": percent}} within WynnBuilder's limits."""
    if not specials:
        return
    w = specials.get("weapon")
    if w:
        name, power = w
        if name not in SPECIAL_BY_NAME:
            raise ValueError(f"unknown weapon powder special {name!r}; "
                             f"one of {', '.join(SPECIAL_BY_NAME)}")
        if not 1 <= int(power) <= 7:
            raise ValueError(f"{name} power must be 1-7, not {power}")
    for e, v in (specials.get("armor") or {}).items():
        if e not in SKP_ELEMENTS:
            raise ValueError(f"armor special element must be one of e t w f a, not {e!r}")
        cap = POWDER_SPECIALS[SKP_ELEMENTS.index(e)]["cap"]
        if not 0 <= v <= cap:
            raise ValueError(f"{POWDER_SPECIALS[SKP_ELEMENTS.index(e)]['armor']} boost must be "
                             f"0-{cap}%, not {v}")
POWDER_TIERS = 7
SKP_ELEMENTS = ELEMENTS[1:]


# ------------------------------------------------------------------ small helpers

def merge_stat(stats, name, value):
    """js/build_utils.js merge_stat: add, except the multiplier maps and the
    non-stacking multipliers (highest wins)."""
    parts = name.split(".")
    start = parts[0]
    end = parts[1] if len(parts) > 1 else None
    if start in MULT_MAPS:
        sub = stats.setdefault(start, {})
        if isinstance(value, dict):
            for k, v in value.items():
                merge_stat(sub, k, v)
            return
        if end in NONSTACKING and end in sub:
            if value > sub[end]:
                sub[end] = value
            return
        merge_stat(sub, name[name.index(".") + 1:], value)
        return
    if name in stats:
        stats[name] = stats[name] + value
    else:
        stats[name] = value


def translate(tree, v):
    """atree_translate: "abilityId.prop" reads a (merged) ability property."""
    if isinstance(v, str):
        id_str, prop = v.split(".")
        return tree[int(id_str)]["properties"].get(prop)
    return v


def round_near(x):
    r = js_round(x)
    return r if abs(x - r) < 1e-8 else x


def raw_to_pct(raw, pct):
    if raw < 0:
        return min(0, raw - raw * pct)
    if raw > 0:
        return raw + raw * pct
    return 0


def raw_to_pct_uncapped(raw, pct):
    if raw < 0:
        return raw - raw * pct
    if raw > 0:
        return raw + raw * pct
    return 0


def _damage_range(s):
    if not isinstance(s, str) or "-" not in s:
        return [0, 0]
    lo, hi = s.split("-")
    return [float(lo) if "." in lo else int(lo), float(hi) if "." in hi else int(hi)]


# ------------------------------------------------------------------ powders

def weapon_powder_damage(weapon, powders, ingred_powders=(), base=None):
    """calc_weapon_powder: per element [min, max] after powders, and which are present.
    `base` (crafted weapons) replaces neutral with floor(base*0.9)..floor(base*1.1);
    `ingred_powders` are a crafted weapon's powder ingredients (half strength)."""
    damages = [_damage_range(weapon.get(f"{e}Dam")) for e in ELEMENTS]
    if base is not None:
        damages[0] = [math.floor(base * 0.9), math.floor(base * 1.1)]
    neutral = damages[0][:]
    order, info = [], {}

    def add(element, conv, mn, mx):
        if element in info:
            a = info[element]
            a[0] += conv
            a[1] += mn
            a[2] += mx
        else:
            order.append(element)
            info[element] = [conv, mn, mx]

    for pid in powders:
        p = POWDER_STATS[pid]
        add(pid // POWDER_TIERS, p[2] / 100, p[0], p[1])
    for pid in ingred_powders:
        p = POWDER_STATS[pid]
        add(pid // POWDER_TIERS, p[2] / 100 / 2, math.floor(p[0] / 2), math.floor(p[1] / 2))
    for element in order:
        conv, mn, mx = info[element]
        min_diff = min(neutral[0], conv * neutral[0])
        max_diff = min(neutral[1], conv * neutral[1])
        neutral[0] -= min_diff
        neutral[1] -= max_diff
        damages[element + 1][0] += min_diff
        damages[element + 1][1] += max_diff
        damages[element + 1][0] += mn
        damages[element + 1][1] += mx
    damages[0] = neutral
    return damages, [d[1] > 0 for d in damages]


def _ingred_powders(item, gd):
    craft = item.get("craft")
    if not craft:
        return []
    cd = gd.crafts
    return [cd.ing_by_name[n]["pid"] for n in craft.ingredients
            if cd.ing_by_name[n].get("isPowder")]


def weapon_stats(item, powders, gd):
    """The weapon's damage ranges with powders (what calculateSpellDamage reads).
    Crafted weapons use their high-roll base, as WynnBuilder does."""
    powders = list(powders)[:item.get("slots") or 0]
    if item.get("tier") == "Crafted":
        dam, present = weapon_powder_damage(item, powders, _ingred_powders(item, gd),
                                            base=item["nDamBaseHigh"])
    else:
        dam, present = weapon_powder_damage(item, powders)
    return {"damages": dam, "present": present, "atkSpd": item.get("atkSpd"),
            "type": item.get("type")}


def armor_powder_stats(item, powders):
    """applyArmorPowders: +def to the powder's element, -def to the one before it
    (cycle ETWFA), and flat health by tier."""
    out = {}
    for pid in list(powders)[:item.get("slots") or 0]:
        p = POWDER_STATS[pid]
        e = pid // POWDER_TIERS
        name, prev = SKP_ELEMENTS[e], SKP_ELEMENTS[(e + 4) % 5]
        out[name + "Def"] = out.get(name + "Def", 0) + p[3]
        out[prev + "Def"] = out.get(prev + "Def", 0) - p[4]
        out["hp"] = out.get("hp", 0) + POWDER_ARMOR_HP[pid % POWDER_TIERS]
    return out


# ------------------------------------------------------------------ build stats

def build_stats(build, gd, roll="max", inventory=None):
    """Build.initBuildStats plus the editable-ID step: the stat map every later
    step reads. `roll` "max" is what WynnBuilder shows; inventory rolls win."""
    from .inventory import with_rolls
    sp = build_skillpoints(build.equipment, build.tomes, gd)
    stats = {k: 0 for k in STATIC_IDS + MUST_IDS}
    stats["hp"] = base_hp(build.level)
    stats["agiDef"] = 90
    majors = set()
    powders = dict(zip(POWDERABLE, build.powders))
    objs = []
    for idx, name in enumerate(build.equipment[:8]):
        if name is not None:
            objs.append((with_rolls(gd.item(name), inventory.rolls(name) if inventory else None),
                         powders.get(idx, [])))
    for t in build.tomes:
        if t is not None:
            objs.append((gd.tome(t), []))
    weapon_name = build.equipment[8]
    if weapon_name is not None:
        objs.append((with_rolls(gd.item(weapon_name),
                                inventory.rolls(weapon_name) if inventory else None), []))
    for obj, pw in objs:
        for key in ROLLED_IDS:
            v = stat(obj, key, roll)
            if v:
                stats[key] = stats.get(key, 0) + v
        armor = armor_powder_stats(obj, pw) if obj.get("category") == "armor" and pw else {}
        for key in STATIC_IDS:
            v = obj.get(key) or 0
            if isinstance(v, (dict, str)):
                v = 0
            v += armor.get(key, 0)
            if v:
                stats[key] += v
        majors.update(obj.get("majorIds") or [])
    stats["damMult"] = {"tome": stats["damMobs"]}
    stats["defMult"] = {"tome": stats["defMobs"]}
    set_stats, set_majors = set_bonus_stats(sp.set_counts, gd.sets)
    for key, v in set_stats.items():
        stats[key] = stats.get(key, 0) + v
    majors |= set_majors
    stats["activeMajorIDs"] = majors
    stats["poisonPct"] = 0
    stats["healMult"] = {}
    stats["manaMult"] = {}
    weapon = gd.item(weapon_name) if weapon_name else {}
    stats["atkSpd"] = weapon.get("atkSpd")
    from .verify import resolve_skillpoints
    for s, v in zip(SKILLS, resolve_skillpoints(build, gd).final):
        stats[s] = v
    stats["classDef"] = CLASS_DEFENSE.get(weapon.get("type"))
    return stats


# ------------------------------------------------------------------ ability tree

def sorted_tree(tree):
    """get_sorted_class_atree: WynnBuilder's merge order (Kosaraju SCC order)."""
    nodes = {n["id"]: {"ability": n, "children": [], "parents": []} for n in tree}
    head = None
    for n in tree:
        if not n["parents"]:
            head = nodes[n["id"]]
    for n in tree:
        node = nodes[n["id"]]
        for pid in n["parents"]:
            nodes[pid]["children"].append(node)
            node["parents"].append(nodes[pid])
    res, visited = [], set()

    def visit(u):
        if id(u) in visited:
            return
        visited.add(id(u))
        for c in u["children"]:
            if id(c) not in visited:
                visit(c)
        res.append(u)

    visit(head)
    res.reverse()
    assigned, out = set(), []

    def assign(node, scc):
        if id(node) in assigned:
            return
        scc.append(node)
        assigned.add(id(node))
        for p in node["parents"]:
            assign(p, scc)

    for node in res:
        if id(node) in assigned:
            continue
        scc = []
        assign(node, scc)
        out.extend(scc)
    return [n["ability"] for n in out]


DEFAULT_SPELLS = {
    "wand": {"type": "replace_spell", "name": "Wand Melee", "base_spell": 0, "scaling": "melee",
             "use_atkspd": False, "display": "Melee",
             "parts": [{"name": "Melee", "multipliers": [100, 0, 0, 0, 0, 0]}]},
    "spear": {"type": "replace_spell", "name": "Melee", "base_spell": 0, "scaling": "melee",
              "use_atkspd": False, "display": "Melee",
              "parts": [{"name": "Melee", "multipliers": [100, 0, 0, 0, 0, 0]}]},
    "bow": {"type": "replace_spell", "name": "Bow Shot", "base_spell": 0, "scaling": "melee",
            "use_atkspd": False, "display": "Single Shot",
            "parts": [{"name": "Single Shot", "multipliers": [100, 0, 0, 0, 0, 0]}]},
    "dagger": {"type": "replace_spell", "name": "Melee", "base_spell": 0, "scaling": "melee",
               "use_atkspd": False, "display": "Melee",
               "parts": [{"name": "Melee", "multipliers": [100, 0, 0, 0, 0, 0]}]},
    "relik": {"type": "replace_spell", "name": "Relik Melee", "base_spell": 0,
              "spell_type": "damage", "scaling": "melee", "use_atkspd": False, "display": "Total",
              "parts": [{"name": "Single Beam", "multipliers": [33, 0, 0, 0, 0, 0]},
                        {"name": "Total", "hits": {"Single Beam": 3}}]},
}
CLASS_WEAPON = {v: k for k, v in WEAPON_CLASS.items()}
MELEE_PROPS = {"Mage": {"range": 12}, "Warrior": {"range": 4}, "Archer": {"range": 9},
               "Assassin": {"range": 3}, "Shaman": {"range": 32.25, "speed": 0}}


def default_abilities(cls):
    melee = {"display_name": f"{cls} Melee", "id": 999, "desc": [f"{cls} basic attack."],
             "properties": dict(MELEE_PROPS[cls]), "effects": [DEFAULT_SPELLS[CLASS_WEAPON[cls]]]}
    mastery = {"display_name": "Elemental Mastery", "id": 998, "properties": {}, "effects": [],
               "desc": []}
    return [melee, mastery]


def merge_tree(cls, active, gd, aspects=(), majors=()):
    """atree_merge: active nodes (in WynnBuilder's order), then aspects, then the
    major IDs' abilities, each merged into its base ability. Returns {id: ability}."""
    merged = {}
    for a in default_abilities(cls):
        merged[a["id"]] = copy.deepcopy(a)

    def merge(abil):
        if "base_abil" in abil:
            base = merged.get(abil["base_abil"])
            if base is None:
                return
            desc = abil.get("desc")
            if desc:
                base["desc"] = base["desc"] + (desc if isinstance(desc, list) else [desc])
            base["effects"] = base["effects"] + copy.deepcopy(abil.get("effects") or [])
            for k, v in (abil.get("properties") or {}).items():
                base["properties"][k] = base["properties"][k] + v if k in base["properties"] else v
        else:
            a = copy.deepcopy(abil)
            if not isinstance(a.get("desc"), list):
                a["desc"] = [a.get("desc")]
            a.setdefault("properties", {})
            a.setdefault("effects", [])
            merged[abil["id"]] = a

    active = set(active)
    for node in sorted_tree(gd.tree(cls)):
        if node["id"] in active:
            merge(node)
    by_id = {a["id"]: a for a in gd.aspects(cls)} if aspects else {}
    for entry in aspects or ():
        if not entry:
            continue
        aid, tier = entry
        asp = by_id.get(aid)
        if asp is None:
            continue
        abils = asp["tiers"][tier - 1].get("abilities")
        for abil in abils or ():
            if all(d in active for d in abil.get("dependencies") or ()):
                merge(abil)
    for name in majors:
        mid = gd.majids.get(name)
        if not mid:
            continue
        for abil in mid.get("abilities") or ():
            if abil.get("class") in (cls, "Any") and \
                    all(d in active for d in abil.get("dependencies") or ()):
                merge(abil)
    return merged


def raw_tree_stats(merged):
    """atree_raw_stats: untoggled raw_stat "stat" bonuses."""
    out = {}
    for abil in merged.values():
        for eff in abil["effects"]:
            if eff.get("type") == "raw_stat" and not eff.get("toggle"):
                for b in eff["bonuses"]:
                    if b.get("type") == "stat":
                        merge_stat(out, b["name"], b["value"])
    return out


def interactives(merged):
    """atree_make_interactives without the DOM: sliders {name: {max, default, step,
    label}} and toggle names. Values used are the defaults unless overridden."""
    sliders, toggles = {}, {}
    to_process = [(e, a) for a in merged.values() for e in a["effects"]
                  if (e.get("type") == "stat_scaling" and e.get("slider") is True)
                  or (e.get("type") == "raw_stat" and e.get("toggle"))]
    unprocessed = []
    for _ in range(len(to_process)):
        for eff, abil in to_process:
            if eff.get("type") == "stat_scaling" and eff.get("slider") is True:
                name = eff["slider_name"]
                behavior = eff.get("behavior", "merge")
                if name in sliders:
                    info = sliders[name]
                    if behavior == "overwrite":
                        if "slider_max" in eff:
                            info["max"] = eff["slider_max"]
                        if "slider_default" in eff:
                            info["default"] = eff["slider_default"]
                        if "scaling" in eff:
                            for other in info["abil"]["effects"]:
                                if "scaling" in other and other is not eff and \
                                        other["output"]["name"] == eff["output"]["name"]:
                                    other["scaling"] = [0]
                        info["overwritten"] = True
                    elif not info.get("overwritten"):
                        info["max"] += eff.get("slider_max", 0)
                        if "slider_max_mult" in eff:
                            info["max_mult"] = (info.get("max_mult") or 1) * eff["slider_max_mult"]
                        info["default"] += eff.get("slider_default", 0)
                elif behavior == "merge":
                    sliders[name] = {"label": f"{name} ({abil['display_name']})",
                                     "max": eff.get("slider_max", 0),
                                     "default": eff.get("slider_default", 0),
                                     "step": eff.get("slider_step"), "abil": abil}
                else:
                    unprocessed.append((eff, abil))
            if eff.get("type") == "raw_stat" and eff.get("toggle"):
                toggles[eff["toggle"]] = abil
        if len(unprocessed) == len(to_process):
            break
        to_process, unprocessed = unprocessed, []
    for info in sliders.values():
        if info.get("max_mult") not in (None, 1):
            info["max"] = js_round(info["max"] * info["max_mult"])
    return sliders, toggles


def tree_scaling(merged, pre_stats, sliders, toggles, slider_values=None, toggles_on=()):
    """atree_scaling: property bonuses first, then stat bonuses. Returns
    (edited tree, added stats)."""
    slider_values = slider_values or {}
    edit = {k: copy.deepcopy(v) for k, v in merged.items()}
    out = {}

    def apply(bonus, value, only):
        typ = bonus.get("type")
        if only and typ != only:
            return
        if typ == "stat":
            merge_stat(out, bonus["name"], translate(edit, value))
        elif typ == "prop":
            target = edit.get(bonus.get("abil"))
            if target:
                props, name = target["properties"], bonus["name"]
                v = translate(edit, value)
                # a property the ability doesn't have is undefined in JS: NaN
                if bonus.get("mult", False):
                    props[name] = props.get(name, math.nan) * v
                else:
                    props[name] = props.get(name, math.nan) + v

    def total_of(eff):
        scaling = eff.get("scaling", [0])
        positive = eff.get("positive", True)
        total = 0
        if eff.get("slider", False):
            name = eff.get("slider_name")
            if eff.get("behavior", "merge") == "modify" and name not in sliders:
                return None
            val = slider_values.get(name, sliders[name]["default"])
            if eff.get("requirement", 0) > val:
                return None
            n = int(val - eff.get("requirement", 0))
            if eff.get("multiplicative"):
                total = (((100 + translate(edit, scaling[0])) / 100) ** n - 1) * 100
            else:
                total = n * translate(edit, scaling[0])
            positive = False
        else:
            for sc, inp in zip(scaling, eff.get("inputs", [])):
                if inp["type"] == "stat":
                    total += pre_stats.get(inp["name"], 0) * translate(edit, sc)
                elif inp["type"] == "prop":
                    target = edit.get(inp["abil"])
                    if target:
                        total += target["properties"][inp["name"]] * translate(edit, sc)
        total += translate(edit, eff.get("base", 0))
        return total, positive

    def process(only):
        for abil in merged.values():
            for eff in abil["effects"]:
                t = eff.get("type")
                if t == "raw_stat":
                    if eff.get("toggle"):
                        if eff["toggle"] not in toggles_on:
                            continue
                        for b in eff["bonuses"]:
                            apply(b, b.get("value"), only)
                    else:
                        for b in eff["bonuses"]:
                            if b.get("type") != "stat":
                                apply(b, b.get("value"), only)
                elif t == "stat_scaling":
                    if "output" not in eff:
                        continue
                    rnd = eff.get("round", not eff.get("slider"))
                    res = total_of(eff)
                    if res is None:
                        continue
                    total, positive = res
                    if rnd:
                        total = math.floor(round_near(total))
                    if positive and total < 0:
                        total = 0
                    if "max" in eff:
                        mx = translate(edit, eff["max"])
                        if mx > 0 and total > mx:
                            total = eff["max"]
                        if mx < 0 and total < mx:
                            total = eff["max"]
                    outs = eff["output"] if isinstance(eff["output"], list) else [eff["output"]]
                    for o in outs:
                        apply(o, total, only)

    process("prop")
    process("stat")
    return edit, out


def collect_spells(tree):
    """atree_collect_spells: replace_spell first, then add_spell_prop and
    convert_spell_conv in ability order. Returns {base_spell: spell}."""
    spells = {}
    for abil in tree.values():
        for eff in abil["effects"]:
            if eff.get("type") != "replace_spell":
                continue
            spell = spells.get(eff["base_spell"])
            if spell is not None:
                for k, v in eff.items():
                    spell[k] = copy.deepcopy(v)
            else:
                spell = copy.deepcopy(eff)
                spells[eff["base_spell"]] = spell
            for part in spell["parts"]:
                if "hits" in part:
                    for k in part["hits"]:
                        part["hits"][k] = translate(tree, part["hits"][k])
    for abil in tree.values():
        for eff in abil["effects"]:
            t = eff.get("type")
            if t == "add_spell_prop":
                base = eff["base_spell"]
                if base not in spells:
                    continue
                spell = spells[base]
                target = eff.get("target_part")
                behavior = eff.get("behavior", "merge")
                if "cost" in spell:
                    spell["cost"] = _js_plus(spell["cost"], eff.get("cost", 0))
                if eff.get("mana_gained"):
                    v = translate(tree, eff["mana_gained"])
                    spell["mana_gained"] = v if spell.get("mana_gained") is None \
                        else spell["mana_gained"] + v
                if "display" in eff:
                    spell["display"] = eff["display"]
                if target is None:
                    continue
                found = False
                for part in spell["parts"]:
                    if part["name"] != target:
                        continue
                    if "multipliers" in eff:
                        for i, v in enumerate(eff["multipliers"]):
                            if behavior == "overwrite":
                                part["multipliers"][i] = v
                            else:
                                part["multipliers"][i] += v
                    elif "power" in eff:
                        part["power"] = eff["power"] if behavior == "overwrite" \
                            else part["power"] + eff["power"]
                    elif "hits" in eff:
                        for k, v in eff["hits"].items():
                            v = translate(tree, v)
                            if behavior == "overwrite" or k not in part["hits"]:
                                part["hits"][k] = v
                            else:
                                part["hits"][k] += v
                    else:
                        raise ValueError("invalid spell add effect")
                    if "hide" in eff:
                        part["display"] = False
                    if "ignored_mults" in eff:
                        if "ignored_mults" in part:
                            part["ignored_mults"].append(eff["ignored_mults"])
                        else:
                            part["ignored_mults"] = eff["ignored_mults"]
                    found = True
                    break
                if not found and behavior == "merge":
                    new = copy.deepcopy(eff)
                    new["name"] = target
                    if "hits" in new:
                        for k in new["hits"]:
                            new["hits"][k] = translate(tree, new["hits"][k])
                    if "hide" in eff:
                        new["display"] = False
                    spell["parts"].append(new)
            elif t == "convert_spell_conv":
                spell = spells[eff["base_spell"]]
                idx = DAMAGE_CLASSES.index(eff["conversion"])
                every = eff["target_part"] == "all"
                for part in spell["parts"]:
                    if (every or part["name"] == eff["target_part"]) and "multipliers" in part:
                        conv = [part["multipliers"][0], 0, 0, 0, 0, 0]
                        conv[idx] = sum(part["multipliers"][1:6])
                        part["multipliers"] = conv
    return spells


def _js_plus(a, b):
    if isinstance(a, str) or isinstance(b, str):
        return f"{a}{b}"
    return a + b


# ------------------------------------------------------------------ damage

def calculate_spell_damage(stats, weapon, conversions, use_spell, ignore_speed=False,
                           part_filter=None, ignore_str=False, ignored_mults=()):
    """js/damage_calc.js calculateSpellDamage. Returns
    (normal_total, crit_total, per-element [nmin, nmax, cmin, cmax], conversions)."""
    weapon_damages = weapon["damages"]
    present = list(weapon["present"])
    conversions = list(conversions)
    if part_filter is not None:
        for i, e in enumerate(ELEMENTS):
            k = f"{e}ConvBase:{part_filter}"
            if k in stats:
                conversions[i] += stats[k]
    for i, e in enumerate(ELEMENTS):
        k = f"{e}ConvBase"
        if k in stats:
            conversions[i] += stats[k]

    damages = []
    neutral_convert = conversions[0] / 100
    if neutral_convert == 0:
        present = [False] * 6
    wmin = wmax = 0
    for d in weapon_damages:
        damages.append([d[0] * neutral_convert, d[1] * neutral_convert])
        wmin += d[0]
        wmax += d[1]
    total_convert = 0
    for i in range(1, 6):
        if conversions[i] > 0:
            f = conversions[i] / 100
            damages[i][0] += f * wmin
            damages[i][1] += f * wmax
            present[i] = True
            total_convert += f
    total_convert += conversions[0] / 100

    if not ignore_speed:
        m = ATTACK_SPEED[weapon["atkSpd"]]
        for d in damages:
            d[0] *= m
            d[1] *= m

    g = stats.get
    for i, e in enumerate(ELEMENTS):
        if present[i]:
            damages[i][0] += g(e + "DamAddMin", 0)
            damages[i][1] += g(e + "DamAddMax", 0)

    b = "Sd" if use_spell else "Md"
    skill_boost = [0] + [sp_to_pct(g(s, 0)) * SKILLPOINT_DAMAGE_MULT[i]
                         for i, s in enumerate(SKILLS)]
    static_boost = (g(b.lower() + "Pct", 0) + g("damPct", 0)) / 100
    total_min = total_max = 0
    save = []
    for i, e in enumerate(ELEMENTS):
        save.append(damages[i][:])
        total_min += damages[i][0]
        total_max += damages[i][1]
        boost = 1 + skill_boost[i] + static_boost + \
            (g(e + b + "Pct", 0) + g(e + "DamPct", 0)) / 100
        if i > 0:
            boost += (g("r" + b + "Pct", 0) + g("rDamPct", 0)) / 100
        damages[i][0] *= boost
        damages[i][1] *= boost
    elem_min = total_min - save[0][0]
    elem_max = total_max - save[0][1]

    prop_raw = g(b.lower() + "Raw", 0) + g("damRaw", 0)
    rainbow_raw = g("r" + b + "Raw", 0) + g("rDamRaw", 0)
    for i, e in enumerate(ELEMENTS):
        s, d = save[i], damages[i]
        raw = 0
        if present[i]:
            raw += g(e + b + "Raw", 0) + g(e + "DamRaw", 0)
        mn = mx = raw
        if total_max > 0:
            mn += (s[1] / total_max if total_min == 0 else s[0] / total_min) * prop_raw
            mx += (s[1] / total_max) * prop_raw
        if i != 0 and elem_max > 0:
            mn += (s[1] / elem_max if elem_min == 0 else s[0] / elem_min) * rainbow_raw
            mx += (s[1] / elem_max) * rainbow_raw
        d[0] += mn * total_convert
        d[1] += mx * total_convert

    str_boost = 1 if ignore_str else 1 + skill_boost[1]
    damage_mult = 1
    ele_mult = [1] * 6
    for k, v in stats["damMult"].items():
        if ":" in k and k.split(":")[1] != part_filter:
            continue
        if k in ignored_mults:
            continue
        if ";" in k:
            bonus = k.split(";")[1]
            if bonus == "m" and not use_spell:
                damage_mult *= 1 + v / 100
            elif bonus in ELEMENTS:
                ele_mult[ELEMENTS.index(bonus)] *= 1 + v / 100
        else:
            damage_mult *= 1 + v / 100
    # A crit adds +100% on top of Strength's bonus. The Critical Damage Bonus ID
    # is a master modifier on crits (multiplicative), per the developer guide
    # (knowledge/mechanics.md); WynnBuilder adds it to the +100% instead
    # (crit_mult = 1 + critDamPct/100 beside strBoost). A hit is never negative.
    crit_boost = str_boost if ignore_str else \
        (str_boost + 1) * max(0.0, 1 + g("critDamPct", 0) / 100)
    for i in range(6):
        damages[i][0] *= ele_mult[i]
        damages[i][1] *= ele_mult[i]
        conversions[i] *= ele_mult[i] * damage_mult

    norm, crit, results = [0, 0], [0, 0], []
    for d in damages:
        d[0] = max(d[0], 0)
        d[1] = max(d[1], 0)
        r = [d[0] * str_boost * damage_mult, d[1] * str_boost * damage_mult,
             d[0] * crit_boost * damage_mult, d[1] * crit_boost * damage_mult]
        results.append(r)
        norm[0] += r[0]
        norm[1] += r[1]
        crit[0] += r[2]
        crit[1] += r[3]
    return norm, crit, results, conversions


def spell_parts(stats, weapon, spell):
    """SpellDamageCalcNode: every part of one spell, totals resolved."""
    use_speed = spell.get("use_atkspd", True)
    use_spell = spell["scaling"] == "spell" if "scaling" in spell else True
    pending = {p["name"]: p for p in spell["parts"]}
    done = {}

    def ev(name):
        if name in done:
            return done[name]
        part = pending.get(name)
        if part is None:
            return None
        nonlocal use_spell, use_speed
        part_id = f"{spell['base_spell']}.{part['name']}"
        if "multipliers" in part:
            if "scaling" in part:
                use_spell = spell.get("scaling")
            if "use_atkspd" in part:
                use_speed = spell.get("scaling")
            norm, crit, res, mults = calculate_spell_damage(
                stats, weapon, part["multipliers"], use_spell, not use_speed, part_id,
                not part.get("use_str", True), part.get("ignored_mults", []))
            r = {"type": "damage", "normal_min": [x[0] for x in res],
                 "normal_max": [x[1] for x in res], "normal_total": norm,
                 "crit_min": [x[2] for x in res], "crit_max": [x[3] for x in res],
                 "crit_total": crit, "is_spell": use_spell, "multipliers": mults}
        elif "power" in part:
            heal = 1
            for k, v in stats["healMult"].items():
                if ":" in k and k.split(":")[1] != part_id:
                    continue
                heal *= 1 + v / 100
            heal *= 1 + stats.get("healPct", 0) / 100
            r = {"type": "heal", "heal_amount": part["power"] * defense_stats(stats)["hp"] * heal}
        else:
            keys = ["normal_min", "normal_max", "normal_total", "crit_min", "crit_max",
                    "crit_total", "multipliers"]
            r = {k: [0] * (2 if k.endswith("total") else 6) for k in keys}
            r["heal_amount"] = 0
            for sub_name, hits in part["hits"].items():
                sub = ev(sub_name)
                if not sub:
                    continue
                if r.get("type"):
                    if sub.get("type") != r["type"]:
                        raise ValueError("SpellCalc total subpart type mismatch")
                else:
                    r["type"] = sub.get("type")     # may stay undefined, as in JS
                eff = 1.0 / (math.floor(1.0 / hits * 20) * 0.05) if part.get("tick_rounding") \
                    else hits
                if r["type"] == "damage":
                    for k in keys:
                        for i in range(6):     # JS loops 6 indices; totals only have 2
                            if i < len(r[k]):
                                r[k][i] += sub[k][i] * eff
                else:
                    r["heal_amount"] += sub["heal_amount"] * eff
        r["name"] = part["name"]
        r["display"] = part.get("display", True)
        done[name] = r
        return r

    return [ev(p["name"]) for p in spell["parts"]]


def spell_cost(stats, spell, capped=True):
    """js/display.js getSpellCost."""
    n = spell["base_spell"]
    cost = spell["cost"] * (1 - sp_to_pct(stats.get("int", 0)) * SKILLPOINT_FINAL_MULT[2])
    cost += stats.get(f"spRaw{n}", 0)
    cost *= 1 + stats.get(f"spPct{n}", 0) / 100
    final = stats.get(f"spPct{n}Final", 0) / 100
    if capped:
        return max(1, cost) * (1 + final)
    if cost < 0:
        return cost + final
    return cost * (1 + final)


def defense_stats(stats):
    """builder_graph.js getDefenseStats."""
    def_pct = sp_to_pct(stats.get("def", 0)) * SKILLPOINT_FINAL_MULT[3]
    agi_pct = sp_to_pct(stats.get("agi", 0)) * SKILLPOINT_FINAL_MULT[4]
    hp = max(stats.get("hp", 0) + stats.get("hpBonus", 0), 5)
    def_mult = 2 - stats["classDef"]
    for v in stats["defMult"].values():
        def_mult *= 1 - v / 100
    agi_red = (100 - stats.get("agiDef", 90)) / 100
    with_agi = agi_red * agi_pct + (1 - agi_pct) * (1 - def_pct)
    hpr = raw_to_pct(stats.get("hprRaw", 0), stats.get("hprPct", 0) / 100)
    eledefs = [raw_to_pct_uncapped(stats.get(e + "Def", 0),
                                   (stats.get(e + "DefPct", 0) + stats.get("rDefPct", 0)) / 100)
               for e in SKP_ELEMENTS]
    return {"hp": hp,
            "ehp": hp / with_agi / def_mult, "ehp_no_agi": hp / (1 - def_pct) / def_mult,
            "hpr": hpr,
            "ehpr": hpr / with_agi / def_mult, "ehpr_no_agi": hpr / (1 - def_pct) / def_mult,
            "def_pct": def_pct * 100, "agi_pct": agi_pct * 100,
            "eledefs": dict(zip(SKP_ELEMENTS, eledefs))}


# ------------------------------------------------------------------ whole build

def final_stats(build, gd, roll="max", inventory=None, sliders=None, toggles=(), specials=None,
                base=None):
    """The page's final stat map, merged tree, spells and interactive defaults.
    `specials`: powder specials switched on (check_specials; off by default, as
    on WynnBuilder's page). `base`: build_stats already worked out (or changed)."""
    stats = base if base is not None else build_stats(build, gd, roll, inventory)
    weapon_name = build.equipment[8]
    cls = gd.weapon_class(weapon_name)
    merged = merge_tree(cls, build.atree, gd, build.aspects or (), stats["activeMajorIDs"])
    pre = {}
    for src in (stats, raw_tree_stats(merged)):
        for k, v in src.items():
            merge_stat(pre, k, v)
    specials = specials or {}
    if specials.get("weapon"):                 # PowderSpecialCalcNode, into pre-scale stats
        name, power = specials["weapon"]
        boost = SPECIAL_BY_NAME[name][1]["boost"]
        if boost:
            merge_stat(pre, "damMult." + name, boost[int(power) - 1])
            pre["poisonPct"] = boost[int(power) - 1]          # WynnBuilder's "legacy" line
    slider_info, toggle_info = interactives(merged)
    tree, scaled = tree_scaling(merged, pre, slider_info, toggle_info, sliders, toggles)
    final = {}
    boosts = {"damMult.Potion": 0, "damMult.Strength": 0, "damMult.Vulnerability": 0,
              "defMult.Potion": 0, "defMult.AbilityWeaken": 0}
    # armor_powder_node: the armor specials' "% <element> Dmg Boost" sliders
    armor_boost = {e + "DamPct": (specials.get("armor") or {}).get(e, 0) for e in SKP_ELEMENTS}
    for src in (pre, scaled, armor_boost, boosts):
        for k, v in src.items():
            merge_stat(final, k, v)
    return final, tree, collect_spells(tree), slider_info, toggle_info


def damage_report(build, gd, roll="max", inventory=None, sliders=None, toggles=(), specials=None,
                  base=None):
    """Everything the builder page's right column shows, as plain data."""
    if build.equipment[8] is None:
        return None
    check_specials(specials)
    stats, tree, spells, slider_info, toggle_info = final_stats(
        build, gd, roll, inventory, sliders, toggles, specials, base)
    weapon = weapon_stats(_weapon_item(build, gd), dict(zip(POWDERABLE, build.powders))[8], gd)
    crit = sp_to_pct(stats.get("dex", 0))
    out = []
    for base_spell in sorted(spells):
        spell = spells[base_spell]
        parts = spell_parts(stats, weapon, spell)
        entry = {"base_spell": base_spell, "name": spell.get("name"), "display": spell.get("display"),
                 "parts": []}
        if spell.get("cost"):
            c = spell_cost(stats, spell)
            if isinstance(c, float) and math.isnan(c):
                c = None
            entry["cost"] = c
        for p in parts:
            if not p["display"]:
                continue
            if p.get("type") == "damage":
                nc = (p["normal_total"][0] + p["normal_total"][1]) / 2
                cr = (p["crit_total"][0] + p["crit_total"][1]) / 2
                avg = (1 - crit) * nc + crit * cr
                entry["parts"].append({"name": p["name"], "type": "damage", "average": avg,
                                       "non_crit": nc, "crit": cr,
                                       "normal_min": p["normal_min"], "normal_max": p["normal_max"],
                                       "crit_min": p["crit_min"], "crit_max": p["crit_max"]})
                if p["name"] == spell.get("display"):
                    entry["summary"] = avg
                    if base_spell == 0:
                        adj = ATTACK_SPEEDS.index(stats["atkSpd"]) + stats.get("atkTier", 0)
                        adj = min(6, max(0, adj))
                        entry["dps"] = avg * ATTACK_SPEED[ATTACK_SPEEDS[adj]]
                        entry["attack_speed"] = ATTACK_SPEED_NAMES[adj]
            elif p.get("type") == "heal":
                heal = max(p["heal_amount"], 0)
                entry["parts"].append({"name": p["name"], "type": "heal", "heal": heal})
                if p["name"] == spell.get("display"):
                    entry["summary"] = heal
                    entry["summary_type"] = "heal"
        out.append(entry)
    return {"roll": roll, "spells": out, "defense": defense_stats(stats),
            "poison_tick": max(math.floor(stats.get("poison", 0) / 3), 0),
            "crit_chance": crit, "skills": {k: stats.get(k, 0) for k in SKILLS},
            "specials": specials or None, "powders_give": build_specials(build, gd),
            "powder_special": _special_burst(stats, weapon, specials, crit),
            "sliders": {k: {kk: vv for kk, vv in v.items() if kk != "abil"}
                        for k, v in slider_info.items()},
            "toggles": sorted(toggle_info)}


def _special_burst(stats, weapon, specials, crit):
    """displayPowderSpecials: the instant hit of Quake, Chain Lightning or Courage."""
    if not specials or not specials.get("weapon"):
        return None
    name, power = specials["weapon"]
    idx, sp = SPECIAL_BY_NAME[name]
    if not sp["damage"]:
        return {"name": name, "power": int(power), "boost": sp["boost"][int(power) - 1]}
    conv = [0] * 6
    conv[idx + 1] = sp["damage"][int(power) - 1]
    norm, crit_tot, _, _ = calculate_spell_damage(stats, weapon, conv, False, True,
                                                  "0.Powder Special")
    if sp["boost"]:              # Courage's own boost doesn't apply to its burst
        div = 1 + sp["boost"][int(power) - 1] / 100
        norm, crit_tot = [x / div for x in norm], [x / div for x in crit_tot]
    nc, cr = sum(norm) / 2, sum(crit_tot) / 2
    return {"name": name, "power": int(power), "element": DAMAGE_CLASSES[idx + 1],
            "boost": sp["boost"][int(power) - 1] if sp["boost"] else None,
            "average": (1 - crit) * nc + crit * cr, "non_crit": nc, "crit": cr}


def _weapon_item(build, gd):
    return gd.item(build.equipment[8])


def spell_values(build, gd, roll="base", inventory=None):
    """{spell name: headline number} (melee: average DPS), for solver floors."""
    rep = damage_report(build, gd, roll, inventory)
    out = {}
    for sp in rep["spells"]:
        v = sp.get("dps") if sp["base_spell"] == 0 else sp.get("summary")
        if v is not None:
            out[sp["name"]] = v
    return out


def _r(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, 2)


def compact(report):
    """damage_report trimmed for build files and the web page: rounded, and only
    the elements each part actually deals."""
    spells = []
    for s in report["spells"]:
        parts = []
        for p in s["parts"]:
            if p["type"] == "heal":
                parts.append({"name": p["name"], "type": "heal", "heal": _r(p["heal"])})
                continue
            ranges = [[DAMAGE_CLASSES[i], _r(p["normal_min"][i]), _r(p["normal_max"][i]),
                       _r(p["crit_min"][i]), _r(p["crit_max"][i])]
                      for i in range(6) if p["normal_max"][i] or p["crit_max"][i]]
            parts.append({"name": p["name"], "type": "damage", "average": _r(p["average"]),
                          "non_crit": _r(p["non_crit"]), "crit": _r(p["crit"]), "ranges": ranges})
        spells.append({"name": s["name"], "cost": _r(s.get("cost")), "display": s["display"],
                       "summary": _r(s.get("summary")),
                       "summary_type": s.get("summary_type", "damage"),
                       "dps": _r(s.get("dps")), "attack_speed": s.get("attack_speed"),
                       "parts": parts})
    d = report["defense"]
    ps = report.get("powder_special")
    return {"spells": spells,
            "defense": {**{k: _r(d[k]) for k in ("hp", "ehp", "ehp_no_agi", "hpr", "ehpr",
                                                  "def_pct", "agi_pct")},
                        "eledefs": {e: _r(v) for e, v in d["eledefs"].items()}},
            "skills": report.get("skills"), "specials": report.get("specials"),
            "powders_give": report.get("powders_give"),
            "powder_special": None if ps is None else {k: _r(v) if isinstance(v, float) else v
                                                       for k, v in ps.items()},
            "poison_tick": report["poison_tick"], "crit_chance": _r(report["crit_chance"] * 100),
            "sliders": {k: {"max": v["max"], "default": v["default"]}
                        for k, v in report["sliders"].items()},
            "toggles": report["toggles"]}


def summary(build, gd, inventory=None, specials=None):
    """Typical (100%) and perfect (130%, WynnBuilder's view) damage, for status."""
    if build.equipment[8] is None:
        return None
    try:
        out = {"typical": compact(damage_report(build, gd, "base", inventory, specials=specials)),
               "perfect": compact(damage_report(build, gd, "max", inventory, specials=specials))}
        return out
    except Exception as e:           # never let a damage quirk block saving a build
        return {"error": f"{type(e).__name__}: {e}"}
