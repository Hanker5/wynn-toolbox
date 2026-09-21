"""Game formulas, each ported from the WynnBuilder source file noted beside it."""
import math

SKILLS = ["str", "dex", "int", "def", "agi"]

# js/build_utils.js `baseDamageMultiplier`: attacks per second for each speed tier.
ATTACK_SPEED = {"SUPER_SLOW": 0.51, "VERY_SLOW": 0.83, "SLOW": 1.5, "NORMAL": 2.05,
                "FAST": 2.5, "VERY_FAST": 3.1, "SUPER_FAST": 4.3}

# js/builder/atree.js `atree_level_table`: ability points available at each level.
_AP_TABLE = [0, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 8, 8, 9, 9, 10, 11, 11, 12, 12, 13, 14, 14,
             15, 16, 16, 17, 17, 18, 18, 19, 19, 20, 20, 20, 21, 21, 22, 22, 23, 23, 23, 24, 24,
             25, 25, 26, 26, 27, 27, 28, 28, 29, 29, 30, 30, 31, 31, 32, 32, 33, 33, 34, 34, 34,
             35, 35, 35, 36, 36, 36, 37, 37, 37, 38, 38, 38, 38, 39, 39, 39, 39, 40, 40, 40, 40,
             41, 41, 41, 41, 42, 42, 42, 42, 43, 43, 43, 43, 44, 44, 44, 44, 45, 45, 45, 46, 46,
             46, 47, 47, 47, 48, 48, 48, 49, 49, 49, 49, 50, 50]
MAX_LEVEL = 121

# js/build_utils.js `maxRolls`/`minRolls`: positive IDs roll 30-130% of the stored
# base value. Database values are therefore 100% rolls, not perfect rolls.
ROLL_MIN, ROLL_MAX = 0.3, 1.3


def skill_points(level):
    """js/build_utils.js `levelToSkillPoints`."""
    if level < 1:
        return 0
    return 200 if level >= 101 else (level - 1) * 2


def base_hp(level):
    """js/build_utils.js `levelToHPBase`."""
    return 5 * min(max(level, 1), MAX_LEVEL) + 5


def ability_points(level):
    return _AP_TABLE[min(max(level, 0), MAX_LEVEL)]


def sp_to_pct(sp):
    """js/build_utils.js `skillPointsToPercentage` (diminishing returns, caps at 150)."""
    if sp <= 0:
        return 0.0
    sp = min(sp, 150)
    r = 0.9908
    return (r / (1 - r) * (1 - r ** sp)) / 100.0


def max_mana(bonus_mana, total_int):
    """js/display.js `#maxManaTotal`: 100 base + item/tome Max Mana + Intelligence bonus."""
    return 100 + bonus_mana + math.floor(sp_to_pct(total_int) * 100)


def poison_per_second(poison):
    """js/display.js shows poison as floor(poison / 3) damage per second."""
    return poison // 3
