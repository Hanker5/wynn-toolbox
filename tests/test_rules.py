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
