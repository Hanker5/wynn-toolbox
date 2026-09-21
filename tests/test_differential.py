"""Cross-check the Python port against WynnBuilder's own JavaScript.

Runs WynnBuilder's JS in QuickJS (see tests/js/wynnbuilder_harness.py) on
randomized inputs and compares results field by field. Needs network the first
time (to fetch WynnBuilder's JS) and uv (to run Python 3.12 with quickjs).

    uv run pytest -m differential
"""
import json
import random
import shutil
import subprocess
import urllib.request
from pathlib import Path

import pytest

from wynntools import codec
from wynntools.bits import BitWriter
from wynntools.crafting import (ACCESSORY_TYPES, ARMOR_TYPES, WEAPON_TYPES, Craft,
                                craft_item, encode_craft_hash)
from wynntools.data import BASE_URL, CACHE_DIR, VERSIONS, load
from wynntools.rules import SKILLS

pytestmark = pytest.mark.differential
HARNESS = Path(__file__).parent / "js" / "wynnbuilder_harness.py"
JS_FILES = ("js/utils.js", "js/build_utils.js", "js/powders.js", "js/loader.js",
            "js/load_ing.js", "js/craft.js", "js/builder/build_encode_decode.js",
            "js/skillpoints.js")


@pytest.fixture(scope="module")
def js_dir():
    d = CACHE_DIR / "wynnbuilder-js"
    for f in JS_FILES:
        dest = d / f
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(f"{BASE_URL}/{f}", timeout=60) as r:
                dest.write_bytes(r.read())
    return d


