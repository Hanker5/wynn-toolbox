"""`wt` command line: fetch, decode, verify, tree, gear, link."""
import argparse
import json
import sys
from pathlib import Path

from .codec import POWDERABLE, SLOTS, TOME_SLOTS, Build, powder_name, to_link
from .data import LATEST, VERSIONS, GameData, fetch
from . import buildfile
from .gear_solver import Spec, solve_gear
from .progress import ProgressBar
from .presets import PRESETS, summoner_hits_per_sec
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
        print(f"  {slot:<11}{name or '—'}{pw}")
    used = [(TOME_SLOTS[k], gd.name(gd.tome(tid))) for k, tid in enumerate(b.tomes) if tid is not None]
    print(f"Tomes: {len(used)}/14")
    for slot, name in used:
        print(f"  {slot:<15}{name}")
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
    print(f"Skill points: {s['sp_total']}/{s['sp_available']} needed {s['sp_need']}")
    print("Note: item stats are 100% rolls (real items roll 30-130%).")
    print("VERIFIED OK" if ok else "PROBLEMS:\n  - " + "\n  - ".join(rep["problems"]))


def _tree_for(build_level, weapon, preset, gd):
    cls = gd.weapon_class(weapon)
    P = PRESETS[preset]
    if P["class"] != cls:
        raise SystemExit(f"preset {preset} is for {P['class']}, weapon {weapon} is {cls}")
    return solve_tree(gd.tree(cls), P["weights"], ability_points(build_level))


def _resolve_tomes(entries, gd):
    tomes = [None] * len(TOME_SLOTS)
    for k, t in enumerate(entries or []):
        if t is not None:
            tomes[k] = gd.tome(t)["id"]
    return tomes


def cmd_fetch(a):
    print("cached in", fetch(refresh=a.refresh))


def _link_arg(arg, gd):
    """A link, a bare hash, or a path to a build file."""
    if arg.endswith(".json") and Path(arg).exists():
        return to_link(buildfile.to_build(buildfile.read(arg), gd), gd)
    return arg


def cmd_decode(a):
    gd = GameData()
    ok, rep = check_link(_link_arg(a.link, gd), gd)
    _print_report(ok, rep, gd)
    return 0 if ok else 1


def cmd_tree(a):
    gd = GameData()
    P = PRESETS[a.preset]
    tree = gd.tree(P["class"])
    ap = a.ap or ability_points(a.level)
    sel = solve_tree(tree, P["weights"], ap)
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


def cmd_gear(a):
    gd = GameData()
    raw = json.load(open(a.spec))
    spec = Spec(cls=raw["class"], level=raw["level"], objective=raw["objective"],
                floors=raw.get("floors", {}), require_major=raw.get("require_major", []),
                force=raw.get("force", {}), exclude=set(raw.get("exclude", [])),
                exclude_tiers=set(raw.get("exclude_tiers", [])),
                tomes=[gd.tome(t)["id"] for t in raw.get("tomes", []) if t is not None],
                topn=raw.get("topn", 8))
    r = solve_gear(spec, gd, progress=None if a.quiet else ProgressBar("gear search"))
    if r is None:
        print("No build satisfies these constraints.")
        return 1
    if a.confirm:
        spec.topn += 3
        r2 = solve_gear(spec, gd, progress=None if a.quiet else ProgressBar("confirm search"))
        if r2 and r2.score > r.score + 1e-9:
            print(f"(confirm: larger shortlists found a better build, {r2.score:g} > {r.score:g})")
            r = r2
        else:
            print(f"(confirm: larger shortlists found nothing better)")
    print(f"Search took {r.seconds:.0f}s; objective {r.score:g}")
    b = _build_from(raw, r.equipment, a.tree, gd)
    link = to_link(b, gd)
    ok, rep = check_link(link, gd)
    _print_report(ok, rep, gd)
    print(link)
    if a.save:
        doc = {"name": a.name or Path(a.save).stem,
               "notes": raw.get("_about", ""), **buildfile.from_build(b, gd),
               "spec": {k: v for k, v in raw.items() if not k.startswith("_")},
               "tree_preset": a.tree}
        buildfile.write(a.save, buildfile.refresh(doc, gd))
        print(f"saved {a.save}")
    return 0 if ok else 1


def cmd_import(a):
    gd = GameData()
    from .codec import decode
    b = decode(a.link, gd)
    doc = buildfile.refresh({"name": a.name or Path(a.path).stem, "notes": "",
                             **buildfile.from_build(b, gd)}, gd)
    buildfile.write(a.path, doc)
    print(f"saved {a.path} ({'verified' if doc['status']['verified'] else 'HAS PROBLEMS'})")
    return 0 if doc["status"]["verified"] else 1


def cmd_link(a):
    gd = GameData()
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
    s = sub.add_parser("tree", help="solve an ability tree from a preset")
    s.add_argument("preset", choices=sorted(PRESETS))
    s.add_argument("--level", type=int, default=105)
    s.add_argument("--ap", type=int, help="override the ability-point cap")
    s.set_defaults(fn=cmd_tree)
    s = sub.add_parser("gear", help="search gear from a JSON spec, then build and verify a link")
    s.add_argument("spec")
    s.add_argument("--tree", choices=sorted(PRESETS), help="also solve the tree with this preset")
    s.add_argument("--confirm", action="store_true", help="re-run with larger shortlists")
    s.add_argument("--save", metavar="PATH", help="write the result as a build file")
    s.add_argument("--name", help="display name for the saved build")
    s.add_argument("--quiet", action="store_true", help="no progress output")
    s.set_defaults(fn=cmd_gear)
    s = sub.add_parser("import", help="save a WynnBuilder link as a build file")
    s.add_argument("link")
    s.add_argument("path")
    s.add_argument("--name")
    s.set_defaults(fn=cmd_import)
    s = sub.add_parser("link", help="verify a build file and print its link")
    s.add_argument("build")
    s.add_argument("--write", action="store_true", help="update the file's link and status")
    s.set_defaults(fn=cmd_link)
    a = p.parse_args(argv)
    sys.exit(a.fn(a) or 0)
