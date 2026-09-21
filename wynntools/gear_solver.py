"""Gear search: branch and bound over per-slot candidate pools.

The pools are a heuristic (top items per slot under several rankings), so the
result is the best build *within the pools*, not a proven global optimum. See
docs/ROADMAP.md for the planned exact (MILP) version.
"""
import dataclasses
import time
from dataclasses import dataclass, field
from itertools import product

from .codec import SLOTS
from .rules import SKILLS, base_hp, max_mana, skill_points
from .verify import REQ, sp_requirements
from .verify import stat as _stat

CLASS_WEAPON = {"Mage": "wand", "Archer": "bow", "Assassin": "dagger",
                "Warrior": "spear", "Shaman": "relik"}


@dataclass
class Spec:
    cls: str                                     # "Shaman", "Mage", ...
    level: int
    objective: dict                              # stat -> weight, e.g. {"eSteal": 1}
    floors: dict = field(default_factory=dict)   # hp, mr, spd, mana, weapon_dps
    require_major: list = field(default_factory=list)   # e.g. ["GREED", "MAGNET"]
    force: dict = field(default_factory=dict)    # slot -> item name
    exclude: set = field(default_factory=set)    # item names never to use
    exclude_tiers: set = field(default_factory=set)     # e.g. {"Mythic"}
    tomes: list = field(default_factory=list)    # tome ids; their stats count toward floors
    roll: str = "base"                           # "base" (100%), "max" (perfect) or "min"
    crafted: bool = False                        # also consider crafted items (see craft_solver)
    topn: int = 8                                # shortlist size per ranking (8 reproduces all session results)


@dataclass
class Result:
    score: float
    equipment: list
    sp_need: list
    seconds: float


def _slot_of(item, cls):
    t = item.get("type")
    if t == CLASS_WEAPON[cls]:
        return "weapon"
    return t if t in ("helmet", "chestplate", "leggings", "boots", "ring",
                      "bracelet", "necklace") else None


def _usable(gd, spec):
    pools = {s: [] for s in SLOTS}
    for it in gd.items:
        slot = _slot_of(it, spec.cls)
        if slot is None or (it.get("lvl") or 0) > spec.level:
            continue
        cr = it.get("classReq")
        if cr and cr.lower() != spec.cls.lower():
            continue
        if gd.name(it) in spec.exclude or it.get("tier") in spec.exclude_tiers:
            continue
        for s in (("ring1", "ring2") if slot == "ring" else (slot,)):
            pools[s].append(it)
    return pools


def _major_options(pools, gd, major):
    opts = []
    for s in SLOTS:
        if s == "ring2":
            continue
        for it in pools[s]:
            if major in (it.get("majorIds") or []):
                opts.append(("ring" if s == "ring1" else s, gd.name(it)))
    if not opts:
        raise ValueError(f"no usable item carries major ID {major}")
    return opts


def _force_sets(spec, pools, gd):
    """Every way of placing one item per required major ID, merged with spec.force."""
    options = [_major_options(pools, gd, m) for m in spec.require_major]
    for combo in product(*options) if options else [()]:
        force, ok = dict(spec.force), True
        for slot, name in combo:
            if name in force.values():
                continue                     # one item may carry several majors
            if slot == "ring":
                slot = next((r for r in ("ring1", "ring2") if r not in force), None)
            if slot is None or slot in force:
                ok = False
                break
            force[slot] = name
        if ok:
            yield force


def _crafted_candidates(spec, gd):
    """A few crafted items per slot: best for the objective alone, and best for
    the objective with HP (and mana regen when there's a floor on it) mixed in."""
    from .craft_solver import CraftSpec, suggest_crafts
    kinds = ["helmet", "chestplate", "leggings", "boots", "ring", "bracelet", "necklace",
             CLASS_WEAPON[spec.cls]]
    out = {}
    for kind in kinds:
        variants = [dict(spec.objective)]
        base = max(spec.objective.values())
        variants.append({**spec.objective, "hp": base / 400})
        if "mr" in spec.floors:
            variants.append({**spec.objective, "mr": base / 2})
        found = {}
        for obj in variants:
            for _, it in suggest_crafts(CraftSpec(kind, spec.level, obj, roll=spec.roll), gd.crafts, top=2):
                found[it["name"]] = it
                gd._craft_cache[it["name"]] = it          # so gd.item() can find it later
        out[kind] = list(found.values())
    return out