def run_js(js_dir, program):
    if not shutil.which("uv"):
        pytest.skip("uv not available")
    out = subprocess.run(
        ["uv", "run", "--quiet", "--no-project", "--python", "3.12", "--with", "quickjs",
         "python", str(HARNESS), str(js_dir)],
        input=program, capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise AssertionError(out.stderr[-2000:])
    return json.loads(out.stdout)


def setup_program():
    version = VERSIONS[-1]
    return (f"ENC = {json.dumps(load('encoding'))};"
            f"ings = {json.dumps(load('ingreds'))};"
            f"recipes = {json.dumps(load('recipes')['recipes'])};"
            "for (const i of ings) clean_ing(i); ingredient_loader.init_maps();")


def test_craft_stats_and_hashes_match_wynnbuilder(gd, js_dir):
    cd = gd.crafts
    rng = random.Random(20260921)
    gear = [r["name"] for r in cd.recipes
            if r["type"].lower() in ARMOR_TYPES | WEAPON_TYPES | ACCESSORY_TYPES]
    names = [i["displayName"] for i in cd.ingredients]
    movers = [i["displayName"] for i in cd.ingredients if any(i["posMods"].values())]
    crafts = []
    for _ in range(400):
        pool = movers if rng.random() < 0.5 else names    # exercise effectiveness a lot
        crafts.append(Craft(rng.choice(gear), [rng.choice(pool) for _ in range(6)],
                            (rng.randint(1, 3), rng.randint(1, 3)),
                            rng.choice(["SLOW", "NORMAL", "FAST"])))
    program = setup_program() + "JSON.stringify(" + json.dumps(
        [[c.recipe, c.ingredients, list(c.mat_tiers), c.atk_spd] for c in crafts]) + """
      .map(([r, ings, tiers, atk]) => {
        const c = new Craft(expandRecipe(recipeMap.get(r)), tiers,
                            ings.map((n) => expandIngredient(ingMap.get(n))), atk, "");
        const s = c.statMap, rolls = {};
        for (const [k, v] of s.get("maxRolls")) {
          const lo = s.get("minRolls").get(k);
          if (v || lo) rolls[k] = [lo, v];
        }
        return {hash: encodeCraft(c).toB64(), hp: s.get("hp"), hpLow: s.get("hpLow"),
                reqs: s.get("reqs"), sp: s.get("skillpoints"), rolls,
                durability: s.get("durability"), missing: s.get("missingDurability") ?? null,
                nDam: s.get("nDam"), nDamLow: s.get("nDamLow") ?? null};
      }))"""
    js = run_js(js_dir, program)
    assert len(js) == len(crafts)
    # the random cases must actually exercise the interesting paths
    assert sum(bool(j["rolls"]) for j in js) > 100
    assert sum(any(j["reqs"]) for j in js) > 100
    assert sum(j["missing"] is not None for j in js) > 20
    assert sum(j["missing"] is None for j in js) > 20
    assert sum(isinstance(j["nDam"], str) and j["nDam"] != "0-0" for j in js) > 20
    for c, j in zip(crafts, js):
        it = craft_item(c, cd)
        where = f"{c.recipe} {c.ingredients} {c.mat_tiers} {c.atk_spd}"
        assert encode_craft_hash(c, cd) == "CR-" + j["hash"], where
        if it["category"] == "armor":
            assert (it["hp"], it["hpLow"]) == (j["hp"], j["hpLow"]), where
        if it["category"] == "weapon":
            assert (it["nDam"], it["nDamLow"]) == (j["nDam"], j["nDamLow"]), where
        assert [it[f"{s}Req"] for s in SKILLS] == j["reqs"], where
        assert [it[s] for s in SKILLS] == j["sp"], where
        py_rolls = {k: list(v) for k, v in it["rolls"].items() if any(v)}
        js_rolls = {k: v for k, v in j["rolls"].items() if k not in SKILLS and any(v)}
        assert py_rolls == js_rolls, where
        assert (j["missing"] is not None) == any("durability" in p for p in it["problems"]), where
        if j["missing"] is None:
            assert it["durability"] == j["durability"], where


def test_build_sections_match_wynnbuilder(gd, js_dir):
    """Powders, assigned skill points, level, aspects and tomes, bit for bit."""
    enc = gd.enc
    rng = random.Random(7)
    cases = []
    for _ in range(300):
        powders = [rng.randrange(35) for _ in range(rng.randint(0, 6))]
        if rng.random() < 0.3:                     # clustered powders exercise repeats
            powders = sorted(powders)
        sp = None if rng.random() < 0.3 else [
            None if rng.random() < 0.4 else rng.choice([-1, 1]) * rng.randint(1, 150) for _ in range(5)]
        if sp is not None and all(x is None for x in sp):
            sp[0] = 42
        aspects = None if rng.random() < 0.3 else [
            None if rng.random() < 0.4 else (rng.randrange(32), rng.randint(1, 4)) for _ in range(5)]
        tomes = [None if rng.random() < 0.5 else rng.randrange(256) for _ in range(14)]
        cases.append({"powders": powders, "sp": sp, "level": rng.randint(1, 121),
                      "aspects": aspects, "tomes": tomes})

    def py(section, fn, *args):
        w = BitWriter()
        fn(w, *args, enc)
        return w.to_b64()
    program = setup_program() + "JSON.stringify(" + json.dumps(cases) + """
      .map((c) => {
        const tomes = c.tomes.map((t) => ({statMap: t === null ? new Map([["NONE", true]])
                                                                : new Map([["id", t]])}));
        const aspects = (c.aspects ?? [null, null, null, null, null]).map((a) =>
            a === null ? [{NONE: true}, 1] : [{id: a[0]}, a[1]]);
        const finalSp = (c.sp ?? [0, 0, 0, 0, 0]).map((x) => x ?? 0);
        return {powders: encodePowders(c.powders, 0).toB64(),
                sp: encodeSp(finalSp, [0, 0, 0, 0, 0], 0).toB64(),
                level: encodeLevel(c.level, 0).toB64(),
                aspects: encodeAspects(aspects, 0).toB64(),
                tomes: encodeTomes(tomes).toB64()};
      }))"""
    js = run_js(js_dir, program)
    assert len(js) == len(cases)
    for c, j in zip(cases, js):
        assert py("powders", codec._encode_powders, c["powders"]) == j["powders"], c
        assert py("sp", codec._encode_sp, c["sp"]) == j["sp"], c
        assert py("level", codec._encode_level, c["level"]) == j["level"], c
        aspects = None if c["aspects"] is None else [None if a is None else tuple(a) for a in c["aspects"]]
        assert py("aspects", codec._encode_aspects, aspects) == j["aspects"], c
        assert py("tomes", codec._encode_tomes, c["tomes"]) == j["tomes"], c


def test_skillpoints_match_wynnbuilder(gd, js_dir):
    """calculate_skillpoints on random equipment: set pieces, crafted items and
    negative bonuses included."""
    from wynntools.skillpoints import SPItem, calculate_skillpoints

    rng = random.Random(4242)
    by_type = {}
    for it in gd.items:
        by_type.setdefault(it.get("type"), []).append(it)
    with_reqs = {t: [i for i in v if any(i.get(r) for r in ("strReq", "dexReq", "intReq", "defReq", "agiReq"))]
                 for t, v in by_type.items()}
    set_names = [n for n, st in gd.sets.items() if len(st["items"]) >= 3]
    guilds = [t for t in gd.tomes if t.get("type") == "guildTome" and "֎" not in gd.name(t)]
    slots = ["boots", "leggings", "chestplate", "helmet", "ring", "ring", "bracelet", "necklace"]
    weapons = [i for t in ("wand", "bow", "dagger", "spear", "relik") for i in with_reqs[t]]

    def crafted():
        return SPItem(skillpoints=[rng.choice([0, 0, rng.randint(-8, 8)]) for _ in range(5)],
                      reqs=[rng.choice([0, 0, rng.randint(-40, 90)]) for _ in range(5)], crafted=True)

    cases = []
    for _ in range(300):
        eq = []
        favourite = rng.choice(set_names) if rng.random() < 0.4 else None
        for t in slots:
            if favourite:
                pieces = [gd.item(n) for n in gd.sets[favourite]["items"]
                          if n in gd.item_by_name and gd.item(n).get("type") == t]
                if pieces and rng.random() < 0.8:
                    it = rng.choice(pieces)
                    eq.append(SPItem.of(it, gd.set_of.get(gd.name(it))))
                    continue
            r = rng.random()
            if r < 0.1:
                eq.append(SPItem())
            elif r < 0.2:
                eq.append(crafted())
            else:
                it = rng.choice(with_reqs[t])
                eq.append(SPItem.of(it, gd.set_of.get(gd.name(it))))
        eq.append(SPItem.of(rng.choice(guilds)) if rng.random() < 0.5 else SPItem())
        w = rng.choice(weapons)
        cases.append((eq, SPItem.of(w, gd.set_of.get(gd.name(w)))))

    def js_item(it):
        return {"skillpoints": it.skillpoints, "reqs": it.reqs, "set": it.set, "crafted": it.crafted}
    payload = [[[js_item(i) for i in eq], js_item(w)] for eq, w in cases]
    program = ("var sets = new Map(Object.entries(" + json.dumps(gd.sets) + "));"
               "JSON.stringify(" + json.dumps(payload) + """.map(([eq, w]) => {
                   const mk = (o) => { const m = new Map(Object.entries(o)); if (o.crafted) m.set("crafted", true);
                                       else m.delete("crafted"); if (!o.set) m.delete("set"); return m; };
                   const r = calculate_skillpoints(eq.map(mk), mk(w));
                   return {assigned: r[1], final: r[2], total: r[3], sets: Object.fromEntries(r[4])};
               }))""")
    js = run_js(js_dir, program)
    assert len(js) == len(cases)
    assert sum(bool(j["sets"]) for j in js) > 50              # set pieces really exercised
    assert sum(j["total"] > 150 for j in js) > 20             # hard cases included
    for (eq, w), j in zip(cases, js):
        r = calculate_skillpoints(eq, w, gd.sets)
        where = [(i.name, i.set, i.reqs, i.skillpoints) for i in eq + [w]]
        assert r.assigned == j["assigned"], where
        assert r.total_assigned == j["total"], where
        assert r.final == j["final"], where
        assert r.set_counts == j["sets"], where
