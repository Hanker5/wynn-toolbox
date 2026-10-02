"""Sorting an ender chest: which group each thing belongs to, where it should go, and the
clicks that get it there.

The player's rules (`inventory.json` "sorting", one set for the Account chest and one for
every Character chest) name groups in the order they fill the pages; anything no rule
matches follows the default groups (weapons by class, armor, accessories, tomes, ...).
`target_layout` turns that into a destination for every slot of one chest, and
`plan_moves` into the clicks the chest-export mod makes: only plain left clicks
(pick up, put down, swap), never with an item on the cursor across a page turn, carrying
items between pages in free slots of the player's own inventory. Every click names what
the slot and the cursor hold before it (the mod's `sig` for the stack, and its count), so
the mod can stop the moment the game shows anything else.

Groups for things that aren't gear are read from names (ingredients and powders from
WynnBuilder's ingredient list; materials, keys, potions, ... from how Wynncraft names
them): a sorting choice, not a game fact. A rule's `name` pattern overrides them.
"""
import datetime
import re
from dataclasses import dataclass, field

from .data import WEAPON_CLASS
from .gameimport import clean
from .inventory import STORAGE_SLOTS, place_kind

CHESTS = ("account", "character")
ROW = 9
# Player-inventory slots the mod may carry items in: the main rows, except 9-12, where
# Wynncraft keeps the accessories. The hotbar holds the weapon and the character compass.
BUFFER_SLOTS = range(13, 36)

TIER_RANK = {"Mythic": 6, "Fabled": 5, "Legendary": 4, "Rare": 3, "Set": 2, "Unique": 2, "Normal": 1}
CLASSES = ("Warrior", "Mage", "Archer", "Assassin", "Shaman")
_CLASS_WEAPON = {c: t for t, c in WEAPON_CLASS.items()}

DEFAULT_GROUPS = (
    *((f"weapon:{c.lower()}", f"{c} weapons") for c in CLASSES),
    ("armor:helmet", "Helmets"), ("armor:chestplate", "Chestplates"),
    ("armor:leggings", "Leggings"), ("armor:boots", "Boots"),
    ("accessory:ring", "Rings"), ("accessory:bracelet", "Bracelets"), ("accessory:necklace", "Necklaces"),
    ("tome", "Tomes"), ("aspect", "Aspects"), ("unidentified", "Unidentified gear"),
    ("ingredient", "Ingredients"), ("powder", "Powders"), ("material", "Crafting materials"),
    ("consumable", "Potions, scrolls and food"), ("emerald", "Emeralds and pouches"),
    ("key", "Dungeon keys and fragments"), ("rune", "Runes, amplifiers and tokens"),
    ("tool", "Gathering tools"), ("mount", "Mounts"), ("misc", "Everything else"),
)
GROUP_LABEL = dict(DEFAULT_GROUPS)

_MATERIAL = re.compile(r"\b(Ingot|Gem|Paper|Planks?|Wood|Log|Ore|String|Grains|Oil|Meat)$")
_CHARGES = re.compile(r"\[\d+/\d+\]")
_CONSUMABLE = re.compile(r"\b(Potions?|Scroll|Elixir|Tonic)\b")
_POWDER = re.compile(r"\bPowder [IVX]+$")
_KEY = re.compile(r"\bKey$|\bFragment$|^Corrupted .*(?:'s|s') ")
_RUNE = re.compile(r"\b(Rune|Amplifier [IVX]+|Catalyst [IVX]+|Voucher|Token)$|^Ability Shard$")
_TOOL = re.compile(r"\b(Axe|Pickaxe|Scythe|Rod) T\d+$")
_MOUNT = re.compile(r"\b(Reins|Flute|Saddle)$")

