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
command. To update, run it again: your builds and settings are kept.

**First run.** Wynn Toolbox opens in your browser and asks which AI assistant
you want: **Claude Code**, **Codex** or **Gemini CLI** (or none). If it isn't
installed, "Install for me" runs the official installer in the built-in
terminal, where you can watch it. Then it starts the AI, which asks you to
sign in the first time.

From then on, opening Wynn Toolbox also starts your AI in the terminal panel.
To switch, click the **AI** button in the sidebar (or run
`wt config ai codex`).

**For developers** (from a clone):

```bash
git clone https://github.com/Hanker5/wynn-toolbox && cd wynn-toolbox
bin/wt-init            # installs uv + dependencies, fetches data, runs tests
uv run wt serve
```

## What the tools do

```bash
uv run wt decode "<wynnbuilder link>"      # read and check any build
uv run wt gear examples/shaman-105-stealing.json --tree summoner-stealing
uv run wt tree mage-poison-riftwalker --level 105
uv run wt craft --type ring --level 105 --maximize eSteal
```

- **Link codec**: decodes and encodes WynnBuilder links, including tomes and the
  ability tree.
- **Gear solver**: searches the item database under your class, level, required
  Major IDs, minimum HP/mana/regen/speed, and weapon constraints.
- **Crafting**: exact crafted-item stats (checked against WynnBuilder's own code)
  and suggestions for the best ingredients and layout for a slot and goal;
  the gear search can include crafted pieces.
- **Tree solver**: exact ability-tree optimization with WynnBuilder's activation
  rules.
- **Verifier**: skill points (negative bonuses included), tree activation order,
  and link round-trip. No link goes out without passing.

## The web app

```bash
uv run wt serve        # opens http://127.0.0.1:8765 in your browser
```

- **Builds**: open, edit and save builds with item search, tomes, a clickable
  ability tree and live re-checking. Changes the AI makes to the same files show
  up within a second.
- **New build from goals**: set what to maximize, your minimums and required
  Major IDs, then watch the search run with a progress bar.
- **Terminal panel**: a shell in the toolbox folder (PowerShell on Windows).
  Your chosen AI assistant starts in it when the app opens; the setup wizard
  (the sidebar's AI button) installs or switches it. The shell keeps running if
  you reload. Starting the app a second time just reopens the running one.

**Security:** the app only accepts connections from this computer, needs the
one-time token in the link `wt serve` prints, and the terminal only accepts
connections from the app's own page. The terminal is a real shell with your
permissions, so don't try to expose the app to other machines.

See `AGENTS.md` for the rules the AI follows and `knowledge/mechanics.md` for
what is proven, what was tested in game, and what is still unknown.

## Limits

- Item stats are 100% rolls; real items roll 30–130%.
- Damage follows WynnBuilder's model with its page defaults (no potions, raid
  buffs or powder specials; ability sliders at their defaults).
- Custom items and old-format links are not supported yet.

See `docs/ROADMAP.md`.

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
