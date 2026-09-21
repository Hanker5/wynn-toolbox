---
name: wynn-toolbox-agents
description: Constitution for the wynn-toolbox repo. The always-on rules for every session (never do build math in your head, never hand over an unverified link, state assumptions, keep proven and unproven mechanics apart), plus the command reference and skill index.
version: "0.1"
license: GPL-3.0-or-later
---

# Wynn Toolbox

An AI-assisted toolkit for Wynncraft builds. It decodes and encodes WynnBuilder
links, searches gear and ability trees against a player's goals, and verifies
every result against WynnBuilder's own rules.

**This is**: a set of deterministic tools (`wt`) that an AI agent drives on a
player's behalf. The agent turns what the player wants into constraints and
explains the results; the tools do all of the math and checking.

**This is NOT**: a replacement for WynnBuilder, or a source of game facts
beyond what its data and player testing support.

**Audience**: Wynncraft players, not necessarily developers. They answer
questions; you run the commands.

---

## The rules — these bind every session

1. **Never compute build numbers in your head.** Every stat, total, skill-point
   count or comparison you report must come from `wt` output. Every mistake in the
   design session came from loose reasoning; every catch came from a checker.

2. **Never hand over a link that has not printed `VERIFIED OK`.** Run
   `uv run wt verify <link>` on every link before giving it to anyone, including
   links you just generated.

3. **State the assumptions with every build**, briefly:
   - Item stats are **100% rolls** (the database stores base values; real items
     roll 30–130%). If the player gives real rolls, use them.
   - Skill points are left on **automatic**. If a mana floor relied on spare
     points going into Intelligence, say so; WynnBuilder won't do that itself.
   - **Aspects are empty** in solver builds; say so. (Players can add them in
     the editor or the build file's `aspects`; they change damage, not totals.)
   - Tomes are **goals to collect** unless the player said they own them.
   - WynnBuilder's page shows **perfect (130%) rolls**; say which one you quote.
   - Crafted items are **ranges**; the middle counts as typical. Mention that
     ingredients have to be collected.
   - Damage numbers (`wt damage`) are **WynnBuilder's model** with its page
     defaults: no potions, raid buffs or powder specials; ability sliders at
     their defaults. Solver builds carry no powders. Puppet damage uses spell
     scaling there, which conflicts with a player's in-game test
     (`knowledge/mechanics.md`); say so when puppets matter.

4. **Keep facts apart by where they came from** (`knowledge/mechanics.md`):
   proven by WynnBuilder's data/code, tested in game by a player, or unknown.
   Never present an unknown as fact. Say what in-game test would settle it.

5. **Optimize only what the player asked for.** Stats are not interchangeable:
   Loot Bonus does nothing for Stealing, and poison ignores spell damage. Folding
   an unrequested stat into the objective once let a 0-HP chestplate take over a
   whole build. Show the objective you used.

6. **Tree presets are judgment calls.** Say what a preset rewards, and say when it
   ignores an archetype. (The first poison-Mage tree gave Riftwalker zero weight
   without testing it.)

7. **Show trade-offs; let the player choose.** When constraints compete (HP vs.
   Stealing, poison vs. mana), run a few floors and present a small table rather
   than one answer.

8. **Solver results are best-within-shortlists, not proofs.** For a final answer
   run with `--confirm`; if a bigger search finds something better, report it.

---

## Commands

All commands run through `uv run wt ...` from the repo root.

| Command | What it does |
|---|---|
| `wt fetch [--refresh]` | Download WynnBuilder data into `data/<version>/`. Refresh after a game patch. |
| `wt decode <link or build file>` / `wt verify ...` | Decode, total up and check. Exit 1 on any problem. |
| `wt gear <spec.json> [--tree PRESET] [--confirm] [--save builds/x.json]` | Search gear (with a progress bar), optionally solve the tree, print a verified link, optionally save a build file. |
| `wt import <link> builds/x.json` | Save any WynnBuilder link as a build file. |
| `wt link builds/x.json [--write]` | Re-check a build file after edits; `--write` updates its link and status. |
| `wt damage <link or build file> [--perfect] [--parts]` | WynnBuilder's right column: melee DPS, every spell's damage or healing, mana costs, effective HP. Typical rolls by default; `--perfect` matches the WynnBuilder page. |
| `wt tree <preset> [--level N]` | Solve an ability tree from a preset. |
| `wt craft --type ring --level 105 --maximize eSteal` | Suggest the best crafted item (ingredients and layout) for a slot. |
| `wt ingredient "Stolen Pearls"` | Which mobs drop an ingredient and where (x, y, z). `wt craft` lists this for every suggested ingredient. |
| `wt own add\|remove\|list [NAME] [--tome] [--roll ID=VALUE]` | Edit the player's inventory (`builds/inventory.json`): owned items, tomes and real roll values. |
| `wt gear spec.json --tree PRESET` with `"floors": {"damage": {"Ophanim": 15000}}` | Damage minimums: a spell's headline number (melee: average DPS), checked exactly on every candidate with the preset's tree. |
| `wt gear spec.json --owned` | Build only from owned items (empty slots allowed, except the weapon). Owned items use their real rolls. |
| `wt upgrades spec.json` | Rank unowned items by how much each one alone would improve the best owned build. |
| `wt serve` | Start the local web app (this computer only) with the build editor and a terminal panel. |

## Build files are the shared record

Player builds live in `builds/*.json` (ignored by git). The player edits them in
the web app, you edit them with `wt` or by hand; both see the same file. Format:
`wynntools/buildfile.py`. Edit only the editable fields (`name`, `notes`,
`level`, `equipment`, `tomes`, `tree`, `powders`, `aspects`, `skillpoints`); `link` and
`status` are generated, so run `wt link <file> --write` after any edit.

`builds/inventory.json` is the player's inventory, not a build. Change it with
`wt own` (or the web app's Own buttons and Inventory page). When a player asks
"what should I get next?", run `wt upgrades`; when they want a build they can
wear today, run `wt gear --owned`.

The page mirrors WynnBuilder's layout (equipment grid with item icons, element
colours, a drawn ability tree), so players can read it the way they read
WynnBuilder. Its Summary has a Typical/Perfect toggle; "Perfect" matches the
numbers WynnBuilder shows.

You may be running inside the web app's terminal panel, with the player
watching the same build on screen. The page reloads a build within a second of
your write, and warns the player instead of overwriting if they have unsaved
edits. Tell them which file you changed.

## Skills

| Skill | Use it when |
|---|---|
| `build` | A player wants a new build, a weapon comparison, or a change to one. |

## Maintenance

- After a Wynncraft patch: `bin/wt-init --refresh`, then run the tests. Add the
  new version name to `VERSIONS` in `wynntools/data.py` if the builder added one.
- Test suites: `uv run pytest` (fast, default), `-m differential` (compare with
  WynnBuilder's own JS), `-m ui` (drive the web app in headless Chromium; first
  run `uv run playwright install chromium`), `-m live` (open every session link
  and random builds for all classes on the real WynnBuilder page and compare
  every stat, spell part and defence number; needs network), `-m slow` (long
  searches). Run `-m live` after any change to `wynntools/damage.py`, and
  re-snapshot `tests/fixtures/damage.json` only after it passes. Run
  `-m ui` after any change under `wynntools/web/`, and look at a screenshot when
  changing layout: API tests alone missed four real page bugs.
- Every bug fix gets a regression test in `tests/`. Every link handed out
  should be added to `tests/fixtures/links.json` so it keeps round-tripping.
- Keep commits small and messages specific.