MATCH_KEYS = {"group", "kind", "category", "type", "class", "tier", "name", "level", "untradable"}
_CHOICES = {
    "kind": {"item", "tome", "aspect", "other"},
    "category": {"weapon", "armor", "accessory", "tome", "aspect", "other"},
    "type": {"helmet", "chestplate", "leggings", "boots", "ring", "bracelet", "necklace",
             *WEAPON_CLASS, "weaponTome", "armorTome", "dungeonXpTome", "mobXpTome", "gatherXpTome",
             "guildTome", "lootrunTome"},
    "class": set(CLASSES),
    "tier": set(TIER_RANK),
}


class SortError(ValueError):
    """Rules or a chest that can't be sorted, with the reason for the player."""


# ------------------------------------------------------------------ what a slot is
def describe(gd, entry):
    """What a slot holds, for rules and default groups: {"group", "kind", "category",
    "type", "class", "tier", "level", "name", "untradable"}."""
    name, kind = entry.get("name") or "", entry.get("kind") or "other"
    out = {"kind": kind, "name": name, "category": "other", "type": None, "class": None,
           "tier": None, "level": 0, "untradable": False}
    if kind == "item" and name in gd.item_by_name:
        it = gd.item_by_name[name]
        cat, typ = it.get("category"), it.get("type")
        cls = WEAPON_CLASS.get(typ) if cat == "weapon" else None
        out.update(category=cat, type=typ, tier=it.get("tier"), level=int(it.get("lvl") or 0),
                   untradable=it.get("restrict") in ("untradable", "quest_item"), **{"class": cls})
        out["group"] = f"weapon:{cls.lower()}" if cls else f"{cat}:{typ}"
        if out["group"] not in GROUP_LABEL:
            out["group"] = "misc"
        return out
    if kind == "tome":
        t = gd.tome_by_name.get(name) or {}
        out.update(category="tome", type=t.get("type"), tier=t.get("tier"), level=int(t.get("lvl") or 0),
                   group="tome")
        return out
    if kind == "aspect":
        out.update(category="aspect", group="aspect", level=int(entry.get("tier") or 0),
                   **{"class": entry.get("cls")})
        return out
    out["group"] = _other_group(gd, name)
    return out


def _other_group(gd, name):
    ing = gd.crafts.ing_by_name.get(name)
    if ing is not None or _POWDER.search(name):
        return "powder" if (ing or {}).get("isPowder") or _POWDER.search(name) else "ingredient"
    if name.startswith("Unidentified "):
        return "unidentified"
    if "Emerald" in name:
        return "emerald"
    for group, pattern in (("key", _KEY), ("rune", _RUNE), ("tool", _TOOL), ("mount", _MOUNT)):
        if pattern.search(name):
            return group
    if _CHARGES.search(name) or _CONSUMABLE.search(name):
        return "consumable"
    if _MATERIAL.search(name):
        return "material"
    return "misc"


# ------------------------------------------------------------------ rules
def _as_list(v):
    return list(v) if isinstance(v, (list, tuple)) else [v]


def validate_rules(rules):
    """Problems with a "sorting" section ({"account": {...}, "character": {...}}), as
    messages; [] when it is fine. Choices are checked case-insensitively."""
    errors = []
    if not isinstance(rules, dict):
        return ["the sorting rules must be an object: {\"account\": {...}, \"character\": {...}}"]
    for chest, r in rules.items():
        if chest not in CHESTS:
            errors.append(f"unknown chest {chest!r}: use \"account\" or \"character\"")
            continue
        if not isinstance(r, dict):
            errors.append(f"{chest}: must be an object with \"groups\" (and \"keep_pages\")")
            continue
        for k in r:
            if k not in ("groups", "keep_pages"):
                errors.append(f"{chest}: unknown key {k!r} (use \"groups\" and \"keep_pages\")")
        keep = r.get("keep_pages", [])
        if not isinstance(keep, list) or not all(isinstance(p, int) and p >= 1 for p in keep):
            errors.append(f"{chest}: keep_pages must be a list of page numbers")
        groups = r.get("groups", [])
        if not isinstance(groups, list):
            errors.append(f"{chest}: groups must be a list")
            continue
        for n, g in enumerate(groups, 1):
            where = f"{chest} group {n}"
            if not isinstance(g, dict) or not isinstance(g.get("name"), str) or not g["name"].strip():
                errors.append(f"{where}: needs a \"name\"")
                continue
            where = f"{chest} group {g['name']!r}"
            for k in g:
                if k not in ("name", "match", "new_page"):
                    errors.append(f"{where}: unknown key {k!r} (use \"name\", \"match\", \"new_page\")")
            if "new_page" in g and not isinstance(g["new_page"], bool):
                errors.append(f"{where}: new_page must be true or false")
            match = g.get("match")
            if not isinstance(match, dict) or not match:
                errors.append(f"{where}: needs a \"match\" with at least one of {', '.join(sorted(MATCH_KEYS))}")
                continue
            errors += [f"{where}: {e}" for e in _match_errors(match)]
    return errors


