# Wynn Toolbox

**AI-assisted Wynncraft build toolkit.** Tell your AI assistant what you want
(a Stealing Summoner, a poison Mage with at least 15,000 HP) and it uses these
tools to search gear and ability trees, check every result against WynnBuilder's
rules, and hand you a working WynnBuilder link.

> **This is** a set of exact, tested tools that your AI assistant runs for you.
> The AI turns your goals into constraints and explains the results; the tools
> do the math.
>
> **This is NOT** a replacement for
> [WynnBuilder](https://wynnbuilder.github.io), or affiliated with Wynncraft or
> WynnBuilder.

## Getting started

**Install** (one line; no developer tools needed):

- **Windows** (PowerShell):
  ```powershell
  irm https://raw.githubusercontent.com/Hanker5/wynn-toolbox/main/install/install.ps1 | iex
  ```
- **macOS / Linux** (Terminal):
  ```bash
  curl -fsSL https://raw.githubusercontent.com/Hanker5/wynn-toolbox/main/install/install.sh | sh
  ```

The installer sets up Python (through [uv](https://docs.astral.sh/uv/)),
downloads WynnBuilder's data and adds a **Wynn Toolbox** shortcut (Start menu
and Desktop on Windows, apps menu or Desktop elsewhere) plus a `wynn-toolbox`
command. Wynn Toolbox checks GitHub for updates when it opens and asks whether
to **Update now** or **Ignore** (it asks again when something newer appears;
"Check for updates" in the sidebar looks any time). You can also run the
installer again. Either way your builds and settings are kept.

**First run.** Wynn Toolbox opens in its own window and asks which AI assistant
you want: **Claude Code**, **Codex** or **Gemini CLI** (or none). If it isn't
installed, "Install for me" runs the official installer in the built-in
terminal, where you can watch it. Then it starts the AI, which asks you to
sign in the first time.

From then on, opening Wynn Toolbox also starts your AI in the terminal panel.
To switch, click the **AI** button in the sidebar (or run
`wt config ai codex`).

Each AI comes set up for the toolbox: a shared `build` skill, a prompt hook
that tells it which build you have open, and (Claude Code, Gemini CLI)
permission to run `wt` without asking. Say yes when it asks whether to trust
the folder. Codex also asks you to approve new hooks once: type `/hooks` and
trust the Wynn Toolbox one.

**For developers** (from a clone):

```bash
git clone https://github.com/Hanker5/wynn-toolbox && cd wynn-toolbox
bin/wt-init            # installs uv + dependencies, fetches data, runs tests
uv run wt serve
```

## What the tools do

You normally don't type these yourself; your AI assistant runs them. They're
here so you can see what it's doing (and for developers):

```bash
uv run wt decode "<wynnbuilder link>"      # read and check any build
uv run wt gear examples/shaman-105-stealing.json --tree shaman-summoner
uv run wt damage builds/my-build.json      # spell/melee damage, effective HP
uv run wt compare builds/a.json builds/b.json
uv run wt tree mage-riftwalker --level 105
uv run wt craft --type ring --level 105 --maximize eSteal
uv run wt own add "Warp" --roll spd=180    # items you own, with real rolls
uv run wt upgrades examples/shaman-105-stealing.json
```

Run `uv run wt --help` (or `wt <command> --help`) for the full list.

- **Link codec**: decodes and encodes WynnBuilder links, including tomes, powders,
  aspects and the ability tree.
- **Gear solver**: an exact search (mixed-integer programming) over every usable
  item under your class, level, required Major IDs, minimums (HP, mana, regen,
  speed, elemental defences, final skill points, effective HP, DPS, spell
  damage), items to leave out, "at most one of these" groups and weapon
  constraints. Goals can be item stats or numbers WynnBuilder works out
  (effective HP, main-attack, puppet or summon DPS). When nothing fits, it says
  which requirements conflict. It can also re-search just some slots of an
  existing build (`wt gear --edit`), or save results as candidates to compare.
- **Trade-offs**: a few legal builds from max damage to max survival, side by
  side (`wt tradeoffs`).
- **Powders**: suggested weapon and armor powders for damage, health, balanced
  elemental defence or a powder-special playstyle (`wt powders`).
- **Damage**: WynnBuilder's right column (melee DPS, every spell's damage or
  healing, mana costs, effective HP, elemental defences), checked against the
  live WynnBuilder page and following the developer guide "How Damage Is
  Calculated - Fruma Edition", with powder specials to compare (the tools
  work out which one your powders give).
- **Compare**: two builds side by side: gear, totals, skill points, damage, HP.
- **Inventory and upgrades**: record the items and tomes you own (with their real
  rolls), build only from those, and rank which unowned item would help most.
