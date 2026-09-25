---
name: build
description: Make, compare, adjust or improve a Wynncraft build with the wt tools. Use when a player asks for a build, wants to compare weapons or items, or wants an existing build changed or improved ("this build", "make my build tankier", "a better helmet"), or asks for a NEW build. Decides first whether the player wants a new build or a change to the open one: changes to an existing build go into its file, a request for a new one never touches it. Produces verified WynnBuilder links saved to the player's build list.
---

# Build

Follow AGENTS.md throughout: its rules and assumptions bind every step. The
steps below are the procedure.

## 0. New build or change? Decide first, and say which

The player having a build open does not mean they want it changed. Read their
words, not the context note about the open build:

| They say | Do this |
|---|---|
| "new", "another", "different", "from scratch", "make me a ..." (a class, goal or playstyle) | **Create**: `wt gear <spec> --save builds/<new name>.json`. Leave the open build alone. |
| "this build", "my build", "it", "improve", "tankier", "swap in X", "a better helmet" | **Edit** that build: section 4b. |
| "another version of this", "try it with ...", "keep this one but ..." | **Variant**: `--save-as builds/<name>-v2.json` (or `--candidate`). |
| A WynnBuilder link | `wt import <link> builds/<name>.json`, then edit that. |
| Unclear | Ask one short question: "change your open build, or make a new one?" |

Before running a search, say in one line **"Editing builds/x.json"** or
**"Creating builds/y.json"**; `wt gear` prints the same line, so check it
matches what the player asked for. `wt gear --save` refuses to overwrite an
existing file: choose another name rather than forcing.

For each new build, run `wt intake [spec]` to see what is still missing, ask
only that in one short batch, and use `knowledge/goals.md` to turn their words
into a goal and floors. Run `wt spec-check <spec> --tree PRESET` before a long
search.

