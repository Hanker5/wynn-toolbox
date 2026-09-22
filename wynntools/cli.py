"""`wt` command line: fetch, decode, verify, tree, gear, link."""
import argparse
import json
import sys
from pathlib import Path

from .codec import POWDERABLE, SLOTS, TOME_SLOTS, Build, powder_name, to_link
from .data import LATEST, VERSIONS, GameData, fetch
from . import buildfile
from . import inventory as inv_mod
from .gear_solver import Spec, solve_gear, upgrades
from .progress import ProgressBar
from .presets import PRESETS, preset_weights, summoner_hits_per_sec
from .rules import ability_points
from .tree_solver import solve_tree
from .verify import check_link


def _print_report(ok, rep, gd):
    b, s = rep["build"], rep["summary"]
    t = s["totals"]
    print(f"Level {b.level} · data {VERSIONS[b.version]}")
    for i, (slot, name) in enumerate(zip(SLOTS, b.equipment)):
        pw = ""
        if i in POWDERABLE and b.powders[POWDERABLE.index(i)]:
            pw = "  [" + " ".join(powder_name(p) for p in b.powders[POWDERABLE.index(i)]) + "]"
        if name and name.startswith("CR-"):
            it = gd.item(name)
            print(f"  {slot:<11}crafted {it['type']} ({', '.join(x for x in it['craft'].ingredients if x != 'No Ingredient')}){pw}")
        else:
            print(f"  {slot:<11}{name or '—'}{pw}")
    used = [(TOME_SLOTS[k], gd.name(gd.tome(tid))) for k, tid in enumerate(b.tomes) if tid is not None]
    print(f"Tomes: {len(used)}/14")
    for slot, name in used:
        print(f"  {slot:<15}{name}")
    if b.weapon and b.aspects and any(b.aspects):
        names = {a["id"]: a["displayName"] for a in gd.aspects(gd.weapon_class(b.weapon))}
        print("Aspects: " + ", ".join(f"{names[a[0]]} (tier {a[1]})" for a in b.aspects if a))
    if b.weapon:
        tree = gd.tree(gd.weapon_class(b.weapon))
        names = sorted(n["display_name"] for n in tree if n["id"] in b.atree)
        print(f"Ability tree: {len(names)} nodes, {rep['ap'][0]}/{rep['ap'][1]} AP")
        if gd.weapon_class(b.weapon) == "Shaman":
            steady, buffed = summoner_hits_per_sec(tree, b.atree)
            print(f"  summon hits/sec: {steady:.1f} steady, {buffed:.1f} with Aura buffs")
    print(f"HP {t['hp']:,} · mana {s['mana_min_int']} (min Int) / {s['mana_spare_into_int']} "
          f"(spare into Int) · mr {t['mr']} · spd {t['spd']}%")
    extras = {k: t[k] for k in ("eSteal", "lb", "poison", "sdPct", "mdPct", "ms", "hprRaw") if t[k]}
    if extras:
        print("  " + " · ".join(f"{k} {v:,}" for k, v in extras.items()))
    if t["poison"]:
        print(f"  poison {s['poison_per_second']:,}/sec")
    tm = s["totals_max"]
    perfect = [f"HP {tm['hp']:,}"] + [f"{k} {tm[k]:,}" for k in ("eSteal", "poison", "mr", "lb") if tm[k]]
    print("  perfect rolls (what WynnBuilder shows): " + " · ".join(perfect))
    for st in s["sets"]:
        bonus = ", ".join(f"{k} {v:+}" if isinstance(v, int) else f"{k} {v}" for k, v in st["bonus"].items())
        print(f"Set {st['name']} ({st['pieces']}/{st['of']}): {bonus or 'no bonus at this count'}")
    print(f"Skill points: {s['sp_total']}/{s['sp_available']} to assign {s['sp_need']}")
    print("Note: totals above are 100% rolls; real items roll 30-130%.")
    print("VERIFIED OK" if ok else "PROBLEMS:\n  - " + "\n  - ".join(rep["problems"]))


def _print_damage(dmg, parts=False, label="typical rolls"):
    """One line per spell, like WynnBuilder's right column; `parts` adds detail."""
    if not dmg:
        return
    if "error" in dmg:
        print(f"Damage: could not compute ({dmg['error']})")
        return
    d = dmg["defense"]
    print(f"Damage ({label}; crit chance {dmg['crit_chance']}%):")
    for sp in dmg["spells"]:
        cost = f" ({sp['cost']:.2f} mana)" if sp["cost"] else ""
        if sp["dps"] is not None:
            line = f"{sp['dps']:,.0f} DPS · {sp['summary']:,.0f} per hit · {sp['attack_speed']}"
        elif sp["summary"] is None:
            line = "no damage"
        elif sp["summary_type"] == "heal":
            line = f"{sp['display']}: {sp['summary']:,.0f} healed"
        else:
            line = f"{sp['display']}: {sp['summary']:,.0f}"
        print(f"  {sp['name']}{cost}: {line}")
        if parts:
            for p in sp["parts"]:
                if p["type"] == "heal":
                    print(f"      {p['name']}: {p['heal']:,.0f} healed")
                else:
                    elems = ", ".join(f"{r[0]} {r[1]:,.0f}-{r[2]:,.0f}" for r in p["ranges"])
                    print(f"      {p['name']}: avg {p['average']:,.0f} "
                          f"(non-crit {p['non_crit']:,.0f}, crit {p['crit']:,.0f}) [{elems}]")
    print(f"  Effective HP {d['ehp']:,.0f} ({d['ehp_no_agi']:,.0f} without agility dodge) · "
          f"HP regen {d['hpr']:,.0f}")
    if dmg["poison_tick"]:
        print(f"  Poison {dmg['poison_tick']:,}/s")
    if dmg["sliders"] or dmg["toggles"]:
        extra = [f"{k} at {v['default']}" for k, v in dmg["sliders"].items()] + \
                [f"{t} off" for t in dmg["toggles"]]
        print("  Ability sliders/toggles at WynnBuilder's defaults: " + ", ".join(extra))


def _tree_for(build_level, weapon, preset, gd):
    cls = gd.weapon_class(weapon)
    if preset not in PRESETS:        # e.g. a build file naming a preset that was removed
        raise SystemExit(f"unknown tree preset {preset!r}; `wt tree --help` lists them")
    P = PRESETS[preset]
    if P["class"] != cls:
        raise SystemExit(f"preset {preset} is for {P['class']}, weapon {weapon} is {cls}")
    return solve_tree(gd.tree(cls), preset_weights(preset, gd), ability_points(build_level))


