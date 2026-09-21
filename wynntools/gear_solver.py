"""Gear search: branch and bound over per-slot candidate pools.

The pools are a heuristic (top items per slot under several rankings), so the
result is the best build *within the pools*, not a proven global optimum. See
docs/ROADMAP.md for the planned exact (MILP) version.
"""
import time
from dataclasses import dataclass, field
from itertools import product

from .codec import SLOTS
from .rules import SKILLS, base_hp, max_mana, skill_points
from .verify import REQ, sp_requirements, stat

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


def solve_gear(spec, gd):
    """Return the best Result under `spec`, or None if nothing satisfies it."""
    t0 = time.time()
    pools = _usable(gd, spec)
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

    best = None
    for force in _force_sets(spec, pools, gd):
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
        chosen, names = [], set()

        def dfs(k, val, hp, mr, spd, mreq, ring1_idx):
            nonlocal best
            if best and val + suf["obj"][k] <= best.score:
                return
            if hp + suf["hp"][k] < hp_floor or mr + suf["mr"][k] < mr_floor \
                    or spd + suf["spd"][k] < spd_floor:
                return
            if sum(max(0, mreq[j] - mb[k][j]) for j in range(5)) > budget:
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
            for ci, c in enumerate(cl[k]):
                nm = gd.name(c)
                if nm in names:
                    continue
                if ring_sym and SLOTS[k] == "ring2" and ci <= ring1_idx:
                    continue               # ring pairs are unordered
                chosen.append(c)
                names.add(nm)
                dfs(k + 1, val + obj(c), hp + stat(c, "hp"), mr + stat(c, "mr"),
                    spd + stat(c, "spd"),
                    [max(mreq[j], c.get(REQ[j]) or 0) for j in range(5)],
                    ci if SLOTS[k] == "ring1" else ring1_idx)
                chosen.pop()
                names.discard(nm)

        dfs(0, 0.0, 0, 0, 0, [0] * 5, -1)
    if best:
        best.seconds = time.time() - t0
    return best
