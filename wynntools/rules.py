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


# js/build_utils.js `rolledIDs` / `reversedIDs`. Everything else (hp, skill points,
# requirements, damage ranges) is static and never rolls.
ROLLED_IDS = frozenset("""
hprPct mr sdPct mdPct ls ms xpb lb ref thorns expd spd atkTier poison hpBonus spRegen eSteal
hprRaw sdRaw mdRaw fDamPct wDamPct aDamPct tDamPct eDamPct fDefPct wDefPct aDefPct tDefPct
eDefPct spPct1 spRaw1 spPct2 spRaw2 spPct3 spRaw3 spPct4 spRaw4 rSdRaw sprint sprintReg jh lq
gXp gSpd eMdPct eMdRaw eSdPct eSdRaw eDamRaw eDamAddMin eDamAddMax tMdPct tMdRaw tSdPct tSdRaw
tDamRaw tDamAddMin tDamAddMax wMdPct wMdRaw wSdPct wSdRaw wDamRaw wDamAddMin wDamAddMax fMdPct
fMdRaw fSdPct fSdRaw fDamRaw fDamAddMin fDamAddMax aMdPct aMdRaw aSdPct aSdRaw aDamRaw
aDamAddMin aDamAddMax nMdPct nMdRaw nSdPct nSdRaw nDamPct nDamRaw nDamAddMin nDamAddMax damPct
damRaw damAddMin damAddMax rMdPct rMdRaw rSdPct rDamPct rDamRaw rDamAddMin rDamAddMax critDamPct
spPct1Final spPct2Final spPct3Final spPct4Final healPct kb weakenEnemy slowEnemy rDefPct maxMana
mainAttackRange""".split())
REVERSED_IDS = frozenset("spPct1 spRaw1 spPct2 spRaw2 spPct3 spRaw3 spPct4 spRaw4".split())
ROLLS = ("min", "base", "max")


def js_round(x):
    """JavaScript Math.round: halves round up (Python's round() rounds to even)."""
    return math.floor(x + 0.5)


def id_round(x):
    """js/build_utils.js `idRound`: never rounds a non-zero roll to 0."""
    r = js_round(x)
    return r if r != 0 else (x > 0) - (x < 0)


def rolled(key, base, roll="base", fixed=False):
    """Value of an ID at a roll: "base" (100%, the stored value), "max" (a perfect
    roll: what WynnBuilder's build totals show), or "min" (the worst roll)."""
    if roll == "base" or fixed or not base or key not in ROLLED_IDS:
        return base
    good = (base > 0) != (key in REVERSED_IDS)
    if roll == "max":
        return id_round(base * (1.3 if good else 0.7))
    return id_round(base * (0.3 if good else 1.3))