def _resolve_tomes(entries, gd):
    tomes = [None] * len(TOME_SLOTS)
    for k, t in enumerate(entries or []):
        if t is not None:
            tomes[k] = gd.tome(t)["id"]
    return tomes


def cmd_fetch(a):
    from .web import client

    def downloaded(done, total, name):
        client.report(done / total, f"{done}/{total} files · {name}")
    print("cached in", fetch(refresh=a.refresh, progress=downloaded))


def _link_arg(arg, gd):
    """A link, a bare hash, or a path to a build file."""
    if arg.endswith(".json") and Path(arg).exists():
        return to_link(buildfile.to_build(buildfile.read(arg), gd), gd)
    return arg


def cmd_decode(a):
    from .damage import summary
    gd = GameData()
    ok, rep = check_link(_link_arg(a.link, gd), gd)
    _print_report(ok, rep, gd)
    dmg = summary(rep["build"], gd)
    if dmg:
        _print_damage(dmg.get("typical", dmg))
    return 0 if ok else 1


def cmd_damage(a):
    """WynnBuilder's spell/melee damage and effective HP for a link or build file."""
    from .codec import decode, link_hash
    from .damage import summary
    gd = GameData()
    inventory = inv_mod.load(a.inventory) if a.inventory else None
    build = decode(link_hash(_link_arg(a.link, gd)), gd)
    dmg = summary(build, gd, inventory)
    if not dmg:
        raise SystemExit("this build has no weapon")
    if "error" in dmg:
        raise SystemExit(f"could not compute damage: {dmg['error']}")
    if a.json:
        print(json.dumps(dmg["perfect" if a.perfect else "typical"], indent=2))
        return 0
    _print_damage(dmg["perfect" if a.perfect else "typical"], parts=a.parts,
                  label="perfect rolls, as WynnBuilder shows" if a.perfect else "typical rolls")
    return 0


def cmd_tree(a):
    gd = GameData()
    P = PRESETS[a.preset]
    tree = gd.tree(P["class"])
    ap = a.ap or ability_points(a.level)
    sel = solve_tree(tree, preset_weights(a.preset, gd), ap)
    print(f"{a.preset}: {P['about']}")
    by_id = {n["id"]: n for n in tree}
    print(f"{len(sel)} nodes, {sum(by_id[i].get('cost') or 0 for i in sel)}/{ap} AP")
    for i in sorted(sel):
        print(f"  {by_id[i]['display_name']:<26}{by_id[i].get('archetype') or ''}")


def _build_from(spec, equipment, tree_preset, gd):
    b = Build(equipment=equipment, level=spec["level"],
              tomes=_resolve_tomes(spec.get("tomes"), gd), version=LATEST)
    if tree_preset:
        b.atree = _tree_for(b.level, b.weapon, tree_preset, gd)
    return b


def _damage_tree(spec, preset, gd):
    """Damage floors are checked on a fixed tree: the preset's, solved up front."""
    if not spec.floors.get("damage"):
        return
    if not preset:
        raise SystemExit("damage floors need a tree: add --tree PRESET")
    if PRESETS[preset]["class"] != spec.cls:
        raise SystemExit(f"preset {preset} is for {PRESETS[preset]['class']}")
    spec.atree = set(solve_tree(gd.tree(spec.cls), preset_weights(preset, gd),
                                ability_points(spec.level)))


def _spec_from(raw, gd):
    return Spec(cls=raw["class"], level=raw["level"], objective=raw["objective"],
                floors=raw.get("floors", {}), require_major=raw.get("require_major", []),
                force=raw.get("force", {}), exclude=set(raw.get("exclude", [])),
                exclude_tiers=set(raw.get("exclude_tiers", [])),
                tomes=[None if t is None else gd.tome(t)["id"] for t in raw.get("tomes", [])],
                topn=raw.get("topn", 8), crafted=bool(raw.get("crafted")),
                roll=raw.get("roll", "base"))


def _slot_list(text):
    slots = [x.strip() for x in (text or "").split(",") if x.strip()]
    bad = [x for x in slots if x not in SLOTS]
    if bad:
        raise SystemExit(f"unknown slot {bad[0]!r}; slots are {', '.join(SLOTS)}")
    return slots


def _edit_spec(a, doc, gd):
    """The spec for re-searching an existing build: the spec file if given, else the
    one the build was made with. Class, level and tomes default to the build's, and
    the slots the player keeps are forced to the build's items."""
    if a.spec:
        raw = json.load(open(a.spec, encoding="utf-8"))
    elif doc.get("spec"):
        raw = dict(doc["spec"])
    else:
        raise SystemExit(f"{a.edit} wasn't made by `wt gear`, so it has no spec to reuse: "
                         f"write one (class, level, objective, floors, ...) and pass it")
    equipment = list(doc.get("equipment") or [None] * len(SLOTS))
    if equipment[8]:
        raw.setdefault("class", gd.weapon_class(equipment[8]))
    raw.setdefault("level", doc["level"])
    if "tomes" not in raw and any(doc.get("tomes") or []):
        raw["tomes"] = doc["tomes"]
    if a.keep and a.change:
        raise SystemExit("pass --keep or --change, not both")
    keep = _slot_list(a.keep) if a.keep else \
        [s for s in SLOTS if s not in _slot_list(a.change)] if a.change else []
    force = dict(raw.get("force") or {})
    for slot in keep:
        item = equipment[SLOTS.index(slot)]
        if not item:
            raise SystemExit(f"can't keep {slot}: it's empty in {a.edit}; let the search fill it")
        if force.get(slot, item) != item:
            raise SystemExit(f"the spec forces {force[slot]} into {slot}, but --keep keeps {item}")
        force[slot] = item
    raw["force"] = force
    return raw


def _same_ring_order(new, old):
    """Rings are interchangeable: put a ring the build already had back in its old
    slot, so a re-search doesn't report a swap as a change."""
    r1, r2 = SLOTS.index("ring1"), SLOTS.index("ring2")
    if (new[r1] != old[r1] and new[r2] == old[r1]) or (new[r2] != old[r2] and new[r1] == old[r2]):
        new[r1], new[r2] = new[r2], new[r1]


