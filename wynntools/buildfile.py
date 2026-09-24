"""Build files: the shared record that the player, the web app and the AI all edit.

A build file is flat, human-readable JSON. Item, tome and ability-node entries
are names, not ids, so people can edit them by hand:

    {
      "name": "...", "notes": "...",
      "level": 105,
      "equipment": [9 item names or null, in codec.SLOTS order],
      "tomes": [14 tome names or null, in codec.TOME_SLOTS order],
      "tree": [ability node names],
      "powders": [[...], ...],          # optional, 5 lists of names like "t6"
                                        # (helmet, chestplate, leggings, boots, weapon)
      "aspects": [["Aspect of ...", 3], null, ...],   # optional, 5 [name, tier] or null
      "skillpoints": null,              # optional; null = automatic, else 5 FINAL
                                        # totals (null entries automatic), as in links
      "locked": ["weapon", ...],        # optional: slots searches from this build keep
      "parent": "x.json",               # optional: this is a candidate for x.json
      "spec": {...}, "tree_preset": "...",   # optional: how it was generated
      "link": "...", "status": {...}    # written by the tools, do not edit
    }
"""
import datetime
import json
import os
import tempfile
from pathlib import Path

from .codec import POWDER_ELEMENTS, POWDER_TIERS, TOME_SLOTS, Build, powder_name, to_link
from .data import LATEST
from .verify import check_link

GENERATED = ("link", "status")
# Skill-point fields of the check's summary that a build's status carries.
SP_STATUS = ("sp_need", "sp_total", "sp_available", "sp_final", "sp_manual", "sp_wearable",
             "sp_auto_need", "sp_auto_final", "sp_effective")


def _powder_id(name):
    return POWDER_ELEMENTS.index(name[0]) * POWDER_TIERS + int(name[1:]) - 1


def to_build(doc, gd):
    b = Build(equipment=list(doc["equipment"]), level=doc["level"], version=LATEST)
    tomes = doc.get("tomes") or []
    b.tomes = [None if t is None else gd.tome(t)["id"] for t in tomes] \
        + [None] * (len(TOME_SLOTS) - len(tomes))
    if doc.get("powders"):
        b.powders = [[_powder_id(p) for p in slot] for slot in doc["powders"]]
    from .skillpoints import check_manual
    check_manual(doc.get("skillpoints"))
    b.skillpoints = doc.get("skillpoints")
    if doc.get("aspects") and any(doc["aspects"]):
        if b.weapon is None:
            raise KeyError("aspects need a weapon (they belong to a class)")
        cls = gd.weapon_class(b.weapon)
        by_name = {a["displayName"]: a for a in gd.aspects(cls)}
        aspects = []
        for entry in doc["aspects"]:
            if not entry:
                aspects.append(None)
                continue
            name, tier = entry
            if name not in by_name:
                raise KeyError(f"not a {cls} aspect: {name!r}")
            tiers = len(by_name[name]["tiers"])
            if not 1 <= int(tier) <= tiers:
                raise KeyError(f"{name} has tiers 1-{tiers}, not {tier}")
            aspects.append((by_name[name]["id"], int(tier)))
        b.aspects = aspects + [None] * (5 - len(aspects))
    if b.weapon is not None:
        tree = gd.tree(gd.weapon_class(b.weapon))
        ids = {n["display_name"]: n["id"] for n in tree}
        unknown = [x for x in doc.get("tree") or [] if x not in ids]
        if unknown:
            raise KeyError(f"not in the {gd.weapon_class(b.weapon)} tree: {unknown}")
        root = next(n["id"] for n in tree if not n["parents"])
        b.atree = {root} | {ids[x] for x in doc.get("tree") or []}
    return b


def from_build(b, gd):
    doc = {"level": b.level, "equipment": list(b.equipment),
           "tomes": [None if t is None else gd.name(gd.tome(t)) for t in b.tomes]}
    if b.weapon is not None:
        names = {n["id"]: n["display_name"] for n in gd.tree(gd.weapon_class(b.weapon))}
        doc["tree"] = [names[i] for i in sorted(b.atree)]
    if any(b.powders):
        doc["powders"] = [[powder_name(p) for p in slot] for slot in b.powders]
    if b.aspects and any(b.aspects) and b.weapon is not None:
        names = {a["id"]: a["displayName"] for a in gd.aspects(gd.weapon_class(b.weapon))}
        doc["aspects"] = [None if a is None else [names[a[0]], a[1]] for a in b.aspects]
    doc["skillpoints"] = b.skillpoints
    return doc


def refresh(doc, gd, inventory=None):
    """Re-derive link and status from the editable fields. Returns the new doc.
    With an inventory, owned items use their real rolls in the totals."""
    from .damage import summary as damage_summary
    link = to_link(to_build(doc, gd), gd)
    ok, rep = check_link(link, gd, inventory=inventory)
    s = rep["summary"]
    damage = damage_summary(rep["build"], gd, inventory)
    problems = list(rep["problems"])
    if damage and "error" in damage:     # never verified while damage can't be worked out
        problems.append(f"damage could not be calculated ({damage['error']})")
    status = {"verified": not problems, "problems": problems,
              "totals": s["totals"], "totals_max": s["totals_max"],
              **{k: s[k] for k in SP_STATUS},
              "sets": s["sets"], "set_majors": s["set_majors"],
              "mana_min_int": s["mana_min_int"], "mana_spare_into_int": s["mana_spare_into_int"],
              "poison_per_second": s["poison_per_second"],
              "ap": list(rep.get("ap", (0, 0))), "tree_failed": rep.get("tree_failed", []),
              "damage": damage,
              "checked": datetime.datetime.now().isoformat(timespec="seconds")}
    return {**{k: v for k, v in doc.items() if k not in GENERATED},
            "link": link, "status": status}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, doc):
    """Atomic write, so the web app never sees a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
