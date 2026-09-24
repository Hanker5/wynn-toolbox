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


def _with_manual(links, gd, manual):
    from wynntools.codec import encode
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    b.skillpoints = manual
    return b, encode(b, gd)


def test_partial_manual_skill_points_are_final_totals(gd, links):
    """Regression: a link with only some skills set by hand (null for the rest)
    crashed the damage calculation while the build still showed as verified.
    WynnBuilder stores a manual entry as the skill's final total; the points
    assigned are final - automatic final + automatic assigned."""
    from wynntools.damage import summary
    auto = check_link(links["shaman_105_stormdrain"]["hash"], gd)[1]["summary"]
    target = auto["sp_final"]["int"] + 20
    b, h = _with_manual(links, gd, [None, None, target, None, None])
    assert decode(h, gd).skillpoints == [None, None, target, None, None]
    ok, rep = check_link(h, gd)
    s = rep["summary"]
    assert ok, rep["problems"]
    assert s["sp_final"]["int"] == target and s["sp_manual"]["int"] and not s["sp_manual"]["str"]
    assert s["sp_need"]["int"] == auto["sp_need"]["int"] + 20
    assert s["sp_total"] == auto["sp_total"] + 20
    assert s["sp_final"]["str"] == auto["sp_final"]["str"]           # automatic ones unchanged
    dmg = summary(b, gd)
    assert "error" not in dmg
    auto_cost = summary(decode(links["shaman_105_stormdrain"]["hash"], gd), gd)
    assert dmg["typical"]["spells"][1]["cost"] < auto_cost["typical"]["spells"][1]["cost"]  # more Int


def test_manual_points_too_low_to_wear_the_gear(gd, links):
    auto = check_link(links["shaman_105_stormdrain"]["hash"], gd)[1]["summary"]
    _, h = _with_manual(links, gd, [auto["sp_final"]["str"] - 10, None, None, None, None])
    ok, rep = check_link(h, gd)
    assert not ok and any("too low to wear" in p and "Strength" in p for p in rep["problems"])


def test_manual_points_over_budget_and_over_100(gd, links):
    auto = check_link(links["shaman_105_stormdrain"]["hash"], gd)[1]["summary"]
    _, h = _with_manual(links, gd, [None, None, None, None, 101])     # Agi: 0 assigned now
    ok, rep = check_link(h, gd)
    assert not ok
    assert any("more than 100 points" in p and "Agility 101" in p for p in rep["problems"])
    assert any("assigns 266 skill points" in p for p in rep["problems"]), auto["sp_total"]


def test_malformed_skill_points_in_a_build_file_are_rejected(gd, links):
    import pytest
    from wynntools import buildfile
    doc = buildfile.from_build(decode(links["shaman_105_stormdrain"]["hash"], gd), gd)
    for bad, msg in (([1, 2, 3], "list of 5"), ([None, "40", None, None, None], "whole number"),
                     ([None, None, 5000, None, None], "outside"), ({"str": 1}, "list of 5")):
        with pytest.raises(ValueError, match=msg):
            buildfile.to_build({**doc, "skillpoints": bad}, gd)


def test_damage_failure_is_never_verified(gd, links, monkeypatch):
    from wynntools import buildfile, damage
    doc = buildfile.from_build(decode(links["shaman_105_stormdrain"]["hash"], gd), gd)
    monkeypatch.setattr(damage, "summary", lambda *a, **k: {"error": "TypeError: boom"})
    st = buildfile.refresh(doc, gd)["status"]
    assert not st["verified"] and any("damage could not be calculated" in p for p in st["problems"])