def _merge_into(doc, new, gd, tree_preset=None):
    """The re-searched build `new` written over `doc`. Name and notes carry over,
    and so do powders on unchanged items, and aspects and the tree while the
    class stays the same (unless `tree_preset` re-solves the tree). Returns the
    doc and lines describing what changed."""
    old_eq = list(doc.get("equipment") or [None] * len(SLOTS))
    new_eq = new["equipment"]
    out = {**doc, "level": new["level"], "equipment": new_eq, "tomes": new["tomes"]}
    lines = [f"  {slot:<12}{old_eq[k] or '(empty)'} -> {new_eq[k] or '(empty)'}"
             for k, slot in enumerate(SLOTS) if old_eq[k] != new_eq[k]]
    if (doc.get("tomes") or []) != new["tomes"]:
        lines.append("  tomes       now the spec's")
    same_class = bool(old_eq[8]) and gd.weapon_class(old_eq[8]) == gd.weapon_class(new_eq[8])
    if doc.get("powders"):             # powder lists: helmet, chestplate, leggings, boots, weapon
        powders = [list(p) for p in doc["powders"]]
        for k, slot in enumerate((0, 1, 2, 3, 8)):
            if powders[k] and old_eq[slot] != new_eq[slot]:
                lines.append(f"  powders     taken off: the {SLOTS[slot]} changed")
                powders[k] = []
        out["powders"] = powders
    if not same_class:
        if doc.get("aspects") and any(doc["aspects"]):
            lines.append("  aspects     cleared: the weapon's class changed")
        out.pop("aspects", None)
        out["tree_preset"] = tree_preset
    if tree_preset or not same_class or not doc.get("tree"):
        out["tree"] = new.get("tree", [])
        if tree_preset:
            out["tree_preset"] = tree_preset
        if doc.get("tree") and out["tree"] != doc["tree"]:
            lines.append(f"  tree        re-solved with {tree_preset}" if tree_preset else
                         "  tree        cleared: the weapon's class changed (add --tree PRESET)")
    if doc.get("skillpoints") and old_eq != new_eq:
        lines.append("  skill points  back to automatic: the items changed")
        out["skillpoints"] = None
    return out, lines


def cmd_gear(a):
    gd = GameData()
    if a.edit:
        if a.save:
            raise SystemExit("--edit writes back into the build; use --save-as for a variant, not --save")
        _refuse_if_unsaved(a.edit, a.force or bool(a.save_as))
        if a.save_as and Path(a.save_as).exists() and not a.force:
            raise SystemExit(f"{a.save_as} already exists; pick another name or pass --force")
        old_doc = buildfile.read(a.edit)
        raw = _edit_spec(a, old_doc, gd)
    elif a.save_as or a.keep or a.change:
        raise SystemExit("--save-as, --keep and --change go with --edit builds/<name>.json")
    elif not a.spec:
        raise SystemExit("give a spec file, or --edit builds/<name>.json to re-search a build")
    else:
        raw = json.load(open(a.spec, encoding="utf-8"))
    spec = _spec_from(raw, gd)
    _damage_tree(spec, a.tree, gd)
    if a.owned:
        inv = inv_mod.load(a.inventory)
        spec.only, spec.inventory, spec.crafted = inv.names(), inv, False
        print(f"Searching only the {len(inv.names())} items in {a.inventory} (real rolls where given).")
    if a.edit:
        from .gear_solver import _usable
        pools = _usable(gd, spec)
        unusable = [f"{slot}={name}" for slot, name in spec.force.items()
                    if not any(gd.name(i) == name for i in pools[slot])]
        if unusable:
            raise SystemExit(f"the search can't use these kept items: {', '.join(unusable)} (above the "
                             f"level, excluded, not owned, or for another class); --change those slots")
    exact = not a.shortlists and not spec.floors.get("damage")
    if not a.shortlists and not exact:
        print("(damage floors use the shortlist search; the exact search can't check them)")
    if exact:
        from .gear_milp import solve_gear_exact
        from .web import client

        def rounds(p):
            client.report(None, f"round {p['round']} · best bound {p['best']:g}")
            if not a.quiet:
                print(f"\r  exact search: round {p['round']}, best bound {p['best']:g}, "
                      f"{p['elapsed']:.0f}s", end="", file=sys.stderr, flush=True)
        try:
            r = solve_gear_exact(spec, gd, progress=rounds)
        except (ValueError, TimeoutError) as e:
            raise SystemExit(str(e))
        if not a.quiet:
            print(file=sys.stderr)
    else:
        r = solve_gear(spec, gd, progress=None if a.quiet else ProgressBar("gear search"))
    if r is None:
        print("No build satisfies these constraints.")
        return 1
    if exact:
        print("(exact search: the best build over every usable item)")
    elif a.confirm:
        spec.topn += 3
        r2 = solve_gear(spec, gd, progress=None if a.quiet else ProgressBar("confirm search"))
        if r2 and r2.score > r.score + 1e-9:
            print(f"(confirm: larger shortlists found a better build, {r2.score:g} > {r.score:g})")
            r = r2
        else:
            print(f"(confirm: larger shortlists found nothing better)")
    print(f"Search took {r.seconds:.0f}s; objective {r.score:g}")
    if a.edit:
        _same_ring_order(r.equipment, old_doc.get("equipment") or [None] * len(SLOTS))
    b = _build_from(raw, r.equipment, a.tree, gd)
    link = to_link(b, gd)
    ok, rep = check_link(link, gd)
    _print_report(ok, rep, gd)
    from .damage import summary
    dmg = summary(b, gd, spec.inventory)
    if dmg:
        _print_damage(dmg.get("typical", dmg))
    print(link)
    if a.edit:
        doc, lines = _merge_into(old_doc, buildfile.from_build(b, gd), gd, a.tree)
        doc["spec"] = {k: v for k, v in raw.items() if not k.startswith("_")}
        if a.name:
            doc["name"] = a.name
        elif a.save_as:
            doc["name"] = Path(a.save_as).stem
        doc = buildfile.refresh(doc, gd)
        out = a.save_as or a.edit
        print("changes:" if lines else "(no changes: the build's gear is already the best for this spec)")
        for line in lines:
            print(line)
        if doc["link"] != link:          # powders, aspects or its own tree carried over
            ok, rep = check_link(doc["link"], gd)
            print("with what the build already had (powders, aspects, tree):")
            _print_report(ok, rep, gd)
            print(doc["link"])
        buildfile.write(out, doc)
        print(f"{'saved' if a.save_as else 'updated'} {out}")
        if not a.no_show:
            _show_in_app(out)
    elif a.save:
        doc = {"name": a.name or Path(a.save).stem,
               "notes": raw.get("_about", ""), **buildfile.from_build(b, gd),
               "spec": {k: v for k, v in raw.items() if not k.startswith("_")},
               "tree_preset": a.tree}
        buildfile.write(a.save, buildfile.refresh(doc, gd))
        print(f"saved {a.save}")
        if not a.no_show:
            _show_in_app(a.save)
    else:
        print("(not saved: add --save builds/<name>.json to put it in the player's build list)")
    return 0 if ok else 1


