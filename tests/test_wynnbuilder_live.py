"""Compare wynntools.damage with the live WynnBuilder builder page.

Each build is opened at wynnbuilder.github.io/builder/#<hash> in headless
Chromium. The test then asks the page for its own final stat map and runs its
own SpellDamageCalcNode, getSpellCost and getDefenseStats, so every spell part,
cost and defence number is checked against WynnBuilder's code and graph wiring,
not a re-wiring of it. Builds: every session link, plus seeded random builds
(random gear, powders, aspects and a random valid tree) for all five classes.

    uv run pytest -m live          (needs network and: uv run playwright install chromium)
    WT_LIVE_SEEDS=20 uv run pytest -m live     (more random builds per class)
"""
import json
import math
import os
import random
from pathlib import Path

import pytest

from wynntools.codec import POWDERABLE, TOME_SLOTS, Build, decode, encode
from wynntools.damage import final_stats, damage_report, spell_parts, weapon_stats
from wynntools.rules import ability_points

pytestmark = pytest.mark.live
LINKS = json.loads((Path(__file__).parent / "fixtures" / "links.json").read_text())
PAGE = "https://wynnbuilder.github.io/builder/#"
CLASS_WEAPON = {"Mage": "wand", "Warrior": "spear", "Archer": "bow", "Assassin": "dagger",
                "Shaman": "relik"}

PROBE = """() => {
  const stats = stat_agg_node.value, build = build_node.value;
  const num = v => (typeof v === 'number' && !Number.isFinite(v)) ? String(v) : v;
  const flat = {};
  for (const [k, v] of stats) {
    if (typeof v === 'number') flat[k] = num(v);
    else if (v instanceof Map) flat[k] = Object.fromEntries([...v].map(([a, b]) => [a, num(b)]));
  }
  const spells = [];
  for (const [id, spell] of [...atree_collect_spells.value].sort((a, b) => a[0] - b[0])) {
    const parts = new SpellDamageCalcNode(spell).compute_func(
        new Map([['build', build], ['stats', stats]]));
    const cost = ('cost' in spell && spell.cost != 0) ? num(getSpellCost(stats, spell)) : null;
    spells.push({base: id, name: spell.name, display: spell.display ?? null, cost,
                 parts: JSON.parse(JSON.stringify(parts, (k, v) => num(v)))});
  }
  return {stats: flat, spells, defense: getDefenseStats(stats).map(x => x)};
}"""


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def page_numbers(browser, h, edit=None):
    """The page's numbers for hash `h`. With `edit(page)`, the edit is made in
    WynnBuilder's own inputs first, and the hash it then writes is returned too."""
    page = browser.new_page()
    try:
        page.goto(PAGE + h, wait_until="networkidle", timeout=120_000)
        ready = ("() => typeof stat_agg_node !== 'undefined' && stat_agg_node.value"
                 " && atree_collect_spells.value")
        page.wait_for_function(ready, timeout=120_000)
        page.wait_for_timeout(500)
        if edit is None:
            return page.evaluate(PROBE)
        edit(page)
        page.keyboard.press("Tab")
        page.wait_for_function(f"() => location.hash.slice(1) !== {json.dumps(h)}", timeout=30_000)
        page.wait_for_timeout(1000)
        return page.evaluate(PROBE), page.evaluate("() => location.hash.slice(1)")
    finally:
        page.close()


def close(a, b, what):
    if isinstance(a, str) or isinstance(b, str) or a is None or b is None:
        a = "NaN" if isinstance(a, float) and math.isnan(a) else a
        assert a == b, what
        return
    assert b == pytest.approx(a, rel=1e-9, abs=1e-6), what


