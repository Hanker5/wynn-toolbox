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

8. **Save every build you present.** Pass `--save builds/<name>.json` to
   `wt gear` (and use `wt import` or `wt edit --save-as` for links and variants;
   `wt gear --edit` and `wt edit` write changes back into the existing file).
   A build that only exists in your terminal output never reaches the player's
   build list. For trade-off tables, save the option the player picks, or each
   row if they want to compare them in the app.

9. **Know which search ran.** `wt gear` is exact by default: the best build over
   every usable item, under the spec and the stated assumptions (100% rolls,
   automatic skill points). With damage floors, or `--shortlists`, it searches
   per-slot shortlists instead, which can miss the best build; then run
   `--confirm` and say the result is best-within-shortlists.

---

## Commands

Run commands from the repo root. In the web app's terminal, plain `wt ...`
works (the toolbox's `wt` is first on PATH there) and is the fastest. Elsewhere,
use `uv run wt ...`. **Sandboxed agents** (Codex): `uv run` fails inside the
sandbox ("Read-only file system" on uv's cache), so use `wt`, or `.venv/bin/wt`
(Windows: `.venv\Scripts\wt.exe`) outside the app. All `wt` commands work in
the sandbox, including the ones that talk to the web app.

| Command | What it does |
|---|---|
| `wt fetch [--refresh]` | Download WynnBuilder data into `data/<version>/`. Refresh after a game patch. |
| `wt decode <link or build file>` / `wt verify ...` | Decode, total up and check. Exit 1 on any problem. |
| `wt gear <spec.json> [--tree PRESET] --save builds/x.json` | Exact gear search (MILP over every usable item), optionally solve the tree, print a verified link, save a build file and open it in the app. `--shortlists [--confirm]` uses the older per-slot search (automatic with damage floors). |
| `wt gear --edit builds/x.json [spec.json] [--change SLOTS \| --keep SLOTS] [--save-as builds/y.json]` | Re-search an existing build in place: only the `--change` slots (or all but the `--keep` ones), with the given spec or the one the build was made with. Keeps its name, notes, tree, aspects and powders on unchanged items, and prints what changed. |
| `wt import <link> builds/x.json` | Save any WynnBuilder link as a build file. |
| `wt link builds/x.json [--write]` | Re-check a build file after edits; `--write` updates its link and status. |
| `wt current` | What the player is looking at in the web app: the build file, its full report and link, and any **unsaved** edits in the page. |
| `wt builds` | List the build files (the app's sidebar); `▶` marks the one open in the app. |
| `wt show builds/x.json` | Open a build in the player's web app. |
| `wt edit builds/x.json --item helmet="Name" --tome armorTome1="Name" --level N --name ... --tree-preset P [--save-as builds/y.json]` | Change a build file safely (checks names and slots), re-check it, and open it in the app. `--save-as` makes a variant and leaves the original alone. |
| `wt damage <link or build file> [--perfect] [--parts]` | WynnBuilder's right column: melee DPS, every spell's damage or healing, mana costs, effective HP. Typical rolls by default; `--perfect` matches the WynnBuilder page. |
| `wt compare <a> <b> [--perfect]` | Two builds (links or files) side by side: gear, totals, skill points, spell damage, effective HP. The web app's "Compare builds" page shows the same. |
| `wt tree <preset> [--level N]` | Solve an ability tree from a preset. Every class has a generic preset per archetype (`archer-boltslinger`, `warrior-paladin`, `mage-riftwalker`, ...); none is tuned for a particular goal. |
| `wt craft --type ring --level 105 --maximize eSteal` | Suggest the best crafted item (ingredients and layout) for a slot. |
| `wt ingredient "Stolen Pearls"` | Which mobs drop an ingredient and where (x, y, z). `wt craft` lists this for every suggested ingredient. |
| `wt own add\|remove\|list [NAME] [--tome] [--roll ID=VALUE]` | Edit the player's inventory (`builds/inventory.json`): owned items, tomes and real roll values. |
| `wt gear spec.json --tree PRESET` with `"floors": {"damage": {"Ophanim": 15000}}` | Damage minimums: a spell's headline number (melee: average DPS), checked exactly on every candidate with the preset's tree. |
| `wt gear spec.json --owned` | Build only from owned items (empty slots allowed, except the weapon). Owned items use their real rolls. |
| `wt upgrades spec.json` | Rank unowned items by how much each one alone would improve the best owned build. |
| `wt serve [--browser\|--no-browser]` | Start the local web app (this computer only) with the build editor and a terminal panel, in its own borderless window (`--browser`: a browser tab; `--no-browser`: open nothing). |
| `wt config [ai [claude\|codex\|gemini\|shell\|none]]` / `wt config check_updates on\|off` | Show or change the AI assistant the web app starts in its terminal, or turn the update check off (`builds/settings.json`). |
| `wt update [--check]` | Is a newer Wynn Toolbox on GitHub? Without `--check`, install it (only while the app is closed; in the app the player uses its Update button). |

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

`builds/settings.json` (app settings, including the window size and an ignored
update) and `builds/.server.json` (the running server's address) are not builds
either; change settings with `wt config`. `builds/.update.json`,
`builds/update.log` and `builds/app.log` belong to the app too.

**Never write a `wt gear`/`wt upgrades` spec.json into `builds/`.** It's a
search input, not a build — the web app's sidebar globs every `builds/*.json`
and shows anything it can't parse as a build as "can't read file". Write spec
files to your scratchpad/temp directory (or wherever you're already running
commands from) and pass that path to `wt gear`; only pass `builds/...` for
`--save`, `--save-as` and the build file itself.

Deleting a build in the app (the editor's Delete button) moves it into
`builds/.trash/` with a timestamp; it isn't listed any more but can be
restored. Don't delete a player's build unless they ask; if they do, move it
there too rather than erasing it.

The page mirrors WynnBuilder's layout (equipment grid with item icons, element
colours, a drawn ability tree), so players can read it the way they read
WynnBuilder. Its Summary has a Typical/Perfect toggle; "Perfect" matches the
numbers WynnBuilder shows.

## Inside the web app

You are probably running in the web app's terminal panel (the environment
variable `WYNN_TOOLBOX=1` is set there), with the player watching the page.

- Claude Code, Codex and Gemini CLI get a one-line note with each message
  naming the build the player has open (a prompt hook: `.claude/settings.json`,
  `.codex/hooks.json`, `.gemini/settings.json`). It names the file only.
- **"This build", "the current build", "my build"** means the one open in the
  page. Run `uv run wt current` to find out which file it is and what's in it,
  before answering or editing. Don't guess from the file list. Run it again when
  the player may have switched builds since you last looked.
- If `wt current` says the build has **unsaved edits**, its numbers include
  them, but the file doesn't. Ask the player to press Save (or Revert) before
  you change the file; `wt edit` and `wt link --write` refuse until they do.
- **Builds you make belong in the list on the left.** `wt gear --save`,
  `wt import` and `wt edit` write to `builds/` and open the build in the page
  automatically; `wt show` opens any other one. The page
  never throws away the player's unsaved edits for this: it tells them instead.
- When the player wants their build changed or improved, change **that file**
  instead of making a new build: `wt edit` for a named change,
  `wt gear --edit` to search for a better one. Use `--save-as` only when they
  want to keep the original. If you edit the JSON by hand, run
  `wt link <file> --write` afterwards. The page reloads within a second.
- Tell the player which file you changed or created.
- Any `wt` command that runs longer than a second shows a progress bar above
  the terminal (with a percentage where the search knows one), so the player
  can see a long search is still working.

## Skills

| Skill | Use it when |
|---|---|
| `build` | A player wants a new build, a weapon comparison, or a change to one. |

The skill lives in `.claude/skills/build/` (Claude Code) and
`.agents/skills/build/` (Codex, Gemini CLI). The two files must stay identical;
a test checks it.

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