def _match_errors(match):
    errors = []
    for k, v in match.items():
        if k not in MATCH_KEYS:
            errors.append(f"unknown match key {k!r} (use {', '.join(sorted(MATCH_KEYS))})")
        elif k == "name":
            try:
                re.compile(v)
            except (re.error, TypeError) as e:
                errors.append(f"name must be a pattern ({e})")
        elif k == "level":
            ok = isinstance(v, int) or (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) for x in v))
            if not ok:
                errors.append("level must be a level or [lowest, highest]")
        elif k == "untradable":
            if not isinstance(v, bool):
                errors.append("untradable must be true or false")
        elif k == "group":
            known = {g for g, _ in DEFAULT_GROUPS} | {g.split(":")[0] for g, _ in DEFAULT_GROUPS}
            for x in _as_list(v):
                if not isinstance(x, str) or x.lower() not in known:
                    errors.append(f"unknown group {x!r} (one of {', '.join(sorted(known))})")
        else:
            choices = {c.lower(): c for c in _CHOICES[k]}
            for x in _as_list(v):
                if not isinstance(x, str) or x.lower() not in choices:
                    errors.append(f"unknown {k} {x!r} (one of {', '.join(sorted(_CHOICES[k]))})")
    return errors


def matches(match, info):
    """Whether a slot (as `describe` tells it) fits every condition of a rule's match."""
    for k, v in match.items():
        if k == "name":
            if not re.search(v, info["name"], re.I):
                return False
        elif k == "level":
            low, high = (v, v) if isinstance(v, int) else v
            if not low <= info["level"] <= high:
                return False
        elif k == "untradable":
            if info["untradable"] != v:
                return False
        elif k == "group":
            if not any(info["group"] == x.lower() or info["group"].startswith(x.lower() + ":") for x in _as_list(v)):
                return False
        else:
            if str(info.get(k) or "").lower() not in {str(x).lower() for x in _as_list(v)}:
                return False
    return True


def rules_for(inv, place):
    """The rules for one place's chest: {"groups": [...], "keep_pages": [...]}."""
    return dict((getattr(inv, "sorting", None) or {}).get(place_kind(place)) or {})


# ------------------------------------------------------------------ the layout
@dataclass
class Thing:
    page: int
    slot: int
    entry: dict
    info: dict
    group: int = 0          # index into Layout.groups
    order: tuple = ()

    @property
    def sig(self):
        return stack_sig(self.entry)


def stack_sig(entry):
    """What tells two stacks apart: the mod's `sig` (its name, tooltip and item), or for
    pages exported by an older mod, the name and rolls (enough for a preview)."""
    if entry.get("sig"):
        return entry["sig"]
    rolls = ",".join(f"{k}={v}" for k, v in sorted((entry.get("rolls") or {}).items()))
    return f"~{entry.get('name')}|{rolls}|{entry.get('tier') or ''}|{entry.get('item_id') or ''}"


