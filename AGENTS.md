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

**This is NOT**: a damage calculator (spell damage is not ported yet), a
replacement for WynnBuilder, or a source of game facts beyond what its data and
player testing support.

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
   - **Aspects are empty.**
   - Tomes are **goals to collect** unless the player said they own them.
   - WynnBuilder's page shows **perfect (130%) rolls**; say which one you quote.
   - Crafted items are **ranges**; the middle counts as typical. Mention that
     ingredients have to be collected.

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
| `wt tree <preset> [--level N]` | Solve an ability tree from a preset. |
| `wt craft --type ring --level 105 --maximize eSteal` | Suggest the best crafted item (ingredients and layout) for a slot. |
| `wt serve` | Start the local web app (this computer only) with the build editor and a terminal panel. |

## Build files are the shared record

Player builds live in `builds/*.json` (ignored by git). The player edits them in
the web app, you edit them with `wt` or by hand; both see the same file. Format:
`wynntools/buildfile.py`. Edit only the editable fields (`name`, `notes`,
`level`, `equipment`, `tomes`, `tree`, `powders`, `skillpoints`); `link` and
`status` are generated, so run `wt link <file> --write` after any edit.

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
- Every bug fix gets a regression test in `tests/`. Every link handed out
  should be added to `tests/fixtures/links.json` so it keeps round-tripping.
- Keep commits small and messages specific.
