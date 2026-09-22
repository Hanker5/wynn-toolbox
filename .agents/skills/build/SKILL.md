---
name: build
description: Create, compare, or adjust a Wynncraft build with Wynn Toolbox. Use when a player asks for a build, wants to compare gear or weapons, or wants their current build changed.
---

# Wynncraft Build

Follow `AGENTS.md` for the project rules and assumptions. Use this skill for a
player-facing build task, not for general Wynn Toolbox development.

## Understand the request

For “this build”, “my build”, or “the current build”, first run:

    uv run wt current

For a WynnBuilder link, decode it before asking for details:

    uv run wt decode "<link>"

Only collect what remains unknown: class and level, the intended stat goal,
hard floors or required Major IDs, weapon constraints, whether crafted items
are acceptable, and whether tomes are owned or aspirational. Check
`knowledge/mechanics.md` when a player term is ambiguous or a mechanic needs a
source classification.

## Search or change the build

Write a gear spec under `builds/specs/`, using an example as a starting point.
Keep the objective to the stats the player actually requested. Add hard
requirements as floors, `require_major`, `force`, `exclude`, or
`exclude_tiers` rather than silently trading them away.

Choose a tree preset with:

    uv run wt tree <preset> --level <level>

Explain what its weights favor, especially if it does not cover every
archetype. Then solve and save the result:

    uv run wt gear builds/specs/<name>.json --tree <preset> \
        --save builds/<name>.json --name "<readable name>"

Always use `--save` for a build presented to the player. It puts the build in
the app and opens it when the app is running. When changing an existing saved
build, prefer `wt edit`; use `--save-as` for a variant. If `wt current` reports
unsaved page edits, ask the player to save or revert before changing that file.

## Verify and compare

Never calculate or infer build totals manually. The solver output is the source
of stats, skill points, and the generated link. Confirm every player-facing
link prints `VERIFIED OK`:

    uv run wt verify <link>

Use `wt damage` for damage comparisons, and use multiple solver runs when
competing floors create a real trade-off. Damage floors and `--shortlists` use
the shortlist search path, so add `--confirm` and describe the result as best
within those shortlists.

## Present the result

State the objective used, the requested trade-offs, and the assumptions required
by `AGENTS.md`: rolls, automatic skill points, empty aspects, tome ownership,
and relevant damage or crafted-item caveats. Keep proven WynnBuilder behavior,
in-game tests, and unknown mechanics distinct.