@dataclass
class Layout:
    place: str
    pages: list                                   # the pages sorted into (owned, not kept)
    kept: list                                    # pages left as they are
    groups: list                                  # [{"name", "count", "rule": bool}]
    dest: dict = field(default_factory=dict)      # (page, slot) now -> (page, slot) sorted
    things: dict = field(default_factory=dict)    # (page, slot) now -> Thing
    packing: str = "tidy"                         # tidy, rows (new pages ignored) or dense
    problems: list = field(default_factory=list)

    def page_groups(self):
        """{page: [group names on it, in order]} for the sorted chest."""
        out = {}
        for now, to in sorted(self.dest.items(), key=lambda kv: kv[1]):
            name = self.groups[self.things[now].group]["name"]
            names = out.setdefault(to[0], [])
            if not names or names[-1] != name:
                names.append(name)
        return out

    def sorted_pages(self):
        """{page: {slot: entry}} as the chest will look."""
        out = {p: {} for p in self.pages}
        for now, (page, slot) in self.dest.items():
            out[page][slot] = self.things[now].entry
        return out


def chest_pages(inv, place):
    """{page: {slot: entry}} for one chest, as last exported."""
    pages = (inv.places.get(place) or {}).get("pages") or {}
    return {int(p): {s["slot"]: s for s in pg.get("slots") or [] if 0 <= s.get("slot", -1) < STORAGE_SLOTS}
            for p, pg in pages.items()}


def target_layout(gd, inv, place, rules=None):
    """Where everything in `place` ("account" or "character:<id>") goes under the rules
    (by default the player's own). Raises SortError if the chest can't be sorted."""
    if place_kind(place) not in CHESTS:
        raise SortError(f"{place} isn't an ender chest; only the Account and Character chests can be sorted")
    rules = rules_for(inv, place) if rules is None else rules
    errors = validate_rules({place_kind(place): rules})
    if errors:
        raise SortError("; ".join(errors))
    now = chest_pages(inv, place)
    if not now:
        raise SortError(f"no pages of the {inv.place_label(place)} have been exported yet")
    keep = set(rules.get("keep_pages") or [])
    owned = sorted(now)
    out = Layout(place, [p for p in owned if p not in keep], [p for p in owned if p in keep], [])
    missing = [p for p in range(1, max(owned) + 1) if p not in now]
    if missing:
        out.problems.append(f"pages {', '.join(map(str, missing))} haven't been exported: export every page first")

    rule_groups = list(rules.get("groups") or [])
    out.groups = [{"name": g["name"], "count": 0, "rule": True, "new_page": bool(g.get("new_page"))}
                  for g in rule_groups]
    default_index = {}
    for key, label in DEFAULT_GROUPS:
        default_index[key] = len(out.groups)
        out.groups.append({"name": label, "count": 0, "rule": False, "new_page": False})
    for page in out.pages:
        for slot, entry in now[page].items():
            info = describe(gd, entry)
            g = next((k for k, r in enumerate(rule_groups) if matches(r.get("match") or {}, info)), None)
            if g is None:
                g = default_index[info["group"]]
            order = (-TIER_RANK.get(info["tier"] or "", 0), -info["level"], info["name"].lower(),
                     -int(entry.get("count") or 1), stack_sig(entry), page, slot)
            out.things[(page, slot)] = Thing(page, slot, entry, info, g, order)
            out.groups[g]["count"] += 1

    by_group = {}
    for key, t in sorted(out.things.items(), key=lambda kv: (kv[1].group, kv[1].order)):
        by_group.setdefault(t.group, []).append(key)
    for packing in ("tidy", "rows", "dense"):
        dest = _pack(by_group, out.groups, out.pages, packing)
        if dest is not None:
            out.dest, out.packing = dest, packing
            break
    if out.packing == "rows":
        out.problems.append("not every group marked new_page could start its own page; they follow on")
    elif out.packing == "dense":
        out.problems.append("the chest is too full to start each group on a new row; groups follow straight on")
    out.groups = [g for g in out.groups if g["count"]]
    _renumber(out, by_group)
    return out


def _renumber(out, by_group):
    """Drop empty groups from Layout.groups, keeping things pointing at the right one."""
    old = sorted(by_group)
    remap = {g: k for k, g in enumerate(old)}
    for t in out.things.values():
        t.group = remap[t.group]


