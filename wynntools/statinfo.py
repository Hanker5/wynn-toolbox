"""Names and groups for every item stat the searches take as a goal, minimum or
maximum (the web form's stat pickers, and labels in explanations)."""
from .rules import ROLLED_IDS

ELEM = {"e": "Earth", "t": "Thunder", "w": "Water", "f": "Fire", "a": "Air",
        "n": "Neutral", "r": "Rainbow (all elements)"}

_BASIC = {
    "hp": "Health (base)", "hpBonus": "Health bonus", "hprRaw": "Health regen (raw)",
    "hprPct": "Health regen %", "healPct": "Healing efficiency %", "ls": "Life steal",
    "thorns": "Thorns %", "ref": "Reflection %", "expd": "Exploding %", "poison": "Poison",
    "mr": "Mana regen", "maxMana": "Max mana", "ms": "Mana steal",
    "spd": "Walk speed %", "sprint": "Sprint %", "sprintReg": "Sprint regen %",
    "jh": "Jump height", "kb": "Knockback %", "slowEnemy": "Slow enemy %",
    "weakenEnemy": "Weaken enemy %", "atkTier": "Attack speed tier",
    "mainAttackRange": "Main attack range %", "eSteal": "Stealing", "lb": "Loot bonus",
    "xpb": "XP bonus", "lq": "Loot quality", "gXp": "Gathering XP", "gSpd": "Gathering speed",
    "spRegen": "Soul point regen", "damAddMin": "Damage, min bonus", "damAddMax": "Damage, max bonus",
    **{f"{c}Def": f"{n} defence (raw)" for c, n in ELEM.items() if c in "etwfa"},
    "critDamPct": "Critical damage %",
    "damPct": "Damage %", "damRaw": "Damage (raw)", "mdPct": "Main attack damage %",
    "mdRaw": "Main attack damage (raw)", "sdPct": "Spell damage %", "sdRaw": "Spell damage (raw)",
}
GROUPS = [
    ("Health and healing", ["hp", "hpBonus", "hprRaw", "hprPct", "healPct", "ls", "thorns", "ref", "expd", "poison"]),
    ("Mana", ["mr", "ms", "maxMana"]),
    ("Movement and utility", ["spd", "sprint", "sprintReg", "jh", "kb", "slowEnemy", "weakenEnemy",
                              "atkTier", "mainAttackRange"]),
    ("Economy", ["eSteal", "lb", "xpb", "lq", "gXp", "gSpd", "spRegen"]),
    ("Damage", ["critDamPct", "damPct", "damRaw", "mdPct", "mdRaw", "sdPct", "sdRaw"]),
]


def _label(k):
    if k in _BASIC:
        return _BASIC[k]
    if k.endswith("Final") and k.startswith("spPct"):
        return f"Spell {k[5]} cost % (final)"
    if k.startswith(("spPct", "spRaw")):
        return f"Spell {k[5]} cost {'%' if k[2:4] == 'Pc' else '(raw)'}"
    if k[0] in ELEM:
        el, rest = ELEM[k[0]], k[1:]
        kinds = {"DefPct": "defence %", "DamPct": "damage %", "DamRaw": "damage (raw)",
                 "MdPct": "main attack damage %", "MdRaw": "main attack damage (raw)",
                 "SdPct": "spell damage %", "SdRaw": "spell damage (raw)",
                 "DamAddMin": "damage, min bonus", "DamAddMax": "damage, max bonus"}
        if rest in kinds:
            return f"{el} {kinds[rest]}"
    return k


def catalog(stat_keys):
    """[(group, [(key, label), ...]), ...] over `stat_keys`, every one exactly once."""
    left = set(stat_keys)
    out = []

    def take(group, keys):
        ks = [k for k in keys if k in left]
        left.difference_update(ks)
        if ks:
            out.append((group, [(k, _label(k)) for k in ks]))
    for g, keys in GROUPS:
        take(g, keys)
    for c in "etwfarn":
        take(ELEM[c].split(" (")[0], sorted(k for k in left if k[0] == c and k[1:2].isupper()))
    take("Spell costs", sorted(k for k in left if k.startswith(("spPct", "spRaw"))))
    take("Other", sorted(left))
    return out


LABELS = {k: _label(k) for k in ROLLED_IDS | {"hp", "hpBonus"}}
