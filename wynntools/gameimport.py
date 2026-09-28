"""Turns a raw dump of in-game inventory slots (from the Fabric export mod) into inventory changes.

Each slot is {"name", "lore": [...], "item_id", "count", ...}. Names are matched exactly
against the game data after stripping formatting; anything that matches nothing is
reported back as unknown so the mod's players can see what was skipped.
"""
import datetime
import json
import re
import unicodedata

from .rules import ROLLED_IDS

_FORMAT = re.compile(r"§.")
# Wynncraft pads names with private-use and unassigned code points (custom-font spacing).
_INVISIBLE = {"Co", "Cn", "Cs", "Cc", "Cf"}

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}
_TIER = re.compile(r"\bTier\s+(\d+|[IVX]+)\b", re.I)


_WIDE_SPACE = re.compile("À+")     # Wynncraft's font draws "À" as a gap ("Broken IceÀÀÀBarrows Key")


def clean(text):
    text = "".join(c for c in _FORMAT.sub("", text or "") if unicodedata.category(c) not in _INVISIBLE)
    return " ".join(_WIDE_SPACE.sub(" ", text).split())


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
    """Merge `slots` from an older mod (format 1: no pages or places) into `inv`. Only adds:
    an item is added by hand if the player owns no copy of it yet, and the first copy in
    the dump gives the rolls of that copy.
    Returns {"imported": {"items": n, "tomes": n, "aspects": n, "rolls": n}, "unknown": [names]}.
    """
    items, tome_seen, aspects, unknown = 0, {}, 0, []
    rolls, rolled = 0, set()      # the first copy of an item in a dump gives its rolls
    for slot in slots or []:
        name = clean(slot.get("name"))
        if not name:
            continue
        if name in gd.item_by_name:
            hand = next((e for e in inv.items if e["name"] == name), None)
            if hand is None and not inv.owns(name):
                inv.add_copy(name)
                hand = inv.items[-1]
                items += 1
            found = read_rolls(gd.item_by_name[name], slot.get("lore"))
            if found and name not in rolled and hand is not None:
                rolled.add(name)
                if hand.get("rolls") != found:
                    hand["rolls"] = found
                    rolls += 1
        elif name in gd.tome_by_name:
            tome_seen[name] = tome_seen.get(name, 0) + 1
        else:
            got = _aspect(gd, name, slot.get("lore"))
            if got is None:
                if name not in unknown:
                    unknown.append(name)
                continue
            if got[2] > inv.aspect_tier(got[0], name):
                inv.set_aspect(got[0], name, got[2])
                aspects += 1
    tomes = 0
    for name, seen in tome_seen.items():
        missing = seen - inv.tome_counts().get(name, 0)
        for _ in range(max(missing, 0)):
            inv.tomes.append(name)
            tomes += 1
    return {"imported": {"items": items, "tomes": tomes, "aspects": aspects, "rolls": rolls},
            "unknown": unknown}


def _aspect(gd, name, lore):
    """(class, name, tier) if `name` is an aspect."""
    cls, top = _aspect_class(gd, name)
    if cls is None:
        return None
    return cls, name, min(max(_tier(lore), 1), max(top, 1))


def classify(gd, slot):
    """One slot as a page keeps it: {"slot", "name", "kind", ...}, or None if it's empty.
    kind is item (with the rolls its tooltip shows), tome, aspect (with its tier) or
    other (ingredients, potions, emeralds, ...: kept to show the page, never gear)."""
    name = clean(slot.get("name"))
    if not name:
        return None
    out = {"slot": int(slot.get("slot") or 0), "name": name}
    count = int(slot.get("count") or 1)
    if name in gd.item_by_name:
        out["kind"] = "item"
        found = read_rolls(gd.item_by_name[name], slot.get("lore"))
        if found:
            out["rolls"] = found
        return out
    if name in gd.tome_by_name:
        out["kind"] = "tome"
    else:
        got = _aspect(gd, name, slot.get("lore"))
        if got is not None:
            out.update(kind="aspect", cls=got[0], tier=got[2])
        else:
            out["kind"] = "other"
            if slot.get("item_id"):
                out["item_id"] = slot["item_id"]
    if count != 1:
        out["count"] = count
    return out