def _pack(by_group, groups, pages, packing):
    """{(page, slot) now: (page, slot) sorted}, or None if it doesn't fit this way.
    tidy: each group starts on a new row, and on a new page if it would otherwise run
    over the page's end (or the rule says new_page). rows: the same without new_page.
    dense: one after another."""
    dest, k, slot = {}, 0, 0
    for g in sorted(by_group):
        keys = by_group[g]
        if packing != "dense" and slot % ROW:
            slot += ROW - slot % ROW
        if packing != "dense" and slot and (slot + len(keys) > STORAGE_SLOTS
                                            or (packing == "tidy" and groups[g]["new_page"])
                                            or slot >= STORAGE_SLOTS):
            k, slot = k + 1, 0
        for key in keys:
            if slot >= STORAGE_SLOTS:
                k, slot = k + 1, 0
            if k >= len(pages):
                return None
            dest[key] = (pages[k], slot)
            slot += 1
    return dest


# ------------------------------------------------------------------ the clicks
def _stack(entry):
    """What the mod checks a slot or the cursor holds: [sig, count, name]."""
    return [stack_sig(entry), int(entry.get("count") or 1), entry.get("name") or ""]


def free_buffer(inv, place):
    """Empty player-inventory slots the mod may carry items in (13-35), from the last
    export of the character's inventory."""
    cid = place.split(":", 1)[1] if ":" in place else None
    if cid is None:
        cid = max((k for k in inv.characters if k != "unknown"),
                  key=lambda k: inv.characters[k].get("seen") or "", default=None)
    pages = (inv.places.get(f"inventory:{cid}") or {}).get("pages") or {}
    used = {s.get("slot") for s in (pages.get("1") or {}).get("slots") or []}
    return [s for s in BUFFER_SLOTS if s not in used]


