"""What a player owns: items (every copy, with its real rolls and where it is), tomes and crafts.

Stored as builds/inventory.json, shared by the CLI, the web app and the AI:

    {
      "version": 2,
      "items": [{"name": "Leo", "rolls": {"hprRaw": 180}}, {"name": "Galleon"}],
      "places": {
        "account": {"pages": {"3": {"updated": "2026-09-28T10:00:00", "slots": [
            {"slot": 12, "name": "Galleon", "kind": "item", "rolls": {"eSteal": 14}},
            {"slot": 13, "name": "Liquid Emerald", "kind": "other", "count": 64}]}}},
        "character:a1b2c3d4": {"pages": {"1": {...}}},
        "inventory:a1b2c3d4": {"pages": {"1": {...}}}
      },
      "characters": {"a1b2c3d4": {"name": "", "class": "Shaman", "seen": "..."}},
      "tomes": ["Tome of Scavenging Expertise III", ...],
      "crafts": ["CR-..."],
      "aspects": {"Mage": {"Aspect of the Vortex": 3}},
      "unavailable": {"Stardew": "too expensive", "Warp": ""}
    }

"items" are copies added by hand (no location). "places" mirror the player's storages
as the chest-export mod last saw them, page by page: the Account ender chest (shared by
every character), each character's own Character ender chest, and each character's
inventory. A page slot's "kind" is item, tome, aspect or other (ingredients, potions,
...: shown, never counted as gear). Every item in a page is a copy the player owns, so
two copies of an item are two entries, whether their rolls differ or not.

A copy's rolls replace the 100% base roll for the listed IDs (and don't change with the
Typical/Perfect switch, since they are real). IDs not listed follow the chosen roll.
A copy's fingerprint (`fp`) identifies its rolls: copies with identical rolls share it,
and a build names the copy it uses by fingerprint.

"tomes" are tomes added by hand (repeat a name to own two); tomes in pages count too.
"aspects" maps each class to the aspects the player has, with the highest tier reached
(1 is the first tier); the editor offers no higher tier than that.

"unavailable" lists items the player can't or won't get (too expensive, not on the
market, ...), with an optional reason. Every search leaves them out unless the player
forces one into a slot.

Version 1 files (items as {name: {"rolls": {...}}}) load as copies added by hand.
"""
import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT = Path("builds/inventory.json")
VERSION = 2

# Pages each ender chest can have (Wynntils' AccountBankContainer / CharacterBankContainer).
PAGES = {"account": 21, "character": 12, "inventory": 1, "tomes": 1, "aspects": 1}
STORAGE_SLOTS = 45           # an ender chest page's own slots: 5 rows of 9
HAND = "hand"                # the "place" of a copy added by hand
_ARMOR = {36: "boots", 37: "leggings", 38: "chestplate", 39: "helmet"}
_ACCESSORY = {9: "ring slot 1", 10: "ring slot 2", 11: "bracelet slot", 12: "necklace slot"}


class Owned(str):
    """An item name that also says which copy of it a build uses (`fp`, its rolls'
    fingerprint). It compares and hashes as the plain name, so everything keyed by name
    keeps working; roll lookups (`rolls_for`) and the searches, which tell copies apart,
    read `fp`. Links and JSON see the plain name; build files keep the copies apart."""
    fp = None

    def __new__(cls, name, fp=None):
        out = super().__new__(cls, name)
        out.fp = fp
        return out

    def __getnewargs__(self):
        return str(self), self.fp

    def __repr__(self):
        return f"Owned({str(self)!r}, {self.fp!r})"


def owned_name(name, fp):
    """`name` marked with copy `fp` (the plain name when there is none)."""
    return name if name is None or not fp else Owned(name, fp)


def fp_of(name):
    """The copy a name is marked with, or None."""
    return getattr(name, "fp", None)


def name_of(gd, item):
    """An item's name, marked with the copy it is (searches carry copies as items)."""
    return owned_name(gd.name(item), item.get("_copy"))


def with_copies(equipment, copies):
    """Build equipment names marked with a build file's "copies" (9 fingerprints or null)."""
    copies = list(copies or [])
    return [owned_name(n, copies[k] if k < len(copies) else None) for k, n in enumerate(equipment)]


def copies_of(equipment):
    """The "copies" list for a build file, or None when no slot names a copy."""
    out = [fp_of(n) for n in equipment]
    return out if any(out) else None


def rolls_for(inventory, name):
    """The real rolls a build's item uses: its copy's, or the first copy's."""
    return inventory.rolls(name, fp_of(name)) if inventory is not None and name else None


