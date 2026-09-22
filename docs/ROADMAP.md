# Roadmap

Rough priority order. Want to take one? Say so in an issue first; see
`CONTRIBUTING.md`.

1. ~~**Exact gear solver (MILP).**~~ Done: `wynntools/gear_milp.py`, the default.
   Damage floors still use the shortlist search.
2. ~~**Real item rolls.**~~ Done: `wt own --roll` and the Inventory page;
   `wt gear --owned` and `wt upgrades` use them.
3. **Differential tests for decoding and the tree.** Encoding of powders, skill
   points, aspects, tomes and crafts is checked against WynnBuilder's own JS;
   extend the same harness to full-link decoding and ability-tree activation.
4. ~~**Spell damage.**~~ Done: `wynntools/damage.py`, checked against the live
   WynnBuilder page (`-m live`).
5. **More skills**: `explain` (walk a player through a decoded build), `decode`
   for quick lookups. (`wt compare` and the Compare builds page are done.)
6. **Aspects** in specs and output, with names.
7. **Custom items** in the link codec; legacy (pre-binary) links and legacy
   crafted hashes; item data for older game versions.
8. **Crafting**: consumables (potions, scrolls, food); powders as crafting
   ingredients in suggestions; crafted weapon DPS from the damage calculator.
9. ~~**Ability tree view.**~~ Done: the web app draws WynnBuilder's tree layout.
10. **CI**: the fast suite runs on Linux, macOS and Windows for every push and
   pull request. Still to do: a scheduled run that refreshes data and flags
   breakage after a game patch.
11. **Local AI models.** A choice in the setup wizard and `wt config ai` for a
   model running on the player's own computer (for example through
   [Ollama](https://ollama.com)), so the toolbox works without a cloud AI
   account. Needs an agent that can run `wt` commands with a local model, the
   build skill and prompt hook wired up for it, and testing that a local model
   follows the rules in `AGENTS.md` (verified links, no numbers from its head)
   well enough to recommend.
