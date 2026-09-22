## What this changes

<!-- What and why. Link the issue: "Closes #123". -->

## How it was checked

<!-- Tick the suites you ran. See CONTRIBUTING.md for which ones your change needs. -->

- [ ] `uv run pytest` (fast suite)
- [ ] `-m differential` (codec, skill points, crafting)
- [ ] `-m live` (damage)
- [ ] `-m ui` (web app; screenshot attached for layout changes)
- [ ] `-m slow` (gear solvers)

## Checklist

- [ ] Bug fixes have a regression test in `tests/`
- [ ] New game facts are in `knowledge/mechanics.md` with their source
- [ ] Docs updated where players or the AI would notice (`README.md`, `AGENTS.md`, build skill, `docs/ROADMAP.md`)
- [ ] No files from `builds/` or `data/`
