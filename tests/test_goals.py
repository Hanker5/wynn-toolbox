"""New floors, derived goals, acquisition constraints, explanations, trade-offs,
survivability, powder specials and planner, puppet models, candidates and
import diagnostics. Every build a search returns must pass WynnBuilder's checks."""
import dataclasses

import pytest

from wynntools import buildfile, variants
from wynntools.codec import Build, decode, to_link
from wynntools.damage import check_specials, damage_report
from wynntools.derived import metrics
from wynntools.diagnose import diagnose_link
from wynntools.explain import explain
from wynntools.gear_milp import GearModel, solve_gear_exact
from wynntools.gear_solver import Spec, solve_gear
from wynntools.inventory import Inventory
from wynntools.powders import plan_armor, plan_weapon
from wynntools.rules import skill_points
from wynntools.search import kind_for, spec_from
from wynntools.verify import build_skillpoints, check_link, summarize

STORM = Spec(cls="Shaman", level=105, objective={"hp": 1}, force={"weapon": "Stormdrain"})


def build_of(spec, r, gd, atree=()):
    return Build(equipment=r.equipment, level=spec.level, skillpoints=r.skillpoints,
                 tomes=list(spec.tomes) + [None] * (14 - len(spec.tomes)), atree=set(atree))


def verified(gd, spec, r, atree=()):
    ok, rep = check_link(to_link(build_of(spec, r, gd, atree), gd), gd)
    assert ok, rep["problems"]
    return rep["summary"]


# ------------------------------------------------------------ floors (exact search)
def test_sum_floors_hold(gd):
    spec = dataclasses.replace(STORM, floors={"hprRaw": 300, "fDef": 150, "min_eledef": 0})
    r = solve_gear_exact(spec, gd)
    s = verified(gd, spec, r)
    t = s["totals"]
    assert t["hprRaw"] >= 300 and t["fDef"] >= 150
    assert min(t[k] for k in ("eDef", "tDef", "wDef", "fDef", "aDef")) >= 0


def test_skill_floor_assigns_points_and_keeps_them(gd):
    spec = dataclasses.replace(STORM, floors={"def": 90, "agi": 60, "int": 100})
    r = solve_gear_exact(spec, gd)
    auto = build_skillpoints(r.equipment, [None] * 14, gd)
    assert auto.final[2] < 100 and r.skillpoints[2] == 100     # the gear alone falls short: points set by hand
    s = verified(gd, spec, r)
    assert s["sp_final"]["def"] >= 90 and s["sp_final"]["agi"] >= 60 and s["sp_final"]["int"] == 100
    assert s["sp_manual"]["int"]
    assert s["sp_total"] <= skill_points(105)


def test_lowest_elemental_defence_goal_is_exact(gd):
    spec = dataclasses.replace(STORM, objective={"min_eledef": 1}, floors={"hp": 15000})
    r = solve_gear_exact(spec, gd)
    t = verified(gd, spec, r)["totals"]
    low = min(t[k] for k in ("eDef", "tDef", "wDef", "fDef", "aDef"))
    assert r.score == pytest.approx(low)
    plain = solve_gear_exact(dataclasses.replace(spec, objective={"hp": 1}), gd)
    t2 = summarize(build_of(spec, plain, gd), gd)["totals"]
    assert low >= min(t2[k] for k in ("eDef", "tDef", "wDef", "fDef", "aDef"))


def test_at_most_one_group_and_exclusions(gd):
    base = solve_gear_exact(dataclasses.replace(STORM, objective={"eSteal": 1}), gd)
    pair = [n for n in base.equipment[:8] if n][:2]
    spec = dataclasses.replace(STORM, objective={"eSteal": 1}, at_most_one=[pair])
    r = solve_gear_exact(spec, gd)
    assert sum(n in pair for n in r.equipment) <= 1
    verified(gd, spec, r)
    r2 = solve_gear(dataclasses.replace(spec, topn=4), gd)       # the shortlist search too
    assert sum(n in pair for n in r2.equipment) <= 1


def test_unavailable_items_are_left_out(gd):
    inv = Inventory(unavailable={"Leo": "too expensive"})
    raw = {"class": "Shaman", "level": 105, "objective": {"hp": 1}, "force": {"weapon": "Stormdrain"}}
    spec = spec_from(raw, gd, inv)
    assert "Leo" in spec.exclude
    assert "Leo" not in solve_gear_exact(spec, gd).equipment
    forced = spec_from({**raw, "force": {**raw["force"], "chestplate": "Leo"}}, gd, inv)
    assert "Leo" not in forced.exclude                 # forcing an item wins


def test_preferred_item_breaks_a_tie_without_changing_the_score(gd):
    spec = dataclasses.replace(STORM, objective={"eSteal": 1})
    r = solve_gear_exact(spec, gd)
    model = GearModel(spec, gd)
    # any other ring that can replace ring 2 at the same score gets preferred
    for v in model.by_kind["ring"]:
        it = model.var_item[v]
        name = gd.name(it)
        if name in r.equipment or model.stat(it, "eSteal") != model.stat(gd.item(r.equipment[5]), "eSteal"):
            continue
        r2 = solve_gear_exact(dataclasses.replace(spec, prefer={name: 0}), gd)
        assert r2.score == pytest.approx(r.score)
        break


