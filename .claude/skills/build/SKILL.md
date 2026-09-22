---
name: build
description: Make, compare or adjust a Wynncraft build with the wt tools. Use when a player asks for a build, wants to compare weapons or items, or wants their current build changed ("this build"). Produces verified WynnBuilder links saved to the player's build list.
---

# Build

Follow AGENTS.md throughout: its rules and assumptions bind every step. The
steps below are the procedure.

Commands are written as `wt ...`, which works in the web app's terminal (the
toolbox's `wt` is first on PATH there). Elsewhere, run `uv run wt ...` from the
repo root. In a sandbox where `uv run` fails with a read-only file system
error (Codex's), use `wt` or `.venv/bin/wt` (Windows: `.venv\Scripts\wt.exe`).

## 1. Find out what they want

If they mean the build open in the web app ("this build", "my current build"),
run `wt current` first. If they have a WynnBuilder link, decode it. Either
tells you class, level and gear without asking:

    wt decode "<link>"

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
slot, `wt craft --type <slot> --level N --maximize <stat>` shows the best
crafts with their ingredient grid, a WynnBuilder crafter link, and which mobs
drop each ingredient and where (`wt ingredient <name>` for all spots).
Mention when an ingredient has no listed mob.

Use one objective stat unless the player asked for more. A tiny tiebreaker
weight (0.01) on a second stat is fine. Put hard requirements in floors,
`require_major`, `force`, `exclude` or `exclude_tiers`; never trade them away
silently.

## 3. Pick a tree preset

`wt tree <preset> --level N` lists what a preset selects. There is one
generic preset per archetype for every class: `<class>-<archetype>`, e.g.
`archer-boltslinger`, `assassin-shadestepper`, `warrior-battle-monk`,
`mage-arcanist`, `shaman-ritualist` (`wt tree --help` lists all). Each takes
the class's four spells, then as many nodes of that archetype as fit, all
valued the same. They ignore damage, utility and the other archetypes, and
may leave points unspent; say so, and suggest the player finish the tree in
the editor.

Say what the preset's weights favor, especially an archetype it ignores. If
the player's goal needs a different tree, change that build's tree (the
editor, or `tree` in the build file, then `wt link --write`) rather than adding
a preset: presets are shared by every player, so they stay generic. Say that
the changes are a judgment call.

## 4. Run, save and verify

    wt gear builds/specs/<name>.json --tree <preset> \
        --save builds/<name>.json --name "<readable name>"

Always pass `--save`: it puts the build in the app's list and opens it there.
The search is exact over every usable item (it says so). With a damage floor it
falls back to per-slot shortlists; add `--confirm` then, and call the result
best within the shortlists. It prints the build, totals and a link, and says
`VERIFIED OK` or lists problems. Never pass on a link without `VERIFIED OK`
(`wt verify <link>` checks any link). Never work out totals yourself.

To change a saved build (swap an item, add a tome), use
`wt edit builds/<name>.json --item helmet="Name"` (add
`--save-as builds/<new>.json` to keep the original). If `wt current` reports
unsaved edits in the page, ask the player to Save or Revert first. For fields
`wt edit` doesn't cover, edit the file's editable fields by hand, then
`wt link builds/<name>.json --write` to re-check it.

## 5. When goals compete, show the trade-off

Run the spec at 2–4 values of the contested floor (e.g. HP 14k / 17k / 20k) and
present a short table: floor, goal stat, HP, mana regen, skill points. Point
out cliffs where one step costs much more than the last.

For weapon comparisons, force each candidate weapon with the same spec and
compare with `wt damage <link>` (spell and melee damage, effective HP), or
`wt compare <a> <b>` for two saved builds. When a player wants to keep a
spell's damage up while maximizing something else, add
`"floors": {"damage": {"<spell name>": N}}` and pass `--tree PRESET`. Quote
damage at typical rolls unless comparing with the WynnBuilder page (`--perfect`).
Poison is per second (`floor(poison / 3)`), not per hit.

## 6. Present

- The link, a table of the 9 items, and the key totals.
- Which file you saved, so the player can find it in the list.
- The objective you used, and the assumptions from AGENTS.md rule 3, in two or
  three lines.
- Anything the result depends on that is only tested or unknown per
  `knowledge/mechanics.md`.
- When developing the toolbox (not for players): add keeper links to
  `tests/fixtures/links.json`.
