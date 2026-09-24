"""Decode and encode WynnBuilder build links.

Port of js/builder/build_encode_decode.js (binary format). Crafted and custom
items, and legacy (pre-binary) links, are not supported yet.
"""
from dataclasses import dataclass, field

from .bits import BitReader, BitWriter, is_binary_link
from .crafting import decode_craft_hash, encode_craft_hash, read_craft, write_craft
from .data import LATEST, GameData

SLOTS = ["helmet", "chestplate", "leggings", "boots", "ring1", "ring2",
         "bracelet", "necklace", "weapon"]
POWDERABLE = [0, 1, 2, 3, 8]            # helmet, chestplate, leggings, boots, weapon
TOME_SLOTS = ["weaponTome1", "weaponTome2", "armorTome1", "armorTome2", "armorTome3",
              "armorTome4", "guildTome1", "lootrunTome1", "gatherXpTome1", "gatherXpTome2",
              "dungeonXpTome1", "dungeonXpTome2", "mobXpTome1", "mobXpTome2"]
POWDER_TIERS = 7                        # js/powders.js; powder id = element * 7 + tier - 1
POWDER_ELEMENTS = "etwfa"
VECTOR_FLAG = 0xC
VERSION_BITLEN = 10
BASE_URL = "https://wynnbuilder.github.io/builder/#"


@dataclass
class Build:
    equipment: list                     # 9 item names (None = empty), in SLOTS order
    level: int
    powders: list = field(default_factory=lambda: [[] for _ in POWDERABLE])
    tomes: list = field(default_factory=lambda: [None] * len(TOME_SLOTS))  # tome ids
    skillpoints: list | None = None     # None = let WynnBuilder assign automatically
    aspects: list | None = None         # None, or 5 entries of (aspect id, tier) / None
    atree: set = field(default_factory=set)  # active ability node ids, root included
    version: int = LATEST
    remapped: list = field(default_factory=list)   # decode: slots whose item id was retired
                                                   # and redirected to today's item

    @property
    def weapon(self):
        return self.equipment[8]


def powder_name(pid):
    return f"{POWDER_ELEMENTS[pid // POWDER_TIERS]}{pid % POWDER_TIERS + 1}"


def link_hash(link):
    return link.split("#", 1)[-1].strip()


def tree_children(tree):
    """Children in the order WynnBuilder builds them: raw JSON order per parent."""
    kids = {n["id"]: [] for n in tree}
    for n in tree:
        for p in n["parents"]:
            kids[p].append(n["id"])
    root = next(n["id"] for n in tree if not n["parents"])
    return root, kids


# ---------------------------------------------------------------- decoding