- **Crafting**: exact crafted-item stats (checked against WynnBuilder's own code)
  and suggestions for the best ingredients and layout for a slot and goal, plus
  where each ingredient drops; the gear search can include crafted pieces.
- **Tree solver**: exact ability-tree optimization with WynnBuilder's activation
  rules, with a preset for every archetype.
- **Verifier**: skill points (negative bonuses included, and any set by hand),
  tree activation order, damage, and link round-trip. No link goes out without
  passing. Imported links are checked first, with notes on anything unusual.

## The web app

```bash
uv run wt serve              # opens the app in its own window
uv run wt serve --browser    # ...or in your browser, at http://127.0.0.1:8765
```

- **Its own window**: borderless, with its own title bar (drag it, double-click
  to maximize, F11 for full screen) and a close button that warns about
  unsaved edits. It remembers its size. Closing it quits the app. If the window
  can't open (no display, missing system libraries) the app opens in your
  browser instead.
- **Updates**: when GitHub has a newer version, the app lists what changed and
  offers Update now or Ignore. Updating closes the app, installs the new
  version and reopens it. Developer clones are told to `git pull` instead.
  `wt config check_updates off` turns the check off.
- **Builds**: open, edit and save builds with item search, tomes, a clickable
  ability tree, skill points you can set by hand, a powder planner and live
  re-checking. A Survivability panel shows effective HP, regen and every
  elemental defence, flags weaknesses and offers a fix. Changes the AI makes to
  the same files show up within a second.
- **New build from goals**: set what to maximize, your minimums and required
  Major IDs, then watch the search run with a progress bar, or show the
  damage-versus-survival trade-offs. Searches from a build (Improve, Fix) save
  candidates under it to compare, pick one and trash the rest.
- **Compare builds** and **Inventory** pages: two builds side by side, and the
  items and tomes you own.
- **Terminal panel**: a shell in the toolbox folder (PowerShell on Windows).
  Your chosen AI assistant starts in it when the app opens; the setup wizard
  (the sidebar's AI button) installs or switches it. The shell keeps running if
  you reload. Starting the app a second time just reopens the running one.
- **The AI sees what you see**: ask it about "this build" and it checks which
  build you have open (including edits you haven't saved). Builds it makes or
  changes appear in your list and open on screen, and it never overwrites a
  build you're in the middle of editing.

**Security:** the app only accepts connections from this computer, needs the
one-time token in the link `wt serve` prints, and the terminal only accepts
connections from the app's own page. The terminal is a real shell with your
permissions, so don't try to expose the app to other machines.

See `AGENTS.md` for the rules the AI follows and `knowledge/mechanics.md` for
what is proven, what was tested in game, and what is still unknown.

## Limits

- Item stats are 100% rolls; real items roll 30–130%.
- Damage follows WynnBuilder's model with its page defaults (no potions, raid
  buffs or powder specials unless you switch them on to compare; ability
  sliders at their defaults).
- Searches for damage goals and damage minimums are good but not proven the
  best (they say so); the exact search is proven best.
- Custom items and old-format (pre-binary) links are not supported yet.
- Game knowledge beyond WynnBuilder's data comes from player testing; see
  `knowledge/mechanics.md` for what has and hasn't been checked in game.

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for what's planned.

## Contributing

Bug reports, in-game test results and pull requests are all welcome. You don't
need to write code to help:

- **Found a wrong number or a bad link?** [Open an issue](https://github.com/Hanker5/wynn-toolbox/issues/new/choose)
  with the WynnBuilder link (or the build file) and what you expected.
- **Tested a mechanic in game?** Results that confirm or overturn an entry in
  `knowledge/mechanics.md` are valuable; the issue form asks for what you need.
- **Want to write code?** Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup,
  tests and how pull requests are reviewed. Items on the roadmap are a good
  place to start; say which one you're taking in an issue first so work isn't
  duplicated.

## Credits and license

Game data and the build-link format come from
[WynnBuilder](https://github.com/wynnbuilder/wynnbuilder.github.io) (GPL-3.0);
the link codec and formulas are ports of its source. Wynn Toolbox is therefore
also licensed under the **GNU GPL v3.0 or later** (see `LICENSE`).

The ability tree is drawn with a port of WynnBuilder's tree renderer (grid,
connector routing, highlight rules and "can take now" logic from
`js/builder/atree.js`). Item and ability-tree icons are WynnBuilder's images, downloaded into the local
cache by `wt fetch` rather than stored in this repository, since some are
derived from Wynncraft's own art. The web app's layout follows WynnBuilder's.

Structure inspired by
[canvas-toolbox](https://github.com/chaz-clark/canvas-toolbox).
