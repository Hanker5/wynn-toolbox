"""Ability-tree objectives.

A preset is a set of node weights handed to the tree solver. There is one
generic preset per archetype of every class, for any player; none is tuned for
a particular goal. The weights are judgment calls, not facts; each preset says
what it rewards.
"""

# One starting-point preset per archetype, for every class. The node lists come
# from WynnBuilder's tree data when solved, so they follow game patches; nothing
# here is a claim about which nodes are strong.
ARCHETYPES = {
    "Archer": ("Boltslinger", "Sharpshooter", "Trapper"),
    "Assassin": ("Shadestepper", "Trickster", "Acrobat"),
    "Warrior": ("Fallen", "Battle Monk", "Paladin"),
    "Mage": ("Light Bender", "Arcanist", "Riftwalker"),
    "Shaman": ("Summoner", "Ritualist", "Acolyte"),
}
SPELL_WEIGHT = 5      # each of the class's four spells: always worth taking
ARCHETYPE_WEIGHT = 1  # each node of the chosen archetype, whatever its cost

PRESETS = {}
for _cls, _names in ARCHETYPES.items():
    for _arch in _names:
        PRESETS[f"{_cls.lower()}-{_arch.lower().replace(' ', '-')}"] = {
            "class": _cls, "archetype": _arch,
            "about": (f"Generic {_arch} tree: all four {_cls} spells, then as many {_arch} "
                      f"nodes as the ability points allow, each valued the same. A starting "
                      f"point for a player who plays {_arch}, not tuned for any goal: it "
                      f"ignores the other archetypes and doesn't weigh damage or utility."),
        }


def archetype_weights(tree, archetype):
    """Weights for an archetype preset: the first node that unlocks each spell
    (in tree order), and every node of the archetype."""
    weights = {}
    spells = set()
    for n in sorted(tree, key=lambda n: (n["display"]["row"], n["display"]["col"])):
        name = n["display_name"]
        if n.get("archetype") == archetype:
            weights[name] = ARCHETYPE_WEIGHT
        for e in n.get("effects") or []:
            b = e.get("base_spell")
            if e.get("type") == "replace_spell" and b in (1, 2, 3, 4) and b not in spells \
                    and not n.get("archetype"):
                spells.add(b)
                weights[name] = SPELL_WEIGHT
    return weights


def preset_weights(name, gd):
    """The node weights for preset `name`, resolved against the current tree."""
    P = PRESETS[name]
    return archetype_weights(gd.tree(P["class"]), P["archetype"])


def summoner_hits_per_sec(tree, selected):
    """(steady, buffed) summon + beam hits per second for a Shaman tree selection.

    Rates come from the tree properties: puppets attack 2/s, totems tick 2.5/s,
    hummingbirds 4/s each, effigy 2/s, Patchwork 0.8/s. Buffed adds Invigorating
    Wave (+1.2 puppet, +0.75 totem) and Commander (+0.5 puppet). Beams are left
    out because they depend on the weapon.
    """
    on = {n["display_name"] for n in tree if n["id"] in selected}
    puppets = ("Puppet Master" in on) * (3 + ("More Puppets" in on)
                                         + 2 * ("More Puppets II" in on) + 2 * ("Puppetry" in on))
    totems = 1 + ("Double Totem" in on) + ("Triple Totem" in on)
    extra = 8 * ("Hummingbird's Song" in on) + 2 * ("Crimson Effigy" in on) \
        + 0.8 * ("Patchwork Abomination" in on)
    steady = puppets * 2 + totems * 2.5 + extra
    p_freq = 2 + 1.2 * ("Invigorating Wave" in on) + 0.5 * ("Commander" in on)
    t_rate = 2.5 + 0.75 * ("Invigorating Wave" in on)
    return steady, puppets * p_freq + totems * t_rate + extra
