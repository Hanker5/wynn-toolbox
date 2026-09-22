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
from .skillpoints import set_bonus_stats
from .verify import REQ, build_skillpoints
from .verify import stat as _stat

# Stand-in for an empty slot (allowed when searching only what you own).
EMPTY = {"name": "", "displayName": "", "tier": "", "type": ""}

CLASS_WEAPON = {"Mage": "wand", "Archer": "bow", "Assassin": "dagger",
                "Warrior": "spear", "Shaman": "relik"}


# Rough "helps damage" shortlist key for damage floors (the floor itself is exact).
DAMAGE_PCT = ["sdPct", "mdPct", "damPct", "rDamPct", "rSdPct", "rMdPct",
              "eDamPct", "tDamPct", "wDamPct", "fDamPct", "aDamPct", "critDamPct"]


@dataclass
class Spec:
    cls: str                                     # "Shaman", "Mage", ...
    level: int
    objective: dict                              # stat -> weight, e.g. {"eSteal": 1}
    floors: dict = field(default_factory=dict)   # hp, mr, spd, mana, weapon_dps, damage
    # floors["damage"] = {spell name: minimum}: the spell's headline number as
    # WynnBuilder shows it (melee: average DPS). Checked exactly per build; needs atree.
    require_major: list = field(default_factory=list)   # e.g. ["GREED", "MAGNET"]
    force: dict = field(default_factory=dict)    # slot -> item name
    exclude: set = field(default_factory=set)    # item names never to use
    exclude_tiers: set = field(default_factory=set)     # e.g. {"Mythic"}
    tomes: list = field(default_factory=list)    # 14 tome ids (None = empty), TOME_SLOTS order
    roll: str = "base"                           # "base" (100%), "max" (perfect) or "min"
    crafted: bool = False                        # also consider crafted items (see craft_solver)
    only: set | None = None                      # restrict to these names (e.g. what you own)
    inventory: object = None                     # Inventory: use real rolls of owned items
    topn: int = 8                                # shortlist size per ranking (8 reproduces all session results)
    atree: set | None = None                     # ability node ids (needed for damage floors)


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
    from .inventory import with_rolls
    pools = {s: [] for s in SLOTS}
    extra = [gd.item(n) for n in sorted({*(spec.only or ()), *(spec.force or {}).values()})
             if n.startswith("CR-")]                  # owned or kept crafts
    for it in [*gd.items, *extra]:
        name = gd.name(it)
        if spec.only is not None and name not in spec.only:
            continue
        slot = _slot_of(it, spec.cls)
        if slot is None or (it.get("lvl") or 0) > spec.level:
            continue
        cr = it.get("classReq")
        if cr and cr.lower() != spec.cls.lower():
            continue
        if name in spec.exclude or it.get("tier") in spec.exclude_tiers:
            continue
        if spec.inventory is not None:
            it = with_rolls(it, spec.inventory.rolls(name))
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
        where = " that you own" if getattr(_major_options, "owned_only", False) else ""
        raise ValueError(f"no usable item{where} carries major ID {major}")
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
    tome_ids = list(spec.tomes) + [None] * (14 - len(spec.tomes))
    tomes = [gd.tome(t) for t in tome_ids if t is not None]
    obj = lambda i: sum(w * stat(i, k) for k, w in spec.objective.items())

    def set_contrib(stats):
        """(objective, hp, mr, spd) added by a set bonus's stats."""
        return (sum(w * (stats.get("hpBonus", 0) if k == "hp" else stats.get(k, 0))
                    for k, w in spec.objective.items()),
                stats.get("hpBonus", 0), stats.get("mr", 0), stats.get("spd", 0))

    def set_tables(cl):
        """Per-set bound tables so pruning stays valid with set bonuses.

        bound[si][k][c] = the most set `si` can add (objective, hp, mr, spd) when
        it has c pieces after slot k and the slots from k on could add up to
        cap[k] more. Only sets that can add something relevant are tracked.
        """
        n = len(cl)
        names = sorted({gd.set_of[gd.name(it)] for pool in cl for it in pool if gd.name(it) in gd.set_of})
        tracked, bound, set_idx = [], [], {}
        for name in names:
            nb = len(gd.sets[name]["bonuses"])
            contrib = [(0.0, 0, 0, 0)] + [set_contrib(set_bonus_stats({name: c}, gd.sets)[0])
                                          for c in range(1, nb + 1)]
            if not any(v > 0 for row in contrib for v in row):
                continue
            has = [any(gd.set_of.get(gd.name(it)) == name for it in cl[k]) for k in range(n)]
            cap = [sum(has[k:]) for k in range(n + 1)]
            table = []
            for k in range(n + 1):
                row = []
                for c in range(10):
                    hi = min(nb, c + cap[k])
                    rng = contrib[min(c, nb):hi + 1] or [contrib[min(c, nb)]]
                    row.append(tuple(max(r[i] for r in rng) for i in range(4)))
                table.append(row)
            set_idx[name] = len(tracked)
            tracked.append(name)
            bound.append(table)
        return set_idx, bound

    sp_cache = {}

    def exact_sp(names):
        key = tuple(names)
        if key not in sp_cache:
            sp_cache[key] = build_skillpoints(list(names), tome_ids, gd)
        return sp_cache[key]
    fl = spec.floors
    dmg_floors = fl.get("damage") or {}
    if dmg_floors and not spec.atree:
        raise ValueError("damage floors need an ability tree: give a tree preset")

    def damage_ok(names_now):
        from .codec import Build
        from .damage import spell_values
        b = Build(equipment=list(names_now), level=spec.level, tomes=tome_ids,
                  atree=set(spec.atree))
        got = spell_values(b, gd, spec.roll, spec.inventory)
        return all(got.get(name, -1) >= v for name, v in dmg_floors.items())
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
            return [EMPTY] if spec.only is not None else []
        omax = max(abs(obj(i)) for i in pool) or 1
        hmax = max(abs(stat(i, "hp")) for i in pool) or 1
        keys = [obj, lambda i: stat(i, "hp"),
                lambda i: obj(i) / omax + stat(i, "hp") / hmax,
                lambda i: stat(i, "hp") + 30 * stat(i, "mr"),
                lambda i: stat(i, "hp") + 60 * stat(i, "spd")]
        if "mr" in fl:
            keys.append(lambda i: 2000 * stat(i, "mr") + obj(i) / omax)
        if dmg_floors:
            if slot == "weapon":      # base damage dominates every spell
                keys.append(lambda i: i.get("averageDps") or 0)
            keys.append(lambda i: sum(stat(i, k) for k in DAMAGE_PCT) + sum(stat(i, k) for k in SKILLS)
                        + (stat(i, "sdRaw") + stat(i, "mdRaw")) / 20)
        if "mana" in fl:
            keys.append(lambda i: 50 * stat(i, "maxMana") + stat(i, "hp"))
        out, seen = [], set()
        for k in keys:
            for it in sorted(pool, key=k, reverse=True)[:spec.topn]:
                if gd.name(it) not in seen:
                    seen.add(gd.name(it))
                    out.append(it)
        if spec.only is not None:
            out.append(EMPTY)          # an inventory may have nothing for this slot
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
        cl[SLOTS.index("weapon")] = [c for c in cl[SLOTS.index("weapon")] if c is not EMPTY]
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
                # optimistic bonus per slot (never negative: WynnBuilder ignores the
                # weapon's bonus, so a negative one can't raise the requirement)
                mb[k][j] = mb[k + 1][j] + max(0, max(stat(c, sk) for c in cl[k])) \
                    + (sum(max(0, stat(t, sk)) for t in tomes) if k == n - 1 else 0)
        set_idx, set_bound = set_tables(cl)
        n_sets = len(set_bound)
        set_cnt = [0] * n_sets
        ring_sym = "ring1" not in force and "ring2" not in force
        # Precompute each candidate once; the search loop only touches these tuples.
        # (name, item, objective, hp, mr, spd, requirements, is_crafted)
        pre = [[(gd.name(c), c, obj(c), stat(c, "hp"), stat(c, "mr"), stat(c, "spd"),
                 tuple(c.get(r) or 0 for r in REQ), c is EMPTY or gd.name(c).startswith("CR-"),
                 set_idx.get(gd.set_of.get(gd.name(c)), -1) if c is not EMPTY else -1)
                for c in cl[k]] for k in range(n)]
        is_ring2 = [SLOTS[k] == "ring2" for k in range(n)]
        is_ring1 = [SLOTS[k] == "ring1" for k in range(n)]
        chosen, names = [], {}

        def dfs(k, val, hp, mr, spd, mreq, ring1_idx):
            nonlocal best
            track["nodes"] += 1
            if track["nodes"] % 2000 == 0:
                report()
            s_obj = s_hp = s_mr = s_spd = 0
            for si in range(n_sets):
                b = set_bound[si][k][set_cnt[si]]
                s_obj += b[0]; s_hp += b[1]; s_mr += b[2]; s_spd += b[3]
            if best and val + suf["obj"][k] + s_obj <= best.score:
                return
            if hp + suf["hp"][k] + s_hp < hp_floor or mr + suf["mr"][k] + s_mr < mr_floor \
                    or spd + suf["spd"][k] + s_spd < spd_floor:
                return
            mbk = mb[k]
            if sum(max(0, mreq[j] - mbk[j]) for j in range(5)) > budget:
                return
            if k == n:
                names_now = [None if c is EMPTY else gd.name(c) for c in chosen]
                sp = exact_sp(names_now)          # WynnBuilder's skill-point rules
                if sp.total_assigned > budget or not sp.under_100:
                    return
                set_stats, _ = set_bonus_stats(sp.set_counts, gd.sets)
                a_obj, a_hp, a_mr, a_spd = set_contrib(set_stats)
                total = val + a_obj
                if best and total <= best.score:
                    return
                if hp + a_hp < hp_floor or mr + a_mr < mr_floor or spd + a_spd < spd_floor:
                    return
                if "mana" in fl:
                    spare = budget - sp.total_assigned
                    int_items = sp.final[2] - sp.assigned[2]
                    mana = max_mana(sum(stat(o, "maxMana") for o in (*chosen, *tomes))
                                    + set_stats.get("maxMana", 0),
                                    min(100, sp.assigned[2] + spare) + int_items)
                    if mana < fl["mana"]:
                        return
                if dmg_floors and not damage_ok(names_now):
                    return
                best = Result(total, names_now, sp.assigned, 0)
                return
            for ci, (nm, c, o, h, m, sp_, rq, crafted, si) in enumerate(pre[k]):
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
                if si >= 0:
                    set_cnt[si] += 1
                dfs(k + 1, val + o, hp + h, mr + m, spd + sp_,
                    (max(mreq[0], rq[0]), max(mreq[1], rq[1]), max(mreq[2], rq[2]),
                     max(mreq[3], rq[3]), max(mreq[4], rq[4])),
                    ci if is_ring1[k] else ring1_idx)
                chosen.pop()
                names[nm] -= 1
                if si >= 0:
                    set_cnt[si] -= 1

        dfs(0, 0.0, 0, 0, 0, (0, 0, 0, 0, 0), -1)
    report(final=True)
    if best:
        best.seconds = time.time() - t0
    return best


