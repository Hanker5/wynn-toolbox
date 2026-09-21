from wynntools.rules import (ability_points, base_hp, max_mana, poison_per_second,
                             skill_points)


def test_level_tables():
    assert [ability_points(l) for l in (104, 105, 107, 121)] == [45, 45, 46, 50]
    assert skill_points(100) == 198 and skill_points(105) == 200
    assert base_hp(105) == 530


def test_intelligence_gives_mana():
    assert max_mana(0, 0) == 100
    assert max_mana(0, 40) == 133
    assert max_mana(13, 0) == 113


def test_poison_is_per_three_seconds():
    assert poison_per_second(91400) == 30466


def test_roll_modes_match_wynnbuilder_expand_item():
    from wynntools.rules import rolled
    assert rolled("poison", 24000, "max") == 31200       # perfect Sequoia
    assert rolled("poison", 24000, "min") == 7200
    assert rolled("poison", 24000, "base") == 24000
    assert rolled("eSteal", 1, "min") == 1               # idRound never rounds to 0
    assert rolled("mr", -6, "max") == -4                 # negative IDs: best roll is 70%
    assert rolled("spRaw1", -5, "max") == -6             # reversed IDs: -5*1.3=-6.5, JS rounds to -6
    assert rolled("str", 7, "max") == 7                  # skill points never roll
    assert rolled("poison", 100, "max", fixed=True) == 100


def test_wynnbuilder_shows_perfect_rolls(gd, links):
    from wynntools.codec import decode
    from wynntools.verify import summarize
    s = summarize(decode(links["mage_105_sequoia"]["hash"], gd), gd)
    assert s["totals"]["poison"] == 91400
    assert s["totals_max"]["poison"] > s["totals"]["poison"] * 1.29
