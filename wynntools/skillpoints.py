"""Skill points exactly as WynnBuilder computes them.

A line-by-line port of js/skillpoints.js (`calculate_skillpoints` and helpers;
GPL-3.0). Key behaviours, all of which differ from a naive "sum everyone
else's bonuses" model:

* The nine equippables (boots, leggings, chestplate, helmet, ring1, ring2,
  bracelet, necklace, guild tome - Wynncraft's own order) are equipped one at a
  time in the order that needs the fewest assigned points. An item's bonus only
  helps items equipped after it.
* The weapon, and crafted items, go on last: their bonuses never help any
  other item's requirement.
* "Pop" rule: a (non-crafted) item whose requirement is met only thanks to its
  own bonus would fall off, so points are assigned to prevent that.
* Set bonuses never count toward requirements; their skill points are added to
  the build's totals afterwards.

tests/test_differential.py checks this against WynnBuilder's JavaScript.
"""
from dataclasses import dataclass, field

from .rules import SKILLS

REQ_KEYS = [s + "Req" for s in SKILLS]
WYNN_ORDER = ["boots", "leggings", "chestplate", "helmet", "ring1", "ring2",
              "bracelet", "necklace", "guildTome1"]


@dataclass
class SPItem:
    """What calculate_skillpoints needs from an item (a statMap in JS)."""
    skillpoints: list = field(default_factory=lambda: [0] * 5)
    reqs: list = field(default_factory=lambda: [0] * 5)
    set: str | None = None
    crafted: bool = False
    name: str | None = None

    @classmethod
    def of(cls, item, set_name=None):
        if item is None:
            return cls()
        return cls(skillpoints=[int(item.get(s) or 0) for s in SKILLS],
                   reqs=[int(item.get(r) or 0) for r in REQ_KEYS],
                   set=set_name, crafted=item.get("tier") == "Crafted",
                   name=item.get("displayName") or item.get("name"))


@dataclass
class SPResult:
    order: list            # items in the equip order that was chosen
    assigned: list         # points the player must assign, per skill
    final: list            # total skill points on the build (assigned + items + sets)
    total_assigned: int
    set_counts: dict       # set name -> number of pieces worn
    item_total: list       # skill points from items (and set bonuses)
    under_100: bool        # whether every assigned skill is <= 100


def _vadd5(a, b):
    return [a[i] + b[i] for i in range(5)]


def _apply_skillpoints(sp, item, set_counts):
    for i in range(5):
        sp[i] += item.skillpoints[i]
    if item.set:
        set_counts[item.set] = set_counts.get(item.set, 0) + 1


def _can_equip(sp, item):
    for i in range(5):
        if item.reqs[i] <= 0:
            continue
        if item.reqs[i] > sp[i]:
            return False
    return True


def _fix_should_pop(sp, item):
    applied = [0] * 5
    for i in range(5):
        if item.reqs[i] <= 0:
            continue
        req = item.reqs[i] if item.crafted else item.reqs[i] + item.skillpoints[i]
        if req > sp[i]:
            diff = req - sp[i]
            applied[i] += diff
            sp[i] += diff
    return applied


def _apply_to_fit(sp, item):
    applied = [0] * 5
    for i in range(5):
        if item.reqs[i] <= 0:
            continue
        if item.reqs[i] > sp[i]:
            diff = item.reqs[i] - sp[i]
            applied[i] += diff
            sp[i] += diff
    return applied


def calculate_skillpoints(equipment, weapon, sets):
    """equipment: 9 SPItems in WYNN_ORDER; weapon: SPItem; sets: {name: {"bonuses": [...]}}."""
    crafted_items = [it for it in equipment if it.crafted]
    total_item = list(weapon.skillpoints)
    for it in equipment:
        total_item = _vadd5(total_item, it.skillpoints)

    best = {"order": list(equipment), "assigned": [0] * 5, "final": [0] * 5,
            "total": float("inf"), "sets": {}, "under_100": False}

    def recurse(_applied, _totals, _sets, _total_applied, skipped_states,
                prior_skipped, equipped, remains):
        if len(remains) == 1:
            item = equipment[remains[0]]
            sp = list(_totals)
            deltas1 = _apply_to_fit(sp, item)
            sets_now = dict(_sets)
            if not item.crafted:
                _apply_skillpoints(sp, item, sets_now)
            deltas2 = _apply_to_fit(sp, weapon)
            deltas = _vadd5(deltas1, deltas2)
            for it in equipment:                 # fix items that would pop
                deltas = _vadd5(deltas, _fix_should_pop(sp, it))
            for j, idx in enumerate(prior_skipped):   # the order must still hold
                if _can_equip(_vadd5(skipped_states[j], deltas), equipment[idx]):
                    return
            applied = _vadd5(_applied, deltas)
            total_applied = _total_applied + sum(deltas)
            under = all(a <= 100 for a in applied)
            if best["under_100"] and not under:
                return
            if total_applied < best["total"] or (under and not best["under_100"]):
                for c in crafted_items:
                    _apply_skillpoints(sp, c, sets_now)
                _apply_skillpoints(sp, weapon, sets_now)
                best.update(final=sp, assigned=applied, total=total_applied, sets=sets_now,
                            order=[equipment[k] for k in equipped + [remains[0]]],
                            under_100=under)
            return

        for i in range(len(remains)):
            head = remains[:i]
            skipped = prior_skipped + head
            sp = list(_totals)
            item = equipment[remains[i]]
            deltas = _apply_to_fit(sp, item)
            sim_states = []
            blocked = False
            for j, idx in enumerate(prior_skipped):
                sim = _vadd5(skipped_states[j], deltas)
                if _can_equip(sim, equipment[idx]):
                    blocked = True
                    break
                sim_states.append(sim)
            if blocked:
                continue
            for idx in head:
                if _can_equip(sp, equipment[idx]):
                    blocked = True
                    break
                sim_states.append(sp)
            if blocked:
                continue
            mod = list(sp)
            sets_now = dict(_sets)
            if not item.crafted:
                _apply_skillpoints(mod, item, sets_now)
            recurse(_vadd5(_applied, deltas), mod, sets_now, _total_applied + sum(deltas),
                    sim_states, skipped, equipped + [remains[i]],
                    remains[i + 1:] + head)

    recurse([0] * 5, [0] * 5, {}, 0, [], [], [], list(range(len(equipment))))

    final = list(best["final"])
    for name, count in best["sets"].items():
        bonus = sets[name]["bonuses"][count - 1]
        for i, s in enumerate(SKILLS):
            final[i] += bonus.get(s) or 0
            total_item[i] += bonus.get(s) or 0
    return SPResult(order=best["order"], assigned=best["assigned"], final=final,
                    total_assigned=best["total"], set_counts=best["sets"],
                    item_total=total_item, under_100=best["under_100"])