class _Planner:
    def __init__(self, layout, buffer, reserve, start):
        self.layout = layout
        self.at = {}                    # (page, slot) -> thing key, for chest slots
        self.pos = {}                   # thing key -> ("chest", page, slot) | ("inv", slot) | ("cursor",)
        self.dest = dict(layout.dest)   # thing key -> (page, slot)
        for key in layout.dest:
            self.at[key] = key
            self.pos[key] = ("chest",) + key
        self.buffer = {b: None for b in buffer if b != reserve}
        self.reserve = reserve
        self.page = start
        self.cursor = None
        self.steps = []
        self.turns = 0
        self.visits = 0

    def entry(self, key):
        return self.layout.things[key].entry

    def sig(self, key):
        return self.layout.things[key].sig

    def stack(self, key):
        return None if key is None else _stack(self.entry(key))

    # one click: the slot and the cursor trade places (pick up, put down or swap)
    def click_chest(self, slot):
        here = self.at.get((self.page, slot))
        assert not (here and self.cursor and self.sig(here) == self.sig(self.cursor)), "would merge stacks"
        self.steps.append({"op": "click", "area": "chest", "slot": slot,
                           "slot_has": self.stack(here), "cursor_has": self.stack(self.cursor)})
        held = self.cursor
        self.at.pop((self.page, slot), None)
        if held is not None:
            self.at[(self.page, slot)] = held
            self.pos[held] = ("chest", self.page, slot)
        self.cursor = here
        if here is not None:
            self.pos[here] = ("cursor",)

    def click_inv(self, slot):
        here = self.buffer[slot]
        self.steps.append({"op": "click", "area": "inv", "slot": slot,
                           "slot_has": self.stack(here), "cursor_has": self.stack(self.cursor)})
        held = self.cursor
        self.buffer[slot] = held
        if held is not None:
            self.pos[held] = ("inv", slot)
        self.cursor = here
        if here is not None:
            self.pos[here] = ("cursor",)

    def goto(self, page):
        assert self.cursor is None
        self.turns += abs(page - self.page)
        self.page = page
        self.visits += 1
        expect = [[slot] + self.stack(key) for (p, slot), key in sorted(self.at.items()) if p == page]
        self.steps.append({"op": "page", "page": page, "expect": expect})

    # bookkeeping
    def placed(self, key):
        return self.pos[key] == ("chest",) + self.dest[key]

    def carried(self):
        return [(b, k) for b, k in self.buffer.items() if k is not None]

    def free(self):
        return [b for b, k in self.buffer.items() if k is None]

    def work(self, page):
        """Something to do on `page`: carried items to put down, items in the wrong slot of
        this page, or (with room to carry) items that belong on another page."""
        if any(self.dest[k][0] == page for _, k in self.carried()):
            return True
        room = bool(self.free())
        for (p, _), key in self.at.items():
            if p == page and not self.placed(key) and (self.dest[key][0] == page or room):
                return True
        return False

    def same_kind_here(self, held, target):
        """If `target` holds a stack like the one held, they trade destinations (either may
        go in either slot), so the click that would merge them is never made."""
        there = self.at.get(target)
        if there is not None and there != held and self.sig(there) == self.sig(held):
            self.dest[held], self.dest[there] = self.dest[there], self.dest[held]
            return True
        return False

    def chain(self, origin_inv=None, origin_slot=None):
        """Put the held item where it goes; keep going with whatever that displaces while
        it belongs on this page. Anything for another page goes into a free carrying
        slot, or back where the chain started (that slot is empty until the chain ends)."""
        while self.cursor is not None:
            held = self.cursor
            to = self.dest[held]
            if to[0] == self.page:
                if self.same_kind_here(held, to):
                    continue
                self.click_chest(to[1])
                continue
            free = self.free()
            if free:
                self.click_inv(free[0])
            elif origin_slot is not None and (self.page, origin_slot) not in self.at:
                self.click_chest(origin_slot)
            else:
                raise SortError("internal: nowhere to put down an item")   # unreachable

    def visit(self):
        page = self.page
        # 1. put down what was carried here
        for b, key in sorted(self.carried(), key=lambda bk: self.dest[bk[1]]):
            if self.buffer[b] != key or self.dest[key][0] != page:
                continue                 # moved, or traded destinations meanwhile
            self.click_inv(b)
            self.chain(origin_inv=b)
        # 2. items in the wrong slot of this page
        while True:
            wrong = sorted(s for (p, s), key in self.at.items()
                           if p == page and not self.placed(key) and self.dest[key][0] == page)
            if not wrong:
                break
            self.click_chest(wrong[0])
            self.chain(origin_slot=wrong[0])
        # 3. pick up what belongs on other pages, while there is room to carry it
        for s in sorted(s for (p, s), key in self.at.items() if p == page and self.dest[key][0] != page):
            free = self.free()
            if not free:
                break
            self.click_chest(s)
            self.click_inv(free[0])

    def run(self):
        """Visit pages like a lift: keep going one way while there is work that way."""
        guard, direction = 0, 1
        while not all(self.placed(k) for k in self.dest):
            pages = [p for p in self.layout.pages if self.work(p)]
            if not pages:
                raise SortError("internal: items out of place but nothing to do")    # unreachable
            ahead = [p for p in pages if (p - self.page) * direction >= 0]
            if not ahead:
                direction, ahead = -direction, pages
            nxt = min(ahead, key=lambda p: (abs(p - self.page), p))
            if nxt != self.page or not self.steps:
                self.goto(nxt)
            self.visit()
            guard += 1
            if guard > 100000:
                raise SortError("internal: the plan doesn't finish")
        return self.steps


