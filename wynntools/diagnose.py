"""What to know about a build before saving it: checked when a link is imported.

Each finding is {"level", "code", "message"}:
  error  the build is wrong or can't be worked out as it stands (it won't show as
         verified): skill points that don't fit, damage that can't be computed,
         a link the toolbox can't read;
  warn   it works, but not the way the player may think: skill points set by
         hand for only some skills, items above the build's level, retired item
         ids, items marked unavailable;
  info   limits of the numbers: crafted ranges, powder specials off, puppet
         damage models, untradable items.
"""
import re

from . import buildfile
from .codec import SLOTS, decode, link_hash
from .data import LATEST, VERSIONS
from .verify import SKILL_NAMES

SLOT_NAMES = {"ring1": "ring 1", "ring2": "ring 2"}


def _where(info):
    """"the Corrupted Ice Barrows dungeon merchant", from an item's dropInfo."""
    if not info or not info.get("name"):
        return None
    kind = re.sub(r"(?<!^)([A-Z])", r" \1", info.get("type") or "").lower()
    return f"{info['name']}{' ' + kind if kind else ''}"


def diagnose_link(link, gd, inventory=None, name=None):
    """{"ok", "findings", "doc"}: `doc` is the build file the link makes (None
    when it can't be read); `ok` is False when any finding is an error."""
    findings = []

    def add(level, code, message):
        findings.append({"level": level, "code": code, "message": message})
    try:
        b = decode(link_hash(link), gd)
    except NotImplementedError as e:
        text = str(e)
        if "only supported for the latest version" in text:
            m = re.search(r"this link is for ([\d.]+)", text)
            add("error", "old_version",
                f"This link was made with WynnBuilder's data for {m.group(1) if m else 'an older version'}; "
                f"the toolbox reads links made with the current data ({VERSIONS[LATEST]}) only.")
        else:
            add("error", "unreadable", f"The toolbox can't read this link: {text}.")
        return {"ok": False, "findings": findings, "doc": None}
    except (KeyError, ValueError, IndexError) as e:
        why = str(e).strip(chr(34)) if not isinstance(e, IndexError) else "it isn't a WynnBuilder build link"
        add("error", "unreadable", f"The toolbox can't read this link: {why}.")
        return {"ok": False, "findings": findings, "doc": None}

    doc = {"name": name or "", "notes": "", **buildfile.from_build(b, gd)}
    try:
        doc = buildfile.refresh(doc, gd, inventory)
    except (KeyError, ValueError, NotImplementedError) as e:
        add("error", "unreadable", f"The build can't be checked: {e}.")
        return {"ok": False, "findings": findings, "doc": None}
    st = doc["status"]

    # ---- skill points
    manual = [k for k, v in st["sp_manual"].items() if v]
    if manual:
        auto = [SKILL_NAMES[k] for k in SKILL_NAMES if k not in manual]
        hand = ", ".join(f"{SKILL_NAMES[k]} {st['sp_final'][k]}" for k in manual)
        if auto:
            add("warn", "sp_partial",
                f"Skill points: {hand} set by hand in WynnBuilder (final totals); "
                f"{', '.join(auto)} stay automatic, so they follow the gear. "
                f"{st['sp_total']} of {st['sp_available']} points assigned.")
        else:
            add("info", "sp_manual", f"Skill points are all set by hand ({hand}); "
                                     f"{st['sp_total']} of {st['sp_available']} assigned.")
    for p in st["problems"]:
        if p.startswith("damage could not be calculated"):
            add("error", "damage", f"Damage can't be worked out for this build ({p.split('(', 1)[-1].rstrip(')')}); "
                                   f"it will be saved but not verified.")
        elif "skill point" in p or "100 points" in p:
            add("error", "sp", p[:1].upper() + p[1:] + ".")
        elif "round-trip" in p and b.remapped:
            continue                       # explained below
        else:
            add("error" if "ability" not in p else "warn", "problem", p[:1].upper() + p[1:] + ".")

    # ---- items
    for slot in b.remapped:
        add("warn", "retired_id", f"The {SLOT_NAMES.get(slot, slot)} item's id is retired; WynnBuilder "
                                  f"redirects it to today's {b.equipment[SLOTS.index(slot)]}, whose stats "
                                  f"may differ from when the link was made. The saved link uses the new id.")
    unavailable = getattr(inventory, "unavailable", None) or {}
    crafted = [SLOT_NAMES.get(s, s) for s, n in zip(SLOTS, b.equipment) if n and n.startswith("CR-")]
    if crafted:
        add("info", "crafted", f"Crafted {', '.join(crafted)}: stats are ranges and the numbers use "
                               f"the middle. The ingredients have to be collected.")
    for slot, n in zip(SLOTS, b.equipment):
        if not n:
            continue
        it = gd.item(n)
        where = SLOT_NAMES.get(slot, slot)
        if n in unavailable:
            why = f" ({unavailable[n]})" if unavailable[n] else ""
            add("warn", "unavailable", f"{n} ({where}) is on your unavailable list{why}.")
        lvl = it.get("lvlLow") if n.startswith("CR-") else it.get("lvl")
        if lvl and lvl > b.level:
            add("warn", "level", f"{n if not n.startswith('CR-') else 'The crafted ' + where} needs level "
                                 f"{lvl}; the build is level {b.level}.")
        if not n.startswith("CR-") and it.get("restrict") in ("untradable", "quest_item"):
            src = _where(it.get("dropInfo"))
            add("info", "untradable", f"{n} can't be traded: you have to get it yourself"
                                      + (f" (from {src})." if src else "."))

    # ---- what the numbers leave out
    dmg = st.get("damage") or {}
    if b.weapon and "error" not in dmg:
        from .damage import build_specials
        give = build_specials(b, gd)
        named = ([f"{give['weapon'][0]} power {give['weapon'][1]}"] if give["weapon"] else []) + \
            [f"{a['name']} power {a['power']} ({a['slot']})" for a in give["armor"]]
        if named:
            add("info", "specials", f"The powders give {', '.join(named)}. Damage numbers leave "
                                    f"powder specials off, as WynnBuilder does; the Damage panel can "
                                    f"switch them on to compare.")
        knobs = (dmg.get("typical") or {}).get("sliders") or {}
        if knobs:
            add("info", "sliders", "Ability sliders are at WynnBuilder's defaults ("
                + ", ".join(f"{k} {v['default']}" for k, v in knobs.items()) + ").")
    return {"ok": not any(f["level"] == "error" for f in findings), "findings": findings, "doc": doc}
