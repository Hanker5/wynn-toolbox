"""Helpers that keep an AI agent on the rails: what to ask a player (`wt intake`),
a spec sanity check before a long search (`wt spec-check`), and the fixed
end-of-build report with the assumptions AGENTS.md requires (`wt report`)."""
from .codec import SLOTS
from .gear_solver import MIN_ELEDEF

# (key, what it is, the question to ask when the spec doesn't say)
QUESTIONS = (
    ("class", "Class", "Which class (Archer, Assassin, Mage, Shaman, Warrior)?"),
    ("level", "Level", "What level is the build (max 121)?"),
    ("goal", "Goal", "What should it be best at, in game terms (stealing, tankiness, poison, "
                     "puppet damage, ...)? Confirm ambiguous words; see knowledge/goals.md."),
    ("requirements", "Hard requirements", "Any must-haves: Major IDs, minimum HP/mana/regen/speed, "
                                          "elemental defences, skill points?"),
    ("weapon", "Weapon and unavailable items", "Must it use a particular weapon, or avoid any items "
                                               "(too expensive, no mythics)?"),
    ("tomes", "Tomes", "Which tomes do they own, or should the plan assume aspirational ones?"),
    ("crafted", "Crafted gear", "Do they craft? (Crafted items need ingredients they must collect.)"),
    ("tree", "Ability tree", "Which archetype/tree preset fits? (`wt tree --help`; presets are generic.)"),
)


def _known(raw, tree=None):
    """{key: short description} of what a spec (or None) already answers."""
    raw = raw or {}
    out = {}
    if raw.get("class"):
        out["class"] = raw["class"]
    if raw.get("level"):
        out["level"] = str(raw["level"])
    if raw.get("objective"):
        out["goal"] = ", ".join(f"{k} x{v:g}" for k, v in raw["objective"].items())
    req = [*(f"{k} >= {v}" for k, v in (raw.get("floors") or {}).items() if not isinstance(v, dict)),
           *(f"damage {k} >= {v}" for k, v in ((raw.get("floors") or {}).get("damage") or {}).items()),
           *(f"major {m}" for m in raw.get("require_major") or []),
           *(f"{k} <= {v}" for k, v in (raw.get("caps") or {}).items())]
    if req:
        out["requirements"] = ", ".join(req)
    wp = [*(f"{s}={n}" for s, n in (raw.get("force") or {}).items()),
          *(f"exclude {n}" for n in raw.get("exclude") or []),
          *(f"no {t}" for t in raw.get("exclude_tiers") or [])]
    if wp:
        out["weapon"] = ", ".join(wp)
    if any(raw.get("tomes") or []):
        out["tomes"] = f"{sum(1 for t in raw['tomes'] if t)}/14 chosen"
    if "crafted" in raw:
        out["crafted"] = "yes" if raw["crafted"] else "no"
    if tree:
        out["tree"] = tree
    return out


def intake(raw=None, tree=None):
    """Lines: what a spec already answers and what is still to ask the player."""
    known = _known(raw, tree)
    lines = ["Known:" if known else "Nothing known yet."]
    lines += [f"  {label}: {known[key]}" for key, label, _ in QUESTIONS if key in known]
    missing = [(label, q) for key, label, q in QUESTIONS if key not in known]
    lines.append("Still to ask (only what is missing; skip what the player has already said):")
    lines += [f"  {label}: {q}" for label, q in missing] or ["  (nothing: ready to run)"]
    optional = {"requirements", "weapon", "tomes", "crafted", "tree"}
    must = [label for key, label, _ in QUESTIONS if key not in known and key not in optional]
    if must:
        lines.append(f"Required before a search: {', '.join(must)}.")
    return lines


