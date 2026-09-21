# Wynncraft mechanics for build work

Every entry is tagged by where it comes from. Keep them apart; only **Proven**
entries may be stated as fact.

- **Proven**: read from WynnBuilder's data files or source code (file noted).
- **Tested**: a player checked it in game (who and when noted). Reliable, but
  one test on one build.
- **Unknown**: nobody has checked. Say so, and say how to test it.

## Proven (WynnBuilder data and code)

### Stats and words players use
- **Greed** and **Magnet** are Major IDs (`majid.json`), not ability-tree nodes.
  Greed: picking up emeralds heals you and nearby players for 8% max HP. Magnet:
  pulls mob drops toward you.
- **Stealing** is the `eSteal` stat. **Loot Bonus** is `lb`. They are separate:
  Loot Bonus does nothing for Stealing.
- **PLAGUE** is a Major ID: poisoned mobs spread their poison to nearby mobs.

### Levels, points, rolls
- Skill points: 200 at level 101 and above (`levelToSkillPoints`). At most 100
  assigned to any one skill.
- A skill requirement is met by assigned points plus the bonuses of every other
  equipped item and tome, **including negative bonuses**.
- Ability points: 45 at levels 104–106, 46 at 107, 50 at 121 (`atree_level_table`).
- Max build level is 121; items go up to level 120.
- Base HP = 5 × level + 5.
- Database values are **base (100%) rolls**. Positive IDs roll 30–130% of base
  (`maxRolls`/`minRolls` in `build_utils.js`).

### Mana
- Max mana = 100 + Max Mana from gear/tomes + an Intelligence bonus
  (`#maxManaTotal` in `display.js`). The Intelligence curve is
  `107.7 × (1 − 0.9908^int)` percent, capped at 150 Int: 40 Int ≈ +33 mana.
- WynnBuilder assigns only the minimum skill points. Mana from spare points in
  Intelligence only exists if the player puts them there.

### Damage
- Poison deals `floor(poison / 3)` damage per second (`display.js`). WynnBuilder
  does not scale it by spell or melee damage %.
- `averageDps` on a weapon is main-attack DPS with attack speed included. It is
  misleading for spell and summon builds, which scale off damage per hit.
- Attack speed in hits/sec: SUPER_SLOW 0.51, VERY_SLOW 0.83, SLOW 1.5,
  NORMAL 2.05, FAST 2.5, VERY_FAST 3.1, SUPER_FAST 4.3.
- WynnBuilder models Shaman puppet hits as **spell** scaling: the Puppet Master
  node has no `scaling` field, so it defaults to `"spell"`. (Compare Tested below.)

### Ability trees
- A node turns on only when a parent is on, its dependencies are on, no blocker
  is on, and enough **other, already-active** nodes of its archetype are on.
- The Mage tree has **no poison nodes** (checked all 88).
- Shaman summon rates from tree properties: puppets attack 2/s each (max 8 with
  More Puppets, More Puppets II, Puppetry); totems tick 2.5/s (max 3 with Double
  and Triple Totem); hummingbirds 4/s each (2); Crimson Effigy 2/s; Patchwork
  Abomination 0.8/s. Invigorating Wave adds +1.2 puppet attacks/s and +0.75 totem
  ticks/s while active; Commander adds +0.5 puppet attacks/s.

## Tested (in game)

- **Puppet hits trigger Stealing.** Tested by Hank, 2026-09-20.
- **Puppet damage comes from main-attack damage**, per Hank. This conflicts with
  WynnBuilder's spell-scaling model above; unresolved. It decides whether melee
  or spell damage % boosts puppets.

## Unknown

- Whether **totem ticks, hummingbirds, Crimson Effigy and Patchwork** trigger
  Stealing. Only puppets were tested. The `summoner-stealing` preset assumes all
  summons count; if only puppets do, puppet count is all that matters.
  *Test: equip one Stealing item, place only totems, count emeralds per minute.*
- Whether Stealing has a **cap**, or whether emeralds per proc scale with mob level.
- Whether **sigil and tornado ticks re-apply poison** on every hit. The poison
  Mage presets assume they do.
- Whether two copies of the same tome can sit in paired slots (both mobXp slots,
  for example). WynnBuilder allows it.

## Mistakes the verifiers catch

Each has a regression test.

| Mistake | Symptom | Test |
|---|---|---|
| Negative skill bonuses ignored | WynnBuilder: "Too many skillpoints need to be assigned!" | `test_negative_bonuses_count` |
| Archetype requirement counted over the whole tree, not in order | Only 10 of 29 nodes could activate | `test_archetype_requirement_is_checked_in_order` |
| Unrequested stat in the objective | A 154% Loot Bonus, 0-HP chest dominated a Stealing build | AGENTS.md rule 5 |
| `averageDps` used to rank summon/spell weapons | Steered away from the best per-hit relik | mechanics note above |
| Base values treated as perfect rolls | Wand comparison overstated by ~40% vs. real items | AGENTS.md rule 3 |