def compare(build, gd, got, specials=None):
    stats, tree, spells, *_ = final_stats(build, gd, specials=specials)
    for k, v in got["stats"].items():
        if isinstance(v, dict):
            mine = stats.get(k, {})
            for kk, vv in v.items():
                close(mine.get(kk, 0), vv, f"stat {k}.{kk}")
        else:
            close(stats.get(k, 0), v, f"stat {k}")
    weapon = weapon_stats(gd.item(build.equipment[8]), dict(zip(POWDERABLE, build.powders))[8], gd)
    assert [s["base"] for s in got["spells"]] == sorted(spells)
    report = {s["base_spell"]: s for s in damage_report(build, gd, specials=specials)["spells"]}
    for js in got["spells"]:
        spell = spells[js["base"]]
        assert js["name"] == spell.get("name")
        if js["cost"] is not None:
            close(report[js["base"]].get("cost"), js["cost"], f"{js['name']} cost")
        for mine, theirs in zip(spell_parts(stats, weapon, spell), js["parts"], strict=True):
            where = f"{js['name']} / {theirs['name']}"
            assert mine["name"] == theirs["name"], where
            assert mine.get("type") == theirs.get("type"), where
            if theirs.get("type") == "damage":
                # With a Critical Damage Bonus ID the crits differ on purpose: the
                # developer guide multiplies crit damage by it, WynnBuilder adds it.
                crits = ("crit_min", "crit_max", "crit_total") if not stats.get("critDamPct") else ()
                for key in ("normal_min", "normal_max", "normal_total", *crits):
                    # JS pads a summed part's 2-entry totals out to 6 with NaN; ignore those
                    theirs_k = theirs[key][:2] if key.endswith("total") else theirs[key]
                    for x, y in zip(mine[key], theirs_k, strict=True):
                        close(x, y, f"{where} {key}")
            elif theirs.get("type") == "heal":
                close(mine["heal_amount"], theirs["heal_amount"], f"{where} heal")
    if specials:
        return
    # Summary totals (gear, tomes, sets, armor powders, tree bonuses) at perfect rolls
    from wynntools.verify import STAT_KEYS, summarize
    tm = summarize(build, gd)["totals_max"]
    page = got["stats"]
    for k in STAT_KEYS:
        want = page.get("hp", 0) + page.get("hpBonus", 0) if k == "hp" else page.get(k, 0)
        close(tm[k], want, f"summary {k}")
    d = damage_report(build, gd)["defense"]
    hp, ehp, hpr, ehpr = got["defense"][:4]
    close(d["hp"], hp, "hp")
    close(d["ehp"], ehp[0], "ehp")
    close(d["ehp_no_agi"], ehp[1], "ehp no agi")
    close(d["hpr"], hpr, "hpr")
    close(d["ehpr"], ehpr[0], "ehpr")


@pytest.mark.parametrize("name", [k for k in LINKS if not k.startswith("_")])
def test_session_links_match_wynnbuilder(gd, browser, name):
    h = LINKS[name]["hash"]
    compare(decode(h, gd), gd, page_numbers(browser, h))


def random_tree(tree, level, rng):
    """A random tree WynnBuilder accepts: grow from the root, one available node
    at a time (parent on, dependencies on, no blocker, archetype met, AP left)."""
    root = next(n for n in tree if not n["parents"])
    active, arch = {root["id"]}, {}
    ap = ability_points(level) - (root.get("cost") or 0)
    if root.get("archetype"):
        arch[root["archetype"]] = 1
    while True:
        options = []
        for n in tree:
            if n["id"] in active or (n.get("cost") or 0) > ap:
                continue
            if not any(p in active for p in n["parents"]):
                continue
            if any(d not in active for d in n.get("dependencies") or []):
                continue
            if any(b in active for b in n.get("blockers") or []):
                continue
            req = n.get("archetype_req") or 0
            if req and arch.get(n.get("req_archetype") or n.get("archetype"), 0) < req:
                continue
            options.append(n)
        if not options or rng.random() < 0.03:
            return active
        n = rng.choice(options)
        active.add(n["id"])
        ap -= n.get("cost") or 0
        if n.get("archetype"):
            arch[n["archetype"]] = arch.get(n["archetype"], 0) + 1


def random_build(gd, cls, rng):
    level = rng.choice([80, 105, 106, 121])
    pools = {}
    for it in gd.items:
        if "type" not in it or (it.get("lvl") or 0) > level or it.get("tier") == "Crafted":
            continue
        pools.setdefault(it["type"], []).append(gd.name(it))
    wanted = ["helmet", "chestplate", "leggings", "boots", "ring", "ring", "bracelet", "necklace",
              CLASS_WEAPON[cls]]
    equipment = [rng.choice(pools[t]) if (i == 8 or rng.random() < 0.9) else None
                 for i, t in enumerate(wanted)]
    powders = [[rng.randrange(35) for _ in range(rng.randint(0, 3))] for _ in POWDERABLE]
    tomes = [rng.choice([None, *[t["id"] for t in gd.tomes if t["type"] == s.rstrip("12")]])
             for s in TOME_SLOTS]
    aspects = rng.sample([a["id"] for a in gd.aspects(cls)], 5)
    by_id = {a["id"]: a for a in gd.aspects(cls)}
    aspects = [(a, rng.randint(1, len(by_id[a]["tiers"]))) if rng.random() < 0.8 else None
               for a in aspects]
    return Build(equipment=equipment, level=level, powders=powders, tomes=tomes,
                 aspects=aspects, atree=random_tree(gd.tree(cls), level, rng))


SEEDS = int(os.environ.get("WT_LIVE_SEEDS", 3))     # more for a deeper check


@pytest.mark.parametrize("cls,seed", [(c, s) for c in CLASS_WEAPON for s in range(SEEDS)])
def test_random_builds_match_wynnbuilder(gd, browser, cls, seed):
    rng = random.Random(f"{cls}-{seed}")
    build = random_build(gd, cls, rng)
    h = encode(build, gd)
    build = decode(h, gd)             # exactly what the page will see
    compare(build, gd, page_numbers(browser, h))