def cmd_import(a):
    gd = GameData()
    from .codec import decode
    b = decode(a.link, gd)
    doc = buildfile.refresh({"name": a.name or Path(a.path).stem, "notes": "",
                             **buildfile.from_build(b, gd)}, gd)
    buildfile.write(a.path, doc)
    print(f"saved {a.path} ({'verified' if doc['status']['verified'] else 'HAS PROBLEMS'})")
    if not a.no_show:
        _show_in_app(a.path)
    return 0 if doc["status"]["verified"] else 1


def cmd_link(a):
    gd = GameData()
    if a.write:
        _refuse_if_unsaved(a.build, a.force)
    doc = buildfile.read(a.build)
    if not doc.get("tree") and doc.get("tree_preset"):
        b = _build_from(doc, doc["equipment"], doc["tree_preset"], gd)
        doc = {**doc, **buildfile.from_build(b, gd)}
    link = to_link(buildfile.to_build(doc, gd), gd)
    ok, rep = check_link(link, gd)
    _print_report(ok, rep, gd)
    print(link)
    if a.write:
        buildfile.write(a.build, buildfile.refresh(doc, gd))
        print(f"updated {a.build}")
    return 0 if ok else 1


# ---------------------------------------------------------------- the web app
BUILDS = Path("builds")
VIEW_NAMES = {"empty": "the start page", "editor": "the build editor",
              "solver": "the \"New build from goals\" form", "inventory": "the Inventory page",
              "compare": "the Compare builds page"}


# What the terminal panel's progress bars call each command while it runs.
ACTIVITY = {"fetch": "Downloading WynnBuilder data", "decode": "Checking a build",
            "verify": "Checking a build", "damage": "Calculating damage",
            "tree": "Solving the ability tree", "gear": "Searching for gear",
            "upgrades": "Ranking upgrades", "import": "Importing a build",
            "link": "Checking a build", "edit": "Editing a build",
            "craft": "Finding crafted items", "compare": "Comparing builds",
            "ingredient": "Looking up an ingredient"}
NO_PROGRESS = {"serve", "update"}      # the app itself, and replacing it


def _in_builds(path):
    return Path(path).resolve().parent == BUILDS.resolve()


def _show_in_app(path):
    """Open a build file in the running web app. Does nothing if the app isn't
    running or the file isn't one the app lists (directly inside builds/)."""
    from .web import client
    if not _in_builds(path) or not client.running(BUILDS):
        return False
    client.request_show(BUILDS, Path(path).name)
    print(f"opened {Path(path).name} in the web app")
    return True


def _view():
    from .web import client
    return client.view(BUILDS)


def _hook_context(v):
    """One or two lines for an AI's per-prompt hook: what the player has open."""
    if not v or v.get("at") is None:
        return None
    where = VIEW_NAMES.get(v.get("view"), "the app")
    if not v.get("file"):
        return f"[Wynn Toolbox] The player is on {where} in the web app, with no build open."
    path = BUILDS / v["file"]
    doc = v.get("doc") if v.get("dirty") and v.get("doc") else (buildfile.read(path) if path.exists() else {})
    name = doc.get("name") or path.stem
    first = (f"[Wynn Toolbox] The player has {path} (\"{name}\", level {doc.get('level')}) open in the build editor"
             if v.get("view") == "editor" else
             f"[Wynn Toolbox] The player is on {where}; the last build they opened is {path} (\"{name}\")")
    if v.get("dirty"):
        first += ", with UNSAVED edits (ask them to Save before you change the file)"
    return first + ". \"This build\" means that one; run `wt current` for its details before answering about it."


def _refuse_if_unsaved(path, force):
    """Don't write over a build the player is editing in the page without saving."""
    v = _view()
    if force or not v or not v.get("dirty") or not _in_builds(path) or v.get("file") != Path(path).name:
        return
    raise SystemExit(f"The player has unsaved edits to {path} in the web app. Ask them to Save "
                     f"(or Revert) first. --force writes anyway; the page then asks them which "
                     f"version to keep.")


def cmd_current(a):
    """What the player is looking at in the web app, with the build's full report."""
    from .damage import summary
    v = _view()
    if a.hook:                    # for Claude/Codex/Gemini prompt hooks: fast, always exit 0
        text = _hook_context(v)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": a.hook, "additionalContext": text}}
                         if text else {}))
        return 0
    if v is None:
        print("The web app isn't running, so there is no current build. "
              "List the build files with `uv run wt builds`.")
        return 1
    if v.get("at") is None:
        print("The web app is running, but no page has opened it yet.")
        return 1
    if a.json:
        print(json.dumps({**v, "path": str(BUILDS / v["file"]) if v.get("file") else None}, indent=2))
        return 0
    where = VIEW_NAMES.get(v["view"], v["view"])
    if not v.get("file"):
        print(f"The player is on {where}, with no build open.")
        return 0
    path = BUILDS / v["file"]
    if v["view"] == "editor":
        print(f"The player is looking at {path}")
    else:
        print(f"The player is on {where}. The last build they opened is {path}")
    if not path.exists():
        print("(that file no longer exists)")
        return 1
    on_disk = buildfile.read(path)
    doc = v["doc"] if v.get("dirty") and v.get("doc") else on_disk
    if v.get("dirty"):
        print("It has UNSAVED edits in the page. Everything below includes them; the file on disk "
              "doesn't yet. Ask the player to Save before you change the file.")
    print(f"Name: {doc.get('name') or path.stem}")
    if doc.get("notes"):
        print(f"Notes: {doc['notes']}")
    if on_disk.get("spec"):
        print(f"Made by `wt gear` from: {json.dumps(on_disk['spec'])}"
              + (f" with tree preset {on_disk['tree_preset']}" if on_disk.get("tree_preset") else ""))
    gd = GameData()
    inventory = inv_mod.load(a.inventory)
    try:
        b = buildfile.to_build(doc, gd)
    except (KeyError, ValueError, NotImplementedError) as e:
        print(f"PROBLEMS:\n  - can't read this build: {e}")
        return 1
    link = to_link(b, gd)
    ok, rep = check_link(link, gd, inventory=inventory)
    _print_report(ok, rep, gd)
    dmg = summary(rep["build"], gd, inventory)
    if dmg:
        _print_damage(dmg.get("typical", dmg))
    print(link)
    return 0 if ok else 1


