"""Numbers that aren't a plain sum of item stats: effective HP, health regen,
elemental defences, main-attack, puppet and summon DPS. All come from
WynnBuilder's model (wynntools.damage); this module names them, so the editor,
the solver's goals and floors, trade-offs and warnings all mean the same thing.
"""
import math

from .damage import DAMAGE_CLASSES, PUPPET_SPELL, SKP_ELEMENTS, SUMMON_SPELLS, damage_report

# key -> (label, unit). The keys are what specs use in "objective" and "floors".
DERIVED = {
    "ehp": ("Effective HP", ""),
    "ehp_no_agi": ("Effective HP (no agility dodge)", ""),
    "hpr": ("Health regen", ""),
    "min_eledef": ("Lowest elemental defence", ""),
    "melee_dps": ("Main-attack DPS", ""),
    "puppet_dps": ("Puppet DPS", ""),
    "summon_dps": ("Total summon DPS", ""),
}
# Derived numbers that depend on the weapon's damage (and so the ability tree).
DAMAGE_KEYS = ("melee_dps", "puppet_dps", "summon_dps")
ELEMENT_NAMES = dict(zip(SKP_ELEMENTS, DAMAGE_CLASSES[1:]))
SKILL_NAMES = {"str": "Strength", "dex": "Dexterity", "int": "Intelligence", "def": "Defence",
               "agi": "Agility"}


def from_report(rep):
    """Derived numbers from a damage_report (typical or perfect rolls)."""
    d = rep["defense"]
    spells = {sp["name"]: sp for sp in rep["spells"]}
    melee = next((sp for sp in rep["spells"] if sp["base_spell"] == 0), None)

    def headline(name):
        sp = spells.get(name)
        v = sp.get("summary") if sp else None
        return 0.0 if v is None or (isinstance(v, float) and math.isnan(v)) else v
    eledefs = dict(d["eledefs"])
    return {"ehp": d["ehp"], "ehp_no_agi": d["ehp_no_agi"], "hpr": d["hpr"], "hp": d["hp"],
            "eledefs": eledefs, "min_eledef": min(eledefs.values()),
            "def_pct": d["def_pct"], "agi_pct": d["agi_pct"],
            "skills": rep.get("skills") or {},
            "melee_dps": (melee or {}).get("dps") or 0.0,
            "puppet_dps": headline(PUPPET_SPELL),
            "summon_dps": sum(headline(n) for n in SUMMON_SPELLS),
            "summons": {n: headline(n) for n in SUMMON_SPELLS if n in spells},
            "powder_special": rep.get("powder_special"),
            "spells": {sp["name"]: (sp.get("dps") if sp["base_spell"] == 0 else sp.get("summary"))
                       for sp in rep["spells"]}}


def metrics(build, gd, roll="base", inventory=None, specials=None):
    """Derived numbers for a build with a weapon (None without one)."""
    rep = damage_report(build, gd, roll, inventory, specials=specials)
    return None if rep is None else from_report(rep)


def value(m, key):
    """One goal's value from metrics(): a DERIVED key, or a spell's headline number."""
    if key in DERIVED:
        return m[key]
    v = m["spells"].get(key)
    return 0.0 if v is None else v


# ---------------------------------------------------------------- survivability

def survivability(status):
    """The editor's Survivability panel, from a build's status (buildfile.refresh):
    for typical and perfect rolls, final Defence and Agility (after gear and
    tree), effective HP, health regen and every elemental defence, with the
    lowest one marked. Works without a weapon too (no effective HP then)."""
    out = {}
    dmg = status.get("damage") or {}
    for key, totals in (("typical", status.get("totals") or {}),
                        ("perfect", status.get("totals_max") or {})):
        d = (dmg.get(key) or {}).get("defense") if "error" not in dmg else None
        skills = (dmg.get(key) or {}).get("skills") if d else None
        skills = skills or status.get("sp_effective") or status.get("sp_final") or {}
        if d:
            eledefs = d["eledefs"]
        else:        # no weapon (or damage failed): raw defences, like the Summary
            eledefs = {e: totals.get(e + "Def", 0) for e in SKP_ELEMENTS}
        low = min(eledefs, key=lambda e: eledefs[e])
        out[key] = {"def": skills.get("def", 0), "agi": skills.get("agi", 0),
                    "def_pct": d["def_pct"] if d else None, "agi_pct": d["agi_pct"] if d else None,
                    "hp": d["hp"] if d else totals.get("hp"),
                    "ehp": d["ehp"] if d else None, "ehp_no_agi": d["ehp_no_agi"] if d else None,
                    "hpr": d["hpr"] if d else None, "eledefs": eledefs,
                    "lowest": {"element": low, "value": eledefs[low]}}
    return out


