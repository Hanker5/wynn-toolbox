# Wynn Toolbox

**AI-assisted Wynncraft build toolkit.** Tell your AI assistant what you want
(a Stealing Summoner, a poison Mage with at least 15,000 HP) and it uses these
tools to search gear and ability trees, check every result against WynnBuilder's
rules, and hand you a working WynnBuilder link.

> **This is** a set of exact, tested tools that your AI assistant runs for you.
> The AI turns your goals into constraints and explains the results; the tools
> do the math.
>
> **This is NOT** a damage calculator, a replacement for
> [WynnBuilder](https://wynnbuilder.github.io), or affiliated with Wynncraft or
> WynnBuilder.

## Getting started

Open an empty folder in an editor with an AI assistant (for example VS Code
with Claude Code) and paste:

> *"Clone https://github.com/<you>/wynn-toolbox into this folder, run
> `bin/wt-init`, and then help me make a Wynncraft build."*

Or by hand:

```bash
git clone <repo-url> wynn-toolbox && cd wynn-toolbox
bin/wt-init            # installs uv + dependencies, fetches data, runs tests
```

## What the tools do

```bash
uv run wt decode "<wynnbuilder link>"      # read and check any build
uv run wt gear examples/shaman-105-stealing.json --tree summoner-stealing --confirm
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
- **Terminal panel**: a shell in the toolbox folder with one-click buttons for
  Claude Code, Codex or Gemini CLI (whichever are installed). Log in and use your
  AI assistant right next to your builds. The shell keeps running if you reload.

**Security:** the app only accepts connections from this computer, needs the
one-time token in the link `wt serve` prints, and the terminal only accepts
connections from the app's own page. The terminal is a real shell with your
permissions, so don't try to expose the app to other machines.

See `AGENTS.md` for the rules the AI follows and `knowledge/mechanics.md` for
what is proven, what was tested in game, and what is still unknown.

## Limits

- Item stats are 100% rolls; real items roll 30–130%.
- Spell damage is not calculated yet.
- Custom items and old-format links are not supported yet.

See `docs/ROADMAP.md`.

## Credits and license

Game data and the build-link format come from
[WynnBuilder](https://github.com/wynnbuilder/wynnbuilder.github.io) (GPL-3.0);
the link codec and formulas are ports of its source. Wynn Toolbox is therefore
also licensed under the **GNU GPL v3.0 or later** (see `LICENSE`).

Item and ability-tree icons are WynnBuilder's images, downloaded into the local
cache by `wt fetch` rather than stored in this repository, since some are
derived from Wynncraft's own art. The web app's layout follows WynnBuilder's.

Structure inspired by
[canvas-toolbox](https://github.com/chaz-clark/canvas-toolbox).