def cmd_show(a):
    """Open a build file in the web app, for the player to look at."""
    from .web import client
    path = Path(a.build)
    if not path.exists() and not path.parent.parts:
        path = BUILDS / path
    if not path.exists():
        raise SystemExit(f"no build file {a.build}")
    if not _in_builds(path):
        raise SystemExit("the web app only lists build files directly inside builds/")
    if not client.running(BUILDS):
        raise SystemExit("The web app isn't running. The player can start it with `uv run wt serve`.")
    client.request_show(BUILDS, path.name)
    print(f"opened {path.name} in the web app (if the player has unsaved edits to another "
          f"build, it is only pointed out to them)")
    return 0


def cmd_builds(a):
    """The player's build files, like the web app's sidebar."""
    gd = GameData()
    v = _view() or {}
    files = [p for p in sorted(BUILDS.glob("*.json"))
             if p.name not in ("inventory.json", "settings.json") and not p.name.startswith(".")]
    if not files:
        print("No build files yet in builds/.")
        return 0
    for p in files:
        mark = "▶" if p.name == v.get("file") else " "
        try:
            doc = buildfile.read(p)
            st = doc.get("status") or {}
            t = st.get("totals") or {}
            weapon = (doc.get("equipment") or [None] * 9)[8]
            cls = gd.weapon_class(weapon) if weapon else "?"
            key = " · ".join(f"{k} {t[k]:,}" for k in ("hp", "eSteal", "poison", "lb") if t.get(k))
            state = "verified" if st.get("verified") else "HAS PROBLEMS" if st else "not checked"
            print(f"{mark} {str(p):<36} {doc.get('name') or p.stem} · {cls} Lv. {doc.get('level')} "
                  f"· {state}" + (f" · {key}" if key else ""))
        except (ValueError, KeyError, OSError, NotImplementedError) as e:
            print(f"{mark} {str(p):<36} can't read: {e}")
    if v.get("file"):
        print("▶ = open in the web app" + (" (with unsaved edits)" if v.get("dirty") else ""))
    return 0


SLOT_KIND = {"ring1": "ring", "ring2": "ring"}


def cmd_edit(a):
    """Change a build file's items, tomes, level, name or tree, then re-check it."""
    from .gear_solver import CLASS_WEAPON
    gd = GameData()
    _refuse_if_unsaved(a.build, a.force or bool(a.save_as))
    doc = buildfile.read(a.build)
    doc["equipment"] = list(doc.get("equipment") or [None] * len(SLOTS))
    doc["tomes"] = list(doc.get("tomes") or []) + [None] * (len(TOME_SLOTS) - len(doc.get("tomes") or []))
    for entry in a.item or []:
        slot, _, name = entry.partition("=")
        if slot not in SLOTS:
            raise SystemExit(f"unknown slot {slot!r}; slots are {', '.join(SLOTS)}")
        name = name.strip() or None
        if name:
            try:
                it = gd.item(name)
            except (KeyError, ValueError, NotImplementedError):
                raise SystemExit(f"no item named {name!r}")
            kinds = set(CLASS_WEAPON.values()) if slot == "weapon" else {SLOT_KIND.get(slot, slot)}
            if it.get("type") not in kinds:
                raise SystemExit(f"{name} is a {it.get('type')}, not a {SLOT_KIND.get(slot, slot)}")
            name = gd.name(it)
        doc["equipment"][SLOTS.index(slot)] = name
    for entry in a.tome or []:
        slot, _, name = entry.partition("=")
        if slot not in TOME_SLOTS:
            raise SystemExit(f"unknown tome slot {slot!r}; slots are {', '.join(TOME_SLOTS)}")
        name = name.strip() or None
        if name:
            try:
                name = gd.name(gd.tome(name))
            except (KeyError, ValueError):
                raise SystemExit(f"no tome named {name!r}")
        doc["tomes"][TOME_SLOTS.index(slot)] = name
    if a.level is not None:
        doc["level"] = a.level
    if a.name is not None:
        doc["name"] = a.name
    elif a.save_as:
        doc["name"] = Path(a.save_as).stem
    if a.notes is not None:
        doc["notes"] = a.notes
    if a.tree_preset:
        if not doc["equipment"][8]:
            raise SystemExit("a tree preset needs a weapon (it decides the class)")
        b = buildfile.to_build({**doc, "tree": []}, gd)
        b.atree = _tree_for(b.level, b.weapon, a.tree_preset, gd)
        doc["tree"] = buildfile.from_build(b, gd)["tree"]
        doc["tree_preset"] = a.tree_preset
    elif doc["equipment"][8] and doc.get("tree"):
        try:                                   # a weapon of another class keeps no nodes
            buildfile.to_build(doc, gd)
        except KeyError:
            print("(the weapon's class changed, so the ability tree was cleared; "
                  "add --tree-preset to pick one)")
            doc["tree"] = []
    try:
        doc = buildfile.refresh(doc, gd)
    except (KeyError, ValueError, NotImplementedError) as e:
        raise SystemExit(f"can't make that build: {e}")
    out = a.save_as or a.build
    if a.save_as and Path(out).exists() and not a.force:
        raise SystemExit(f"{out} already exists; pick another name or pass --force")
    link = doc["link"]
    ok, rep = check_link(link, gd)
    _print_report(ok, rep, gd)
    print(link)
    buildfile.write(out, doc)
    print(f"{'saved' if a.save_as else 'updated'} {out}")
    _show_in_app(out)
    return 0 if ok else 1


