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
- Skill points follow WynnBuilder's `calculate_skillpoints` exactly (ported in
  `wynntools/skillpoints.py`, differential-tested, and matched against
  WynnBuilder's page):
  - the nine equippables (boots, leggings, chestplate, helmet, rings, bracelet,
    necklace, guild tome) go on one at a time in the cheapest order; a bonus
    only helps items equipped after it;
  - the **weapon and crafted items go on last**, so their bonuses never help
    another item's requirement;
  - a negative bonus only costs points when some item actually **requires**
    that skill (a requirement of 0 needs nothing);
  - "pop" rule: an item whose requirement is met only by its own bonus would
    fall off, so points are assigned to prevent it.
- **Set bonuses** (`sets` in the item data; items don't name their set): the
  bonus for the number of pieces worn is added to the build's stats. Its skill
  points are added to the build's totals but never count toward requirements.
  Example: 4/4 Cosmic Foundations = +1,500 HP, +15 all skills, +24 mana steal.
- Ability points: 45 at levels 104–106, 46 at 107, 50 at 121 (`atree_level_table`).
- Max build level is 121; items go up to level 120.
- Base HP = 5 × level + 5.
- Database values are **base (100%) rolls**. Positive IDs roll 30–130% of base
  (`maxRolls`/`minRolls` in `build_utils.js`); negative IDs roll 70–130%; spell
  cost IDs are reversed. Health (`hp`), skill points and requirements never roll;
  Health Bonus (`hpBonus`) does.
- **WynnBuilder's build page adds up perfect (130%) rolls** (`build.js` sums
  `maxRolls`). The tools report 100% rolls and also show the perfect-roll totals,
  labelled as what WynnBuilder shows, so the numbers can be matched up.

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
  `wt damage` follows WynnBuilder here, so its puppet numbers carry the same doubt.
- The damage path (`damage_calc.js`, ported in `wynntools/damage.py`): weapon
  damage after powders → spell conversions (neutral % scales the weapon, element
  % converts from the total) → attack-speed multiplier (spells only) → flat
  "add" damage → % boosts (skill points, spell/melee %, element %, rainbow %) →
  raw damage split by each element's share → strength multiplies everything,
  crit adds `1 + critDamPct%` on top → damage multipliers (tomes' "damage vs
  mobs", ability multipliers).
- Crit chance is the Dexterity skill-point percentage. Strength multiplies all
  damage except parts marked `use_str: false`.
- Effective HP = HP / (agility dodge and defence reduction) / (2 − class defence);
  class defence is 0.6 relik, 0.7 bow, 0.8 wand, 1.0 dagger and spear.
- Armor powders add defence to their element, take some from the element
  before it (cycle ETWFA) and add flat HP by tier (5/10/20/30/45/60/75);
  weapon powders convert neutral damage in the order first applied.
- The page's totals include ability-tree stat bonuses (the Mage tree gives
  +5 mana regen); the Summary does too. Solver floors count gear only, which
  errs on the safe side.
- Ability sliders (stacks, orbs) and toggles change damage; WynnBuilder opens a
  link with sliders at their defaults and toggles off, and so does `wt damage`.

### Ability trees
- A node turns on only when a parent is on, its dependencies are on, no blocker
  is on, and enough **other, already-active** nodes of its archetype are on.
- The Mage tree has **no poison nodes** (checked all 88).
- Shaman summon rates from tree properties: puppets attack 2/s each (max 8 with
  More Puppets, More Puppets II, Puppetry); totems tick 2.5/s (max 3 with Double
  and Triple Totem); hummingbirds 4/s each (2); Crimson Effigy 2/s; Patchwork
  Abomination 0.8/s. Invigorating Wave adds +1.2 puppet attacks/s and +0.75 totem
  ticks/s while active; Commander adds +0.5 puppet attacks/s.

### Crafting (`craft.js`, checked against WynnBuilder's JS on 400 random crafts)
- Six ingredients in a 3×2 grid. Each ingredient can raise or lower the
  effectiveness of other slots (`above`, `under`, `left`, `right`, `touching`,
  `notTouching`), so layout matters as much as ingredient choice.
- An ingredient's IDs are scaled by its slot's effectiveness (rounded down) and
  summed. Its skill requirements are scaled too (rounded); durability is not.
- An ingredient only works for professions in its `skills` list, and only in
  recipes at or above its level. Example: **Filched Purse** (Stealing) is
  Alchemism/Scribing only, so it can't go in gear.
- Durability below 1 makes the craft impossible; material tiers 3/3 give the most
  durability and base health/damage.
- A crafted item's level is its recipe's top level (a 103–105 recipe makes a
  level-105 item). Skill points on crafts use the top of their range.
- Crafted gear can beat drops by a lot for niche stats: at level 105 a crafted
  ring reaches 12–32% Stealing (4 Stolen Pearls + 2 Doom Stones) vs 8% for the
  best normal ring.

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
- Whether a **crafted item's IDs roll randomly** within the ingredient range when
  crafted. The tools treat the middle of the range as typical.
- **How obtainable ingredients are** (drop rates, trading). The suggester only
  knows what is legal, not what is easy to get.
- Whether two copies of the same tome can sit in paired slots (both mobXp slots,
  for example). WynnBuilder allows it.

## Mistakes the verifiers catch

Each has a regression test.

| Mistake | Symptom | Test |
|---|---|---|
| Negative skill bonuses ignored | WynnBuilder: "Too many skillpoints need to be assigned!" | `test_negative_bonuses_count` |
| Simplified skill-point model (every bonus helps every item) | Off by up to 40 points vs. WynnBuilder, both ways | `test_skillpoints_match_wynnbuilder`, `test_matches_wynnbuilder_page` |
| Set bonuses ignored | Full Cosmic Foundations build understated by 1,500 HP | `test_matches_wynnbuilder_page`, `test_set_bonuses_shown` |
| Archetype requirement counted over the whole tree, not in order | Only 10 of 29 nodes could activate | `test_archetype_requirement_is_checked_in_order` |
| Unrequested stat in the objective | A 154% Loot Bonus, 0-HP chest dominated a Stealing build | AGENTS.md rule 5 |
| `averageDps` used to rank summon/spell weapons | Steered away from the best per-hit relik | mechanics note above |
| Retired item/tome ids (`remapID` redirects) read as real entries | An old tome id loaded stale stats (Health Regen 6% instead of 3%); a stats-less "Melancholia" shadowed the real one | `test_retired_ids_redirect_to_current_items`, found by `-m live` |
| Base values treated as perfect rolls | Wand comparison overstated by ~40% vs. real items | AGENTS.md rule 3 |
| Tool totals compared to WynnBuilder's page | WynnBuilder shows 130% rolls, the tools 100% | `test_wynnbuilder_shows_perfect_rolls` |
| Crafting math drifting from WynnBuilder | Wrong stats for crafted gear | `tests/test_differential.py` |