def test_spec_validation_names_the_choices(gd):
    raw = {"class": "Mage", "level": 105, "objective": {"hp": 1}}
    with pytest.raises(ValueError, match="unknown goal"):
        spec_from({**raw, "objective": {"tankiness": 1}}, gd)
    with pytest.raises(ValueError, match="unknown minimum 'hpregen'"):
        spec_from({**raw, "floors": {"hpregen": 5}}, gd)
    with pytest.raises(KeyError):
        spec_from({**raw, "exclude": ["Not An Item"]}, gd)


def test_search_kind(gd):
    assert kind_for(STORM) == "exact"
    assert kind_for(dataclasses.replace(STORM, floors={"ehp": 1})) == "shortlists"
    assert kind_for(dataclasses.replace(STORM, objective={"ehp": 1})) == "local"


def test_derived_floor_in_the_shortlist_search(gd):
    spec = dataclasses.replace(STORM, objective={"eSteal": 1}, floors={"ehp": 20000}, topn=4, atree=set())
    r = solve_gear(spec, gd)
    assert r is not None and r.metrics["ehp"] >= 20000
    m = metrics(build_of(spec, r, gd), gd)
    assert m["ehp"] >= 20000


# ------------------------------------------------------------ derived goals (local search)
def test_effective_hp_goal(gd):
    from wynntools.gear_local import LocalSearch
    spec = dataclasses.replace(STORM, objective={"ehp": 1}, floors={"hp": 15000}, atree=set())
    ls = LocalSearch(spec, gd)
    r = ls.run()
    verified(gd, spec, r)
    got = metrics(build_of(spec, r, gd), gd)["ehp"]
    assert got == pytest.approx(r.score)
    # at least as good as simply maximizing health
    hp = solve_gear_exact(dataclasses.replace(spec, objective={"hp": 1}), gd)
    assert got >= metrics(build_of(spec, hp, gd), gd)["ehp"]
    assert all(tuple(k) in ls.legal or ls.evaluated[k] is None or k[:8] == (None,) * 8
               for k in ls.evaluated)


@pytest.mark.slow
def test_puppet_goal_and_tradeoffs(gd):
    from wynntools.presets import preset_weights
    from wynntools.rules import ability_points
    from wynntools.tradeoffs import tradeoffs
    from wynntools.tree_solver import solve_tree
    tree = set(solve_tree(gd.tree("Shaman"), preset_weights("shaman-summoner", gd), ability_points(105)))
    spec = dataclasses.replace(STORM, objective={"puppet_dps": 1}, floors={"hp": 12000}, atree=tree)
    out = tradeoffs(spec, gd, "puppet_dps")
    opts = out["options"]
    assert len(opts) >= 2 and opts[0]["label"] == "max damage" and opts[-1]["label"] == "max survival"
    for a, b in zip(opts, opts[1:]):          # a Pareto set: less damage, more survival
        assert a["damage"] >= b["damage"] and a["ehp"] <= b["ehp"]
    for o in opts:
        verified(gd, spec, o["result"], tree)
        assert o["hp"] >= 12000


# ------------------------------------------------------------ explanations
def test_explains_a_skill_point_conflict(gd):
    spec = Spec(cls="Shaman", level=105, objective={"hp": 1}, force={"weapon": "Sunstar"},
                floors={"def": 120, "int": 120, "mr": 30, "hp": 15000})
    assert solve_gear_exact(spec, gd) is None
    ex = explain(spec, gd)
    assert set(ex["conflict"]) == {"Sunstar in weapon", "Defence at least 120", "Intelligence at least 120"}
    text = " ".join(ex["lines"])
    assert "Sunstar alone needs 115" in text and "Dexterity 115" in text
    for line in ex["lines"]:                      # "best reached" numbers are below what was asked
        if "reach" in line or "found" in line:
            got = int(line.split(" is ")[1].split(" ")[0].replace(",", ""))
            assert got < 120


def test_explains_an_impossible_floor(gd):
    spec = Spec(cls="Mage", level=105, objective={"poison": 1}, floors={"hp": 60000})
    ex = explain(spec, gd)
    assert ex["conflict"] == ["Health at least 60,000"]
    assert "the most any legal build reaches is" in ex["lines"][0]


# ------------------------------------------------------------ survivability, specials, puppets
def test_survivability_and_warnings(gd, links):
    doc = buildfile.refresh(buildfile.from_build(decode(links["shaman_105_stormdrain"]["hash"], gd), gd), gd)
    sv = doc["status"]["survivability"]["typical"]
    assert sv["lowest"]["element"] == "a" and sv["eledefs"]["a"] < 0
    assert sv["ehp"] > sv["hp"] * 0.5 and sv["def"] == doc["status"]["sp_effective"]["def"]
    w = {x["code"]: x for x in doc["status"]["warnings"]}
    assert w["neg_adef"]["fix"] == {"action": "search", "floors": {"min_eledef": 0},
                                    "why": "no negative elemental defence"}


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


