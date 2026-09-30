"""Links made with an older version's data: read with that data, then brought to
today's (wynntools/upgrade.py). The old links here are made by our encoder with
the old version's data; test_differential checks that encoder against
WynnBuilder's decoder for those versions."""
import shutil

import pytest

from wynntools import cli, data
from wynntools.codec import BASE_URL, Build, decode, encode
from wynntools.data import VERSIONS, GameData
from wynntools.diagnose import diagnose_link
from wynntools.upgrade import _stat_changes, read_link
from wynntools.verify import check_link

OLD = {"2.1.3.0": 19, "2.2.0.0": 24, "2.2.3.0": 33}


def old_link(gd, build, version):
    """`build` (today's data) as a link made with `version`'s data: the tree is
    carried over by node name; tomes that version lacks are left out."""
    og = GameData(version)
    tree = set()
    if build.weapon:
        names = {n["id"]: n["display_name"] for n in gd.tree(gd.weapon_class(build.weapon))}
        old = {n["display_name"]: n["id"] for n in og.tree(og.weapon_class(build.weapon))}
        tree = {old[names[i]] for i in build.atree if names[i] in old}
    b = Build(list(build.equipment), min(build.level, og.enc["MAX_LEVEL"]), build.powders,
              [t if t in og.tome_by_id else None for t in build.tomes], build.skillpoints,
              None, tree, version)
    return BASE_URL + encode(b, og)


def fits(build, version):
    og = GameData(version)
    return all(n is None or n in og.item_by_name for n in build.equipment)


@pytest.fixture(scope="module")
def old_links(gd, links):
    """For each old version, a session build whose items all existed then."""
    out = {}
    for name, v in OLD.items():
        b = next(b for b in (decode(L["hash"], gd) for L in links.values()) if fits(b, v))
        out[name] = old_link(gd, b, v)
    return out


@pytest.mark.parametrize("version", sorted(OLD))
def test_old_link_is_read_with_its_own_data_and_brought_to_todays(gd, old_links, version):
    ok, rep = check_link(old_links[version], gd)
    assert rep["upgraded"]["from"] == version
    b = rep["build"]
    assert b.version == data.latest()
    assert not any("round-trip" in p for p in rep["problems"])
    # the link handed out is today's, and reads back as the same build
    now = decode(rep["link"].split("#")[1], gd)
    assert now.version == data.latest()
    assert (now.equipment, now.tomes, now.atree, now.powders) == (b.equipment, b.tomes, b.atree, b.powders)
    ok2, rep2 = check_link(rep["link"], gd)
    assert rep2["upgraded"] is None
    assert (ok2, rep2["summary"]["totals"]) == (ok, rep["summary"]["totals"])


def test_changed_items_are_listed_with_old_values(gd, links):
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    _, info = read_link(old_link(gd, b, OLD["2.1.3.0"]), gd)
    changed = [n["message"] for n in info["notes"] if n["kind"] == "changed"]
    # 2.1.3.0's data is fixed, so its side of each change is too
    assert any(m.startswith("Leo (chestplate) changed: Health regen (raw) 240 → ") for m in changed)
    tome = next(m for m in changed if m.startswith("Everlasting Tome of Defensive Mastery II"))
    assert "(armorTome1, armorTome2, armorTome3, armorTome4)" in tome      # one note per tome
    assert not any("icon" in m or "lore" in m for m in changed)


def test_renamed_item_uses_todays_name(gd):
    b = Build([None] * 8 + ["Futulism"], 106, version=OLD["2.2.3.0"])
    new, info = read_link(BASE_URL + encode(b, GameData(OLD["2.2.3.0"])), gd)
    assert new.weapon == "Futilism"
    assert [n["kind"] for n in info["notes"]][:1] == ["renamed"]