def _decode_powders(r, enc):
    def pid(x):
        return x + (x // enc["POWDER_TIERS"]) * (POWDER_TIERS - enc["POWDER_TIERS"])
    out = [pid(r.read(enc["POWDER_ID_BITLEN"]))]
    while True:
        if r.read_flag(enc["POWDER_REPEAT_OP"]) == enc["POWDER_REPEAT_OP"]["REPEAT"]:
            out.append(out[-1])
            continue
        if r.read_flag(enc["POWDER_REPEAT_TIER_OP"]) == enc["POWDER_REPEAT_TIER_OP"]["REPEAT_TIER"]:
            wrap = r.read(enc["POWDER_WRAPPER_BITLEN"])
            prev = out[-1]
            elem = (prev // POWDER_TIERS + wrap + 1) % len(enc["POWDER_ELEMENTS"])
            out.append(elem * POWDER_TIERS + prev % POWDER_TIERS)
            continue
        if r.read_flag(enc["POWDER_CHANGE_OP"]) == enc["POWDER_CHANGE_OP"]["NEW_POWDER"]:
            out.append(pid(r.read(enc["POWDER_ID_BITLEN"])))
            continue
        return out                      # NEW_ITEM


def decode(link, gd=None):
    text = link_hash(link)
    if not is_binary_link(text):
        raise NotImplementedError("legacy (pre-binary) WynnBuilder links are not supported")
    r = BitReader(text)
    r.read(6)
    version = r.read(VERSION_BITLEN)
    gd = gd if gd is not None and gd.version == version else GameData(version)
    enc = gd.enc

    equipment, powders, remapped = [], [], []
    current_ids = {it["id"] for it in gd.items}
    for i in range(enc["EQUIPMENT_NUM"]):
        kind = r.read_flag(enc["EQUIPMENT_KIND"])
        if kind == enc["EQUIPMENT_KIND"]["CRAFTED"]:
            equipment.append(encode_craft_hash(read_craft(r, gd.crafts), gd.crafts))
        elif kind == enc["EQUIPMENT_KIND"]["NORMAL"]:
            iid = r.read(enc["ITEM_ID_BITLEN"])
            if iid and iid - 1 not in gd.item_by_id:
                raise KeyError(f"no item with id {iid - 1} in slot {SLOTS[i]} (removed from the game?)")
            equipment.append(None if iid == 0 else gd.name(gd.item_by_id[iid - 1]))
            if iid and iid - 1 not in current_ids:
                remapped.append(SLOTS[i])
        else:
            raise NotImplementedError(f"custom item in slot {SLOTS[i]} is not supported")
        if i in POWDERABLE:
            has = r.read_flag(enc["EQUIPMENT_POWDERS_FLAG"]) == enc["EQUIPMENT_POWDERS_FLAG"]["HAS_POWDERS"]
            powders.append(_decode_powders(r, enc) if has else [])

    tomes = [None] * enc["TOME_NUM"]
    if r.read_flag(enc["TOMES_FLAG"]) == enc["TOMES_FLAG"]["HAS_TOMES"]:
        for k in range(enc["TOME_NUM"]):
            if r.read_flag(enc["TOME_SLOT_FLAG"]) == enc["TOME_SLOT_FLAG"]["USED"]:
                tomes[k] = r.read(enc["TOME_ID_BITLEN"])

    skillpoints = None
    if r.read_flag(enc["SP_FLAG"]) == enc["SP_FLAG"]["ASSIGNED"]:
        skillpoints = []
        w = enc["MAX_SP_BITLEN"]
        for _ in range(enc["SP_TYPES"]):
            if r.read_flag(enc["SP_ELEMENT_FLAG"]) == enc["SP_ELEMENT_FLAG"]["ELEMENT_ASSIGNED"]:
                v = r.read(w)
                skillpoints.append(v - (1 << w) if v >> (w - 1) else v)   # two's complement
            else:
                skillpoints.append(None)

    if r.read_flag(enc["LEVEL_FLAG"]) == enc["LEVEL_FLAG"]["MAX"]:
        level = enc["MAX_LEVEL"]
    else:
        level = r.read(enc["LEVEL_BITLEN"])

    aspects = None
    if r.read_flag(enc["ASPECTS_FLAG"]) == enc["ASPECTS_FLAG"]["HAS_ASPECTS"]:
        aspects = []
        for _ in range(enc["NUM_ASPECTS"]):
            if r.read_flag(enc["ASPECT_SLOT_FLAG"]) == enc["ASPECT_SLOT_FLAG"]["USED"]:
                aid = r.read(enc["ASPECT_ID_BITLEN"])
                aspects.append((aid, r.read(enc["ASPECT_TIER_BITLEN"]) + 1))
            else:
                aspects.append(None)

    atree = set()
    if equipment[8] is not None:
        root, kids = tree_children(gd.tree(gd.weapon_class(equipment[8])))
        atree.add(root)
        visited = set()

        def walk(cur):
            for c in kids[cur]:
                if c in visited:
                    continue
                visited.add(c)
                if r.remaining() and r.read(1):   # trailing padding reads as 0
                    atree.add(c)
                    walk(c)
        walk(root)

    return Build(equipment, level, powders, tomes, skillpoints, aspects, atree, version, remapped)


# ---------------------------------------------------------------- encoding

def _collect_powders(powders):
    """js `collectPowders`: group same-element powders, keeping first-seen order."""
    chunks, order = [], {}
    for p in powders:
        e = p // POWDER_TIERS
        if e not in order:
            order[e] = len(chunks)
            chunks.append([])
        chunks[order[e]].append(p)
    return chunks


def _encode_powders(w, powders, enc):
    if not powders:
        w.flag(enc["EQUIPMENT_POWDERS_FLAG"], "NO_POWDERS")
        return
    w.flag(enc["EQUIPMENT_POWDERS_FLAG"], "HAS_POWDERS")

    def idx(p):
        return (p // POWDER_TIERS) * enc["POWDER_TIERS"] + p % POWDER_TIERS
    prev = -1
    for chunk in _collect_powders(powders):
        i = 0
        while i < len(chunk):
            p = chunk[i]
            if prev >= 0:
                w.flag(enc["POWDER_REPEAT_OP"], "NO_REPEAT")
                if p % POWDER_TIERS == prev % POWDER_TIERS:
                    w.flag(enc["POWDER_REPEAT_TIER_OP"], "REPEAT_TIER")
                    wrap = ((p - prev) // POWDER_TIERS) % len(enc["POWDER_ELEMENTS"]) - 1
                    w.write(wrap, enc["POWDER_WRAPPER_BITLEN"])
                else:
                    w.flag(enc["POWDER_REPEAT_TIER_OP"], "CHANGE_POWDER")
                    w.flag(enc["POWDER_CHANGE_OP"], "NEW_POWDER")
                    w.write(idx(p), enc["POWDER_ID_BITLEN"])
            else:
                w.write(idx(p), enc["POWDER_ID_BITLEN"])
            i += 1
            while i < len(chunk) and chunk[i] == p:
                w.flag(enc["POWDER_REPEAT_OP"], "REPEAT")
                i += 1
            prev = p
    w.flag(enc["POWDER_REPEAT_OP"], "NO_REPEAT")
    w.flag(enc["POWDER_REPEAT_TIER_OP"], "CHANGE_POWDER")
    w.flag(enc["POWDER_CHANGE_OP"], "NEW_ITEM")


def _encode_tomes(w, tomes, enc):
    if all(t is None for t in tomes):
        w.flag(enc["TOMES_FLAG"], "NO_TOMES")
        return
    w.flag(enc["TOMES_FLAG"], "HAS_TOMES")
    for t in tomes:
        if t is None:
            w.flag(enc["TOME_SLOT_FLAG"], "UNUSED")
        else:
            w.flag(enc["TOME_SLOT_FLAG"], "USED")
            w.write(t, enc["TOME_ID_BITLEN"])


def _encode_sp(w, skillpoints, enc):
    """None means automatic; otherwise 5 entries, None where not manually set."""
    if skillpoints is None or all(sp is None for sp in skillpoints):
        w.flag(enc["SP_FLAG"], "AUTOMATIC")
        return
    w.flag(enc["SP_FLAG"], "ASSIGNED")
    for sp in skillpoints:
        if sp is None:
            w.flag(enc["SP_ELEMENT_FLAG"], "ELEMENT_UNASSIGNED")
        else:
            w.flag(enc["SP_ELEMENT_FLAG"], "ELEMENT_ASSIGNED")
            w.write(sp & ((1 << enc["MAX_SP_BITLEN"]) - 1), enc["MAX_SP_BITLEN"])


def _encode_level(w, level, enc):
    if level == enc["MAX_LEVEL"]:
        w.flag(enc["LEVEL_FLAG"], "MAX")
    else:
        w.flag(enc["LEVEL_FLAG"], "OTHER")
        w.write(level, enc["LEVEL_BITLEN"])


def _encode_aspects(w, aspects, enc):
    if not aspects or all(a is None for a in aspects):
        w.flag(enc["ASPECTS_FLAG"], "NO_ASPECTS")
        return
    w.flag(enc["ASPECTS_FLAG"], "HAS_ASPECTS")
    for a in aspects:
        if a is None:
            w.flag(enc["ASPECT_SLOT_FLAG"], "UNUSED")
        else:
            w.flag(enc["ASPECT_SLOT_FLAG"], "USED")
            w.write(a[0], enc["ASPECT_ID_BITLEN"])
            w.write(a[1] - 1, enc["ASPECT_TIER_BITLEN"])


def encode(build, gd=None):
    """Return the link hash (the part after '#') for `build`."""
    gd = gd if gd is not None and gd.version == build.version else GameData(build.version)
    enc = gd.enc
    w = BitWriter()
    w.write(VECTOR_FLAG, 6)
    w.write(build.version, VERSION_BITLEN)

    for i, name in enumerate(build.equipment):
        if name is not None and name.startswith("CR-"):
            w.flag(enc["EQUIPMENT_KIND"], "CRAFTED")
            write_craft(w, decode_craft_hash(name, gd.crafts), gd.crafts)
        else:
            w.flag(enc["EQUIPMENT_KIND"], "NORMAL")
            w.write(0 if name is None else gd.item(name)["id"] + 1, enc["ITEM_ID_BITLEN"])
        if i in POWDERABLE:
            _encode_powders(w, build.powders[POWDERABLE.index(i)], enc)
    _encode_tomes(w, build.tomes, enc)
    _encode_sp(w, build.skillpoints, enc)
    _encode_level(w, build.level, enc)
    _encode_aspects(w, build.aspects, enc)

    if build.weapon is not None:
        root, kids = tree_children(gd.tree(gd.weapon_class(build.weapon)))
        visited = set()

        def walk(cur):
            for c in kids[cur]:
                if c in visited:
                    continue
                visited.add(c)
                if c in build.atree:
                    w.write(1, 1)
                    walk(c)
                else:
                    w.write(0, 1)
        walk(root)

    return w.to_b64()


def to_link(build, gd=None):
    return BASE_URL + encode(build, gd)