@pytest.mark.parametrize("cls", list(CLASS_WEAPON))
def test_links_edited_in_wynnbuilder_round_trip(gd, browser, cls):
    """Powders and aspects typed into WynnBuilder's own inputs: the link it writes
    round-trips through our codec, and our totals and damage equal the page's."""
    rng = random.Random(f"edit-{cls}")
    build = decode(encode(random_build(gd, cls, rng), gd), gd)
    powders = {}
    for slot, idx in zip(["helmet", "chestplate", "leggings", "boots", "weapon"], POWDERABLE):
        name = build.equipment[idx]
        slots = gd.item(name).get("slots") or 0 if name else 0
        powders[slot] = "".join(f"{'etwfa'[rng.randrange(5)]}{rng.randint(1, 7)}"
                                for _ in range(rng.randint(0, slots)))
    aspect = rng.choice(gd.aspects(cls))
    tier = rng.randint(1, len(aspect["tiers"]))

    def edit(page):
        for slot, text in powders.items():
            page.fill(f"#{slot}-powder", text)
        # the aspect inputs live in a collapsed dropdown: set them as typing would
        page.evaluate("""([name, tier]) => {
            for (const [id, v] of [['aspect1-choice', name], ['aspect1-tier-choice', tier]]) {
                const el = document.getElementById(id);
                el.value = v;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }
        }""", [aspect["displayName"], str(tier)])

    got, new_hash = page_numbers(browser, encode(build, gd), edit)
    edited = decode(new_hash, gd)
    assert encode(edited, gd) == new_hash
    assert edited.aspects[0] == (aspect["id"], tier)
    for slot, idx in zip(powders, POWDERABLE):
        want = [f"{c}{t}" for c, t in zip(powders[slot][::2], powders[slot][1::2])]
        from wynntools.codec import powder_name
        assert [powder_name(p) for p in edited.powders[POWDERABLE.index(idx)]] == want, slot
    compare(edited, gd, got)


def test_partial_manual_skill_points_match_wynnbuilder(gd, browser):
    """A link with only Intelligence set by hand (a final total; the rest automatic)."""
    b = decode(LINKS["shaman_105_stormdrain"]["hash"], gd)
    from wynntools.verify import resolve_skillpoints
    b.skillpoints = [None, None, resolve_skillpoints(b, gd).final[2] + 17, None, None]
    h = encode(b, gd)
    got = page_numbers(browser, h)
    assert got["stats"]["int"] == b.skillpoints[2]
    compare(decode(h, gd), gd, got)


@pytest.mark.parametrize("special", [("Curse", 7), ("Wind Prison", 3), ("Quake", 5), ("Courage", 7)])
def test_powder_specials_match_wynnbuilder(gd, browser, special):
    """A weapon special switched on with WynnBuilder's own buttons, and an armor
    special's slider: every spell part, and the special's burst hit."""
    name, power = special
    h = LINKS["shaman_105_stormdrain"]["hash"]
    page = browser.new_page()
    try:
        page.goto(PAGE + h, wait_until="networkidle", timeout=120_000)
        page.wait_for_function("() => typeof stat_agg_node !== 'undefined' && stat_agg_node.value"
                               " && atree_collect_spells.value", timeout=120_000)
        page.wait_for_timeout(500)
        page.evaluate("""([id]) => {
            updatePowderSpecials(id);
            const s = document.getElementById('str_boost_armor');
            s.value = 150; s.dispatchEvent(new Event('change'));
        }""", [f"{name.replace(' ', '_')}-{power}"])
        page.wait_for_timeout(1500)
        got = page.evaluate(PROBE)
        burst = page.evaluate("""([idx, pct, boost]) => {
            const stats = stat_agg_node.value, weapon = build_node.value.weapon.statMap;
            const conv = [0, 0, 0, 0, 0, 0]; conv[idx] = pct;
            const [n, c] = calculateSpellDamage(stats, weapon, conv, false, true, '0.Powder Special');
            const d = 1 + boost / 100;
            return [(n[0] + n[1]) / 2 / d, (c[0] + c[1]) / 2 / d];
        }""", [1 + ["Quake", "Chain Lightning", "Curse", "Courage", "Wind Prison"].index(name),
               {"Quake": [240, 280, 320, 360, 400, 440, 480], "Courage": [110, 125, 140, 155, 170, 185, 200]}
               .get(name, [0] * 7)[power - 1],
               {"Courage": [10, 12.5, 15, 17.5, 20, 22.5, 25]}.get(name, [0] * 7)[power - 1]])
    finally:
        page.close()
    specials = {"weapon": [name, power], "armor": {"e": 150}}
    build = decode(h, gd)
    compare(build, gd, got, specials)
    ps = damage_report(build, gd, specials=specials)["powder_special"]
    if name in ("Quake", "Courage"):
        close(ps["non_crit"], burst[0], "burst non-crit")
        close(ps["crit"], burst[1], "burst crit")
