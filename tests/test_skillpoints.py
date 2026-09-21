from wynntools.codec import decode
from wynntools.verify import check_link, sp_requirements


def test_negative_bonuses_count(gd):
    """Regression: Gaea-Hewn Boots give -30 Dex / -30 Agi.

    The first solver ignored negative bonuses and called this build feasible;
    WynnBuilder reported "Too many skillpoints need to be assigned!".
    """
    names = ["Phoenix Prince's Crown", "Discoverer", "Trench Scourer", "Gaea-Hewn Boots",
             "Old Keeper's Ring", "Sarnfic's Lost Treasure", "Vindicator",
             "Bronze Basic Necklace", "The Watched"]
    need = sp_requirements([gd.item(n) for n in names])
    assert need == [40, 65, 50, 35, 65]
    assert sum(need) > 200


def test_tome_bonuses_count(gd, links):
    """Guild tomes grant skill points; the Stormdrain build needs 160 with them."""
    ok, rep = check_link(links["shaman_105_stormdrain"]["hash"], gd)
    assert ok and rep["summary"]["sp_total"] == 160


def test_all_session_links_verify(gd, links):
    for name, fx in links.items():
        ok, rep = check_link(fx["hash"], gd)
        assert ok, (name, rep["problems"])
