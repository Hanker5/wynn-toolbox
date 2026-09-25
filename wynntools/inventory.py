"""What a player owns: items (optionally with their real rolls), tomes and crafts.

Stored as builds/inventory.json, shared by the CLI, the web app and the AI:

    {
      "items": {"Galleon": {}, "Leo": {"rolls": {"hprRaw": 180}}},
      "tomes": ["Tome of Scavenging Expertise III", ...],
      "crafts": ["CR-..."],
      "aspects": {"Mage": {"Aspect of the Vortex": 3}},
      "unavailable": {"Stardew": "too expensive", "Warp": ""}
    }

An item with "rolls" uses those values for the listed IDs instead of the 100%
base roll (and they don't change with the Typical/Perfect switch, since they are
real). IDs not listed still follow the chosen roll.

"aspects" maps each class to the aspects the player has, with the highest
tier reached (1 is the first tier); the editor offers no higher tier than that.

"unavailable" lists items the player can't or won't get (too expensive, not on
the market, ...), with an optional reason. Every search leaves them out unless
the player forces one into a slot.
"""
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT = Path("builds/inventory.json")


@dataclass
class Inventory:
    items: dict = field(default_factory=dict)     # name -> {"rolls": {id: value}}
    tomes: list = field(default_factory=list)     # tome names (repeat a name to own two)
    crafts: list = field(default_factory=list)    # crafted item hashes ("CR-...")
    unavailable: dict = field(default_factory=dict)   # name -> reason ("" if none given)
    aspects: dict = field(default_factory=dict)   # class -> {aspect name: highest tier owned}

    def tome_counts(self):
        out = {}
        for t in self.tomes:
            out[t] = out.get(t, 0) + 1
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
        return name in self.items or name in self.crafts

    def names(self):
        return set(self.items) | set(self.crafts)

    def rolls(self, name):
        return (self.items.get(name) or {}).get("rolls") or {}

    def to_json(self):
        return {"items": self.items, "tomes": self.tomes, "crafts": self.crafts,
                "unavailable": self.unavailable, "aspects": self.aspects}


def load(path=DEFAULT):
    path = Path(path)
    if not path.exists():
        return Inventory()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Inventory(items=raw.get("items") or {}, tomes=raw.get("tomes") or [],
                     crafts=raw.get("crafts") or [], unavailable=raw.get("unavailable") or {},
                     aspects=raw.get("aspects") or {})


def save(inv, path=DEFAULT):
    from .buildfile import write
    write(path, inv.to_json())


def with_rolls(item, rolls):
    """A copy of `item` whose listed IDs use the player's real roll values."""
    if not rolls:
        return item
    out = copy.copy(item)
    out["_actual"] = dict(rolls)
    return out


def validate(inv, gd):
    """Names that don't exist in the data (typos, removed items)."""
    bad = [n for n in inv.items if n not in gd.item_by_name]
    bad += [t for t in inv.tomes if t not in gd.tome_by_name]
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
    return bad