def cmd_upgrades(a):
    gd = GameData()
    spec = _spec_from(json.load(open(a.spec, encoding="utf-8")), gd)
    _damage_tree(spec, a.tree, gd)
    inv = inv_mod.load(a.inventory)
    if not inv.names():
        print(f"{a.inventory} is empty. Add items with: uv run wt own add \"Item Name\"")
        return 1
    base, ups = upgrades(spec, gd, inv, per_slot=a.per_slot, top=a.top,
                         progress=None if a.quiet else ProgressBar("upgrade search"))
    goal = ", ".join(spec.objective)
    if base:
        print(f"Best build from what you own: {goal} score {base.score:,.2f}")
        print("  " + " / ".join(n or "(empty)" for n in base.equipment))
    else:
        print("You can't make a build that meets these requirements from what you own yet.")
    if not ups:
        print("No single item you don't own improves on that.")
        return 0
    print(f"\nBest single items to get next (each alone, added to what you own):")
    for u in ups:
        gain = "makes a valid build possible" if u.gain is None else f"+{u.gain:,.2f}"
        print(f"  {gain:>28}  {u.slot:<10} {u.item}")
    return 0


def cmd_own(a):
    gd = GameData()
    inv = inv_mod.load(a.inventory)
    if a.action == "list":
        for n in sorted(inv.items):
            r = inv.rolls(n)
            print(f"  {n}" + (f"  (rolls: {', '.join(f'{k} {v}' for k, v in r.items())})" if r else ""))
        for t in inv.tomes:
            print(f"  tome: {t}")
        for c in inv.crafts:
            it = gd.item(c)
            print(f"  crafted {it['type']}: {c}")
        bad = inv_mod.validate(inv, gd)
        if bad:
            print("Not found in the game data: " + ", ".join(bad))
        return 0
    for name in a.names:
        if a.action == "add":
            if a.tome:
                gd.tome(name)
                inv.tomes.append(name)
            elif name.startswith("CR-"):
                gd.item(name)
                inv.crafts.append(name)
            else:
                gd.item(name)                                # raises on typos
                entry = inv.items.setdefault(name, {})
                if a.roll:
                    entry["rolls"] = {**entry.get("rolls", {}),
                                      **{k: int(v) for k, v in (r.split("=") for r in a.roll)}}
        else:
            if a.tome and name in inv.tomes:
                inv.tomes.remove(name)
            inv.items.pop(name, None)
            if name in inv.crafts:
                inv.crafts.remove(name)
    inv_mod.save(inv, a.inventory)
    print(f"{a.inventory}: {len(inv.items)} items, {len(inv.tomes)} tomes, {len(inv.crafts)} crafts")
    return 0


CRAFTER_URL = "https://wynnbuilder.github.io/crafter/#"


def describe_craft(it, cd=None):
    """Human-readable lines for a crafted item."""
    from .verify import stat
    c = it["craft"]
    rows = [c.ingredients[i:i + 2] for i in (0, 2, 4)]
    stats = {k: f"{stat(it, k, 'min')}–{stat(it, k, 'max')}" for k in sorted(it["rolls"])}
    lines = [f"{c.recipe} · materials tier {c.mat_tiers[0]}/{c.mat_tiers[1]}"
             + (f" · {c.atk_spd}" if it["category"] == "weapon" else ""),
             *[("  grid:  " if i == 0 else "         ") + " | ".join(f"{x:<24}" for x in r)
               for i, r in enumerate(rows)],
             "  stats: " + ", ".join(f"{k} {v}" for k, v in stats.items() if v != "0–0")]
    if it["category"] == "armor":
        lines.append(f"  health {it['hp']}")
    reqs = {s: it[f"{s}Req"] for s in ("str", "dex", "int", "def", "agi") if it[f"{s}Req"]}
    lines.append(f"  requirements {reqs or 'none'} · durability {it['durability'][0]}-{it['durability'][1]}")
    lines.append(f"  {CRAFTER_URL}{it['name'][3:]}")
    if cd is not None:
        from .crafting import NO_INGREDIENT, source_line
        lines.append("  where to get them (x, z):")
        for name in dict.fromkeys(c.ingredients):
            if name != NO_INGREDIENT:
                n = c.ingredients.count(name)
                lines.append(f"    {n}x {name}: {source_line(cd.ing_by_name[name])}")
    return lines


def cmd_craft(a):
    from .craft_solver import CraftSpec, suggest_crafts
    gd = GameData()
    objective = {a.maximize: 1.0}
    for extra in a.also or []:
        k, w = extra.split("=")
        objective[k] = float(w)
    res = suggest_crafts(CraftSpec(a.type, a.level, objective, roll=a.roll,
                                   max_total_reqs=a.max_reqs), gd.crafts, top=a.top)
    if not res:
        print("No valid craft found (check the item type and level).")
        return 1
    print(f"Best crafted {a.type} for {objective} at level {a.level} "
          f"(IDs at {a.roll} roll; crafted ranges are ingredient min–max)")
    for rank, (score, it) in enumerate(res, 1):
        print(f"\n#{rank}  score {score:g}")
        for line in describe_craft(it, gd.crafts):
            print("  " + line)
    return 0


def cmd_compare(a):
    """Two builds (links or build files) side by side."""
    from .codec import decode, link_hash
    from .compare import compare
    gd = GameData()
    ba, bb = (decode(link_hash(_link_arg(x, gd)), gd) for x in (a.a, a.b))
    roll = "max" if a.perfect else "base"
    r = compare(ba, bb, gd, roll)
    na, nb = (Path(x).stem if x.endswith(".json") else "A" if i == 0 else "B"
              for i, x in enumerate((a.a, a.b)))
    w, k = 24, 24

    def num(v):
        return "—" if v is None else f"{v:,.0f}" if isinstance(v, float) else f"{v:,}"

    def diff(v):
        return "" if not v else f"{v:+,.0f}" if isinstance(v, float) else f"{v:+,}"

    def item(n):
        if n and n.startswith("CR-"):
            return f"crafted {gd.item(n)['type']}"
        return (n or "—")[:w - 2]
    print(f"{'':<{k}}{na[:w - 2]:<{w}}{nb[:w - 2]:<{w}}({'perfect' if a.perfect else 'typical'} rolls)")
    for row in r["gear"]:
        mark = "" if row["same"] else "*"
        print(f"{row['key']:<{k}}{item(row['a']):<{w}}{item(row['b']):<{w}}{mark}")
    print()
    for row in r["stats"] + r["damage"]:
        print(f"{row['key'][:k - 2]:<{k}}{num(row['a']):<{w}}{num(row['b']):<{w}}{diff(row['diff'])}")
    if not r["same_class"]:
        print("\n(Different classes: spells are listed by name and don't line up.)")
    return 0