def check_spec(raw, gd, tree=None, inventory=None):
    """(errors, warnings) for a spec before it is searched. Errors would stop `wt gear`."""
    from .search import KIND_NOTES, kind_for, needs_tree, spec_from
    errors, warnings = [], []
    for key in ("class", "level"):
        if key not in raw:
            errors.append(f"the spec has no {key!r}")
    if errors:
        return errors, warnings
    try:
        spec = spec_from(raw, gd, inventory)
    except (KeyError, ValueError) as e:
        return [str(e).strip('"')], warnings
    if not 1 <= spec.level <= 121:
        errors.append(f"level {spec.level} is outside 1-121")
    if spec.tomes and len(spec.tomes) != 14:
        errors.append(f"'tomes' has {len(spec.tomes)} entries; it needs 14 in slot order (null for empty)")
    for slot, name in spec.force.items():
        if slot not in SLOTS:
            errors.append(f"force slot {slot!r} is not one of {', '.join(SLOTS)}")
        elif slot == "weapon" and not name.startswith("CR-") and gd.weapon_class(name) != spec.cls:
            errors.append(f"forced weapon {name} is not a {spec.cls} weapon")
    both = sorted(set(spec.objective) & set(spec.caps))
    if both:
        warnings.append(f"{', '.join(both)} is both the goal and capped; the cap limits the goal")
    stats = [k for k in spec.objective if k != MIN_ELEDEF]
    weights = sorted(abs(w) for k, w in spec.objective.items() if k in stats and w)
    if len(weights) > 1 and weights[-2] / weights[-1] > 0.1:
        warnings.append("several goal stats with similar weights: unrequested stats can take a build "
                        "over (AGENTS.md rule 5). Use one goal; put the rest in floors, or a 0.01 tiebreaker.")
    kind = kind_for(spec)
    if needs_tree(spec) and not tree and not spec.atree:
        errors.append("damage goals or minimums need an ability tree: pass --tree PRESET")
    if spec.tome_pool != "fixed" and kind != "exact":
        errors.append("'tome_pool' owned/any needs the exact search; damage-model goals and minimums "
                      "can't use it (list the tomes instead, or drop those goals)")
    if spec.tome_pool == "owned" and not spec.tome_supply:
        warnings.append("'tome_pool' is owned but the inventory has no tomes: no tome will be chosen "
                        "(`wt own add --tome NAME`)")
    if spec.tome_pool == "any":
        warnings.append("tome_pool any: the search may pick tomes the player doesn't own; they are goals "
                        "to collect, and it may put the same tome in two paired slots (untested in game)")
    if kind == "local":
        warnings.append("a derived goal runs the local search: a minute or more, and the result is "
                        "good but not proven best (say so)")
    elif kind == "shortlists":
        warnings.append("damage-model minimums use the shortlist search: run with --confirm and call "
                        "the result best within the shortlists")
    warnings.append(f"search that will run: {KIND_NOTES[kind]}")
    if spec.crafted:
        warnings.append("crafted gear is allowed: the player must collect the ingredients (ask if they craft)")
    return errors, warnings


def _search_kind(doc):
    from .search import KIND_NOTES, kind_for, spec_from
    raw = doc.get("spec")
    if not raw:
        return "not made by `wt gear` (imported or hand-edited): no search ran, so nothing is 'best'"
    try:
        from .data import GameData
        spec = spec_from(raw, GameData())
    except (KeyError, ValueError):
        return "unknown (the saved spec no longer loads)"
    kind = kind_for(spec)
    text = KIND_NOTES[kind]
    if kind == "exact":
        text += " (if the run said it stopped at the time limit, it is valid but not proven best)"
    return f"{kind}: {text}"


def report(doc, gd, path):
    """Lines: the fixed closing report for a build file (link, verification, search, assumptions)."""
    from . import buildfile
    from .verify import check_link
    fresh = buildfile.refresh(doc, gd)
    ok, rep = check_link(fresh["link"], gd)
    st = fresh["status"]
    lines = [f"REPORT {path} (\"{fresh.get('name') or ''}\", level {fresh['level']})",
             f"Link: {fresh['link']}",
             "VERIFIED OK" if ok else "PROBLEMS:\n  - " + "\n  - ".join(rep["problems"]),
             f"Search: {_search_kind(doc)}"]
    spec = doc.get("spec") or {}
    if spec:
        lines.append(f"Objective: {spec.get('objective')}; minimums: {spec.get('floors') or 'none'}"
                     + (f"; majors: {spec['require_major']}" if spec.get("require_major") else ""))
    if doc.get("tree_preset"):
        lines.append(f"Tree preset: {doc['tree_preset']} (generic: it ignores damage, utility and other "
                     f"archetypes; say what it rewards, finish it in the editor)")
    sp = doc.get("skillpoints")
    hand = [v for v in sp or [] if v is not None]
    crafted = [n for n in doc.get("equipment") or [] if n and n.startswith("CR-")]
    tomes = sum(1 for t in doc.get("tomes") or [] if t)
    powders = any(doc.get("powders") or [])
    aspects = any(doc.get("aspects") or [])
    lines += ["Assumptions to state:",
              "  - Item stats are 100% rolls (real items roll 30-130%); WynnBuilder's page shows perfect "
              "(130%) rolls: say which one you quote",
              "  - Skill points: " + (f"set by hand for some skills (final totals {sp}); the build keeps them"
                                      if hand else "automatic"),
              "  - Aspects: " + ("present, as in the file" if aspects else "empty (players can add them; "
                                                                        "they change damage, not totals)"),
              {"owned": f"  - Tomes: {tomes}/14, chosen by the search from the tomes in the player's inventory",
               "any": f"  - Tomes: {tomes}/14, chosen by the search from ANY tome: goals to collect "
                      f"(check which the player owns); the same tome may fill two paired slots (untested in game)",
               }.get(spec.get("tome_pool"),
                     f"  - Tomes: {tomes}/14, goals to collect unless the player owns them"),
              "  - Powders: " + ("as in the file" if powders else "none (`wt powders` suggests some)"),
              "  - Damage: the developer guide's steps at WynnBuilder's defaults (no potions, buffs or "
              "powder specials), before the target's elemental defences"]
    if crafted:
        lines.append(f"  - Crafted items ({len(crafted)}): ranges, the middle counts as typical; the "
                     f"ingredients have to be collected")
    for w in st.get("warnings") or []:
        lines.append(f"  ! {w['message']}" + (" (fixable: search again with more minimums)" if w.get("fix") else ""))
    lines.append("Tell the player which file this is, and anything here that is tested or unknown "
                 "rather than proven (knowledge/mechanics.md).")
    return ok, lines
