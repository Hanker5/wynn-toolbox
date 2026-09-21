---
name: build
description: Make, compare or adjust a Wynncraft build with the wt tools. Use when a player asks for a build, wants to compare weapons or items, or wants an existing build changed. Produces verified WynnBuilder links.
---

# Build

Follow AGENTS.md throughout. The steps below are the procedure.

## 1. Find out what they want

If they have a current WynnBuilder link, decode it first. It tells you class,
level and gear without asking:

    uv run wt decode "<link>"

Then collect only what is still missing:

- **Class and level.** Max build level is 121.
- **The goal**, in stat terms. Map words to stats with `knowledge/mechanics.md`,
  and confirm when a word is ambiguous (e.g. "greed" is a Major ID, "stealing" is
  the `eSteal` stat; "loot" could mean either Stealing or Loot Bonus).
- **Hard requirements**: Major IDs they must have (`require_major`), minimum HP,
  max mana, mana regen, walk speed.
- **Weapon situation**: a weapon they must use (`force`), items they can't get
  (`exclude`), or "no mythics" (`exclude_tiers`).
- **Tomes**: which they own, or whether to plan for aspirational ones.

## 2. Write the spec

Create `builds/specs/<name>.json`. Start from `examples/`. Fields:

    class, level, objective {stat: weight}, floors {hp, mr, spd, mana, weapon_dps},
    require_major [...], force {slot: item}, exclude [...], exclude_tiers [...],
    tomes [14 tome names or null, in slot order], topn

Tome slot order: weapon ×2, armor ×4, guild, lootrun, gatherXp ×2, dungeonXp ×2,
mobXp ×2. Floors include tome stats and base HP.

Set `"crafted": true` to let the search use crafted gear. It often wins for
niche stats (Stealing, for one) and costs little search time. Ask first if the
player doesn't craft, since crafts need ingredients they must collect. For one
slot, `uv run wt craft --type <slot> --level N --maximize <stat>` shows the best
crafts with their ingredient grid and a WynnBuilder crafter link.

Use one objective stat unless the player asked for more. A tiny tiebreaker
weight (0.01) on a second stat is fine.

## 3. Pick a tree preset

`uv run wt tree <preset> --level N` lists what a preset selects. Current presets:
`summoner-stealing`, `mage-poison-lightbender`, `mage-poison-riftwalker`.

If none fits, add one to `wynntools/presets.py` with an `about` string that says
what it rewards and why, and tell the player it is a judgment call.

## 4. Run and verify

    uv run wt gear builds/specs/<name>.json --tree <preset> --confirm \
        --save builds/<name>.json --name "<readable name>"

This shows a progress bar, prints the build, totals and a link, says
`VERIFIED OK` or lists problems, and saves a build file the player can open in
the web app. Never pass on a link without `VERIFIED OK`.

To change a saved build (swap an item, add a tome), edit the file's editable
fields, then `uv run wt link builds/<name>.json --write` to re-check it.

## 5. When goals compete, show the trade-off

Run the spec at 2–4 values of the contested floor (e.g. HP 14k / 17k / 20k) and
present a short table: floor, goal stat, HP, mana regen, skill points. Point
out cliffs where one step costs much more than the last.

For weapon comparisons, force each candidate weapon with the same spec and
compare with `uv run wt damage <link>` (spell and melee damage, effective HP).
When a player wants to keep a spell's damage up while maximizing something else,
add `"floors": {"damage": {"<spell name>": N}}` and pass `--tree PRESET`. Quote
damage at typical rolls unless comparing with the WynnBuilder page (`--perfect`).
Poison is per second (`floor(poison / 3)`), not per hit.

## 6. Present

- The link, a table of the 9 items, and the key totals.
- The assumptions from AGENTS.md rule 3, in two or three lines.
- Anything the result depends on that is only tested or unknown per
  `knowledge/mechanics.md`.
- Add the link to `tests/fixtures/links.json` if it is a keeper.