def plan(gd, inv, place, rules=None, start_page=None, buffer=None):
    """The whole sort of one chest: {"place", "steps", "moves", "clicks", "page_turns",
    "visits", "layout": {page: [groups]}, "groups", "sorted": {page: [entries]}, "buffer",
    "reserve", "notes", "problems", "ready"}. `ready` says whether the mod can run it:
    `problems` say what stops it; `notes` are only for the player.
    Steps are {"op": "page", "page", "expect": [[slot, sig, count, name], ...]} (the whole
    page as it should look on arrival) and {"op": "click", "area": "chest"|"inv", "slot",
    "slot_has", "cursor_has"} (each [sig, count, name] or null)."""
    layout = target_layout(gd, inv, place, rules)
    problems = [p for p in layout.problems if p.startswith("pages ")]
    notes = [p for p in layout.problems if p not in problems]
    buffer = free_buffer(inv, place) if buffer is None else list(buffer)
    moves = sum(1 for now, to in layout.dest.items() if now != to)
    reserve = buffer[-1] if buffer else None
    if moves and 2 <= len(buffer) < 10:
        notes.append(f"only {len(buffer) - 1} inventory slots are free to carry items between pages: "
                     "emptying more means fewer page turns")
    if moves and len(buffer) < 2:
        problems.append("empty at least 2 slots of your inventory's main rows (not the accessory "
                        "slots) so items can be carried between pages")
    if any(not t.entry.get("sig") for t in layout.things.values()):
        problems.append("these pages came from an older chest-export mod: update the mod and export "
                        "again before sorting in game (this plan is a preview)")
    steps, planner = [], None
    if moves and len(buffer) >= 2:
        start = start_page if start_page in layout.pages else layout.pages[-1]
        planner = _Planner(layout, buffer, reserve, start)
        steps = planner.run()
    return {
        "version": 1, "place": place, "label": inv.place_label(place),
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "steps": steps, "moves": moves,
        "clicks": sum(1 for s in steps if s["op"] == "click"),
        "page_turns": planner.turns if planner else 0, "visits": planner.visits if planner else 0,
        "layout": {str(p): names for p, names in layout.page_groups().items()},
        "groups": [{"name": g["name"], "count": g["count"], "rule": g["rule"]} for g in layout.groups],
        "pages": layout.pages, "kept": layout.kept, "packing": layout.packing,
        "sorted": {str(p): [{**e, "slot": s} for s, e in sorted(slots.items())]
                   for p, slots in layout.sorted_pages().items()},
        "buffer": [b for b in buffer if b != reserve], "reserve": reserve,
        "notes": notes, "problems": problems, "ready": bool(moves) and not problems,
    }


# ------------------------------------------------------------------ checking a plan
def simulate(pages, inventory, steps, start_page):
    """Replay `steps` as the game would (each click trades the slot and the cursor;
    stacks alike would merge, which is an error here), checking every expectation the mod
    checks. `pages` {page: {slot: [sig, count, name]}}, `inventory` {slot: [...]}.
    Returns (pages, inventory) at the end; raises AssertionError on any mismatch."""
    pages = {p: dict(s) for p, s in pages.items()}
    inventory = dict(inventory)
    page, cursor = start_page, None

    def same(a, b):
        return (a is None and b is None) or (a is not None and b is not None and list(a)[:2] == list(b)[:2])

    for n, step in enumerate(steps):
        if step["op"] == "page":
            assert cursor is None, f"step {n}: page turn with an item on the cursor"
            page = step["page"]
            got = {s: list(v)[:2] for s, v in pages.get(page, {}).items()}
            want = {e[0]: e[1:3] for e in step["expect"]}
            assert got == want, f"step {n}: page {page} isn't as expected"
            continue
        if step["area"] == "chest":
            assert 0 <= step["slot"] < STORAGE_SLOTS, f"step {n}: clicks control slot {step['slot']}"
            box = pages.setdefault(page, {})
        else:
            assert step["slot"] in BUFFER_SLOTS, f"step {n}: clicks inventory slot {step['slot']}"
            box = inventory
        here = box.get(step["slot"])
        assert same(here, step["slot_has"]), f"step {n}: slot holds {here}, expected {step['slot_has']}"
        assert same(cursor, step["cursor_has"]), f"step {n}: cursor holds {cursor}"
        assert not (here and cursor and here[0] == cursor[0]), f"step {n}: would merge two stacks"
        if cursor is None:
            box.pop(step["slot"], None)
        else:
            box[step["slot"]] = cursor
        cursor = here
    assert cursor is None, "the plan ends with an item on the cursor"
    return pages, inventory
