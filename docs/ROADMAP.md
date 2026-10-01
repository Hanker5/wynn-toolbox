# Roadmap

Rough priority order. Want to take one? Say so in an issue first; see
`CONTRIBUTING.md`.

1. ~~**Exact gear solver (MILP).**~~ Done: `wynntools/gear_milp.py`, the default.
   Damage-model floors still use the shortlist search, and derived goals a
   local search (`wynntools/gear_local.py`); an exact method for those would
   need a better bound on effective HP and damage.
2. ~~**Real item rolls.**~~ Done: `wt own --roll` and the Inventory page;
   `wt gear --owned` and `wt upgrades` use them.
   Tomes and aspects are in the inventory too (tabbed Inventory page); the exact
   and local searches can choose tomes from it or from any tome (`tome_pool`).
   The `wynn-chest-export` mod imports items (with their real rolls, read from
   the tooltip), tomes and aspects from chests. Still to do: choosing tomes in
   the shortlist search and in `wt upgrades`.
3. **Differential tests for decoding and the tree.** Encoding of powders, skill
   points, aspects, tomes and crafts is checked against WynnBuilder's own JS;
   extend the same harness to full-link decoding and ability-tree activation.
4. ~~**Spell damage.**~~ Done: `wynntools/damage.py`, checked against the live
   WynnBuilder page (`-m live`).
5. **More skills**: `explain` (walk a player through a decoded build), `decode`
   for quick lookups. (`wt compare` and the Compare builds page are done.)
6. ~~**Aspects** chosen by the search.~~ Done: `aspect_pool` / `wt gear
   --aspects` lets the local search fill empty aspect slots as it goes.
7. **Custom items** in the link codec; legacy (pre-binary) links and legacy
   crafted hashes. (Links made with older versions' data are done: read with
   that data and brought to today's, `wynntools/upgrade.py`.)
8. **Crafting**: consumables (potions, scrolls, food); powders as crafting
   ingredients in suggestions; crafted weapon DPS from the damage calculator.
9. ~~**Ability tree view.**~~ Done: the web app draws WynnBuilder's tree layout.
10. ~~**CI**~~ Done: the fast suite runs on Linux, macOS and Windows for every
   push and pull request, and a daily `patch watch` run refreshes the data and
   runs the fast and differential suites to flag breakage after a game patch.
11. **Local AI models.** A choice in the setup wizard and `wt config ai` for a
   model running on the player's own computer (for example through
   [Ollama](https://ollama.com)), so the toolbox works without a cloud AI
   account. Needs an agent that can run `wt` commands with a local model, the
   build skill and prompt hook wired up for it, and testing that a local model
   follows the rules in `AGENTS.md` (verified links, no numbers from its head)
   well enough to recommend. Measured 2026-10-01 and shelved: an 8B model on
   an 8 GB GPU passed 1 of 6 requests (Claude and Codex pass 8/8); see
   `docs/PLAN.md` item 4. `evals/agent_eval.py` and `wt agent` are there to
   try a stronger model.