def cmd_ingredient(a):
    """Where an ingredient drops, with every known spot."""
    from .crafting import ingredient_sources
    cd = GameData().crafts
    matches = [n for n in cd.ing_by_name if a.name.lower() in n.lower()]
    exact = [n for n in matches if n.lower() == a.name.lower()]
    if exact:
        matches = exact
    if not matches:
        raise SystemExit(f"no ingredient matches {a.name!r}")
    if len(matches) > 1:
        print("Several ingredients match: " + ", ".join(sorted(matches)[:20]))
        return 1
    ing = cd.ing_by_name[matches[0]]
    stats = ", ".join(f"{k} {v['minimum']}..{v['maximum']}" for k, v in (ing.get("ids") or {}).items())
    print(f"{matches[0]} · level {ing.get('lvl')} · {'★' * (ing.get('tier') or 0)} · "
          f"{', '.join(s.title() for s in ing.get('skills') or [])}")
    if stats:
        print(f"  {stats}")
    src = ingredient_sources(ing)
    if not src:
        print("  No mob is listed in WynnBuilder's data (it may come from a merchant, quest or gathering).")
    for e in src:
        where = "; ".join(f"({x}, {y}, {z}) within {r}" for x, y, z, r in e["spots"]) or "no location listed"
        print(f"  {e['mob']}: {where}")
    return 0


def cmd_config(a):
    """Show or change app settings (builds/settings.json)."""
    from . import settings
    if a.key is None:
        for k, v in settings.load(a.file).items():
            print(f"{k} = {v if v is not None else '(not set)'}")
        return 0
    if a.key not in ("ai", "check_updates"):
        raise SystemExit("settings you can change here: ai, check_updates")
    if a.value is None:
        v = settings.load(a.file)[a.key]
        print(v if v is not None else "(not set)")
        return 0
    if a.key == "check_updates":
        flags = {"on": True, "true": True, "yes": True, "off": False, "false": False, "no": False}
        if a.value.lower() not in flags:
            raise SystemExit("check_updates must be on or off")
        settings.save({"check_updates": flags[a.value.lower()]}, a.file)
        print(f"check_updates = {'on' if flags[a.value.lower()] else 'off'}")
        return 0
    value = None if a.value in ("none", "unset") else a.value
    try:
        settings.save({"ai": value}, a.file)
    except ValueError as e:
        raise SystemExit(str(e))
    print(f"ai = {value or '(not set)'}; the web app uses it the next time its terminal starts.")
    return 0


def cmd_update(a):
    """Is a newer Wynn Toolbox on GitHub? Without --check, install it."""
    from . import updates
    from .web.client import running
    r = updates.check(updates.ROOT, a.builds, force=True)
    if r["error"]:
        raise SystemExit(f"Couldn't check for updates: {r['error']}")
    if not r["available"]:
        print(f"Wynn Toolbox is up to date ({(r['current'] or '?')[:7]} on {r['branch']}).")
        return 0
    what = (f"{r['ahead_by']} new change{'s' if r['ahead_by'] != 1 else ''}"
            if r["ahead_by"] is not None else "a newer version (this one's version is unknown)")
    print(f"Update available: {what}, latest {r['latest'][:7]}.")
    for c in r["commits"]:
        print(f"  - {c['message']}")
    if a.check:
        return 0
    if not r["can_update"]:
        print("This is a git clone: update it with `git pull`.")
        return 0
    if running(a.builds):
        raise SystemExit("Wynn Toolbox is open: use the Update button in the app, or close "
                         "it and run `wt update` again.")
    installer = "install.ps1" if sys.platform == "win32" else "install.sh"
    print(f"Installing (install/{installer} from {r['latest'][:7]})...", flush=True)
    import subprocess
    argv, env, _ = updates.update_command(updates.ROOT, a.builds, r["latest"], pid=0,
                                          relaunch=None)      # pid 0: nothing to wait for
    return subprocess.call(argv, env=env)


def cmd_serve(a):
    from .web.server import serve
    serve(a.builds, a.port, mode="none" if a.no_browser else "browser" if a.browser else None)


