# From what a player says to a spec

Recipes for turning common wishes into a `wt gear` spec. Every stat and goal
name here exists in `wynntools/statinfo.py` or `wynntools/derived.py`. The
game facts behind them are in `mechanics.md`; nothing here adds one.

These are starting points, not rules. Confirm the words with the player, show
the objective you used (AGENTS.md rule 5), and run `wt spec-check` before a
long search. Numbers in floors (HP 17000, mana regen 20, ...) are examples from
past sessions: ask the player, don't copy them.

## Words to goals

| The player says | Objective | Notes |
|---|---|---|
| "stealing", "emeralds from mobs" | `{"eSteal": 1}` | Not `lb`. Puppet hits trigger it (tested); other summons unknown. |
| "loot", "loot bonus" | ask: `eSteal` or `lb`? | Two different stats; `lb` does nothing for Stealing. |
| "greed", "magnet" | `require_major: ["GREED"]` / `["MAGNET"]` | Major IDs, not tree nodes. They are requirements, not the objective. |
| "tanky", "survive" | `{"ehp": 1}` | Derived goal (local search). Not `hp`: defence and agility count. |
| "lots of HP" (literally) | `{"hp": 1}` | Only when they mean the health stat. |
| "poison" | `{"poison": 1}` | Poison ignores spell damage. Per second is `floor(poison / 3)`. Often `require_major: ["PLAGUE"]`. |
| "spell damage" | `{"sdPct": 1}` (or `damage:<spell>` with `--tree`) | Say which; `damage:<spell>` needs the tree. |
| "melee", "main attack" | `{"melee_dps": 1}` | Needs `--tree`. Local search. |
| "puppets", "summons" | `{"puppet_dps": 1}` / `{"summon_dps": 1}` | Needs `--tree`. Summons count as spell damage. |
| "never run out of mana" | floor `mr` (and `mana`) | A mana floor may rely on spare points in Intelligence: say so. |
| "fast" | floor `spd` | Walk speed %. |
| "no elemental weakness" | `{"min_eledef": 1}` or floor `min_eledef` | Exact. |
| "heal myself" | floor or goal `hpr` / `hprRaw` | `hpr` is the derived total; `hprRaw` the item stat. |

## Shapes

- **One goal, the rest floors.** The goal is what the player wants most; hard
  needs (HP, mana, speed, majors) are floors, `require_major`, `force` or
  `exclude`. A tiny tiebreaker (0.01) on a second stat is fine.
- **Competing wishes** (HP vs. Stealing): run 2 to 4 floors and show a table
  (rule 7); don't pick one.
- **Damage and survival**: `wt tradeoffs spec.json --damage puppet_dps --tree PRESET`.

## Class-flavored starting points

Presets are generic per archetype (`wt tree --help`); say what the one you
choose ignores (rule 6).

| Wish | Class and preset to start from | Example spec |
|---|---|---|
| Stealing summoner | Shaman, `shaman-summoner` | `examples/shaman-105-stealing.json` |
| Stealing with crafts | Shaman | `examples/shaman-105-stealing-crafted.json` (ask first: crafts need ingredients) |
| Poison mage | Mage, `mage-riftwalker` or `mage-arcanist` (say which archetype is ignored) | `examples/mage-105-poison-gaia.json` |

## Before you run

1. `wt intake <spec>`: what is still unanswered.
2. `wt spec-check <spec> --tree PRESET`: typos, missing tree, which search runs.
3. `wt gear ... --save builds/<name>.json`, then `wt report builds/<name>.json`.