def solve_gear(spec, gd, progress=None, _pools=None, _seed=None):
    """Return the best Result under `spec`, or None if nothing satisfies it.

    `progress`, if given, is called about ten times a second with a dict:
    fraction (0-1, share of top-level branches finished), nodes (search nodes
    visited), best (best objective so far or None), elapsed (seconds).
    The fraction advances steadily but is not a time estimate: pruning makes
    branches uneven.
    """
    t0 = time.time()

    memo = {}

    def stat(obj, key):
        k = (id(obj), key)
        if k not in memo:
            memo[k] = _stat(obj, key, spec.roll)
        return memo[k]
    pools = _pools if _pools is not None else _usable(gd, spec)
    if spec.crafted and _pools is None:
        for kind, items in _crafted_candidates(spec, gd).items():
            slots = ("ring1", "ring2") if kind == "ring" else \
                ("weapon",) if kind == CLASS_WEAPON[spec.cls] else (kind,)
            for s in slots:
                pools[s].extend(items)
    tomes = [gd.tome(t) for t in spec.tomes]
    obj = lambda i: sum(w * stat(i, k) for k, w in spec.objective.items())
    fl = spec.floors
    tconst = {k: sum(stat(t, k) for t in tomes) for k in ("hp", "mr", "spd")}
    hp_floor = fl.get("hp", -1e18) - base_hp(spec.level) - tconst["hp"]
    mr_floor = fl.get("mr", -1e18) - tconst["mr"]
    spd_floor = fl.get("spd", -1e18) - tconst["spd"]
    budget = skill_points(spec.level)

    def candidates(slot, force):
        pool = pools[slot]
        if slot in force:
            return [i for i in pool if gd.name(i) == force[slot]]
        if slot == "weapon" and "weapon_dps" in fl:
            pool = [i for i in pool if (i.get("averageDps") or 0) >= fl["weapon_dps"]]
        if not pool:
            return []
        omax = max(abs(obj(i)) for i in pool) or 1
        hmax = max(abs(stat(i, "hp")) for i in pool) or 1
        keys = [obj, lambda i: stat(i, "hp"),
                lambda i: obj(i) / omax + stat(i, "hp") / hmax,
                lambda i: stat(i, "hp") + 30 * stat(i, "mr"),
                lambda i: stat(i, "hp") + 60 * stat(i, "spd")]
        if "mr" in fl:
            keys.append(lambda i: 2000 * stat(i, "mr") + obj(i) / omax)
        if "mana" in fl:
            keys.append(lambda i: 50 * stat(i, "maxMana") + stat(i, "hp"))
        out, seen = [], set()
        for k in keys:
            for it in sorted(pool, key=k, reverse=True)[:spec.topn]:
                if gd.name(it) not in seen:
                    seen.add(gd.name(it))
                    out.append(it)
        return out

    # Seed the search with a quick pass over smaller shortlists. Its build is
    # feasible under the same constraints, and the smaller shortlists are subsets
    # of the full ones, so this only tightens pruning; it never changes the answer.
    if _seed is None and spec.topn > 3:
        _seed = solve_gear(dataclasses.replace(spec, topn=3), gd, None, _pools=pools, _seed=False)
    best = _seed or None
    forces = list(_force_sets(spec, pools, gd))
    track = {"nodes": 0, "last": 0.0, "force": 0, "pos": [0, 1, 0, 1]}

    def report(final=False):
        now = time.time()
        if progress is None or (not final and now - track["last"] < 0.1):
            return
        track["last"] = now
        i0, n0, i1, n1 = track["pos"]
        within = 1.0 if final else min(1.0, (i0 + i1 / n1) / n0)
        frac = 1.0 if final else (track["force"] + within) / max(1, len(forces))
        progress({"fraction": frac, "nodes": track["nodes"],
                  "best": best.score if best else None, "elapsed": now - t0})

    for fi, force in enumerate(forces):
        track["force"], track["pos"] = fi, [0, 1, 0, 1]
        cl = [candidates(s, force) for s in SLOTS]
        if any(not c for c in cl):
            continue
        n = len(SLOTS)
        suf = {k: [0.0] * (n + 1) for k in ("obj", "hp", "mr", "spd")}
        mb = [[0] * 5 for _ in range(n + 1)]
        for k in range(n - 1, -1, -1):
            suf["obj"][k] = suf["obj"][k + 1] + max(obj(c) for c in cl[k])
            for s in ("hp", "mr", "spd"):
                suf[s][k] = suf[s][k + 1] + max(stat(c, s) for c in cl[k])
            for j, sk in enumerate(SKILLS):
                mb[k][j] = mb[k + 1][j] + max(stat(c, sk) for c in cl[k]) \
                    + (sum(stat(t, sk) for t in tomes) if k == n - 1 else 0)
        ring_sym = "ring1" not in force and "ring2" not in force
        # Precompute each candidate once; the search loop only touches these tuples.
        # (name, item, objective, hp, mr, spd, requirements, is_crafted)
        pre = [[(gd.name(c), c, obj(c), stat(c, "hp"), stat(c, "mr"), stat(c, "spd"),
                 tuple(c.get(r) or 0 for r in REQ), gd.name(c).startswith("CR-"))
                for c in cl[k]] for k in range(n)]
        is_ring2 = [SLOTS[k] == "ring2" for k in range(n)]
        is_ring1 = [SLOTS[k] == "ring1" for k in range(n)]
        chosen, names = [], {}

        def dfs(k, val, hp, mr, spd, mreq, ring1_idx):
            nonlocal best
            track["nodes"] += 1
            if track["nodes"] % 2000 == 0:
                report()
            if best and val + suf["obj"][k] <= best.score:
                return
            if hp + suf["hp"][k] < hp_floor or mr + suf["mr"][k] < mr_floor \
                    or spd + suf["spd"][k] < spd_floor:
                return
            mbk = mb[k]
            if sum(max(0, mreq[j] - mbk[j]) for j in range(5)) > budget:
                return
            if k == n:
                need = sp_requirements(chosen, tomes)
                if sum(need) > budget or max(need) > 100:
                    return
                if "mana" in fl:
                    spare = budget - sum(need)
                    bonus_int = sum(stat(o, "int") for o in (*chosen, *tomes))
                    mana = max_mana(sum(stat(o, "maxMana") for o in (*chosen, *tomes)),
                                    min(100, need[2] + spare) + bonus_int)
                    if mana < fl["mana"]:
                        return
                best = Result(val, [gd.name(c) for c in chosen], need, 0)
                return
            for ci, (nm, c, o, h, m, sp_, rq, crafted) in enumerate(pre[k]):
                if k < 2:
                    track["pos"][2 * k:2 * k + 2] = [ci, len(pre[k])]
                    if k == 0:
                        track["pos"][2:] = [0, 1]
                if names.get(nm) and not crafted:
                    continue
                if ring_sym and is_ring2[k] and (ci < ring1_idx or (ci == ring1_idx and not crafted)):
                    continue               # ring pairs are unordered (a craft may repeat)
                chosen.append(c)
                names[nm] = names.get(nm, 0) + 1
                dfs(k + 1, val + o, hp + h, mr + m, spd + sp_,
                    (max(mreq[0], rq[0]), max(mreq[1], rq[1]), max(mreq[2], rq[2]),
                     max(mreq[3], rq[3]), max(mreq[4], rq[4])),
                    ci if is_ring1[k] else ring1_idx)
                chosen.pop()
                names[nm] -= 1

        dfs(0, 0.0, 0, 0, 0, (0, 0, 0, 0, 0), -1)
    report(final=True)
    if best:
        best.seconds = time.time() - t0
    return best