SP_LIMIT = 2048          # manual entries are 12-bit two's complement in links (MAX_SP_BITLEN)


def check_manual(manual):
    """Raise ValueError unless `manual` is None or 5 entries of int/None, as a
    link stores them. Build files are edited by hand, so say what's wrong."""
    if manual is None:
        return
    if not isinstance(manual, list) or len(manual) != 5:
        raise ValueError("skillpoints must be null (automatic) or a list of 5 entries "
                         "(Strength, Dexterity, Intelligence, Defence, Agility), each a number or null")
    for s, v in zip(("Strength", "Dexterity", "Intelligence", "Defence", "Agility"), manual):
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"skillpoints: {s} must be a whole number or null, not {v!r}")
        if not -SP_LIMIT <= v < SP_LIMIT:
            raise ValueError(f"skillpoints: {s} {v} is outside what a link can hold "
                             f"({-SP_LIMIT} to {SP_LIMIT - 1})")


@dataclass
class ManualSP:
    """Skill points with WynnBuilder's manual entries applied on top of the
    automatic result. A link's manual entry is the skill's FINAL total (what
    WynnBuilder's skill-point inputs hold), None where the skill stays automatic
    (build_encode_decode.js encodeSp). The points assigned to a skill are then
    final - automatic final + automatic assigned (DisplayBuildWarningsNode)."""
    auto: SPResult
    manual: list             # 5 bools: set by hand
    final: list              # total per skill after gear and set bonuses (before the tree)
    assigned: list           # points the player assigns per skill
    total_assigned: int
    wearable: bool           # every item's requirement holds with these points


def can_wear(equipment, weapon, assigned):
    """Whether some equip order lets every item be worn with `assigned` base
    points, under WynnBuilder's rules (skillpoints.py docstring): a non-crafted
    item's bonus helps only items equipped after it; the weapon and crafts go on
    last and help nobody; no item may rely on its own bonus (the pop rule)."""
    normal = [i for i, it in enumerate(equipment) if not it.crafted]
    crafted = [it for it in equipment if it.crafted]
    full = (1 << len(equipment)) - 1
    seen = set()

    def points(mask):
        sp = list(assigned)
        for i in normal:
            if mask >> i & 1:
                sp = _vadd5(sp, equipment[i].skillpoints)
        return sp

    def search(mask):
        if mask in seen:
            return False
        seen.add(mask)
        if all(mask >> i & 1 for i in normal):
            sp = points(mask)
            for it in [*crafted, weapon]:
                if not _can_equip(sp, it):
                    return False
            for i in normal:           # the pop rule: own bonus doesn't count
                it = equipment[i]
                own = [it.reqs[j] + it.skillpoints[j] if it.reqs[j] > 0 else 0 for j in range(5)]
                if any(own[j] > sp[j] for j in range(5) if it.reqs[j] > 0):
                    return False
            return True
        sp = points(mask)
        return any(search(mask | 1 << i) for i in normal
                   if not mask >> i & 1 and _can_equip(sp, equipment[i]))
    return search(0) if normal else search(full)


def apply_manual(auto, manual, equipment=None, weapon=None):
    """ManualSP for automatic result `auto` and link entries `manual` (see
    check_manual). With `equipment` and `weapon` (as for calculate_skillpoints)
    it also checks the items can still be worn."""
    check_manual(manual)
    entries = manual or [None] * 5
    is_manual = [v is not None for v in entries]
    final = [auto.final[j] if v is None else v for j, v in enumerate(entries)]
    assigned = [auto.assigned[j] + final[j] - auto.final[j] for j in range(5)]
    wearable = True
    if any(is_manual) and equipment is not None:
        wearable = all(assigned[j] >= auto.assigned[j] for j in range(5)) or \
            can_wear(equipment, weapon, assigned)
    return ManualSP(auto=auto, manual=is_manual, final=final, assigned=assigned,
                    total_assigned=sum(assigned), wearable=wearable)


def set_bonus_stats(set_counts, sets):
    """Stats added by active set bonuses (Build.initBuildStats): everything except
    skill points, which calculate_skillpoints already added. Returns (stats, majors)."""
    stats, majors = {}, set()
    for name, count in set_counts.items():
        bonus = sets[name]["bonuses"][count - 1]
        for key, value in bonus.items():
            if key == "majorIds":
                majors.update(value)
            elif key in SKILLS:
                continue
            else:
                stats[key] = stats.get(key, 0) + value
    return stats, majors
