# Wynncraft mechanics for build work

Every entry is tagged by where it comes from. Keep them apart; only **Proven**
entries may be stated as fact.

- **Proven**: read from WynnBuilder's data files or source code (file noted).
- **Guide**: stated in "How Damage Is Calculated - Fruma Edition" by euouae, a
  former Wynncraft content-team member (forums.wynncraft.com/threads/320808,
  updated 2026-03-10). Treated as fact; where it and WynnBuilder disagree, the
  tools follow the guide and say so.
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
- **Manual skill points in links** (`build_encode_decode.js` encodeSp): a skill
  set by hand is stored as its FINAL total; unset skills are null and stay
  automatic. Points assigned to a skill = final − automatic final + automatic
  assigned (`DisplayBuildWarningsNode`). A value below what the gear needs
  means the items can't all be worn; WynnBuilder doesn't stop it, the tools
  flag it.
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
  node has no `scaling` field, so it defaults to `"spell"`. The guide agrees
  (every ability-tree attack but the main attack is spell damage), and so does
  Wynntils, per Hank (2026-09-23), who withdrew his earlier main-attack reading.
- The damage path (`damage_calc.js`, ported in `wynntools/damage.py`): weapon
  damage after powders → spell conversions (neutral % scales the weapon, element
  % converts from the total) → attack-speed multiplier (spells only) → flat
  "add" damage → % boosts (skill points, spell/melee %, element %, rainbow %) →
  raw damage split by each element's share → strength multiplies everything,
  a crit adds +100% on top → damage multipliers (tomes' "damage vs mobs",
  ability multipliers). This is the guide's order too (below).
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
- **Powder specials** (`powders.js` powderSpecialStats, `builder_graph.js`
  PowderSpecialCalcNode, `display.js` displayPowderSpecials). Off by default
  on WynnBuilder's page. Weapon specials, power 1–7: Curse, Courage and Wind
  Prison multiply all damage (+10–25%, +10–25%, +100–250%); Quake, Chain
  Lightning and Courage also have a burst hit (240–480%, 200–350%, 110–200% of
  the weapon's damage as Earth, Thunder, Fire; Courage's burst leaves out its
  own boost). Armor specials (Rage, Kill Streak, Concentration, Endurance,
  Dodge) are a "% element damage" slider capped at 300, 200, 120, 120, 120.
- Elemental defence as WynnBuilder shows it: raw × (1 + (element % + all
  elements %)/100), a negative raw value shrinking toward 0 with a positive %
  (`rawToPctUncapped`). Effective HP does not use elemental defences at all.
- Shaman summon spells in the tree data: Puppet Damage, Crimson Effigy,
  Hummingbird's Song, Patchwork Abomination ("total summon DPS" adds their
  headline numbers).

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

## Guide ("How Damage Is Calculated - Fruma Edition")

- Damage is worked out **per hit**, in six steps: (1) base damage for main
  attacks and powder-special hits, base DPS (base damage × the weapon's *base*
  attack speed) for spells; (2) conversions (neutral % scales every element,
  an elemental % converts the whole base to that element); (3) elemental
  additives (masteries' raw damage, only for elements already present);
  (4) base modifiers, additive with each other (item % IDs, armor specials,
  skill points' elemental %, masteries' %), raw IDs × the total conversion and
  only for present elements, generic raw split by each element's share;
  (5) master and defence modifiers, multiplicative with each other (Strength,
  crit, Curse/Courage/Wind Prison, tree and Major ID multipliers); (6) the
  target's elemental defences, added or subtracted per hit. The damage model
  does steps 1–5; step 6 depends on the mob and isn't modelled.
- Checked: the guide's Whirlwind Strike case study, redone step by step with
  this data version's conversions, equals the engine's number
  (`tests/test_goals.py`). The guide's own figure (729) uses a newer patch's
  conversions.
- **Crits** add +100% on top of Strength's bonus (additive with it).
  **Critical Damage Bonus** is a master modifier on crits: it multiplies crit
  damage. WynnBuilder instead adds it to the +100%; the tools follow the guide
  (22 items carry the ID, all negative; a crit is never below 0).
- Attack Speed Bonus changes main-attack rate only, never spell damage.
  Skill points count from 0 to 150; negative counts as 0. A dodge takes 90% off
  a hit and a dodged hit isn't reduced by Defence.
- **Powder specials**: two or more tier IV+ powders of one element on an item
  give that element's special. With pairs of several elements, the element of
  the first qualifying powder wins (e7e7t7t7 and e7t7t7e7 both give Quake). Power
  from the pair's tiers: IV+IV 1, IV+V 2, V+V or IV+VI 3, V+VI or IV+VII 4,
  VI+VI or V+VII 5, VI+VII 6, VII+VII 7. Quake, Chain Lightning and Courage hits
  follow the main-attack path with a 240–480%, 200–350% or 110–200% conversion
  and no neutral. Armor specials give a % boost that depends on the fight
  (health missing, kills, mana spent, hits taken, time near mobs).
- Strength buffs from abilities (Fortitude, Vengeful Spirit, ...) don't stack
  in a party: the highest applies. Poison ticks every second for 3 s at a third
  of the ID, and nothing boosts it. Exploding hits nearby mobs for 50% of the
  main attack that set it off.

## Tested (in game)

- **Puppet hits trigger Stealing.** Tested by Hank, 2026-09-20.

## Unknown

- **How much a negative elemental defence costs in game.** WynnBuilder's
  numbers don't say (effective HP ignores elemental defences). Test: take the
  same hit from one element's mob with that defence negative, then positive.
- **A special's power with three or more powders of its element.** The guide
  gives pairs only; the tools use the two highest tiers. Test: e4e4e7 against
  e4e7 on the same weapon, compare the special's tooltip.
- Whether **totem ticks, hummingbirds, Crimson Effigy and Patchwork** trigger
  Stealing. Only puppets were tested. Counting every summon's hits (as the
  "summon hits/sec" in `wt decode` does) assumes all summons count; if only
  puppets do, puppet count is all that matters.
  *Test: equip one Stealing item, place only totems, count emeralds per minute.*
- Whether Stealing has a **cap**, or whether emeralds per proc scale with mob level.
- Whether **sigil and tornado ticks re-apply poison** on every hit. Poison Mage
  trees built around sigils and Frozen Tornado assume they do.
- Whether a **crafted item's IDs roll randomly** within the ingredient range when
  crafted. The tools treat the middle of the range as typical.
- **How obtainable ingredients are** (drop rates, trading). WynnBuilder's data
  says which mobs drop an ingredient and where (`wt ingredient`), but not how
  often; 152 of 972 ingredients list no mob at all.
- Whether two copies of the same tome can sit in paired slots (both mobXp slots,
  for example). WynnBuilder allows it. The tome-choosing search (`tome_pool`) keeps
  to the copies a player owns, but with `any` it can pick one twice.
- Tome "levels" (100, 120) are not player-level requirements (they exceed the
  level cap); the search doesn't filter tomes by level. Only guild tomes carry
  skill points (data), and only they count in item skill requirements.

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
| Per-slot shortlists treated as a full search | Missed better builds on 9 of 12 random specs (up to 6% worse) | `test_never_worse_than_shortlists_on_random_specs` (the exact search is now the default) |
| Base values treated as perfect rolls | Wand comparison overstated by ~40% vs. real items | AGENTS.md rule 3 |
| Tool totals compared to WynnBuilder's page | WynnBuilder shows 130% rolls, the tools 100% | `test_wynnbuilder_shows_perfect_rolls` |
| Crafting math drifting from WynnBuilder | Wrong stats for crafted gear | `tests/test_differential.py` |
