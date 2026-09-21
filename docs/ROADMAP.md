# Roadmap

Rough priority order.

1. **Exact gear solver (MILP).** The gear search uses per-slot shortlists, so it
   can miss the true best build (it did once, until the shortlist grew from 7 to
   8). A MILP like the tree solver would be exact and likely faster.
2. **Real item rolls.** Let a player enter the items they own with actual roll
   values instead of 100% base values.
3. **Check powders, assigned skill points and aspects against a real link.** The
   encoder handles them, but they are only tested for self-consistency. A real
   WynnBuilder link with powders (e.g. a powdered Sequoia) would settle it.
4. **Spell damage.** Port WynnBuilder's spell damage calculation so weapon
   comparisons stop relying on rough per-cast estimates.
5. **More skills**: `compare` (weapons/items side by side), `explain` (walk a
   player through a decoded build), `decode` for quick lookups.
6. **Aspects** in specs and output, with names.
7. **Crafted and custom items** in the link codec; legacy (pre-binary) links;
   item data for older game versions.
8. **CI** running the test suite on every push, plus a scheduled run that
   refreshes data and flags breakage after a game patch.