def warnings(status, doc=None):
    """Weaknesses and broken numbers, each with what would fix it. Every entry:
    {"code", "level" ("bad" or "warn"), "message", "fix"}; "fix" is None, or
    {"action": "auto_sp"} (skill points back to automatic), or {"action":
    "search", "floors": {...}, "why": ...}: re-search the build's other slots
    with these minimums, keeping the weapon and any locked items.

    Thresholds are only what the numbers themselves say (negative, zero); none
    is a judgment about how much is "enough"."""
    out = []
    manual = any((status.get("sp_manual") or {}).values())
    dmg = status.get("damage") or {}
    if "error" in dmg:
        out.append({"code": "damage_error", "level": "bad",
                    "message": f"Damage can't be calculated: {dmg['error']}",
                    "fix": {"action": "auto_sp"} if manual else None})
    if status.get("sp_total", 0) > status.get("sp_available", 0) or \
            not status.get("sp_wearable", True) or \
            any(v > 100 for v in (status.get("sp_need") or {}).values()):
        if manual:
            out.append({"code": "sp_manual", "level": "bad",
                        "message": "The skill points set by hand don't work with this gear.",
                        "fix": {"action": "auto_sp"}})
        else:
            out.append({"code": "sp_over", "level": "bad",
                        "message": f"The gear needs {status.get('sp_total')} skill points; "
                                   f"only {status.get('sp_available')} are available.",
                        "fix": {"action": "search", "floors": {},
                                "why": "gear whose requirements fit in the skill points"}})
    hand = [k for k, v in (status.get("sp_manual") or {}).items() if v]
    if hand and len(hand) < 5 and not any(w["code"] == "sp_manual" for w in out):
        auto = [SKILL_NAMES[k] for k in SKILL_NAMES if k not in hand]
        out.append({"code": "sp_partial", "level": "warn",
                    "message": f"Only {', '.join(SKILL_NAMES[k] for k in hand)} set by hand; "
                               f"{', '.join(auto)} follow the gear automatically.",
                    "fix": {"action": "auto_sp"}})
    surv = survivability(status).get("typical") or {}
    for e, v in (surv.get("eledefs") or {}).items():
        if v < 0:
            name = ELEMENT_NAMES[e]
            out.append({"code": f"neg_{e}def", "level": "warn",
                        "message": f"{name} defence is negative ({v:,.0f}). Effective HP doesn't "
                                   f"count elemental defences, so it hides this weakness.",
                        "fix": {"action": "search", "floors": {"min_eledef": 0},
                                "why": "no negative elemental defence"}})
    for k in ("def", "agi"):
        v = surv.get(k)
        if v is not None and v < 0:
            out.append({"code": f"neg_{k}", "level": "warn",
                        "message": f"{SKILL_NAMES[k]} is negative ({v}) after gear: it counts as 0.",
                        "fix": {"action": "search", "floors": {k: 0},
                                "why": f"{SKILL_NAMES[k]} at least 0"}})
    hpr = surv.get("hpr")
    if hpr is None:
        hpr = (status.get("totals") or {}).get("hprRaw")
    if hpr is not None and hpr <= 0:
        out.append({"code": "no_regen", "level": "warn",
                    "message": "No health regen" + (f" ({hpr:,.0f})" if hpr < 0 else "") +
                               ": you only heal from other sources.",
                    "fix": {"action": "search", "floors": {"hprRaw": 1},
                            "why": "some raw health regen"}})
    return out