def fingerprint(rolls):
    """A short id for a set of rolls: copies with identical rolls share it."""
    text = json.dumps(rolls or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def place_kind(key):
    """"account", "character" or "inventory" for a place key."""
    return key.split(":", 1)[0]


def place_character(key):
    return key.split(":", 1)[1] if ":" in key else None


def _place_order(key):
    return ({"account": 0, "character": 1, "inventory": 2, "tomes": 3, "aspects": 4}.get(place_kind(key), 5), key)


@dataclass
class Copy:
    name: str
    rolls: dict
    place: str = HAND                # HAND, "account", "character:<id>" or "inventory:<id>"
    page: int | None = None
    slot: int | None = None
    index: int | None = None         # position in Inventory.items, for copies added by hand

    @property
    def fp(self):
        return fingerprint(self.rolls)

    @property
    def placed(self):
        return self.place != HAND


def _hand_copy(name, entry):
    out = {"name": name}
    if (entry or {}).get("rolls"):
        out["rolls"] = dict(entry["rolls"])
    return out


@dataclass
class Inventory:
    items: list = field(default_factory=list)     # copies added by hand: {"name", "rolls"?}
    tomes: list = field(default_factory=list)     # tome names added by hand (repeat a name to own two)
    crafts: list = field(default_factory=list)    # crafted item hashes ("CR-...")
    unavailable: dict = field(default_factory=dict)   # name -> reason ("" if none given)
    aspects: dict = field(default_factory=dict)   # class -> {aspect name: highest tier owned}
    places: dict = field(default_factory=dict)    # place key -> {"pages": {"n": {"updated", "slots"}}}
    characters: dict = field(default_factory=dict)    # character id -> {"name", "class", "seen"}

    def __post_init__(self):
        if isinstance(self.items, dict):          # version 1: {name: {"rolls": {...}}}
            self.items = [_hand_copy(n, e) for n, e in self.items.items()]

    # ------------------------------------------------------------ copies
    def slots(self):
        """(place, page, slot entry) for every filled slot of every page, in a fixed order."""
        for key in sorted(self.places, key=_place_order):
            pages = self.places[key].get("pages") or {}
            for page in sorted(pages, key=int):
                for s in sorted(pages[page].get("slots") or [], key=lambda s: s.get("slot", 0)):
                    yield key, int(page), s

    def copies(self, name=None):
        """Every copy of an item the player owns (or of `name`): added by hand first,
        then the Account ender chest, Character ender chests and inventories."""
        out = [Copy(e["name"], e.get("rolls") or {}, index=k)
               for k, e in enumerate(self.items) if name is None or e["name"] == name]
        for key, page, s in self.slots():
            if s.get("kind") == "item" and (name is None or s["name"] == name):
                for _ in range(max(int(s.get("count") or 1), 1)):
                    out.append(Copy(s["name"], s.get("rolls") or {}, key, page, s.get("slot")))
        return out

    def copy(self, name, fp):
        """The first copy of `name` with rolls `fp`, or None."""
        return next((c for c in self.copies(name) if c.fp == fp), None)

    def counts(self):
        """{name: copies owned} for items (crafts not included)."""
        out = {}
        for c in self.copies():
            out[c.name] = out.get(c.name, 0) + 1
        return out

    def tome_copies(self, name=None):
        """Every tome the player owns (or of `name`): added by hand (no rolls known), then
        in pages and equipped, with their rolls."""
        out = [Copy(t, {}, index=k) for k, t in enumerate(self.tomes) if name is None or t == name]
        for key, page, s in self.slots():
            if s.get("kind") == "tome" and (name is None or s["name"] == name):
                for _ in range(max(int(s.get("count") or 1), 1)):
                    out.append(Copy(s["name"], s.get("rolls") or {}, key, page, s.get("slot")))
        return out

    def tome_counts(self):
        out = {}
        for t in self.tomes:
            out[t] = out.get(t, 0) + 1
        for _, _, s in self.slots():
            if s.get("kind") == "tome":
                out[s["name"]] = out.get(s["name"], 0) + max(int(s.get("count") or 1), 1)
        return out

    def aspect_tier(self, cls, name):
        """Highest owned tier of an aspect, 0 if not owned."""
        return int((self.aspects.get(cls) or {}).get(name) or 0)

    def set_aspect(self, cls, name, tier):
        """Own `name` up to `tier`; a tier of 0 removes it."""
        mine = self.aspects.setdefault(cls, {})
        if tier > 0:
            mine[name] = int(tier)
        else:
            mine.pop(name, None)
        if not mine:
            del self.aspects[cls]

    def owns(self, name):
        return name in self.crafts or any(e["name"] == name for e in self.items) \
            or any(s.get("kind") == "item" and s["name"] == name for _, _, s in self.slots())

    def names(self):
        return {c.name for c in self.copies()} | set(self.crafts)

    def rolls(self, name, fp=None):
        """The real rolls of copy `fp` of `name`; without `fp` (or if that copy is gone),
        the first copy's."""
        found = self.copies(name)
        chosen = next((c for c in found if c.fp == fp), None) if fp else None
        chosen = chosen or (found[0] if found else None)
        return dict(chosen.rolls) if chosen else {}

    # ------------------------------------------------------------ changes
    def add_copy(self, name, rolls=None):
        self.items.append(_hand_copy(name, {"rolls": rolls}))

    def remove(self, name, fp=None):
        """Remove every copy of `name` (or only one with rolls `fp`), from the copies added
        by hand and from the pages. Returns how many were removed."""
        removed = 0
        for k in range(len(self.items) - 1, -1, -1):
            e = self.items[k]
            if e["name"] == name and (fp is None or fingerprint(e.get("rolls")) == fp):
                del self.items[k]
                removed += 1
                if fp is not None:
                    return removed
        for key in sorted(self.places, key=_place_order):
            for page in (self.places[key].get("pages") or {}).values():
                keep = []
                for s in page.get("slots") or []:
                    if s.get("kind") == "item" and s["name"] == name and \
                            (fp is None or fingerprint(s.get("rolls")) == fp) and \
                            not (fp is not None and removed):
                        removed += 1
                        continue
                    keep.append(s)
                page["slots"] = keep
        return removed

    def set_page(self, key, page, slots, when):
        """Replace one page of a place with what the game showed."""
        pages = self.places.setdefault(key, {}).setdefault("pages", {})
        pages[str(int(page))] = {"updated": when, "slots": list(slots)}

    def drop_pages_above(self, key, last):
        """Forget pages past `last` (the player no longer has them). Returns how many."""
        pages = (self.places.get(key) or {}).get("pages") or {}
        gone = [p for p in pages if int(p) > last]
        for p in gone:
            del pages[p]
        return len(gone)

    # ------------------------------------------------------------ labels
    def character_label(self, cid):
        c = self.characters.get(cid) or {}
        if c.get("name"):
            return c["name"]
        return f"{c['class']} {cid}" if c.get("class") else f"Character {cid}"

    def place_label(self, key):
        kind, cid = place_kind(key), place_character(key)
        if kind == "account":
            return "Account ender chest"
        if kind == "character":
            return f"{self.character_label(cid)} · Character ender chest"
        if kind == "inventory":
            return f"{self.character_label(cid)} · inventory"
        if kind == "tomes":
            return f"{self.character_label(cid)} · equipped tomes"
        if kind == "aspects":
            return f"{self.character_label(cid)} · equipped aspects"
        return "added by hand"

    def where(self, place, page=None, slot=None):
        """"Account ender chest · page 3 · row 2, column 4", "Shaman a1b2c3d4 · inventory · helmet"."""
        if place == HAND:
            return "added by hand"
        parts = [self.place_label(place)]
        if place_kind(place) == "inventory":
            if slot is not None:
                parts.append(inventory_slot_label(slot))
        elif place_kind(place) in ("tomes", "aspects"):
            pass                         # equipped: where it sits in the menu doesn't matter
        else:
            if page is not None:
                parts.append(f"page {page}")
            if slot is not None:
                parts.append(f"row {slot // 9 + 1}, column {slot % 9 + 1}")
        return " · ".join(parts)

    def find(self, query):
        """Every slot and copy whose name contains `query` (any case): items, tomes,
        aspects and other things in pages, and what was added by hand."""
        q = query.strip().lower()
        out = []
        for e in self.items:
            if q in e["name"].lower():
                out.append({"name": e["name"], "kind": "item", "place": HAND, "page": None, "slot": None,
                            "rolls": e.get("rolls") or {}, "fp": fingerprint(e.get("rolls")),
                            "where": "added by hand"})
        for t in self.tomes:
            if q in t.lower():
                out.append({"name": t, "kind": "tome", "place": HAND, "page": None, "slot": None,
                            "where": "added by hand"})
        for key, page, s in self.slots():
            if q in s["name"].lower():
                hit = {"name": s["name"], "kind": s.get("kind", "other"), "place": key, "page": page,
                       "slot": s.get("slot"), "where": self.where(key, page, s.get("slot"))}
                if s.get("count", 1) != 1:
                    hit["count"] = s["count"]
                if s.get("kind") in ("item", "tome"):
                    hit["rolls"] = s.get("rolls") or {}
                    hit["fp"] = fingerprint(s.get("rolls"))
                out.append(hit)
        return out

    def view(self):
        """The file plus what the app shows: copies owned per name, every copy with where
        it is, tome counts, and each place with its label and page count."""
        out = self.to_json()
        out["owned"] = self.counts()
        out["tome_counts"] = self.tome_counts()
        out["copies"] = [{"name": c.name, "rolls": c.rolls, "fp": c.fp, "place": c.place, "page": c.page,
                          "slot": c.slot, "index": c.index, "where": self.where(c.place, c.page, c.slot)}
                         for c in self.copies()]
        out["tome_copies"] = [{"name": c.name, "rolls": c.rolls, "fp": c.fp, "place": c.place, "page": c.page,
                               "slot": c.slot, "index": c.index, "equipped": place_kind(c.place) == "tomes",
                               "where": self.where(c.place, c.page, c.slot)} for c in self.tome_copies()]
        out["place_list"] = [{"key": k, "kind": place_kind(k), "character": place_character(k),
                              "label": self.place_label(k), "max_pages": PAGES.get(place_kind(k), 1),
                              "pages": {n: {**p, "slots": [{**s, "where": self.where(k, int(n), s.get("slot")),
                                                           **({"fp": fingerprint(s.get("rolls"))}
                                                              if s.get("kind") in ("item", "tome") else {})}
                                                          for s in p.get("slots") or []]}
                                        for n, p in (self.places[k].get("pages") or {}).items()}}
                             for k in sorted(self.places, key=_place_order)]
        return out

    def to_json(self):
        return {"version": VERSION, "items": self.items, "tomes": self.tomes, "crafts": self.crafts,
                "unavailable": self.unavailable, "aspects": self.aspects, "places": self.places,
                "characters": self.characters}


def inventory_slot_label(slot):
    """A player-inventory slot as the game lays it out (Wynncraft keeps accessories in 9-12)."""
    if slot in _ARMOR:
        return _ARMOR[slot]
    if slot == 40:
        return "offhand"
    if slot in _ACCESSORY:
        return _ACCESSORY[slot]
    if 0 <= slot <= 8:
        return f"hotbar {slot + 1}"
    return f"row {(slot - 9) // 9 + 1}, column {(slot - 9) % 9 + 1}"


def copy_lines(inventory, equipment):
    """Where each owned item a build wears is kept: "ring1  Galleon: Account ender chest ·
    page 3 · row 1, column 5". Two rings with the same rolls get two different copies."""
    from .codec import SLOTS
    out, taken = [], set()
    if inventory is None:
        return out
    for slot, name in zip(SLOTS, equipment):
        if not name or name.startswith("CR-") or not inventory.owns(name):
            continue
        fp = fp_of(name)
        found = [c for c in inventory.copies(name) if fp is None or c.fp == fp]
        if not found:
            out.append(f"{slot:<11} {name}: the copy this build used is no longer in your inventory "
                       f"(the first copy's rolls count instead)")
            continue
        c = next((c for c in found if (c.place, c.page, c.slot, c.index) not in taken), found[0])
        taken.add((c.place, c.page, c.slot, c.index))
        many = len(inventory.copies(name))
        out.append(f"{slot:<11} {name}: {inventory.where(c.place, c.page, c.slot)}"
                   + (f" (one of {many} copies you own)" if many > 1 else ""))
    return out


def load(path=DEFAULT):
    path = Path(path)
    if not path.exists():
        return Inventory()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Inventory(items=raw.get("items") or [], tomes=raw.get("tomes") or [],
                     crafts=raw.get("crafts") or [], unavailable=raw.get("unavailable") or {},
                     aspects=raw.get("aspects") or {}, places=raw.get("places") or {},
                     characters=raw.get("characters") or {})


def save(inv, path=DEFAULT):
    from .buildfile import write
    write(path, inv.to_json())


def with_rolls(item, rolls, fp=None):
    """A copy of `item` whose listed IDs use the player's real roll values (and, with
    `fp`, remembers which copy they came from)."""
    if not rolls and fp is None:
        return item
    out = copy.copy(item)
    if rolls:
        out["_actual"] = dict(rolls)
    if fp is not None:
        out["_copy"] = fp
    return out


def validate(inv, gd):
    """Names that don't exist in the data (typos, removed items)."""
    bad = [e["name"] for e in inv.items if e["name"] not in gd.item_by_name]
    bad += [t for t in inv.tomes if t not in gd.tome_by_name]
    for _, _, s in inv.slots():
        if s.get("kind") == "item" and s["name"] not in gd.item_by_name:
            bad.append(s["name"])
        elif s.get("kind") == "tome" and s["name"] not in gd.tome_by_name:
            bad.append(s["name"])
    bad += [n for n in inv.unavailable if n not in gd.item_by_name and not n.startswith("CR-")]
    for cls, mine in inv.aspects.items():
        known = {a["displayName"]: len(a.get("tiers") or []) for a in gd.aspects(cls)}
        for name, tier in mine.items():
            if name not in known or not 1 <= int(tier) <= max(known[name], 1):
                bad.append(f"{cls}: {name}")
    for c in inv.crafts:
        try:
            gd.item(c)
        except (KeyError, ValueError, NotImplementedError):
            bad.append(c)
    return list(dict.fromkeys(bad))
