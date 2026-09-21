# Roadmap

Rough priority order.

1. ~~**Exact gear solver (MILP).**~~ Done: `wynntools/gear_milp.py`, the default.
   Damage floors still use the shortlist search.
2. **Real item rolls.** Let a player enter the items they own with actual roll
   values instead of 100% base values.
3. **Differential tests for decoding and the tree.** Encoding of powders, skill
   points, aspects, tomes and crafts is checked against WynnBuilder's own JS;
   extend the same harness to full-link decoding and ability-tree activation.
4. ~~**Spell damage.**~~ Done: `wynntools/damage.py`, checked against the live
   WynnBuilder page (`-m live`).
5. **More skills**: `compare` (weapons/items side by side), `explain` (walk a
   player through a decoded build), `decode` for quick lookups.
6. **Aspects** in specs and output, with names.
7. **Custom items** in the link codec; legacy (pre-binary) links and legacy
   crafted hashes; item data for older game versions.
8. **Crafting**: consumables (potions, scrolls, food); powders as crafting
   ingredients in suggestions; crafted weapon DPS from the damage calculator.
9. **Ability tree view**: draw the real tree layout instead of chips grouped by
   archetype.
10. **CI** running the test suite on every push, plus a scheduled run that
   refreshes data and flags breakage after a game patch.