def app_main():
    """The console-less launcher (Windows shortcut): `wt serve` by default,
    with output to builds/app.log since there is no console to show it."""
    if sys.stdout is None or sys.stderr is None:
        Path("builds").mkdir(exist_ok=True)
        log = open("builds/app.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    main(sys.argv[1:] or ["serve"])


def main(argv=None):
    p = argparse.ArgumentParser(prog="wt", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("fetch", help="download WynnBuilder data into the cache")
    s.add_argument("--refresh", action="store_true")
    s.set_defaults(fn=cmd_fetch)
    s = sub.add_parser("decode", help="decode and verify a link or build file")
    s.add_argument("link")
    s.set_defaults(fn=cmd_decode)
    s = sub.add_parser("verify", help="alias for decode; exits 1 on any problem")
    s.add_argument("link")
    s.set_defaults(fn=cmd_decode)
    s = sub.add_parser("damage", help="spell and melee damage, effective HP (WynnBuilder's numbers)")
    s.add_argument("link", help="link, hash or build file")
    s.add_argument("--perfect", action="store_true", help="130%% rolls, as WynnBuilder's page shows")
    s.add_argument("--parts", action="store_true", help="show every spell part and element")
    s.add_argument("--json", action="store_true")
    s.add_argument("--inventory", help="use real rolls from this inventory file")
    s.set_defaults(fn=cmd_damage)
    s = sub.add_parser("tree", help="solve an ability tree from a preset")
    s.add_argument("preset", choices=sorted(PRESETS))
    s.add_argument("--level", type=int, default=105)
    s.add_argument("--ap", type=int, help="override the ability-point cap")
    s.set_defaults(fn=cmd_tree)
    s = sub.add_parser("gear", help="search gear from a JSON spec, then build and verify a link")
    s.add_argument("spec", nargs="?", help="goals as JSON (optional with --edit: reuses the build's own)")
    s.add_argument("--edit", metavar="BUILD",
                   help="re-search an existing build file and write the result back into it")
    s.add_argument("--keep", metavar="SLOTS", help="with --edit: keep these slots' items (comma-separated)")
    s.add_argument("--change", metavar="SLOTS",
                   help="with --edit: search only these slots, keep the rest (comma-separated)")
    s.add_argument("--save-as", metavar="PATH", help="with --edit: write a new build file instead")
    s.add_argument("--force", action="store_true",
                   help="with --edit: write even if the player has unsaved edits, or --save-as exists")
    s.add_argument("--tree", choices=sorted(PRESETS), help="also solve the tree with this preset")
    s.add_argument("--shortlists", action="store_true",
                   help="use the older shortlist search instead of the exact one (automatic with damage floors)")
    s.add_argument("--confirm", action="store_true", help="with shortlists: re-run with larger ones")
    s.add_argument("--save", metavar="PATH", help="write the result as a build file")
    s.add_argument("--no-show", action="store_true", help="don't open the saved build in the web app")
    s.add_argument("--name", help="display name for the saved build")
    s.add_argument("--quiet", action="store_true", help="no progress output")
    s.add_argument("--owned", action="store_true", help="only use items in the inventory, with their real rolls")
    s.add_argument("--inventory", default=str(inv_mod.DEFAULT))
    s.set_defaults(fn=cmd_gear)
    s = sub.add_parser("upgrades", help="rank items you don't own by how much each would help")
    s.add_argument("spec")
    s.add_argument("--inventory", default=str(inv_mod.DEFAULT))
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--per-slot", type=int, default=6, help="candidates tried per slot")
    s.add_argument("--tree", choices=sorted(PRESETS), help="tree preset (needed for damage floors)")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(fn=cmd_upgrades)
    s = sub.add_parser("own", help="manage your inventory (items, tomes, crafts you own)")
    s.add_argument("action", choices=["add", "remove", "list"])
    s.add_argument("names", nargs="*")
    s.add_argument("--tome", action="store_true", help="the names are tomes")
    s.add_argument("--roll", action="append", metavar="ID=VALUE", help="real roll, e.g. poison=20640")
    s.add_argument("--inventory", default=str(inv_mod.DEFAULT))
    s.set_defaults(fn=cmd_own)
    s = sub.add_parser("import", help="save a WynnBuilder link as a build file")
    s.add_argument("link")
    s.add_argument("path")
    s.add_argument("--name")
    s.add_argument("--no-show", action="store_true", help="don't open it in the web app")
    s.set_defaults(fn=cmd_import)
    s = sub.add_parser("link", help="verify a build file and print its link")
    s.add_argument("build")
    s.add_argument("--write", action="store_true", help="update the file's link and status")
    s.add_argument("--force", action="store_true", help="write even if the player has unsaved edits to it")
    s.set_defaults(fn=cmd_link)
    s = sub.add_parser("current", help="the build the player is looking at in the web app")
    s.add_argument("--json", action="store_true", help="just what the page reported")
    s.add_argument("--hook", metavar="EVENT",
                   help="print a one-line summary as hook JSON for an AI CLI (UserPromptSubmit, BeforeAgent)")
    s.add_argument("--inventory", default=str(inv_mod.DEFAULT))
    s.set_defaults(fn=cmd_current)
    s = sub.add_parser("show", help="open a build file in the web app")
    s.add_argument("build")
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser("builds", help="list build files (the web app's sidebar)")
    s.set_defaults(fn=cmd_builds)
    s = sub.add_parser("edit", help="change items, tomes, level, name or tree in a build file, then re-check it")
    s.add_argument("build")
    s.add_argument("--item", action="append", metavar="SLOT=NAME",
                   help=f"put an item in a slot ({', '.join(SLOTS)}); empty NAME clears it (repeatable)")
    s.add_argument("--tome", action="append", metavar="SLOT=NAME",
                   help="put a tome in a slot (weaponTome1, armorTome1, ...); empty NAME clears it")
    s.add_argument("--level", type=int)
    s.add_argument("--name")
    s.add_argument("--notes")
    s.add_argument("--tree-preset", choices=sorted(PRESETS), help="re-solve the ability tree")
    s.add_argument("--save-as", metavar="PATH", help="write a new build file instead of changing this one")
    s.add_argument("--force", action="store_true",
                   help="write even if the player has unsaved edits, or --save-as exists")
    s.set_defaults(fn=cmd_edit)
    s = sub.add_parser("craft", help="suggest the best crafted item for a slot and goal")
    s.add_argument("--type", required=True, help="helmet, chestplate, ring, relik, ...")
    s.add_argument("--level", type=int, default=105, help="player level")
    s.add_argument("--maximize", required=True, help="stat to maximize, e.g. eSteal")
    s.add_argument("--also", action="append", metavar="STAT=WEIGHT",
                   help="extra objective terms, e.g. hp=0.002 (repeatable)")
    s.add_argument("--roll", choices=["min", "base", "max"], default="base")
    s.add_argument("--max-reqs", type=int, help="cap on total skill requirements")
    s.add_argument("--top", type=int, default=3)
    s.set_defaults(fn=cmd_craft)
    s = sub.add_parser("compare", help="two builds side by side (links or build files)")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("--perfect", action="store_true", help="130%% rolls, as WynnBuilder shows")
    s.set_defaults(fn=cmd_compare)
    s = sub.add_parser("ingredient", help="where a crafting ingredient drops")
    s.add_argument("name")
    s.set_defaults(fn=cmd_ingredient)
    s = sub.add_parser("config", help="show or change app settings, e.g. `wt config ai claude`")
    s.add_argument("key", nargs="?", help="setting name (ai, check_updates)")
    s.add_argument("value", nargs="?", help="ai: claude, codex, gemini, shell, or none; "
                   "check_updates: on or off")
    s.add_argument("--file", default="builds/settings.json")
    s.set_defaults(fn=cmd_config)
    s = sub.add_parser("serve", help="start the local web app (this computer only)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--builds", default="builds", help="folder of build files")
    how = s.add_mutually_exclusive_group()
    how.add_argument("--browser", action="store_true",
                     help="open in the browser instead of the app window")
    how.add_argument("--no-browser", action="store_true", help="just serve; open nothing")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("update", help="check GitHub for a newer Wynn Toolbox and install it")
    s.add_argument("--check", action="store_true", help="only say whether there is one")
    s.add_argument("--builds", default="builds", help="folder of build files")
    s.set_defaults(fn=cmd_update)
    a = p.parse_args(argv)
    if a.cmd in NO_PROGRESS:
        sys.exit(a.fn(a) or 0)
    from .web import client
    shown = " ".join(argv if argv is not None else sys.argv[1:])
    with client.ToolProgress(BUILDS, ACTIVITY.get(a.cmd, f"Running wt {a.cmd}"), f"wt {shown}",
                             key=a.cmd):
        code = a.fn(a) or 0
    sys.exit(code)
