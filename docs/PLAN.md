# Plan: next features (agreed 2026-09-30)

Worked in this order, one at a time. Each step ships with tests.

## 1. Survive game patches without a release  (reliability) — DONE
**Why.** The list of WynnBuilder versions was typed into `wynntools/data.py`. A
link made after a patch carries a version number the toolbox doesn't know, so
every import failed ("it isn't a WynnBuilder build link") until a new release
was installed.

**Work.** Read the version list from WynnBuilder's `js/load_item.js` (at
`wt fetch`, at most twice a day otherwise, and at once when a link names an
unknown version); keep the built-in list as the offline fallback. Say plainly
when a link is newer than the data and can't be updated. A scheduled CI run
refreshes the data, runs the fast and differential suites and flags a
built-in list that has fallen behind.

**Done when.** A link with the next version number decodes after the list
grows, without a code change; offline, it gets a clear message; the
scheduled workflow runs.

## 2. Read links made with older data  (reach)
**Why.** Links shared on Discord, forums and videos are often a patch or two
old; anything but the latest version is refused.

**Work.** Decode with that version's encoding constants (already stored per
version) and resolve items with the current data (ids are stable; `remapID`
redirects retired ones). Say which items changed since, if any. Legacy
(pre-binary) links and custom items stay out of scope.

**Done when.** Links from at least three older versions import, with the
changed items reported; the session links keep verifying after a patch.

## 3. Aspects in the search  (damage accuracy)
**Why.** New builds carry empty aspects, and aspects change endgame damage a
lot, so damage searches can rank gear for a build nobody will play.
`wt aspects --recommend` ranks aspects for a finished build only.

**Work.** Let the local search fill aspect slots (from owned aspects at their
tier, or any), alongside gear, for damage-model goals; save them in the build.

**Done when.** A damage search with owned aspects beats "search gear, then
recommend aspects" on the session specs, or ties them.

## 4. Local AI models, measured first  (audience)
**Why.** A paid AI account is the main barrier for players. Weaker models are
most likely to break rules 1 and 2 (numbers from `wt` only, verified links only).

**Work.** First an evaluation: a set of player requests, checking each reply
went through `wt verify` and quoted only numbers from `wt` output. Run it on
the current assistants (it doubles as a regression test for the build skill),
then on local models. Only then the setup-wizard and `wt config ai` choice.

**Done when.** The evaluation runs; a local model is offered only if it passes.

---

# Earlier plan (agreed 2026-09-21) — all done

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
- DONE: Compare two builds side by side with differences highlighted
  (`wt compare`, "Compare builds" page).
- DONE: Exact gear search as a MILP (`wynntools/gear_milp.py`), now the default.
  Skill points are a relaxation that can't cut a valid build, then checked with
  WynnBuilder's exact rules and cut until one passes. On 12 random specs it beat
  the shortlists 9 times (up to 6%) and tied 3; it ties every session spec.
  Damage floors stay on the shortlist search (too many near-ties to cut one by one).
- DONE: Publish to GitHub (`Hanker5/wynn-toolbox`).
