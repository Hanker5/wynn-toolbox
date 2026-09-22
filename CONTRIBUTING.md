# Contributing to Wynn Toolbox

Thanks for helping. Wynn Toolbox is only useful if its numbers are right, so
most of this guide is about keeping them right.

## Ways to help

- **Report a bug.** Use the [bug report form](https://github.com/Hanker5/wynn-toolbox/issues/new/choose).
  Include the WynnBuilder link or build file, the command you (or your AI) ran,
  and what you expected. If a number disagrees with WynnBuilder, say whether you
  compared typical or perfect rolls.
- **Share an in-game test.** `knowledge/mechanics.md` separates what is
  **proven** (WynnBuilder's data or code), **tested** (checked in game by a
  player) and **unknown**. A test that settles an unknown, or contradicts a
  tested entry, is a real contribution. Use the "In-game test result" form.
- **Suggest a feature.** Check [`docs/ROADMAP.md`](docs/ROADMAP.md) first, then
  open a feature request.
- **Send a pull request.** See below. For anything bigger than a small fix,
  open an issue first (or comment on an existing one) so we can agree on the
  approach and nobody duplicates work.

## Development setup

You need git. `bin/wt-init` installs [uv](https://docs.astral.sh/uv/) if it's
missing, installs dependencies, downloads WynnBuilder's data and runs the tests.

```bash
git clone https://github.com/<you>/wynn-toolbox && cd wynn-toolbox
bin/wt-init
uv run wt serve        # the web app
```

On Windows, run the same steps in Git Bash or WSL, or do them by hand:
`uv sync`, `uv run wt fetch`, `uv run pytest -q`.

Code layout:

| Path | What's there |
|---|---|
| `wynntools/cli.py` | The `wt` command |
| `wynntools/codec.py` | WynnBuilder link encoding and decoding |
| `wynntools/gear_milp.py`, `gear_solver.py` | Gear search (exact, and per-slot shortlists) |
| `wynntools/damage.py` | Damage and effective HP |
| `wynntools/skillpoints.py`, `tree_solver.py`, `crafting.py`, `craft_solver.py` | Skill points, ability tree, crafting |
| `wynntools/verify.py`, `rules.py` | The checks every link must pass |
| `wynntools/buildfile.py` | The build file format (`builds/*.json`) |
| `wynntools/web/` | The web app (server, terminal, static page) |
| `knowledge/mechanics.md` | Game facts, tagged by source |
| `AGENTS.md`, `.claude/skills/build/` | Instructions the AI assistants follow |
| `tests/` | Test suites |

## Tests

```bash
uv run pytest                   # fast suite; run before every PR
uv run pytest -m differential   # compare with WynnBuilder's own JS (network)
uv run pytest -m ui             # drive the web app in headless Chromium
uv run pytest -m live           # compare with the live WynnBuilder page (network)
uv run pytest -m slow           # full gear searches (minutes)
```

The `ui` and `live` suites need a browser once:
`uv run playwright install chromium`.

CI runs the fast suite on Linux, macOS and Windows for every push and pull
request. Run the extra suites yourself when your change touches their area:

- `wynntools/damage.py` → `-m live`. Re-snapshot `tests/fixtures/damage.json`
  only after it passes.
- `wynntools/codec.py`, `skillpoints.py`, `crafting.py` → `-m differential`.
- anything under `wynntools/web/` → `-m ui`, and look at a screenshot when you
  change layout.
- the gear solvers → `-m slow`.

Say in the PR which suites you ran.

## Rules for changes

These come from real mistakes; please follow them.

1. **Match WynnBuilder.** Formulas and the link format are ports of
   [WynnBuilder's source](https://github.com/wynnbuilder/wynnbuilder.github.io).
   When porting, name the file and function you ported from, and add a
   differential or live test that compares against it.
2. **Every bug fix gets a regression test** in `tests/`.
3. **Keep facts apart by source.** Add game facts to `knowledge/mechanics.md`
   under the right heading (proven, tested, unknown), with the file, or the
   tester and date. Never state an unknown as fact.
4. **Links stay round-trippable.** A new kind of link (a new item type, a new
   field) goes into `tests/fixtures/links.json`.
5. **The two copies of the build skill stay identical**:
   `.claude/skills/build/` and `.agents/skills/build/`. A test checks it.
6. **Never commit player data.** `builds/` and `data/` are ignored; keep them
   that way. Spec files for `wt gear` belong in `examples/` or outside the repo,
   never in `builds/`.
7. **Keep commits small** with specific messages ("Don't reopen the app window
   off-screen after a monitor disconnects", not "fix bug").
8. **Match the surrounding code**: its naming, comment style and plain-English
   user-facing messages. Players read the output, and many aren't developers.

## Pull requests

1. Fork the repo and create a branch from `main` (`fix/...`, `feature/...`).
2. Make your change with tests, and run `uv run pytest` plus any suites listed
   above.
3. Update the docs your change affects: `README.md` for anything a player
   sees, `AGENTS.md` and the build skill for anything the AI should do
   differently, `docs/ROADMAP.md` if you finish a roadmap item.
4. Open the PR and fill in the template. Link the issue it closes.

A maintainer reviews every PR. Expect questions, especially about where a
number comes from. Once CI passes and review is done, the PR is merged into
`main` and reaches players through the app's update check.

Using an AI assistant to write your change is fine; you're still responsible
for understanding it and for the tests passing.

## License

Wynn Toolbox is licensed under the GNU GPL v3.0 or later (it ports
GPL-3.0 code from WynnBuilder). By contributing, you agree that your
contribution is licensed the same way.

## Conduct

Be kind and assume good faith. Disagreements about game mechanics are settled
by WynnBuilder's code or an in-game test, not by argument.
