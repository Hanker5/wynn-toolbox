"""Ability-tree objectives.

A preset is a set of node weights handed to the tree solver. The weights are
judgment calls, not facts; each preset says what it rewards and why. Nodes are
named rather than numbered because ids can shift between game versions.
"""

PRESETS = {
    "summoner-stealing": {
        "class": "Shaman",
        "about": ("Maximize hits per second. Stealing rolls on every hit, including puppet "
                  "hits (tested in game), and ignores damage, so summon count is what "
                  "matters. Totem damage penalties from Double/Triple Totem are irrelevant."),
        # Weights are hits/sec added (see summoner_hits_per_sec), plus small utility values.
        "weights": {
            "Puppet Master": 6, "More Puppets": 2, "More Puppets II": 4, "Puppetry": 4,
            "Totem": 2.5, "Double Totem": 2.5, "Triple Totem": 2.5, "Crimson Effigy": 2,
            "Hummingbird's Song": 8,
            # Aura buff: +1.2 puppet attacks/s on 8 puppets, +0.75 totem ticks/s on 3 totems
            "Invigorating Wave": 11.85,
            "Patchwork Abomination": 2.0, "Fortified Formation": 1.0,
            "Nature's Jolt": 0.5, "Crystal Knives": 0.4, "Shepherd": 0.3, "Earth Mastery": 0.3,
            "Friendly Fire": 0.2, "Slingshot": 0.2, "Maddening Roots": 0.15, "Bullwhip": 0.15,
        },
    },
    "mage-poison-lightbender": {
        "class": "Mage",
        "about": ("The Mage tree has no poison nodes, so reward what poison can use: cheaper "
                  "spells, persistent AoE that re-applies poison (sigils, snakes), and "
                  "healing to survive while poison ticks."),
        "weights": {
            "Cheaper Meteor I": 3.3, "Cheaper Teleport": 1.7, "Cheaper Heal": 1.7,
            "Cheaper Ice Snake": 1.7, "Cheaper Teleport II": 1.7, "Cheaper Ice Snake II": 1.7,
            "Cheaper Meteor II": 1.7, "Cheaper Heal II": 1.7,
            "Ice Snake": 3.0, "Meteor": 3.0, "Sunshower": 2.5, "Heal": 3.5, "Ophanim": 3.0,
            "Sunflare": 2.0, "Wisdom": 2.5, "Teleport": 1.0,
            "Burning Sigil": 4.0, "Freezing Sigil": 3.0, "Snake Nest": 3.5,
            "Sentient Snake": 2.0, "Arctic Snake": 1.5, "Divination": 2.0,
            "Frigid Grasp": 1.0, "Blitz": 1.0, "Incandescence": 1.0, "Gleam": 1.0,
        },
    },
}

# Riftwalker variant: same base, plus hit-frequency nodes weighted on the same
# basis as the sigils. The first Mage tree gave Riftwalker zero weight by oversight.
PRESETS["mage-poison-riftwalker"] = {
    "class": "Mage",
    "about": ("Like mage-poison-lightbender, but also rewards Riftwalker's repeated-hit "
              "mechanics (Frozen Tornado every 0.5s, Meteor Shower, Portal to the Beyond) "
              "to spread poison and PLAGUE across packs."),
    "weights": {**PRESETS["mage-poison-lightbender"]["weights"],
                "Frozen Tornado": 4.0, "Meteor Shower": 3.5, "Portal to the Beyond": 3.0,
                "Dimensional Tear": 2.0, "Distortion": 2.0, "Etheric Slash": 2.0,
                "Astral Fragmentation": 2.5, "Time Vortex": 2.0, "Devitalize": 1.5,
                "Paradox": 1.5},
}

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
    if "archetype" in P:
        return archetype_weights(gd.tree(P["class"]), P["archetype"])
    return P["weights"]


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
