"""Two builds side by side: gear, totals, skill points and damage, with differences."""
from .codec import SLOTS
from .damage import spell_values, damage_report
from .rules import SKILLS
from .verify import STAT_KEYS, summarize


def compare(a, b, gd, roll="base", inventory=None):
    """a, b: Build objects. Returns {"gear": [...], "stats": [...], "damage": [...]},
    each row {"key", "a", "b", "diff"} (diff = b - a, None when not numeric).
    Rows where both sides are zero or equal-and-empty are left out."""
    sa, sb = summarize(a, gd, roll, inventory), summarize(b, gd, roll, inventory)
    ta = sa["totals"] if roll != "max" else sa["totals_max"]
    tb = sb["totals"] if roll != "max" else sb["totals_max"]
    def label(n):
        if n is None:
            return None
        it = gd.item(n)
        return {"name": n, "tier": it.get("tier"),
                "text": f"crafted {it['type']}" if n.startswith("CR-") else n}
    gear = [{"key": slot, "a": x, "b": y, "same": x == y, "a_item": label(x), "b_item": label(y)}
            for slot, x, y in zip(SLOTS, a.equipment, b.equipment)]
    stats = []
    for k in STAT_KEYS:
        x, y = ta.get(k, 0), tb.get(k, 0)
        if x or y:
            stats.append({"key": k, "a": x, "b": y, "diff": y - x})
    stats.append({"key": "sp_total", "a": sa["sp_total"], "b": sb["sp_total"],
                  "diff": sb["sp_total"] - sa["sp_total"]})
    for s in SKILLS:
        x, y = sa["sp_final"][s], sb["sp_final"][s]
        if x or y:
            stats.append({"key": f"sp_{s}", "a": x, "b": y, "diff": y - x})
    damage = []
    if a.weapon and b.weapon:
        da, db = spell_values(a, gd, roll, inventory), spell_values(b, gd, roll, inventory)
        for name in dict.fromkeys([*da, *db]):
            x, y = da.get(name), db.get(name)
            damage.append({"key": name, "a": x, "b": y,
                           "diff": None if x is None or y is None else y - x})
        ea = damage_report(a, gd, roll, inventory)["defense"]
        eb = damage_report(b, gd, roll, inventory)["defense"]
        for k in ("ehp", "ehp_no_agi", "hpr"):
            damage.append({"key": k, "a": ea[k], "b": eb[k], "diff": eb[k] - ea[k]})
    return {"roll": roll, "gear": gear, "stats": stats, "damage": damage,
            "same_class": bool(a.weapon and b.weapon
                               and gd.weapon_class(a.weapon) == gd.weapon_class(b.weapon))}