Commands are written as `wt ...`, which works in the web app's terminal (the
toolbox's `wt` is first on PATH there). Elsewhere, run `uv run wt ...` from the
repo root. In a sandbox where `uv run` fails with a read-only file system
error (Codex's), use `wt` or `.venv/bin/wt` (Windows: `.venv\Scripts\wt.exe`).

## 1. Find out what they want

If they mean the build open in the web app ("this build", "my current build"),
run `wt current` first. If they have a WynnBuilder link, decode it. Either
tells you class, level and gear without asking:

    wt decode "<link>"

**New build or a change to one?** Section 0 decides it. When the player talks about a build they
already have ("make my build tankier", "find me a better helmet", "swap in
Gaia", "improve this"), change that build: follow "Changing an existing build"
below instead of making a new one. Make a new build only when they ask for one,
or the change would replace nearly everything (then say so, and offer to keep
the old one with `--save-as`). If you can't tell, ask.

Then collect only what is still missing:

- **Class and level.** Max build level is 121.
- **The goal**, in stat terms. Map words to stats with `knowledge/mechanics.md`,
  and confirm when a word is ambiguous (e.g. "greed" is a Major ID, "stealing" is
  the `eSteal` stat; "loot" could mean either Stealing or Loot Bonus).
- **Hard requirements**: Major IDs they must have (`require_major`), minimum HP,
  max mana, mana regen, walk speed, health regen, elemental defences, final
  skill points (e.g. "at least 60 Defence"), effective HP.
- **Weapon situation**: a weapon they must use (`force`), items they can't get
  (`exclude`, or `wt own unavailable NAME --reason ...` so every search leaves
  them out), "no mythics" (`exclude_tiers`), "only one of these"
  (`at_most_one`), items they'd like if it costs nothing (`prefer`).
- **Tomes**: which they own, or whether to plan for aspirational ones. Record
  owned ones with `wt own add --tome NAME`; then `"tome_pool": "owned"` (or
  `wt gear --tomes owned`) lets the exact search pick the tomes for the slots
  `tomes` leaves empty from what they own; `"any"` picks from any tome (goals to
  collect: say so, and that the same tome may fill two paired slots, untested in
  game). Only the exact search does this: not with effective HP, DPS, spell damage
  or regen-with-% goals or minimums. `wt gear --owned` defaults to owned tomes.
- **Aspects**: `wt own add --aspect --class Mage NAME --tier N` records the ones
  they have. Searches don't choose aspects; the editor can limit its picker to them.

## 2. Write the spec

Create `builds/specs/<name>.json`. Start from `examples/`. Fields:

    class, level, objective {stat: weight}, floors {...}, require_major [...],
    force {slot: item}, exclude [...], exclude_tiers [...], at_most_one [[...]],
    prefer [...], tomes [14 tome names or null, in slot order], topn

Floors: `hp`, `mr`, `spd`, `mana`, `weapon_dps`, `hprRaw`, `eDef` ... `aDef`,
`min_eledef` (every elemental defence), `str` ... `agi` (final skill points),
and the damage-model ones `ehp`, `ehp_no_agi`, `hpr`, `melee_dps`,
`puppet_dps`, `summon_dps`, `damage`. Goals: any item stat, `min_eledef`, or a
derived goal (`ehp`, `hpr`, `melee_dps`, `puppet_dps`, `summon_dps`,
`damage:<spell>`) when that is what the player actually wants ("as tanky as
possible" is `ehp`, not `hp`). Derived goals run the local search and put
spare skill points where they help; damage goals need `--tree`.

Tome slot order: weapon ×2, armor ×4, guild, lootrun, gatherXp ×2, dungeonXp ×2,
mobXp ×2. Floors include tome stats and base HP. `"tome_pool": "fixed"` (the
default) uses exactly the listed `tomes`; with `owned`/`any` the listed ones stay
and the search fills the empty slots.

Set `"crafted": true` to let the search use crafted gear. It often wins for
niche stats (Stealing, for one) and costs little search time. Ask first if the
player doesn't craft, since crafts need ingredients they must collect. For one
slot, `wt craft --type <slot> --level N --maximize <stat>` shows the best
crafts with their ingredient grid, a WynnBuilder crafter link, and which mobs
drop each ingredient and where (`wt ingredient <name>` for all spots).
Mention when an ingredient has no listed mob.

Use one objective stat unless the player asked for more. A tiny tiebreaker
weight (0.01) on a second stat is fine. Put hard requirements in floors,
`require_major`, `force`, `exclude` or `exclude_tiers`; never trade them away
silently.

## 3. Pick a tree preset

`wt tree <preset> --level N` lists what a preset selects. There is one
generic preset per archetype for every class: `<class>-<archetype>`, e.g.
`archer-boltslinger`, `assassin-shadestepper`, `warrior-battle-monk`,
`mage-arcanist`, `shaman-ritualist` (`wt tree --help` lists all). Each takes
the class's four spells, then as many nodes of that archetype as fit, all
valued the same. They ignore damage, utility and the other archetypes, and
may leave points unspent; say so, and suggest the player finish the tree in
the editor.

Say what the preset's weights favor, especially an archetype it ignores. If
the player's goal needs a different tree, change that build's tree (the
editor, or `tree` in the build file, then `wt link --write`) rather than adding
a preset: presets are shared by every player, so they stay generic. Say that
the changes are a judgment call.

## 4. Run, save and verify

    wt gear builds/specs/<name>.json --tree <preset> \
        --save builds/<name>.json --name "<readable name>"

Always pass `--save`: it puts the build in the app's list and opens it there.
The search is exact over every usable item (it says so). With a damage floor it
falls back to per-slot shortlists; add `--confirm` then, and call the result
best within the shortlists. It prints the build, totals and a link, and says
`VERIFIED OK` or lists problems. Never pass on a link without `VERIFIED OK`
(`wt verify <link>` checks any link). Never work out totals yourself.

## 4b. Changing an existing build

Work on the player's file, not a new one. First run `wt current` (or
`wt decode builds/<name>.json`) to see what it has now. If it reports
**unsaved edits**, ask the player to Save or Revert before you change anything;
the commands below refuse until they do.

- **The player named the change** (an item, a tome, the level, a tree preset):

      wt edit builds/<name>.json --item helmet="Name" --tome armorTome1="Name"

- **The player wants it better at something** ("more HP", "better Stealing",
  "a better helmet"): re-search it in place.

      wt gear --edit builds/<name>.json [spec.json] [--change helmet,boots | --keep weapon,...]

  `--change` searches only those slots and keeps every other item; `--keep`
  keeps those slots and searches the rest. With neither, all nine slots are
  searched. Keep what the player didn't ask to change, and always keep a
  weapon they chose. Rings can come back in either slot.

  The spec: a build made by `wt gear` carries its own, so leave the spec
  out to reuse it, or write a new one when the goal changed. Class, level and
  tomes default to the build's, so a spec for an edit can be as small as
  `{"objective": {"hp": 1}, "floors": {"mr": 20}}`. A spec's `tomes` replace
  the build's. Builds from links or the editor have no spec: write one, and
  ask the player for the floors the build has to keep (HP, mana regen, ...).

  It writes the result back into the file and prints what changed. Name,
  notes and powders on unchanged items stay; so do aspects and the tree while
  the class is the same (pass `--tree PRESET` to re-solve it, which replaces
  the player's own tree choices, so ask first). Manual skill points go back
  to automatic when items change. `(no changes: ...)` means the build is
  already the best for that spec: say so rather than inventing a change.

- **Fields neither command covers**: edit the file's editable fields by hand,
  then `wt link builds/<name>.json --write` to re-check it.

- **To compare before committing**, add `--save-as builds/<name>-v2.json`
  (either command) so the original is untouched, then `wt compare` the two.

Present the change as a before/after: the slots that changed, and the key
totals before and after (both from `wt` output, e.g. `wt compare`). Tell the
player which file changed.

## 4c. When nothing fits

`wt gear` prints why: the smallest set of the player's requirements that can't
hold together, how close each gets with the others met, and the skill-point
arithmetic for kept items. Pass that on in plain words and ask which one to
loosen. Don't drop a requirement yourself.

## 4d. Fixing weaknesses

`wt current` and `status.warnings` in the build file list weaknesses (negative
elemental defence or Defence/Agility, no health regen, skill points that don't
fit, damage that can't be worked out), each with a fix. For a search fix,
re-search into a candidate so the player can compare:

    wt gear --edit builds/<name>.json <spec with the fix's floors> --candidate "<what it fixes>"

Keep the weapon and anything locked (`locked` in the file; `wt edit --lock`).
Then `wt variants builds/<name>.json` shows both side by side.

## 5. When goals compete, show the trade-off

Damage against survival: `wt tradeoffs spec.json --damage <melee_dps |
puppet_dps | summon_dps | damage:<spell>> --tree PRESET` prints a few legal
builds from max damage to max effective HP with HP, regen, effective HP,
skill points and puppet DPS side by side. `--parent builds/<name>.json` saves
them as candidates; after the player picks one, `wt variants
builds/<name>.json --choose <file>` (and `--trash-rest` if they agree).

For other contests, run the spec at 2–4 values of the contested floor (e.g. HP
14k / 17k / 20k) and present a short table: floor, goal stat, HP, mana regen,
skill points. Point out cliffs where one step costs much more than the last.

Powders: `wt powders builds/<name>.json --weapon <damage number or
special:<name>> --armor <hp | eledef | special:<e|t|w|f|a>>` suggests them
(weapon and armor separately); `--write` puts them in the build. Say whether
powder specials were on. A special takes two or more tier IV+ powders of one
element on an item, and their tiers set its power (`knowledge/mechanics.md`).
`wt damage --special auto` switches on the one the weapon's powders give;
WynnBuilder's own numbers leave specials off.

Puppets and other summons are spell damage: spell damage % and raw boost them,
main-attack IDs don't.

For weapon comparisons, force each candidate weapon with the same spec and
compare with `wt damage <link>` (spell and melee damage, effective HP), or
`wt compare <a> <b>` for two saved builds. When a player wants to keep a
spell's damage up while maximizing something else, add
`"floors": {"damage": {"<spell name>": N}}` and pass `--tree PRESET`. Quote
damage at typical rolls unless comparing with the WynnBuilder page (`--perfect`).
Poison is per second (`floor(poison / 3)`), not per hit.

## 6. Present

- The link, a table of the 9 items, and the key totals.
- Which file you saved, so the player can find it in the list.
- The objective you used, and the assumptions from AGENTS.md rule 3, in two or
  three lines. `wt report builds/<name>.json` prints the verified link, the
  search kind, the objective and every assumption in one block: build your
  answer from it instead of reconstructing it.
- Anything the result depends on that is only tested or unknown per
  `knowledge/mechanics.md`.
- When developing the toolbox (not for players): add keeper links to
  `tests/fixtures/links.json`.