# ------------------------------------------------------------ powder planner
def test_armor_powders_balance_elemental_defence(gd, links):
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    r = plan_armor(b, gd, "eledef")
    assert r["lowest"] > r["before"]["lowest"] and r["lowest"] >= 0
    b.powders[:4] = [[{"e": 0, "t": 7, "w": 14, "f": 21, "a": 28}[p[0]] + int(p[1]) - 1 for p in r["powders"][s]]
                     for s in ("helmet", "chestplate", "leggings", "boots")]
    after = damage_report(b, gd, "base")["defense"]["eledefs"]
    assert min(after.values()) == pytest.approx(r["lowest"])
    assert plan_armor(b, gd, "special:e")["powders"]["helmet"][0].startswith("e")


def test_weapon_powders_raise_damage(gd, links):
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    r = plan_weapon(b, gd, "puppet_dps")
    assert len(r["powders"]) == gd.item("Stormdrain")["slots"] and r["value"] >= r["before"]
    q = plan_weapon(b, gd, "special:Wind Prison", measure="puppet_dps")
    assert all(p.startswith("a") for p in q["powders"]) and q["special"] == {"weapon": ["Wind Prison", 7]}


# ------------------------------------------------------------ candidates
def test_candidates_choose_and_trash(gd, links, tmp_path):
    doc = buildfile.refresh({"name": "Main", "notes": "keep me", "locked": ["weapon"],
                             **buildfile.from_build(decode(links["shaman_105_stormdrain"]["hash"], gd), gd)}, gd)
    buildfile.write(tmp_path / "main.json", doc)
    for name, key in (("a", "shaman_105_resonance"), ("b", "shaman_105_cryoseism")):
        c = buildfile.from_build(decode(links[key]["hash"], gd), gd)
        buildfile.write(tmp_path / f"main--{name}.json",
                        buildfile.refresh({"name": f"Main: {name}", "parent": "main.json", **c}, gd))
    assert [p.name for p in variants.candidates(tmp_path / "main.json")] == ["main--a.json", "main--b.json"]
    new, trash = variants.choose(tmp_path / "main.json", tmp_path / "main--a.json", gd)
    assert new["name"] == "Main" and new["notes"] == "keep me" and new["locked"] == ["weapon"]
    assert new["equipment"] == buildfile.from_build(decode(links["shaman_105_resonance"]["hash"], gd), gd)["equipment"]
    assert (tmp_path / ".trash" / trash).exists() and "parent" not in new
    moved = variants.trash_candidates(tmp_path / "main.json")
    assert [f for f, _ in moved] == ["main--b.json"] and not variants.candidates(tmp_path / "main.json")


# ------------------------------------------------------------ import diagnostics
def test_import_diagnostics(gd, links):
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    b.skillpoints = [None, None, 80, None, None]
    r = diagnose_link(to_link(b, gd), gd)
    codes = {f["code"]: f["level"] for f in r["findings"]}
    assert r["ok"] and codes["sp_partial"] == "warn" and "puppets" not in codes
    b.powders[4] = [6, 6]                                  # two Earth VII on the weapon: Quake 7
    r = diagnose_link(to_link(b, gd), gd)
    assert any(f["code"] == "specials" and "Quake power 7" in f["message"] for f in r["findings"])
    b.powders[4] = []
    b.skillpoints = [10, None, None, None, None]          # below what the gear needs
    r = diagnose_link(to_link(b, gd), gd)
    assert not r["ok"] and any(f["code"] == "sp" and "too low" in f["message"] for f in r["findings"])
    r = diagnose_link(to_link(b, gd), gd, Inventory(unavailable={"Stormdrain": "sold"}))
    assert any(f["code"] == "unavailable" and "(sold)" in f["message"] for f in r["findings"])
    r = diagnose_link("https://wynnbuilder.github.io/builder/#not-a-link", gd)
    assert not r["ok"] and r["doc"] is None


def test_retired_item_ids_are_flagged(gd, links):
    current = {it["id"] for it in gd.items}
    slot_of = {"helmet": 0, "chestplate": 1, "leggings": 2, "boots": 3, "bracelet": 6, "necklace": 7}
    old = next(i for i, it in gd.item_by_id.items() if i not in current and it.get("type") in slot_of)
    target = gd.name(gd.item_by_id[old])
    slot = slot_of[gd.item_by_id[old]["type"]]
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    b.equipment[slot] = target
    item = gd.item_by_name[target]
    real = item["id"]
    item["id"] = old                         # encode the retired id, as an old link would
    try:
        link = to_link(b, gd)
    finally:
        item["id"] = real
    from wynntools.codec import SLOTS
    assert decode(link, gd).remapped == [SLOTS[slot]]
    r = diagnose_link(link, gd)
    assert any(f["code"] == "retired_id" for f in r["findings"])
    assert not any("round-trip" in f["message"] for f in r["findings"])
