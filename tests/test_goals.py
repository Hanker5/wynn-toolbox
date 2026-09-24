"""The damage engine against the developer guide ("How Damage Is Calculated -
Fruma Edition") and WynnBuilder: powder specials, crits, conversions."""
import pytest

from wynntools.codec import Build, decode
from wynntools.damage import check_specials, damage_report


def test_powder_specials_follow_wynnbuilder(gd, links):
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    off = damage_report(b, gd, "base")
    curse = damage_report(b, gd, "base", specials={"weapon": ["Curse", 7]})
    for a, c in zip(off["spells"], curse["spells"]):     # damMult.Curse: +25% on every hit
        if a.get("summary") and a.get("summary_type") != "heal":
            assert c["summary"] == pytest.approx(a["summary"] * 1.25)
    quake = damage_report(b, gd, "base", specials={"weapon": ["Quake", 7]})
    assert quake["powder_special"]["element"] == "Earth" and quake["powder_special"]["average"] > 0
    rage = damage_report(b, gd, "base", specials={"armor": {e: 100 for e in "etwfa"}})
    assert rage["spells"][0]["dps"] > off["spells"][0]["dps"]
    for bad in ({"weapon": ["Fireball", 7]}, {"weapon": ["Curse", 9]}, {"armor": {"e": 301}}):
        with pytest.raises(ValueError):
            check_specials(bad)


def test_powder_special_activation_follows_the_developer_guide():
    """"How Damage Is Calculated - Fruma Edition": two or more tier IV+ powders of
    one element; the first qualifying element wins; the tiers set the power."""
    from wynntools.damage import powder_special
    ids = lambda text: ["etwfa".index(x[0]) * 7 + int(x[1]) - 1 for x in text.split()]
    table = {"e4 e4": 1, "e4 e5": 2, "e5 e5": 3, "e4 e6": 3, "e5 e6": 4, "e4 e7": 4,
             "e6 e6": 5, "e5 e7": 5, "e6 e7": 6, "e7 e7": 7}
    for text, power in table.items():
        assert powder_special(ids(text)) == (0, power), text
    assert powder_special(ids("e7 e7 t7 t7")) == (0, 7) == powder_special(ids("e7 t7 t7 e7"))
    assert powder_special(ids("e3 e7")) is None and powder_special(ids("e7 t7")) is None


def test_build_specials_read_each_item(gd, links):
    from wynntools.damage import build_specials, damage_report
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    b.powders = [[20, 20, 20], [], [], [], [13, 12]]        # helmet: three Water VII; weapon: t7 t6
    give = build_specials(b, gd)
    assert give["weapon"] == ["Chain Lightning", 6]
    assert give["armor"] == [{"slot": "helmet", "name": "Concentration", "element": "w", "power": 7}]
    assert damage_report(b, gd, "base")["powders_give"] == give


def test_crit_damage_bonus_multiplies_crits(gd, links):
    """The developer guide lists Critical Damage Bonus with the master modifiers
    (multiplicative); WynnBuilder adds it to the crit bonus instead."""
    from wynntools.damage import calculate_spell_damage, final_stats, weapon_stats
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    stats = final_stats(b, gd, "base")[0]
    weapon = weapon_stats(gd.item(b.weapon), [], gd)
    conv = [100, 0, 0, 0, 0, 0]
    plain = calculate_spell_damage(dict(stats, critDamPct=0), weapon, conv, False)
    cut = calculate_spell_damage(dict(stats, critDamPct=-20), weapon, conv, False)
    assert cut[0] == plain[0]                                  # non-crit untouched
    assert cut[1][0] == pytest.approx(plain[1][0] * 0.8)       # crit x 0.8, not -20 points
    assert plain[1][0] > plain[0][0]


def test_whirlwind_strike_follows_the_guides_steps(gd):
    """The guide's Fierce Thunder / Whirlwind Strike case study, step by step,
    with the conversions in this data version (the guide's are from a newer
    patch): the engine must give the same number as the six steps."""
    from wynntools.damage import collect_spells, damage_report, merge_tree
    from wynntools.rules import sp_to_pct
    tree = gd.tree("Warrior")
    by = {n["display_name"]: n["id"] for n in tree}
    root = next(n["id"] for n in tree if not n["parents"])
    sel = {root} | {by[x] for x in ("Uppercut", "Half-Moon Swipe", "Whirlwind Strike", "Water Mastery")}
    b = Build(equipment=[None] * 8 + ["Fierce Thunder"], level=39, atree=sel)
    got = next(s for s in damage_report(b, gd, "max")["spells"] if s["name"] == "Uppercut")["parts"][0]
    conv = next(p["multipliers"] for p in collect_spells(merge_tree("Warrior", sel, gd))[3]["parts"]
                if "multipliers" in p)
    n_, e_, t_, w_, f_, a_ = [c / 100 for c in conv]
    # Step 1: base DPS (spell) = base damage x 2.5 (Fast)
    bn, bt = (17 * 2.5, 38 * 2.5), (10 * 2.5, 57 * 2.5)
    tot = (bn[0] + bt[0], bn[1] + bt[1])
    # Step 2: neutral conversion scales every element; elemental ones convert the total
    N = [x * n_ for x in bn]
    T = [bt[i] * n_ + tot[i] * t_ for i in (0, 1)]
    E, W, A = ([tot[i] * c for i in (0, 1)] for c in (e_, w_, a_))
    # Step 3: Water Mastery adds 2-4 Water (present thanks to the conversion)
    W = [W[0] + 2, W[1] + 4]
    # Step 4: base modifiers: 25 Dex -> Thunder %, Thunder raw 60 x total conversion,
    # Water +30% (item) +15% (mastery)
    dex = sp_to_pct(25)
    T = [x * (1 + dex) + 60 * sum(c / 100 for c in conv) for x in T]
    W = [x * (1 + 0.30 + 0.15) for x in W]
    # Step 5: no master modifiers on a non-crit (no Strength)
    non_crit = sum((lo + hi) / 2 for lo, hi in (N, E, T, W, A))
    assert got["non_crit"] == pytest.approx(non_crit, rel=1e-3)
    assert got["crit"] == pytest.approx(2 * non_crit, rel=1e-3)       # +100% on crit
