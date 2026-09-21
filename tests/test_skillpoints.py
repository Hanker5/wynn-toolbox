from wynntools.codec import decode
from wynntools.verify import build_skillpoints, check_link, sp_requirements


def test_negative_bonuses_count(gd):
    """Regression: Gaea-Hewn Boots give -30 Dex / -30 Agi.

    The first solver ignored negative bonuses and called this build feasible;
    WynnBuilder reported "Too many skillpoints need to be assigned!".
    """
    names = ["Phoenix Prince's Crown", "Discoverer", "Trench Scourer", "Gaea-Hewn Boots",
             "Old Keeper's Ring", "Sarnfic's Lost Treasure", "Vindicator",
             "Bronze Basic Necklace", "The Watched"]
    need = sp_requirements([gd.item(n) for n in names])       # quick lower-bound model
    assert need == [40, 65, 50, 35, 65] and sum(need) > 200
    exact = build_skillpoints(names, [None] * 14, gd)          # WynnBuilder's calculation
    assert exact.total_assigned > 200


def test_matches_wynnbuilder_page(gd, links):
    """Numbers read off WynnBuilder's own build page for these links (2026-09-21)."""
    _, rep = check_link(links["shaman_105_stormdrain"]["hash"], gd)
    s = rep["summary"]
    assert s["sp_total"] == 165                      # "Assigned 165 skillpoints"
    assert s["sp_need"] == {"str": 67, "dex": 0, "int": 52, "def": 46, "agi": 0}
    assert s["totals_max"]["hp"] == 19236 and s["totals_max"]["ms"] == 42
    _, rep = check_link(links["original_user_build"]["hash"], gd)
    s = rep["summary"]
    assert s["sp_total"] == 200 and s["totals_max"]["hp"] == 19208 and s["totals_max"]["ms"] == 20
    assert s["sets"][0]["name"] == "Cosmic Foundations" and s["sets"][0]["pieces"] == 4


def test_all_session_links_verify(gd, links):
    for name, fx in links.items():
        ok, rep = check_link(fx["hash"], gd)
        assert ok, (name, rep["problems"])


def test_negative_bonus_only_matters_against_a_requirement(gd, links):
    """Checked on WynnBuilder's page: Gaea-Hewn Boots (-30 Dex/-30 Agi) in the
    Stormdrain build need 160 points, since nothing else requires Dex or Agi.
    The old model wrongly assigned points to cancel the negatives (220)."""
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    b.equipment[3] = "Gaea-Hewn Boots"
    assert build_skillpoints(b.equipment, b.tomes, gd).total_assigned == 160
    b.equipment[8] = "The Watched"                       # needs 30 in every skill
    assert build_skillpoints(b.equipment, b.tomes, gd).total_assigned == 265
