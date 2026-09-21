# Plan: next features (agreed 2026-09-21)

Worked in this order. Each step ships with tests; anything ported from
WynnBuilder is checked against WynnBuilder's own JavaScript with the QuickJS
differential harness (`tests/js/`, `pytest -m differential`).

## 1. Set bonuses and WynnBuilder's exact skill-point calculation  (correctness) — DONE
**Why.** Set bonuses are ignored today (a 4-piece Cosmic Foundations set gives
+1,500 HP, +15 to all skills, +24 mana steal). Researching them showed our
skill-point model also differs from WynnBuilder's `calculate_skillpoints`:
- items are equipped one at a time in the best order found; a bonus only helps
  items equipped after it;
- the weapon (and crafted items) are equipped last, so their bonuses never help
  other requirements; the guild tome is part of the equip order;
- the "pop" rule: an item whose requirement is met only by its own bonus falls
  off, so points are added to prevent it;
- set bonuses add skill points to the build's totals afterwards, never toward
  requirements; their other stats are added to the build.

**Work.** Port `calculate_skillpoints` (+ helpers) and the set-bonus stat step
of `Build.initBuildStats`. Use them in the verifier, build files, web app and
gear search (set bonuses in the objective, floors and pruning bounds). Show
active set bonuses in the UI. Re-check every saved link.

**Done when.** Differential test matches WynnBuilder on hundreds of random
equipment sets (applied points, final points, active sets); all session links
re-verified; the corrected numbers for the original Cosmic Foundations build
reported.

## 2. Owned items and an upgrade shopping list — DONE
**Work.** An inventory file (`builds/inventory.json`) listing owned items and
tomes, optionally with real roll values. Gear search option "owned only" and an
"upgrades" report: for each missing item, how much it improves the goal if
added (search re-run with that one item allowed), ranked. Inventory editing in
the web app (mark owned from the item card / slot), rolls respected in totals.

**Done when.** A spec can be solved with `owned_only`; the upgrade ranking
reproduces a hand-checked example; UI test covers marking an item owned.

## 3. Damage calculations — DONE
`wynntools/damage.py`; `wt damage`; build status and the editor's Damage panel;
`floors.damage` in the gear solver. `-m live` compares every stat, spell part,
cost and defence number with the real WynnBuilder page for the 11 session links
and seeded random builds of all five classes (125 random builds matched too).
**Work.** Port WynnBuilder's damage path: `damage_calc.js`
(`calculateSpellDamage`), the ability-tree spell merging from `atree.js`, and
the stats it needs (skill-point damage multipliers, powders, attack speed).
Show per-spell / per-summon DPS and effective HP like WynnBuilder's right
column; add DPS as a solver objective or floor.

**Done when.** Differential tests match WynnBuilder's spell damage numbers for
the session builds (all classes represented) within rounding.

## 4. Powders and aspects in the editor — DONE
Powder boxes on the five powderable slots, an Aspects panel, `aspects` in build
files, armor powders and ability-tree bonuses in the Summary totals.
`-m live` types powders and an aspect into WynnBuilder's own inputs for every
class; the link it writes round-trips and all totals and damage match.
**Work.** Powder slots on powderable items (the codec already encodes them) and
powder effects on stats/damage; aspect picker per class with tiers (codec
supports aspects), aspect effects applied.

**Done when.** Links with powders/aspects made in WynnBuilder round-trip and
show the same totals.

## 5. Where to get crafting ingredients — DONE
`wt ingredient`, sources under every `wt craft` suggestion, and a "where to get
them" list in the editor's craft helper, from WynnBuilder's `droppedBy` data.
**Work.** Show `droppedBy` mobs (and coordinates when known) in the crafting
helper and `wt craft`; flag ingredients with no known source.

## 6. Smaller items
- Compare two builds side by side with differences highlighted.
- Exact gear search as a MILP (replaces shortlists).
- Publish to GitHub (waiting on the personal-account login).
