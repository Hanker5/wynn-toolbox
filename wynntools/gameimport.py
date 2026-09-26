"""Turns a raw dump of in-game inventory slots (from the Fabric export mod) into inventory changes.

Each slot is {"name", "lore": [...], "item_id", "count", ...}. Names are matched exactly
against the game data after stripping formatting; anything that matches nothing is
reported back as unknown so the mod's players can see what was skipped.
"""
import re
import unicodedata

from .rules import ROLLED_IDS

_FORMAT = re.compile(r"§.")
# Wynncraft pads names with private-use and unassigned code points (custom-font spacing).
_INVISIBLE = {"Co", "Cn", "Cs", "Cc", "Cf"}

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}
_TIER = re.compile(r"\bTier\s+(\d+|[IVX]+)\b", re.I)


def clean(text):
    text = "".join(c for c in _FORMAT.sub("", text or "") if unicodedata.category(c) not in _INVISIBLE)
    return " ".join(text.split())


# An identification line in the tooltip: "Walk Speed+18%", "Life Steal+161/3s", "Totem Cost-4".
_ID_LINE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z '.\-]*?)\s*(?P<value>[+-]\d[\d,]*)(?P<unit>%|/3s|/5s| tier)?")
_ELEMENTS = {"Earth": "e", "Thunder": "t", "Water": "w", "Fire": "f", "Air": "a", "Neutral": "n",
             "Elemental": "r"}
_LABELS = {
    ("Health", ""): "hpBonus", ("Health Regen", ""): "hprRaw", ("Health Regen", "%"): "hprPct",
    ("Life Steal", "/3s"): "ls", ("Mana Steal", "/3s"): "ms", ("Mana Regen", "/5s"): "mr",
    ("Max Mana", ""): "maxMana", ("Walk Speed", "%"): "spd", ("Sprint", "%"): "sprint",
    ("Sprint Regen", "%"): "sprintReg", ("Jump Height", ""): "jh", ("Knockback", "%"): "kb",
    ("Slow Enemy", "%"): "slowEnemy", ("Weaken Enemy", "%"): "weakenEnemy",
    ("Attack Speed", " tier"): "atkTier", ("Combat Experience", "%"): "xpb", ("Loot", "%"): "lb",
    ("Loot Bonus", "%"): "lb", ("Loot Quality", "%"): "lq", ("Stealing", "%"): "eSteal",
    ("Gather XP Bonus", "%"): "gXp", ("Gathering Experience", "%"): "gXp", ("Gather Speed", "%"): "gSpd",
    ("Gathering Speed", "%"): "gSpd", ("Soul Point Regen", "%"): "spRegen",
    ("Healing Efficiency", "%"): "healPct", ("Main Attack Range", "%"): "mainAttackRange",
    ("Critical Damage", "%"): "critDamPct", ("Critical Damage Bonus", "%"): "critDamPct",
    ("Poison", "/3s"): "poison", ("Exploding", "%"): "expd", ("Reflection", "%"): "ref",
    ("Thorns", "%"): "thorns",
    ("Damage", "%"): "damPct", ("Damage", ""): "damRaw", ("Main Attack Damage", "%"): "mdPct",
    ("Main Attack Damage", ""): "mdRaw", ("Spell Damage", "%"): "sdPct", ("Spell Damage", ""): "sdRaw",
}
for _name, _e in _ELEMENTS.items():
    for _kind, _key in (("Damage", "Dam"), ("Main Attack Damage", "Md"), ("Spell Damage", "Sd")):
        _LABELS[(f"{_name} {_kind}", "%")] = f"{_e}{_key}Pct"
        _LABELS[(f"{_name} {_kind}", "")] = f"{_e}{_key}Raw"
    _LABELS[(f"{_name} Defence", "%")] = f"{_e}DefPct"


def read_rolls(item, lore):
    """The real roll of each identification an identified item's tooltip shows,
    as {id: value} limited to the IDs this item actually rolls."""
    if item.get("fixID"):
        return {}
    out = {}
    for line in lore or []:
        m = _ID_LINE.match(clean(line))
        if not m:
            continue
        label, unit = m.group("label").strip(), m.group("unit") or ""
        key = _LABELS.get((label, unit))
        if key is None and label.endswith(" Cost"):
            # Spell costs are labelled with the spell's name; the item has at most one of each kind.
            kind = "spPct" if unit == "%" else "spRaw"
            options = [f"{kind}{n}" for n in range(1, 5) if item.get(f"{kind}{n}")]
            key = options[0] if len(options) == 1 else None
        base = item.get(key)
        if key in ROLLED_IDS and isinstance(base, (int, float)) and base and key not in out:   # dicts are static
            out[key] = int(m.group("value").replace(",", ""))
    return out


def _tier(lore):
    for line in lore or []:
        m = _TIER.search(clean(line))
        if m:
            v = m.group(1).upper()
            return int(v) if v.isdigit() else _ROMAN.get(v, 1)
    return 1


def _aspect_class(gd, name):
    for cls in gd.atrees:
        for a in gd.aspects(cls):
            if a["displayName"] == name:
                return cls, len(a.get("tiers") or [])
    return None, 0


def import_slots(inv, gd, slots):
    """Merge `slots` into `inv` (additive, never overwrites what the player already set).

    Identified items also get their real rolls read from the tooltip.
    Returns {"imported": {"items": n, "tomes": n, "aspects": n, "rolls": n}, "unknown": [names]}.
    """
    items, tome_seen, aspects, unknown = 0, {}, 0, []
    rolls, rolled = 0, set()      # the first copy of an item in a dump gives its rolls
    for slot in slots or []:
        name = clean(slot.get("name"))
        if not name:
            continue
        if name in gd.item_by_name:
            if name not in inv.items:
                inv.items[name] = {}
                items += 1
            found = read_rolls(gd.item_by_name[name], slot.get("lore"))
            if found and name not in rolled:
                rolled.add(name)
                if inv.items[name].get("rolls") != found:
                    inv.items[name]["rolls"] = found
                    rolls += 1
        elif name in gd.tome_by_name:
            tome_seen[name] = tome_seen.get(name, 0) + 1
        else:
            cls, top = _aspect_class(gd, name)
            if cls is None:
                if name not in unknown:
                    unknown.append(name)
                continue
            tier = min(max(_tier(slot.get("lore")), 1), max(top, 1))
            if tier > inv.aspect_tier(cls, name):
                inv.set_aspect(cls, name, tier)
                aspects += 1
    tomes = 0
    for name, seen in tome_seen.items():
        missing = seen - inv.tome_counts().get(name, 0)
        for _ in range(max(missing, 0)):
            inv.tomes.append(name)
            tomes += 1
    return {"imported": {"items": items, "tomes": tomes, "aspects": aspects, "rolls": rolls},
            "unknown": unknown}