# The ender chest's page arrows (Wynntils' PersonalStorageContainer): "Page 3 >>>>>" in
# slot 52 leads to page 3, "Page 1 <<<<<" in slot 51 back to page 1.
NEXT_SLOT, PREVIOUS_SLOT = 52, 51
_ARROW = re.compile(r"^Page (\d+)\s*([<>])")


def has_next(storage):
    """Whether a page still offers a working next arrow (not the offer to buy a page)."""
    for s in storage or []:
        if s.get("slot") == NEXT_SLOT:
            m = _ARROW.match(clean(s.get("name")))
            lore = [clean(line) for line in s.get("lore") or []]
            return bool(m and m.group(2) == ">" and "Click to go" in lore
                        and not any("Purchase" in line for line in lore))
    return False


def page_of(storage):
    """The page an ender chest export shows, from its arrows; None if unreadable.
    Neither arrow means the chest has one page."""
    arrows = {}
    for s in storage or []:
        m = _ARROW.match(clean(s.get("name")))
        if m and s.get("slot") in (NEXT_SLOT, PREVIOUS_SLOT):
            arrows[s["slot"]] = (int(m.group(1)), m.group(2))
    nxt, prev = arrows.get(NEXT_SLOT), arrows.get(PREVIOUS_SLOT)
    if nxt and nxt[1] == ">":
        page = nxt[0] - 1
    elif prev and prev[1] == "<":
        page = prev[0] + 1
    elif not arrows:
        page = 1
    else:
        return None
    if prev and prev[1] == "<" and prev[0] + 1 != page:
        return None                         # the two arrows disagree
    return page if page >= 1 else None


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _placed(inv):
    """{name: [rolls of each placed copy]} and {tome: placed count}."""
    items, tomes = {}, {}
    for _, _, s in inv.slots():
        if s.get("kind") == "item":
            items.setdefault(s["name"], []).append(s.get("rolls") or {})
        elif s.get("kind") == "tome":
            tomes[s["name"]] = tomes.get(s["name"], 0) + max(int(s.get("count") or 1), 1)
    return items, tomes


def _guess_class(gd, slots):
    """The class whose weapons a character carries most (weapons are class-bound)."""
    seen = {}
    for s in slots:
        if s.get("kind") == "item":
            cls = (gd.item_by_name[s["name"]].get("classReq") or "").title()
            if cls:
                seen[cls] = seen.get(cls, 0) + 1
    return max(seen, key=seen.get) if seen else None