def test_removed_item_empties_its_slot(gd):
    og = GameData(OLD["2.1.3.0"])
    b = Build(["Leo", None, None, None, None, None, None, None, "Bow Of Wisdom"], 60,
              atree={next(n["id"] for n in og.tree("Archer") if not n["parents"])},
              version=OLD["2.1.3.0"])
    new, info = read_link(BASE_URL + encode(b, og), gd)
    assert new.equipment[8] is None and new.equipment[0] == "Leo"
    assert new.atree == set()                   # no weapon, no class, no tree
    removed = [n for n in info["notes"] if n["kind"] == "removed"]
    assert [n["slot"] for n in removed] == ["weapon"]
    assert "Bow Of Wisdom" in removed[0]["message"]


def test_tree_nodes_are_matched_by_name_and_lost_ones_listed(gd):
    """Node ids and order change between versions; names carry the tree over."""
    v = OLD["2.2.3.0"]
    og = GameData(v)
    tree = og.tree("Shaman")
    today = {n["display_name"] for n in gd.tree("Shaman")}
    gone = sorted(n["display_name"] for n in tree if n["display_name"] not in today)
    assert gone                                  # 2.2.3.0 had Shaman nodes today's tree lacks
    b = Build([None] * 8 + ["Stormdrain"], 106, atree={n["id"] for n in tree}, version=v)
    new, info = read_link(BASE_URL + encode(b, og), gd)
    notes = [n["message"] for n in info["notes"] if n["kind"] == "tree"]
    assert notes[0] == "Ability nodes no longer in the tree: " + ", ".join(gone)
    names = {n["id"]: n["display_name"] for n in gd.tree("Shaman")}
    assert {names[i] for i in new.atree} <= {n["display_name"] for n in tree}
    from wynntools.verify import tree_activation
    assert not tree_activation(gd.tree("Shaman"), new.atree)[1]    # every kept node activates


def test_import_explains_what_changed(gd, links):
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    r = diagnose_link(old_link(gd, b, OLD["2.1.3.0"]), gd)
    codes = [f["code"] for f in r["findings"]]
    assert codes[0] == "old_version" and "changed_since" in codes
    head = r["findings"][0]
    assert head["level"] == "warn" and "2.1.3.0" in head["message"]
    assert r["doc"]["link"].split("#")[1] == encode(decode(r["doc"]["link"].split("#")[1], gd), gd)


def test_import_of_unchanged_old_link_is_only_a_note(gd):
    """Nothing in the build changed: the finding is info, nothing to warn about."""
    v = OLD["2.2.3.0"]
    og = GameData(v)
    same = next(og.name(i) for i in og.items if i["type"] == "necklace"
                and og.name(i) in gd.item_by_name and not _stat_changes(i, gd.item(og.name(i))))
    b = Build([None] * 7 + [same, None], 106, version=v)
    r = diagnose_link(BASE_URL + encode(b, og), gd)
    assert [(f["level"], f["code"]) for f in r["findings"]][:1] == [("info", "old_version")]
    assert "changed_since" not in [f["code"] for f in r["findings"]]


def test_old_link_offline_says_so(gd, links, tmp_path, monkeypatch):
    latest_dir = data.CACHE_DIR / VERSIONS[-1]
    link = old_link(gd, decode(links["shaman_105_stormdrain"]["hash"], gd), OLD["2.2.3.0"])
    shutil.copytree(latest_dir, tmp_path / VERSIONS[-1])
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)

    def offline(url, timeout):
        raise OSError("no network")
    monkeypatch.setattr(data, "_download", offline)
    data.load.cache_clear()
    try:
        r = diagnose_link(link, GameData())
    finally:
        data.load.cache_clear()
    assert not r["ok"]
    assert [f["code"] for f in r["findings"]] == ["offline"]


def test_verify_prints_todays_link_for_an_old_one(gd, links, capsys):
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    link = old_link(gd, b, OLD["2.2.3.0"])
    with pytest.raises(SystemExit):
        cli.main(["verify", link])
    out = capsys.readouterr().out
    assert "made with WynnBuilder's data for 2.2.3.0" in out
    today = next(line for line in out.splitlines() if line.startswith("Today's link"))
    ok, rep = check_link(today.split(": ", 1)[1], gd)
    assert rep["upgraded"] is None