@dataclass
class Upgrade:
    item: str
    slot: str
    gain: float | None       # objective gained over the owned-only build (None: no owned build existed)
    result: Result


def upgrades(spec, gd, inventory, per_slot=6, top=10, progress=None):
    """Rank items you don't own by how much each alone would improve the best
    owned-only build. Returns (baseline Result or None, [Upgrade, ...])."""
    owned = inventory.names()
    base_spec = dataclasses.replace(spec, only=owned, inventory=inventory, crafted=False)
    try:
        base = solve_gear(base_spec, gd)
    except ValueError:
        base = None                      # e.g. you own nothing with a required major ID
    full = _usable(gd, dataclasses.replace(spec, only=None, inventory=inventory))
    obj = lambda i: sum(w * stat(i, k) for k, w in spec.objective.items())
    stat = lambda i, k: _stat(i, k, spec.roll)
    majors = set(spec.require_major)
    cands, seen = [], set()
    for slot in SLOTS:
        if slot == "ring2":
            continue
        pool = [i for i in full[slot] if gd.name(i) not in owned]
        picks = sorted(pool, key=obj, reverse=True)[:per_slot]
        picks += sorted(pool, key=lambda i: stat(i, "hp"), reverse=True)[:max(1, per_slot // 2)]
        picks += [i for i in pool if majors & set(i.get("majorIds") or [])]
        for it in picks:
            if gd.name(it) not in seen:
                seen.add(gd.name(it))
                cands.append((slot, it))
    out = []
    for n, (slot, it) in enumerate(cands):
        name = gd.name(it)
        try:
            r = solve_gear(dataclasses.replace(base_spec, only=owned | {name}), gd)
        except ValueError:
            r = None
        if r is not None and name in r.equipment and (base is None or r.score > base.score + 1e-9):
            out.append(Upgrade(name, "ring" if slot == "ring1" else slot,
                               None if base is None else r.score - base.score, r))
        if progress:
            progress({"fraction": (n + 1) / len(cands), "nodes": n + 1,
                      "best": max((u.gain or 0 for u in out), default=None), "elapsed": 0})
    out.sort(key=lambda u: (u.gain is None, -(u.gain or 0), -u.result.score))
    return base, out[:top]