def import_export(inv, gd, body):
    """Import one export from the mod.

    Format 2 replaces each page it shows (and the character's inventory) with what the
    game showed, so items moved out or sold disappear. `pages` (a walk through every
    page) replaces each one; for the chests in "complete" (or all, if it is true), pages
    past the last one seen are dropped.
    Copies added by hand are then claimed by the new copies of the same item (rolls equal
    or unknown), so an item isn't counted twice once its place is known.
    Returns {"imported": {...}, "unknown": [names], "message": text for chat, "warnings": [...]}.
    """
    if body.get("version") != 2:
        out = import_slots(inv, gd, body.get("slots"))
        i = out["imported"]
        out["message"] = (f"{i['items']} new items, {i['rolls']} with updated rolls, {i['tomes']} tomes, "
                          f"{i['aspects']} aspects. Update the chest-export mod to track pages and slots.")
        return out
    when = _now()
    cid = (body.get("character") or {}).get("id") or "unknown"
    before_items, before_tomes = _placed(inv)
    warnings, labels, done, tops = [], [], {}, {}

    inventory = [c for c in (classify(gd, s) for s in body.get("inventory") or []) if c]
    inv.set_page(f"inventory:{cid}", 1, inventory, when)
    labels.append("inventory")
    classified = list(inventory)

    kind = body.get("kind")
    pages = body.get("pages")
    if pages is None and kind in ("account", "character"):
        pages = [{"kind": kind, "storage": body.get("storage") or []}]
    for p in pages or []:
        pk = p.get("kind")
        if pk not in ("account", "character"):
            continue
        n = page_of(p.get("storage"))
        if n is None:
            n = p.get("page") if isinstance(p.get("page"), int) else None
        if n is None:
            warnings.append(f"couldn't tell which {pk} ender chest page this is; it wasn't imported")
            continue
        key = "account" if pk == "account" else f"character:{cid}"
        slots = [c for c in (classify(gd, s) for s in p.get("storage") or [])
                 if c and c["slot"] < 45]
        inv.set_page(key, n, slots, when)
        done.setdefault(key, set()).add(n)
        tops[(key, n)] = p.get("storage")
        classified += slots
    removed_pages = 0
    complete = body.get("complete")          # true, or the chests ("account", "character") read to the end
    for key, seen in done.items():
        if complete is True or (isinstance(complete, list) and key.split(":")[0] in complete):
            if has_next(tops[(key, max(seen))]):      # the mod stopped early: keep the rest
                warnings.append(f"page {max(seen)} still leads to another page, so no pages were dropped")
                continue
            removed_pages += inv.drop_pages_above(key, max(seen))
    for key, seen in done.items():
        pk = "Account" if key == "account" else "Character"
        labels.append(f"{pk} ender chest " + (f"p{min(seen)}" if len(seen) == 1 else f"{len(seen)} pages"))
    if kind == "unknown":
        warnings.append("this container isn't one of your ender chests; only your inventory was read")

    character = inv.characters.setdefault(cid, {"name": ""})
    character["seen"] = when
    guess = _guess_class(gd, inventory)
    if guess:
        character["class"] = guess

    aspects = 0
    for s in classified:
        if s["kind"] == "aspect" and s["tier"] > inv.aspect_tier(s["cls"], s["name"]):
            inv.set_aspect(s["cls"], s["name"], s["tier"])
            aspects += 1

    # Claim copies added by hand: each new placed copy takes one with the same rolls or none.
    after_items, after_tomes = _placed(inv)
    claimed = removed = 0
    for name in set(before_items) | set(after_items):
        was, now = before_items.get(name, []), after_items.get(name, [])
        if len(now) < len(was):
            removed += len(was) - len(now)
        fresh = list(now)
        for r in was:
            if r in fresh:
                fresh.remove(r)
        for r in fresh:
            k = next((k for k, e in enumerate(inv.items) if e["name"] == name and e.get("rolls") == r), None)
            if k is None:
                k = next((k for k, e in enumerate(inv.items) if e["name"] == name and not e.get("rolls")), None)
            if k is not None:
                del inv.items[k]
                claimed += 1
    for name, n in after_tomes.items():
        for _ in range(max(n - before_tomes.get(name, 0), 0)):
            if name in inv.tomes:
                inv.tomes.remove(name)
                claimed += 1

    items = sum(1 for s in classified if s["kind"] == "item")
    tomes = sum(1 for s in classified if s["kind"] == "tome")
    other = sorted({s["name"] for s in classified if s["kind"] == "other"})
    message = f"{', '.join(labels)}: {items} items, {tomes} tomes"
    if aspects:
        message += f", {aspects} aspects raised"
    if removed:
        message += f"; {removed} no longer there"
    message += "." + "".join(f" Note: {w}." for w in warnings)
    return {"imported": {"items": items, "tomes": tomes, "aspects": aspects, "removed": removed,
                         "claimed": claimed, "pages_dropped": removed_pages, "places": labels},
            "unknown": other, "warnings": warnings, "message": message}


SAMPLES = 30      # raw exports kept in builds/.imports/


def keep_sample(builds_dir, body):
    """Save a raw export as builds/.last-import.json and builds/.imports/<time>-<kind>.json
    (the newest SAMPLES), to check new screens and unrecognised names against."""
    from pathlib import Path
    text = json.dumps(body, indent=1, ensure_ascii=False)
    builds_dir = Path(builds_dir)
    (builds_dir / ".last-import.json").write_text(text, encoding="utf-8")
    folder = builds_dir / ".imports"
    folder.mkdir(exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    kind = re.sub(r"[^a-z_]", "", str(body.get("kind") or "v1"))[:20] or "v1"
    (folder / f"{stamp}-{kind}.json").write_text(text, encoding="utf-8")
    for old in sorted(folder.glob("*.json"))[:-SAMPLES]:
        old.unlink()
