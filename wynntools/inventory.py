"""What a player owns: items (optionally with their real rolls), tomes and crafts.

Stored as builds/inventory.json, shared by the CLI, the web app and the AI:

    {
      "items": {"Galleon": {}, "Leo": {"rolls": {"hprRaw": 180}}},
      "tomes": ["Tome of Scavenging Expertise III", ...],
      "crafts": ["CR-..."]
    }

An item with "rolls" uses those values for the listed IDs instead of the 100%
base roll (and they don't change with the Typical/Perfect switch, since they are
real). IDs not listed still follow the chosen roll.
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

    def owns(self, name):
        return name in self.items or name in self.crafts

    def names(self):
        return set(self.items) | set(self.crafts)

    def rolls(self, name):
        return (self.items.get(name) or {}).get("rolls") or {}

    def to_json(self):
        return {"items": self.items, "tomes": self.tomes, "crafts": self.crafts}


def load(path=DEFAULT):
    path = Path(path)
    if not path.exists():
        return Inventory()
    raw = json.loads(path.read_text())
    return Inventory(items=raw.get("items") or {}, tomes=raw.get("tomes") or [],
                     crafts=raw.get("crafts") or [])


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
    for c in inv.crafts:
        try:
            gd.item(c)
        except (KeyError, ValueError, NotImplementedError):
            bad.append(c)
    return bad
