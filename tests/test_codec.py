import pytest

from wynntools.codec import Build, decode, encode


def test_session_links_round_trip(gd, links):
    """Every link handed out in the design session re-encodes byte-for-byte."""
    for name, fx in links.items():
        b = decode(fx["hash"], gd)
        assert encode(b, gd) == fx["hash"], name
        tomes = sum(t is not None for t in b.tomes)
        assert (b.weapon, b.level, len(b.atree), tomes) == \
            (fx["weapon"], fx["level"], fx["tree_nodes"], fx["tomes"]), name


def test_original_user_build(gd, links):
    b = decode(links["original_user_build"]["hash"], gd)
    assert b.equipment == ["Dark Matter", "Gravity", "Neutrino", "Fermion", "Morph-Emerald",
                           "Old Keeper's Ring", "Discordant", "Jackpot", "Procrastination"]


def test_powders_skillpoints_aspects_self_consistent(gd, links):
    """Encoder and decoder agree on powders, assigned skill points and aspects.

    NOTE: only self-consistency. No real WynnBuilder link with these fields has
    been checked yet; add one to fixtures/links.json when available.
    """
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    b.powders = [[5, 5, 12], [], [33, 26, 5], [], [5, 5, 5, 19, 12]]
    b.skillpoints = [67, None, -3, 46, None]
    b.aspects = [(1, 4), None, (7, 2), None, None]
    b2 = decode(encode(b, gd), gd)
    assert (b2.powders, b2.skillpoints, b2.aspects, b2.atree) == \
        (b.powders, b.skillpoints, b.aspects, b.atree)


def test_legacy_links_rejected(gd):
    with pytest.raises(NotImplementedError):
        decode("5_0Ow0Qh0cX0", gd)
