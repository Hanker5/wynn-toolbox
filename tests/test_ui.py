"""Drive the web app in headless Chromium (Playwright).

Each check here was a real bug found by looking at the page in a browser:
hidden panels showing anyway, an empty preset dropdown, and every browser save
failing with a conflict because nanosecond file stamps rounded in JavaScript.

    uv run pytest -m ui        # needs: uv run playwright install chromium
"""
import json
import re
import shutil
from pathlib import Path

import pytest

from wynntools import buildfile
from wynntools.codec import decode

pytestmark = pytest.mark.ui
playwright = pytest.importorskip("playwright.sync_api")

from tests.ui.harness import AppServer  # noqa: E402


@pytest.fixture()
def app(tmp_path, gd, links):
    for name, key in [("stormdrain.json", "shaman_105_stormdrain"), ("crafted.json", "shaman_105_crafted"),
                      ("gaia.json", "mage_105_gaia_lightbender"), ("original.json", "original_user_build")]:
        doc = buildfile.from_build(decode(links[key]["hash"], gd), gd)
        buildfile.write(tmp_path / name, buildfile.refresh({"name": key, **doc}, gd))
    with AppServer(str(tmp_path), terminal_cwd=str(tmp_path)) as srv:
        yield srv


@pytest.fixture()
def page(app):
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:                       # browser not installed
            pytest.skip(f"headless Chromium unavailable: {e}")
        pg = browser.new_page(viewport={"width": 1440, "height": 1000})
        pg.errors = []
        pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.goto(app.url)
        pg.wait_for_selector("#build-list li")
        yield pg
        browser.close()


def open_build(pg, name):
    pg.click(f"#build-list li:has-text('{name}')")
    pg.wait_for_selector("#ed-badge .badge.ok, #ed-badge .badge.bad", timeout=20000)


def settle(pg):
    pg.wait_for_function(
        "!document.querySelector('#ed-badge .badge').textContent.includes('checking')", timeout=20000)


def test_hidden_panels_stay_hidden_and_sidebar_classes(page):
    assert page.locator("#terminal-panel").is_hidden()
    assert page.inner_text("#build-list li:has-text('shaman_105_crafted')").count("Shaman") == 1
    open_build(page, "shaman_105_crafted")
    assert page.locator(".craft-box").first.is_hidden()
    assert "allowCraftsman" not in page.inner_text("#ed-tomes")
    assert not page.errors


def test_bad_swap_is_flagged_live(page):
    """Gaea-Hewn Boots alone are fine (WynnBuilder: 160 points); adding The Watched,
    which needs 30 in every skill, makes WynnBuilder warn (265 points)."""
    open_build(page, "shaman_105_stormdrain")
    boots = page.locator("input[aria-label='boots']")
    boots.fill("Gaea-Hewn")
    page.locator(".ac-item", has_text="Gaea-Hewn Boots").first.click()
    settle(page)
    assert "Verified" in page.inner_text("#ed-badge")
    weapon = page.locator("input[aria-label='weapon']")
    weapon.fill("The Watched")
    page.locator(".ac-item", has_text="The Watched").first.click()
    settle(page)
    assert "problem" in page.inner_text("#ed-badge")
    assert "skill points" in page.inner_text("#ed-banners")
    assert page.is_enabled("#ed-save")


def test_save_from_browser_reaches_disk(page, app):
    """Regression: every browser save used to fail with 409 (rounded file stamp)."""
    open_build(page, "shaman_105_stormdrain")
    page.locator(".slot:has(input[aria-label='ring2']) button:has-text('Craft')").click()
    page.wait_for_selector(".craft-opt", timeout=60000)
    page.locator(".craft-opt button").first.click()
    settle(page)
    page.click("#ed-save")
    page.wait_for_function("document.querySelector('#toast').textContent.startsWith('Saved')", timeout=10000)
    saved = json.loads((Path(app.builds_dir) / "stormdrain.json").read_text())
    assert saved["equipment"][5].startswith("CR-")
    assert saved["status"]["verified"]
    assert not page.errors


def test_delete_asks_first_then_undo_brings_the_build_back(page, app):
    open_build(page, "shaman_105_crafted")
    page.click("#ed-delete")
    page.click("#ask button:has-text('Cancel')")
    assert (Path(app.builds_dir) / "crafted.json").exists()
    page.click("#ed-delete")
    assert page.is_visible("#ask p:has-text('builds/.trash')")
    page.click("#ask button:has-text('Delete')")
    page.wait_for_selector("#empty:not([hidden])")
    assert not (Path(app.builds_dir) / "crafted.json").exists()
    assert page.locator("#build-list li:has-text('shaman_105_crafted')").count() == 0
    page.click("#toast button:has-text('Undo')")
    page.wait_for_selector("#build-list li.active:has-text('shaman_105_crafted')")
    assert (Path(app.builds_dir) / "crafted.json").exists()
    assert not page.errors


STRAY_TEXT_JS = """() => {
  const bad = [], w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) {
    const n = w.currentNode, t = n.textContent.trim();
    if (["null", "undefined", "false", "NaN"].includes(t) && n.parentElement.closest("body > *:not(script)"))
      bad.push(`${t} in ${n.parentElement.closest("[id]")?.id}`);
  }
  return bad;
}"""


def test_no_stray_null_text_anywhere(page):
    """Found by looking at a screenshot: plain replaceChildren() turned a skipped
    row (null) into a "null" line in the Damage panel of every build without poison."""
    found = []
    for li in range(page.locator("#build-list li").count()):
        page.locator("#build-list li").nth(li).click()
        page.wait_for_selector("#ed-badge .badge.ok, #ed-badge .badge.bad", timeout=20000)
        settle(page)
        for roll in ("Perfect", "Typical"):
            page.click(f"#roll-toggle button:has-text('{roll}')")
            found += page.evaluate(STRAY_TEXT_JS)
    for view in ("#new-build", "#open-inventory", "#open-compare"):
        page.click(view)
        page.wait_for_timeout(1500)
        found += page.evaluate(STRAY_TEXT_JS)
    assert not found, sorted(set(found))


FITS_JS = """() => {
  const b = (s) => document.querySelector(s).getBoundingClientRect().bottom;
  const main = document.querySelector('#main');
  main.scrollTop = main.scrollHeight;                  // scroll the page to its end
  const last = [...document.querySelectorAll('#editor > *')].pop();
  return {vh: innerHeight, main: b('#main'), panel: b('#terminal-panel'),
          screen: b('#term .xterm-screen'), term: b('#term'), last: last.getBoundingClientRect().bottom,
          doc: document.documentElement.scrollHeight};
}"""


def check_fits(pg, where):
    pg.wait_for_timeout(400)                            # the terminal refits after a resize
    m = pg.evaluate(FITS_JS)
    vh = m["vh"]
    assert m["main"] <= vh + 0.5 and m["panel"] <= vh + 0.5, (where, m)   # nothing below the window
    assert m["screen"] <= m["term"] + 0.5, (where, m)                    # last terminal row visible
    assert m["last"] <= m["main"] + 0.5, (where, m)                      # page scrolls to its end
    assert m["doc"] <= vh + 0.5, (where, m)                              # no stray page scrollbar


def _resize_and_check(pg):
    for w, hgt in [(1400, 1000), (1400, 600), (1100, 480), (1400, 900)]:   # shrink, then grow back
        pg.set_viewport_size({"width": w, "height": hgt})
        check_fits(pg, f"{w}x{hgt}")
    # every line of a long terminal output is reachable, the prompt last
    pg.click("#term")
    pg.keyboard.type("for i in $(seq 200); do echo line-$i; done; echo END-MARK\n")
    pg.wait_for_function("document.querySelector('#term .xterm-rows').innerText.includes('END-MARK')")
    rows = pg.locator("#term .xterm-rows > div")
    last_row = rows.nth(rows.count() - 1).bounding_box()
    assert last_row["y"] + last_row["height"] <= pg.evaluate("innerHeight") + 0.5


def test_page_and_terminal_fit_the_window_after_resizing(page):
    """Found by the player: after shrinking the window, the bottom of the page
    and of the terminal could no longer be scrolled to. The grid row grew to the
    terminal's old size, and the terminal was fitted 12px too tall (its padding
    was counted as room)."""
    open_build(page, "shaman_105_stormdrain")
    page.click("#toggle-terminal")
    page.wait_for_selector("#term .xterm-screen")
    _resize_and_check(page)
    assert not page.errors


def test_app_window_fits_after_resizing(tmp_path, gd, links):
    doc = buildfile.from_build(decode(links["shaman_105_stormdrain"]["hash"], gd), gd)
    buildfile.write(tmp_path / "storm.json", buildfile.refresh({"name": "storm", **doc}, gd))
    with AppServer(str(tmp_path), terminal_cwd=str(tmp_path)) as srv, playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"headless Chromium unavailable: {e}")
        pg = browser.new_page(viewport={"width": 1400, "height": 1000})
        pg.add_init_script(FAKE_PYWEBVIEW)
        pg.goto(srv.url)
        pg.wait_for_selector("#titlebar:not([hidden])")
        pg.click("#build-list li")
        pg.wait_for_selector("#ed-badge .badge.ok", timeout=20000)
        pg.click("#toggle-terminal")
        pg.wait_for_selector("#term .xterm-screen")
        _resize_and_check(pg)
        browser.close()


def test_outside_edit_appears_in_page(page, app):
    open_build(page, "shaman_105_stormdrain")
    f = Path(app.builds_dir) / "stormdrain.json"
    doc = json.loads(f.read_text())
    buildfile.write(f, {**doc, "notes": "edited by the AI"})
    page.wait_for_function(
        "document.querySelector('#editor textarea').value === 'edited by the AI'", timeout=15000)



def pick_rule(page, text):
    """Search the requirement picker and take the top match with Enter."""
    box = page.get_by_role("combobox", name="Add a requirement")
    box.fill(text)
    box.press("Enter")


def add_rule(page, text, value, name=None):
    """Add a requirement in the solver form: search it, then type its value."""
    pick_rule(page, text)
    page.get_by_role("spinbutton", name=name or text, exact=True).fill(str(value))


def open_fold(page, title):
    """Open a collapsed section of the solver form."""
    page.locator("details.fold > summary", has_text=title).click()


def test_solver_form_runs_and_opens_result(page):
    page.click("#new-build")
    page.get_by_role("combobox", name="Class").select_option("Mage")
    page.get_by_role("combobox", name="Maximize").select_option("poison")
    page.get_by_role("combobox", name="Tree preset").select_option("mage-riftwalker")
    add_rule(page, "health", 15000, "Health")
    add_rule(page, "mana regen", 20, "Mana regen")
    open_fold(page, "Items")
    page.get_by_role("combobox", name="Required major IDs").select_option("PLAGUE")
    page.get_by_role("textbox", name="Weapon (optional)").fill("Gaia")
    page.get_by_role("textbox", name="Name").fill("ui solver test")
    page.click("text=Find the best build")
    page.wait_for_selector("#editor:not([hidden]) #ed-badge .badge.ok", timeout=120000)
    assert page.input_value("#editor .name") == "ui solver test"
    assert "84,300" in page.inner_text("#ed-tiles")
    assert not page.errors


def test_terminal_runs_commands(page):
    page.click("#toggle-terminal")
    page.wait_for_selector("#terminal-panel:not([hidden]) .xterm", timeout=10000)
    page.wait_for_timeout(1500)
    page.locator(".xterm-helper-textarea").type("echo wt-ui-$((6*7))\n")
    page.wait_for_function("document.querySelector('#term').innerText.includes('wt-ui-42')", timeout=15000)
    assert not page.errors


def test_long_wt_commands_show_a_progress_bar_above_the_terminal(app, page):
    """A `wt` command that runs a while shows its label and a bar above the
    terminal; the section is hidden when nothing runs."""
    import time
    from wynntools.web import client
    page.click("#toggle-terminal")
    page.wait_for_selector("#terminal-panel:not([hidden]) .xterm", timeout=10000)
    assert page.locator("#term-tools").is_hidden()
    term_h = page.locator("#term").bounding_box()["height"]
    (Path(app.builds_dir) / ".server.json").write_text("{}")
    gear = client.ToolProgress(app.builds_dir, "Searching for gear", "wt gear spec.json", delay=0, beat=0.5)
    with gear:
        client.report(0.4, "12,000 checked · best 310")
        page.wait_for_selector("#term-tools:not([hidden]) .tool-run", timeout=10000)
        page.wait_for_function("document.querySelector('#term-tools .tool-stat').textContent.startsWith('40%')",
                               timeout=10000)
        assert page.inner_text("#term-tools .tool-label") == "Searching for gear"
        assert "wt gear spec.json" in page.inner_text("#term-tools .tool-cmd")
        bar = page.locator("#term-tools .progress")
        assert bar.get_attribute("aria-valuenow") == "40"
        assert page.evaluate("getComputedStyle(document.querySelector('#term-tools .progress i')).width")\
            .startswith("19")                             # 40% of the 490px-wide bar
        fetch = client.ToolProgress(app.builds_dir, "Downloading WynnBuilder data", "wt fetch", delay=0, beat=0.5)
        fetch.path = fetch.path.with_name("run-other-process.json")   # two commands at once
        with fetch:
            page.wait_for_function("document.querySelectorAll('#term-tools .tool-run').length === 2",
                                   timeout=10000)
            # the second command can't measure itself: its bar is estimated, and moves
            stat = page.locator("#term-tools .tool-stat").nth(1)
            assert stat.inner_text().startswith("~")
            first = page.locator("#term-tools .progress").nth(1).get_attribute("aria-valuenow")
            page.wait_for_function(
                f"document.querySelectorAll('#term-tools .progress')[1].getAttribute('aria-valuenow')"
                f" > {first}", timeout=15000)
            assert page.locator("#term").bounding_box()["height"] < term_h   # the terminal made room
            page.locator("#terminal-panel").screenshot(
                path="/tmp/claude-1000/-var-home-hhays-wynn-toolbox/"
                     "a1a639fd-bb84-4486-afbd-a4a1b66cd05f/scratchpad/tools.png")
    page.wait_for_selector("#term-tools", state="hidden", timeout=10000)
    assert not page.errors


def test_perfect_roll_toggle_matches_wynnbuilder_numbers(page, gd, links):
    """Typical shows 100% rolls; Perfect shows WynnBuilder's 130% numbers."""
    from wynntools.verify import summarize
    s = summarize(decode(links["shaman_105_stormdrain"]["hash"], gd), gd)
    want_typical, want_perfect = s["totals"]["eSteal"], s["totals_max"]["eSteal"]
    assert want_perfect > want_typical
    open_build(page, "shaman_105_stormdrain")
    page.click("#roll-toggle button:has-text('Typical')")
    typical = page.inner_text("#ed-tiles")
    page.click("#roll-toggle button:has-text('Perfect')")
    perfect = page.inner_text("#ed-tiles")
    assert f"+{want_typical}%" in typical and f"+{want_perfect}%" in perfect
    page.click("#roll-toggle button:has-text('Typical')")


def test_item_icons_and_tooltip(page):
    open_build(page, "shaman_105_stormdrain")
    sprite = page.locator(".slot:has(input[aria-label='boots']) .sprite")
    assert "/assets/items.png" in sprite.evaluate("e => e.style.backgroundImage")
    assert page.evaluate("fetch('/assets/items.png').then(r => r.status)") == 200
    page.hover(".slot:has(input[aria-label='boots']) .eq-icon-wrap")
    page.wait_for_selector("#tooltip:not([hidden]) .item-card", timeout=5000)
    card = page.inner_text("#tooltip")
    assert "Galleon" in card and "Stealing" in card


def test_ability_tree_uses_wynnbuilder_art_and_toggles(page):
    open_build(page, "shaman_105_stormdrain")
    assert page.locator(".tree-hit").count() > 80
    assert page.locator(".tree-conn").count() > 100
    assert page.evaluate("fetch('/assets/atree-connectors.png').then(r => r.status)") == 200
    # lit connectors use a highlighted tile (column != the dark "0000" tile for straight links)
    title = page.locator("#ed-tree-title")
    before = title.inner_text()
    node = page.locator(".tree-hit[aria-label='Shepherd']")
    was = node.get_attribute("aria-pressed")
    node.click()
    assert node.get_attribute("aria-pressed") != was
    page.wait_for_function(
        f"document.querySelector('#ed-tree-title').innerText !== {before!r}", timeout=15000)
    assert not page.errors


def test_item_icons_glow_in_tier_colour(page):
    """WynnBuilder's tier glow: Galleon (Mythic) #a0a, Leo (Legendary) #5ff."""
    open_build(page, "shaman_105_stormdrain")
    boots = page.locator(".slot:has(input[aria-label='boots']) .sprite")
    chest = page.locator(".slot:has(input[aria-label='chestplate']) .sprite")
    assert "Mythic-shadow" in boots.get_attribute("class")
    assert "rgb(170, 0, 170)" in boots.evaluate("e => getComputedStyle(e).boxShadow")
    assert "rgb(85, 255, 255)" in chest.evaluate("e => getComputedStyle(e).boxShadow")


def test_set_bonuses_shown(page):
    """The original build wears all four Cosmic Foundations pieces."""
    open_build(page, "original_user_build")
    assert page.locator("#ed-sets-panel").is_visible()
    sets = page.inner_text("#ed-sets")
    assert "Cosmic Foundations" in sets and "4/4" in sets and "+1,500" in sets
    assert "19,118" in page.inner_text("#ed-tiles")          # includes the set's +1,500 health
    assert not page.errors


def test_inventory_tabs_tomes_aspects_unavailable(page, app):
    """Own a tome twice and an aspect tier from the Inventory page; manage the unavailable list."""
    inv_path = Path(app.builds_dir) / "inventory.json"
    read = lambda: json.loads(inv_path.read_text())
    page.click("#open-inventory")
    page.wait_for_selector("#inventory:not([hidden]) .tab")
    page.get_by_role("tab", name="Tomes").click()
    page.get_by_label("Filter tomes…").fill("Scavenging Expertise III")
    own = page.get_by_role("button", name="Own Tome of Scavenging Expertise III")
    own.click()
    own.click()
    page.wait_for_function("document.querySelector('#open-inventory').textContent.includes('2 tomes')")
    assert read()["tomes"] == ["Tome of Scavenging Expertise III"] * 2
    page.get_by_role("button", name="Own one fewer Tome of Scavenging Expertise III").click()
    page.wait_for_function("document.querySelector('#open-inventory').textContent.includes('1 tome')")
    page.get_by_role("tab", name="Aspects").click()
    page.get_by_label("Class").select_option("Mage")
    page.get_by_label("Filter aspects…").fill("Runic Extravagance")
    page.get_by_role("button", name="Aspect of Runic Extravagance tier 2").click()
    page.wait_for_function("document.querySelector('#open-inventory').textContent.includes('aspect')")
    assert read()["aspects"] == {"Mage": {"Aspect of Runic Extravagance": 2}}
    page.get_by_role("tab", name="Unavailable").click()
    page.get_by_label("Add unavailable item").fill("Galleon")
    page.get_by_text("Galleon").first.click()
    page.wait_for_selector(".inv-item:has-text('Galleon')")
    assert "Galleon" in read()["unavailable"]
    page.locator(".inv-item:has-text('Galleon') button:has-text('Remove')").click()
    page.wait_for_selector(".inv-item:has-text('Galleon')", state="detached")
    assert read()["unavailable"] == {}
    assert not page.errors


def test_own_button_rolls_and_upgrades(page, app):
    """Mark an item owned from a build, give it a real roll, see totals follow."""
    open_build(page, "shaman_105_stormdrain")
    before = page.inner_text("#ed-tiles")
    own = page.locator(".slot:has(input[aria-label='boots']) button.own")
    own.click()
    playwright.expect(own).to_contain_text("Owned")
    inv = json.loads((Path(app.builds_dir) / "inventory.json").read_text())
    assert "Galleon" in inv["items"]
    page.click("#open-inventory")
    page.wait_for_selector("#inventory:not([hidden]) .inv-item")
    page.locator(".inv-item:has-text('Galleon') summary").click()          # rolls sit in a drawer
    page.get_by_role("spinbutton", name="Galleon Stealing").fill("5")      # base is 15
    page.locator(".inv-item:has-text('Galleon') button:has-text('Save rolls')").click()
    page.wait_for_function("document.querySelector('#toast').textContent.includes('Rolls saved')")
    inv = json.loads((Path(app.builds_dir) / "inventory.json").read_text())
    assert inv["items"]["Galleon"]["rolls"]["eSteal"] == 5
    open_build(page, "shaman_105_stormdrain")
    page.wait_for_function(f"!document.querySelector('#ed-tiles').innerText.includes({before.split('Stealing')[1].split(chr(10))[1]!r})")
    assert not page.errors


def test_damage_panel_shows_wynnbuilder_numbers(page, gd, links):
    """The right column's spells and effective HP; Perfect matches WynnBuilder's
    page (numbers below were read off wynnbuilder.github.io for this link)."""
    open_build(page, "mage_105_gaia_lightbender")
    page.click("#roll-toggle button:has-text('Perfect')")
    text = page.inner_text("#ed-damage")
    for want in ("4,548.33", "8,918.30", "Ophanim", "(65.00)", "19,482.73", "21,981", "36,100/s"):
        assert want in text, want
    page.click("#ed-damage details.spell:has-text('Ophanim') summary")
    assert "Per Orb" in page.inner_text("#ed-damage details.spell[open]")
    page.click("#roll-toggle button:has-text('Typical')")
    assert "18,315" in page.inner_text("#ed-damage")               # typical Ophanim
    assert page.locator("#ed-damage details.spell[open]").count() == 1   # stays open
    import os
    if os.environ.get("WT_SHOTS"):
        page.set_viewport_size({"width": 1440, "height": 2600})
        page.locator("#ed-damage-panel").screenshot(path=f"{os.environ['WT_SHOTS']}/70-damage.png")
    assert not page.errors


def test_solver_offers_spell_damage_requirement(page):
    page.click("text=New build from goals")
    page.get_by_role("combobox", name="Class").select_option("Mage")
    box = page.get_by_role("combobox", name="Add a requirement")
    box.fill("ophanim")
    assert "No match" in page.inner_text(".pk-list")                # no tree yet, so no spells
    box.fill("spell")
    assert "Pick a tree preset" in page.inner_text(".pk-list")
    page.get_by_role("combobox", name="Tree preset").select_option("mage-light-bender")
    box.fill("ophanim")                                             # the spells load after the preset is chosen
    page.wait_for_selector(".pk-item:has-text('Ophanim')")
    assert page.locator(".pk-item").all_inner_texts() == ["Ophanim"]
    box.press("Enter")
    page.get_by_role("spinbutton", name="Ophanim damage").fill("15000")
    box.fill("ophanim")
    assert "No match" in page.inner_text(".pk-list")                # already added: not offered twice
    assert not page.errors


def test_requirement_picker_filters_as_you_type(page):
    page.click("text=New build from goals")
    box = page.get_by_role("combobox", name="Add a requirement")
    box.click()
    groups = page.locator(".pk-group").all_text_contents()
    assert "Survival" in groups and any(g.startswith("Item stat:") for g in groups)
    box.fill("thunder def")                                         # every word must match
    texts = page.locator(".pk-item").all_inner_texts()
    assert texts and all("thunder" in t.lower() and "def" in t.lower() for t in texts)
    box.press("ArrowDown")
    box.press("Enter")
    assert page.locator(".rule").count() == 1
    box.fill("zzzz")
    assert "No match" in page.inner_text(".pk-list")
    box.press("Escape")
    assert page.locator(".pk-list").count() == 0
    assert not page.errors


def test_solver_takes_any_stat_as_minimum_or_maximum(page):
    page.click("text=New build from goals")
    assert page.locator(".rule").count() == 0                       # nothing until the player adds it
    add_rule(page, "poison", 5000, "Poison")
    pick_rule(page, "spell 1 cost raw")
    page.get_by_role("combobox", name="Spell 1 cost (raw): at least or at most").select_option("max")
    page.get_by_role("spinbutton", name="Spell 1 cost (raw)", exact=True).fill("0")
    page.get_by_role("button", name="Remove Poison").click()
    assert page.locator(".rule").count() == 1
    assert not page.errors


def test_powders_and_aspects_in_editor(page, app):
    open_build(page, "mage_105_gaia_lightbender")
    before = page.inner_text("#ed-damage")
    box = page.locator("input[aria-label='weapon powders']")
    box.fill("t6 t6 t6 t6")                                 # Gaia has 3 slots
    box.press("Tab")
    assert "invalid" in (box.get_attribute("class") or "")
    box.fill("t6t6")
    box.press("Tab")
    settle(page)
    assert box.input_value() == "t6 t6"
    assert page.inner_text("#ed-damage") != before          # powders change the damage
    page.click("#ed-aspects-panel summary")
    first = page.locator("select[aria-label='Aspect 1']")
    name = first.locator("option").nth(1).inner_text()
    first.select_option(name)
    settle(page)
    assert "1/5" in page.inner_text("#ed-aspects-sum")
    assert page.locator("select[aria-label='Aspect 1 tier']").input_value() != ""
    page.click("#ed-save")
    page.wait_for_function("document.querySelector('#ed-save').disabled")
    doc = json.loads((Path(app.builds_dir) / "gaia.json").read_text())
    assert doc["powders"][4] == ["t6", "t6"] and doc["aspects"][0][0] == name
    import os
    if os.environ.get("WT_SHOTS"):
        page.set_viewport_size({"width": 1440, "height": 1800})
        page.locator(".ed-main").screenshot(path=f"{os.environ['WT_SHOTS']}/72-powders-aspects.png")
    assert not page.errors


def test_craft_helper_shows_where_ingredients_drop(page):
    open_build(page, "shaman_105_stormdrain")
    page.click(".slot:has-text('Ring 1') button:has-text('Craft')")
    page.wait_for_selector(".craft-opt details.sources", timeout=60000)
    page.locator(".craft-opt details.sources summary").first.click()
    text = page.locator(".craft-opt details.sources").first.inner_text()
    assert "Stolen Pearls" in text and "Tribal Exile (1488, -1513)" in text
    assert not page.errors


def test_compare_view(page):
    page.click("#open-compare")
    page.select_option("select[aria-label='First build']", label="mage_105_gaia_lightbender")
    page.select_option("select[aria-label='Second build']", label="shaman_105_stormdrain")
    # a table for the default pair may already be up; wait for the chosen one
    page.wait_for_function("document.querySelector('#compare table.cmp') && "
                           "document.querySelector('#compare').innerText.includes('different classes')")
    text = page.inner_text("#compare")
    assert "Gaia" in text and "Stormdrain" in text and "different classes" in text
    import os
    if os.environ.get("WT_SHOTS"):
        page.select_option("select[aria-label='First build']", label="shaman_105_crafted")
        page.wait_for_timeout(800)
        page.set_viewport_size({"width": 1440, "height": 2200})
        page.locator("#compare").screenshot(path=f"{os.environ['WT_SHOTS']}/73-compare.png")
    assert not page.errors


def test_exact_search_from_the_form(page):
    page.click("#new-build")
    page.get_by_role("combobox", name="Class").select_option("Mage")
    page.get_by_role("combobox", name="Maximize").select_option("poison")
    add_rule(page, "health", 15000, "Health")
    add_rule(page, "mana regen", 20, "Mana regen")
    open_fold(page, "Items")
    page.get_by_role("combobox", name="Required major IDs").select_option("PLAGUE")
    page.get_by_role("textbox", name="Weapon (optional)").fill("Gaia")
    page.get_by_role("textbox", name="Name").fill("ui exact test")
    open_fold(page, "Search options")
    page.get_by_label("Exact search (every item)").check()
    page.click("text=Find the best build")
    page.wait_for_selector("#editor:not([hidden]) #ed-badge .badge.ok", timeout=120000)
    assert page.input_value("#editor .name") == "ui exact test"
    assert "84,300" in page.inner_text("#ed-tiles")
    assert not page.errors


# ------------------------------------------------------------ AI setup wizard
def launch(tmp_path, **kw):
    """A page on a fresh app (no builds); returns (playwright, browser, page, server)."""
    srv = AppServer(str(tmp_path), terminal_cwd=str(tmp_path), **kw).__enter__()
    p = playwright.sync_playwright().start()
    try:
        browser = p.chromium.launch()
    except Exception as e:
        p.stop(); srv.__exit__()
        pytest.skip(f"headless Chromium unavailable: {e}")
    pg = browser.new_page(viewport={"width": 1440, "height": 1000})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(srv.url)
    return p, browser, pg, srv


@pytest.fixture()
def fresh(tmp_path, request):
    started = []

    def go(**kw):
        started.append(launch(tmp_path, **kw))
        return started[-1][2]
    yield go
    for p, browser, _pg, srv in started:
        browser.close(); p.stop(); srv.__exit__()


def test_wizard_opens_on_first_run_and_remembers_choice(fresh, tmp_path):
    pg = fresh(ai=None)
    pg.wait_for_selector("#setup[open] .setup-card")
    assert "Claude Code" in pg.inner_text("#setup") and "Codex" in pg.inner_text("#setup")
    assert pg.is_disabled("#setup button:has-text('Next')")
    pg.click("#setup .setup-card:has-text('No AI')")
    pg.click("#setup button:has-text('Next')")
    pg.wait_for_selector("#setup", state="hidden")
    assert json.loads((tmp_path / "settings.json").read_text())["ai"] == "shell"
    assert "Plain terminal" in pg.inner_text("#ai-settings")
    pg.reload()
    pg.wait_for_timeout(800)
    assert not pg.locator("#setup").is_visible()          # not asked again
    pg.click("#ai-settings")                               # ...but can be changed
    pg.wait_for_selector("#setup[open] .setup-card.on:has-text('No AI')")
    assert not pg.errors


def test_install_step_and_saved_ai_opens_terminal(fresh, tmp_path, monkeypatch):
    """Not installed: the install step shows the command and types it into the
    terminal. Installed and saved: opening the app opens the panel and starts it."""
    import os
    from wynntools.web import terminal
    bindir = tmp_path / "bin"; bindir.mkdir()
    fake = {**terminal.AI_CLIS[0], "cmd": "wt-ui-fake-ai",
            "install": {"posix": f"printf '#!/bin/sh\\necho UI-AI-$((40+2))\\n' > {bindir}/wt-ui-fake-ai"
                                 f" && chmod +x {bindir}/wt-ui-fake-ai", "windows": "rem"}}
    monkeypatch.setattr(terminal, "AI_CLIS", [fake, *terminal.AI_CLIS[1:]])
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    pg = fresh(ai=None)
    pg.wait_for_selector("#setup[open] .setup-card")
    pg.click("#setup .setup-card:has-text('Claude Code')")
    pg.click("#setup button:has-text('Next')")
    pg.wait_for_selector("#setup h2:has-text('Install Claude Code')")
    pg.screenshot(path=str(tmp_path / "wizard-install.png"))
    pg.click("#setup button:has-text('Install Claude Code for me')")
    pg.wait_for_selector("#terminal-panel:not([hidden]) .xterm")
    for _ in range(20):                                    # the install is typed once the shell settles
        again = pg.locator("#setup button:has-text('Check again')")
        if not again.count():
            break
        again.click()
        pg.wait_for_timeout(500)
    pg.wait_for_selector("#setup h2:has-text('Claude Code is ready')")
    pg.click("#setup button:has-text('Start Claude Code')")
    pg.wait_for_function("document.querySelector('#term').innerText.includes('UI-AI-42')", timeout=15000)
    assert json.loads((tmp_path / "settings.json").read_text())["ai"] == "claude"
    assert "AI: Claude Code" in pg.inner_text("#ai-settings"), pg.errors
    assert not pg.errors


def test_saved_ai_autostarts_on_open(fresh, tmp_path, monkeypatch):
    import os
    from wynntools.web import terminal
    bindir = tmp_path / "bin"; bindir.mkdir()
    exe = bindir / "wt-ui-fake-ai"
    exe.write_text("#!/bin/sh\necho UI-AUTO-$((20+22))\n"); exe.chmod(0o755)
    monkeypatch.setattr(terminal, "AI_CLIS", [{**terminal.AI_CLIS[0], "cmd": "wt-ui-fake-ai"},
                                              *terminal.AI_CLIS[1:]])
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    pg = fresh(ai="claude")
    pg.wait_for_selector("#terminal-panel:not([hidden]) .xterm")
    pg.wait_for_function("document.querySelector('#term').innerText.includes('UI-AUTO-42')", timeout=15000)
    assert not pg.locator("#setup").is_visible()
    assert not pg.errors


def test_page_tells_the_ai_what_it_shows_and_opens_what_it_asks(page, app):
    """The AI resolves "this build" from the page's report (`wt current`), and
    builds it saves open in the page (`wt show`) without losing unsaved edits."""
    import urllib.request

    from tests.ui.harness import TOKEN

    def call(method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{app.port}{path}", method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"x-wt-token": TOKEN, "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def view_is(pred):
        for _ in range(50):
            v = call("GET", "/api/view")
            if pred(v):
                return v
            page.wait_for_timeout(100)
        raise AssertionError(v)

    open_build(page, "shaman_105_stormdrain")
    view_is(lambda v: v["view"] == "editor" and v["file"] == "stormdrain.json" and not v["dirty"])
    page.fill("#editor textarea", "typed, not saved")
    v = view_is(lambda v: v["dirty"])
    assert v["doc"]["notes"] == "typed, not saved"
    # the AI saves another build: pointed out, but the player's edits stay
    call("POST", "/api/show", {"file": "gaia.json"})
    page.wait_for_function("document.querySelector('#toast').textContent.includes('gaia.json')", timeout=10000)
    assert page.input_value("#editor textarea") == "typed, not saved"
    page.click("#ed-revert")
    settle(page)
    from wynntools.web import client          # the way `wt show` asks: a file, not HTTP
    client.request_show(app.builds_dir, "gaia.json")
    page.wait_for_function("document.querySelector('#editor .name').value === 'mage_105_gaia_lightbender'",
                           timeout=15000)
    view_is(lambda v: v["file"] == "gaia.json" and not v["dirty"])
    page.click("#open-inventory")
    view_is(lambda v: v["view"] == "inventory")
    assert not page.errors


def test_blocked_tree_nodes_are_red_and_cannot_be_added(page):
    """Ophanim is selected in this build. Void Acceleration lists it as a blocker,
    and Ophanim lists Thunderstorm: both are shown red and refuse a click."""
    open_build(page, "mage_105_gaia_lightbender")
    for name in ("Void Acceleration", "Thunderstorm"):
        hit = page.locator(f".tree-hit[aria-label='{name}']")
        assert "blocked" in hit.get_attribute("class"), name
        assert "blocked by Ophanim" in hit.get_attribute("title")
        hit.click()
        page.wait_for_function("document.querySelector('#toast').textContent.includes(\"can't be taken with Ophanim\")",
                               timeout=5000)
        assert hit.get_attribute("aria-pressed") == "false"
    assert page.locator("#ed-save").is_disabled()             # nothing changed
    assert "blocked" not in page.locator(".tree-hit[aria-label='Ophanim']").get_attribute("class")
    page.locator(".tree-hit[aria-label='Void Acceleration']").scroll_into_view_if_needed()
    page.locator(".tree-wrap").screenshot(path="/tmp/claude-1000/-var-home-hhays-wynn-toolbox/"
                                          "3b42f8d6-212a-46a1-b732-0aa67914f57b/scratchpad/blocked.png")
    assert not page.errors


# ------------------------------------------------------------ app window and updates
# A stand-in for pywebview's bridge (wynntools/web/window.py's WindowApi): the
# page only sees `window.pywebview.api`, so the title bar can be tested here.
FAKE_PYWEBVIEW = """
window.__calls = [];
let maximized = false;
const call = (name, ret) => (...args) => { window.__calls.push([name, ...args]); return Promise.resolve(ret?.(...args)); };
window.pywebview = { api: {
  native_moves: call("native_moves", () => false),
  is_maximized: call("is_maximized", () => maximized),
  toggle_maximize: call("toggle_maximize", () => (maximized = !maximized)),
  minimize: call("minimize"), close: call("close"), toggle_fullscreen: call("toggle_fullscreen"),
  start_move: call("start_move"), start_resize: call("start_resize"),
  geometry: call("geometry", () => ({ x: 100, y: 100, width: 1200, height: 800 })),
  set_geometry: call("set_geometry"),
} };
"""


def calls(pg):
    return [c[0] for c in pg.evaluate("window.__calls")]


def test_plain_browser_has_no_title_bar(fresh):
    pg = fresh()
    pg.wait_for_selector("#check-updates")
    assert pg.locator("#titlebar").is_hidden()
    assert not pg.evaluate("document.body.classList.contains('app-window')")
    assert pg.locator(".rz").first.is_hidden()
    pg.click("#check-updates")
    pg.wait_for_selector("#toast.show:has-text('up to date')")
    assert not pg.errors


def test_app_window_title_bar(tmp_path):
    srv = AppServer(str(tmp_path), terminal_cwd=str(tmp_path)).__enter__()
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            srv.__exit__(); pytest.skip(f"headless Chromium unavailable: {e}")
        pg = browser.new_page(viewport={"width": 1400, "height": 900})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.add_init_script(FAKE_PYWEBVIEW)
        pg.goto(srv.url)
        pg.wait_for_selector("#titlebar:not([hidden])")
        pg.wait_for_function("document.getElementById('tb-sub').textContent.startsWith('data')")
        assert pg.evaluate("document.body.classList.contains('app-window')")
        # The app fills the window under the title bar, with no page scrollbar.
        box = pg.locator("#app").bounding_box()
        assert box["y"] >= 34 and box["y"] + box["height"] <= 900
        assert pg.evaluate("document.documentElement.scrollHeight") <= 900
        # Not Qt: pywebview drags by the drag region.
        assert "pywebview-drag-region" in pg.get_attribute(".tb-drag", "class")
        pg.screenshot(path=str(tmp_path / "titlebar.png"), clip={"x": 0, "y": 0, "width": 1400, "height": 120})

        pg.click("#tb-min")
        pg.click("#tb-max")
        pg.wait_for_function("document.body.classList.contains('maximized')")
        assert pg.locator(".rz").first.is_hidden()           # no resize edges when maximized
        pg.dblclick(".tb-title")
        pg.wait_for_function("!document.body.classList.contains('maximized')")
        assert pg.get_attribute("#tb-max", "aria-label") == "Maximize"

        # Resizing from the right edge (the non-Qt path) moves the window edge with the mouse.
        edge = pg.locator(".rz[data-edge='e']").bounding_box()
        pg.mouse.move(edge["x"] + 2, edge["y"] + 100)
        pg.mouse.down(); pg.mouse.move(edge["x"] - 98, edge["y"] + 100); pg.mouse.up()
        pg.wait_for_function("window.__calls.some((c) => c[0] === 'set_geometry')")
        last = [c for c in pg.evaluate("window.__calls") if c[0] == "set_geometry"][-1]
        assert last[1:] == [100, 100, 1100, 800]

        # Closing with unsaved edits asks first (in the page, not a native dialog).
        pg.evaluate("S.cur = { file: 'x.json', dirty: true, doc: { name: 'My build' } }")
        pg.click("#tb-close")
        pg.wait_for_selector("#ask[open]:has-text('My build')")
        pg.click("#ask button:has-text('Cancel')")
        assert "close" not in calls(pg)
        pg.click("#tb-close")
        pg.click("#ask button:has-text('Close anyway')")
        pg.wait_for_function("window.__calls.some((c) => c[0] === 'close')")
        pg.evaluate("S.cur.dirty = false")
        assert calls(pg).count("minimize") == 1 and calls(pg).count("toggle_maximize") == 2
        assert not errors
        browser.close()
    srv.__exit__()


NEW_SHA = "3" * 40


def update_available(*_a, **_k):
    return {"available": True, "kind": "install", "can_update": True, "current": "1" * 40,
            "latest": NEW_SHA, "ahead_by": 12, "repo": "x/y", "branch": "main", "checked_at": 0,
            "error": None, "commits": [{"sha": NEW_SHA, "message": "Newest feature",
                                        "date": "2026-09-01T10:00:00Z"},
                                       {"sha": "2" * 40, "message": "Older fix", "date": None}]}


def test_update_prompt_ignore_and_update(fresh, tmp_path, monkeypatch):
    from wynntools import updates
    started = []
    monkeypatch.setattr(updates, "start_update", lambda *a, **k: started.append(a))
    pg = fresh(update_check=update_available)
    pg.wait_for_selector("#update[open]:has-text('Newest feature')")
    text = pg.inner_text("#update")
    assert "12 new changes" in text and "Older fix" in text and "…and 10 more" in text
    pg.screenshot(path=str(tmp_path / "update-dialog.png"))
    pg.click("#update button:has-text('Ignore')")
    pg.wait_for_selector("#update", state="hidden")
    assert json.loads((tmp_path / "settings.json").read_text())["ignored_update"] == NEW_SHA

    pg.reload()                                          # ignored: not asked again...
    pg.wait_for_selector("#check-updates:has-text('Update available')")
    pg.wait_for_timeout(2000)
    assert pg.locator("#update").is_hidden()
    pg.click("#check-updates")                           # ...but the button still offers it
    pg.wait_for_selector("#update[open]")
    pg.click("#update button:has-text('Update now')")
    pg.wait_for_selector("#update h2:has-text('Updating')")
    assert started and started[0][2] == NEW_SHA
    assert not pg.errors


def test_update_prompt_waits_for_the_setup_wizard(fresh):
    pg = fresh(ai=None, update_check=update_available)
    pg.wait_for_selector("#setup[open]")
    pg.wait_for_timeout(2500)
    assert pg.locator("#update").is_hidden()
    pg.click("#setup .setup-x")
    pg.wait_for_selector("#update[open]")


# ------------------------------------------------------------ skill points, survivability, candidates
def test_manual_skill_points_in_the_editor(page, app):
    open_build(page, "shaman_105_stormdrain")
    settle(page)
    left = int(page.inner_text("#sp-left"))
    page.fill("input[data-skill=int]", str(52 + 10))
    page.press("input[data-skill=int]", "Enter")
    page.wait_for_function(f"document.querySelector('#sp-left').textContent === '{left - 10}'", timeout=20000)
    assert "manual" in page.get_attribute("input[data-skill=int]", "class")
    page.fill("input[data-skill=str]", "10")                  # below what the gear needs
    page.press("input[data-skill=str]", "Enter")
    page.wait_for_selector("#ed-banners .banner.bad:has-text('too low to wear')", timeout=20000)
    page.click("#sp-auto-all")
    page.wait_for_function(f"document.querySelector('#sp-left').textContent === '{left}'", timeout=20000)
    page.click("#ed-save")
    page.wait_for_selector("#ed-badge .badge.ok", timeout=20000)
    assert json.loads((Path(app.builds_dir) / "stormdrain.json").read_text())["skillpoints"] is None
    assert not page.errors


def test_fix_a_weakness_makes_a_candidate_and_it_can_be_chosen(page, app):
    open_build(page, "shaman_105_stormdrain")
    assert "Air Defence" in page.inner_text("#ed-surv .srow.lowest")
    page.click(".fix-btn[data-code=neg_adef]")
    page.wait_for_selector("#solver-from")
    assert page.get_by_role("spinbutton", name="Every elemental defence").input_value() == "0"
    page.wait_for_selector("#solver-run:not([disabled])")
    page.click("#solver-run")
    page.wait_for_selector("#editor:not([hidden]) #ed-cand-banner", timeout=300000)
    settle(page)
    assert "-" not in page.inner_text("#ed-surv .srow.lowest .sv")           # nothing negative now
    assert page.locator("#build-list li.cand").count() == 1
    page.click("#ed-cand-banner >> text=Open the build")
    page.wait_for_selector("#ed-cands-panel:not([hidden]) table")
    page.click("#ed-cands >> text=Use this one")
    page.locator("#ask").get_by_role("button", name="Use it", exact=True).click()
    page.wait_for_function("!document.querySelector('#build-list li.cand')", timeout=20000)
    doc = json.loads((Path(app.builds_dir) / "stormdrain.json").read_text())
    assert min(doc["status"]["survivability"]["typical"]["eledefs"].values()) >= 0
    assert not page.errors


def test_import_preview_lists_what_to_know(page, gd, links):
    from wynntools.codec import to_link
    b = decode(links["shaman_105_stormdrain"]["hash"], gd)
    b.skillpoints = [None, None, 80, None, None]
    page.click("text=Import a WynnBuilder link")
    page.fill("#import-link", to_link(b, gd))
    page.fill("#import-name", "partial sp")
    page.click("#import-go")
    page.wait_for_selector("#ask[open] ul.findings")
    assert "set by hand in WynnBuilder" in page.inner_text("#ask")
    page.locator("#ask").get_by_role("button", name="Import", exact=True).click()
    page.wait_for_selector("#editor:not([hidden]) #ed-badge .badge.ok", timeout=20000)
    assert page.input_value("input[data-skill=int]") != "" and "manual" in page.get_attribute("input[data-skill=int]", "class")
    assert "error" not in page.inner_text("#ed-damage").lower()
    assert not page.errors


def test_specials_scenario_and_powder_planner(page):
    open_build(page, "shaman_105_stormdrain")
    settle(page)
    page.click("#ed-specials summary")
    page.select_option("select[aria-label='Weapon powder special']", "Curse")
    page.click("#ed-specials >> text=Compare")
    page.wait_for_selector("#ed-damage .sv.special", timeout=20000)
    assert "+25.0%" in page.inner_text("#ed-damage")
    assert "no special" in page.inner_text("#ed-powders-give")        # no powders yet
    page.fill("input[aria-label='weapon powders']", "e7 e7")
    page.press("input[aria-label='weapon powders']", "Tab")
    settle(page)
    page.wait_for_selector("#ed-powders-give:has-text('Quake power 7 (weapon)')", timeout=20000)
    page.click("#ed-powder-panel summary")
    page.click("#ed-powder >> text=Suggest")
    page.wait_for_selector("#plan-armor", timeout=20000)
    page.click("#plan-armor >> text=Apply")
    settle(page)
    assert "-" not in page.inner_text("#ed-surv .srow.lowest .sv")
    assert not page.errors


def test_tradeoffs_from_the_form(page):
    page.click("#new-build")
    page.get_by_role("combobox", name="Class").select_option("Shaman")
    page.get_by_role("combobox", name="Tree preset").select_option("shaman-summoner")
    open_fold(page, "Items")
    page.get_by_role("textbox", name="Weapon (optional)").fill("Stormdrain")
    add_rule(page, "health", 12000, "Health")
    page.wait_for_selector("#solver-trade:not([disabled])")
    page.select_option("select[aria-label='Damage to trade']", "puppet_dps")
    page.click("#solver-trade")
    page.wait_for_selector("#tradeoffs table", timeout=600000)
    rows = page.locator("#tradeoffs tbody tr")
    assert rows.count() >= 2
    assert "max damage" in rows.first.inner_text() and "max survival" in rows.last.inner_text()
    rows.first.locator("text=Save").click()
    page.wait_for_selector("#editor:not([hidden]) #ed-badge .badge.ok", timeout=30000)
    assert not page.errors


def test_requirement_picker_opens_at_the_top_with_nothing_selected(page):
    page.click("text=New build from goals")
    page.get_by_role("combobox", name="Add a requirement").click()
    assert page.locator(".pk-item.sel").count() == 0
    assert page.evaluate("document.querySelector('.pk-list').scrollTop") == 0
    assert not page.errors


def test_solver_requires_and_avoids_sets(page):
    page.click("text=New build from goals")
    open_fold(page, "Items")
    req = page.get_by_role("combobox", name="Require a set")
    req.fill("air relic")
    req.press("Enter")
    page.get_by_role("spinbutton", name="Air Relic pieces").fill("3")
    avoid = page.get_by_role("combobox", name="Avoid a set")
    avoid.fill("cindercurse")
    avoid.press("Enter")
    assert page.locator(".chip", has_text="no Cindercurse").count() == 1
    req.fill("cindercurse")
    assert "No match" in page.inner_text(".pk-list")               # already avoided: not offered to require
    page.get_by_role("button", name="Remove Air Relic").click()
    assert page.locator(".set-rule").count() == 0
    assert not page.errors


def test_set_picker_list_opens_right_under_its_box(page):
    page.click("text=New build from goals")
    open_fold(page, "Items")
    box = page.get_by_role("combobox", name="Require a set")
    box.click()
    gap = page.evaluate("""() => { const i = document.querySelector("input[aria-label='Require a set']").getBoundingClientRect();
      const l = document.querySelector('.pk-list').getBoundingClientRect(); return l.top - i.bottom; }""")
    assert 0 <= gap < 12
    right = page.evaluate("""() => document.querySelector("input[aria-label='Avoid a set']").getBoundingClientRect().right
      - document.querySelector('#solver .card.fold').getBoundingClientRect().right""")
    assert right <= 0                                              # the two boxes stay inside the card
    assert not page.errors


def test_health_regen_raw_can_be_required(page):
    page.click("text=New build from goals")
    box = page.get_by_role("combobox", name="Add a requirement")
    for query in ("health regen raw", "hp regen raw", "hprRaw"):     # WynnBuilder's wording, the short form, the ID
        box.fill(query)
        assert page.locator(".pk-item").all_text_contents() == ["Health regen (raw)"]
    box.press("Enter")
    page.get_by_role("spinbutton", name="Health regen (raw)", exact=True).fill("200")
    assert not page.errors


def test_progress_clock_ticks_every_second(page):
    page.click("#new-build")
    page.get_by_role("combobox", name="Class").select_option("Shaman")
    page.get_by_role("combobox", name="Tree preset").select_option("shaman-summoner")
    page.get_by_role("combobox", name="Maximize").select_option("ehp")     # a local search: runs for minutes
    page.click("#solver-run")
    seen = []
    for _ in range(14):                                                    # ~4.2 s
        page.wait_for_timeout(300)
        seen.append(page.inner_text("#solver-status"))
    page.get_by_role("button", name="Cancel").click()
    clocks = [t.split("·")[-1].strip() for t in seen if ":" in t.split("·")[-1]]
    assert len({c for c in clocks if c[0].isdigit() and ":" in c}) >= 4, seen   # 0:00 0:01 0:02 0:03 ...
    page.wait_for_function("document.querySelector('#solver-status').textContent === 'Cancelled.'", timeout=20000)
    assert not page.errors


def test_editor_pickers_mark_and_filter_owned_tomes_and_aspects(page, app):
    """Owned tomes/aspects get a star; "only I own" hides the rest and caps the aspect tier."""
    post = lambda **b: page.evaluate("b => fetch('/api/inventory', {method: 'POST', headers: "
                                     "{'Content-Type': 'application/json'}, body: JSON.stringify(b)})", b)
    post(action="add", kind="tome", name="Tome of Scavenging Expertise III")
    post(action="add", kind="aspect", **{"class": "Mage"}, name="Aspect of Runic Extravagance", tier=1)
    page.click("#open-inventory")                          # reloads the inventory in the page
    page.wait_for_function("document.querySelector('#open-inventory').textContent.includes('tome')")
    open_build(page, "mage_105_gaia_lightbender")
    page.click("#ed-tomes-panel summary")
    page.click("#ed-aspects-panel summary")
    slot = page.locator("select[aria-label='mobXpTome1']")
    page.wait_for_function("document.querySelector(\"select[aria-label='mobXpTome1']\").textContent.includes('★ Tome of Scavenging Expertise III')")
    everything = slot.locator("option").count()
    assert everything > 4
    page.get_by_label("Only tomes I own").check()
    assert slot.locator("option").count() <= 3            # none, the owned tome, and what the build wears
    aspect = page.locator("select[aria-label='Aspect 1']")
    page.get_by_label("Only aspects I own (up to the tier I have)").check()
    assert aspect.locator("option").count() == 2
    aspect.select_option("Aspect of Runic Extravagance")
    assert page.locator("select[aria-label='Aspect 1 tier'] option").count() == 1
    assert not page.errors


# ------------------------------------------------------------------ the Builds list's order and groups
def drag(pg, src, dst, where=0.5):
    """Drag `src` onto `dst` with the mouse, landing at `where` (0 top .. 1 bottom) of it."""
    a, b = pg.locator(src).first.bounding_box(), pg.locator(dst).first.bounding_box()
    pg.mouse.move(a["x"] + 20, a["y"] + a["height"] / 2)
    pg.mouse.down()
    pg.mouse.move(a["x"] + 20, a["y"] + a["height"] / 2 + 12, steps=3)
    pg.mouse.move(b["x"] + 20, b["y"] + b["height"] * where, steps=8)
    pg.mouse.up()


def order(pg):
    """Top-level order: group names and build names, groups' builds indented."""
    return pg.evaluate("""() => [...document.querySelectorAll('#build-list .bl-gname, #build-list li:not(.cand) .bl-name')]
      .map((e) => (e.closest('.bl-group ul') ? '  ' : '') + e.textContent.replace(/\\d+$/, ''))""")


def test_builds_list_groups_and_drag_to_reorder(page, app):
    settings_file = Path(app.builds_dir) / "settings.json"
    assert order(page) == ["shaman_105_crafted", "mage_105_gaia_lightbender",
                           "original_user_build", "shaman_105_stormdrain"]   # by file name at first
    drag(page, "#build-list li:has-text('stormdrain')", "#build-list li:has-text('crafted')", 0.2)
    page.wait_for_function("document.querySelector('#build-list li').textContent.includes('stormdrain')")
    assert order(page)[:2] == ["shaman_105_stormdrain", "shaman_105_crafted"]
    assert not page.locator("#editor").is_visible()                   # a drag doesn't open the build

    page.click("#new-group")
    page.fill("#build-list .bl-rename", "Shaman")
    page.keyboard.press("Enter")
    page.wait_for_selector(".bl-group[data-group='Shaman'] .bl-empty")
    drag(page, "#build-list li:has-text('crafted')", ".bl-group[data-group='Shaman'] .bl-ghead", 0.7)
    page.wait_for_selector(".bl-group[data-group='Shaman'] li:has-text('crafted')")
    drag(page, "#build-list li:has-text('stormdrain')", ".bl-group[data-group='Shaman'] li", 0.8)
    page.wait_for_selector(".bl-group[data-group='Shaman'] li:has-text('stormdrain')")
    assert order(page) == ["Shaman", "  shaman_105_crafted", "  shaman_105_stormdrain",
                           "mage_105_gaia_lightbender", "original_user_build"]
    drag(page, ".bl-group[data-group='Shaman'] .bl-ghead", "#build-list li:has-text('original')", 0.8)
    page.wait_for_function("document.querySelector('#build-list > :last-child')?.dataset?.group === 'Shaman'")

    page.click(".bl-group[data-group='Shaman'] .bl-ghead")               # collapse
    page.wait_for_selector(".bl-group.collapsed[data-group='Shaman']")
    assert page.locator("#build-list li:has-text('stormdrain')").count() == 0
    saved = json.loads(settings_file.read_text())["sidebar"]
    assert saved == {"items": ["gaia.json", "original.json",
                               {"group": "Shaman", "collapsed": True, "builds": ["crafted.json", "stormdrain.json"]}]}
    page.reload()
    page.wait_for_selector(".bl-group.collapsed[data-group='Shaman']")   # remembered

    page.hover(".bl-group[data-group='Shaman'] .bl-ghead")
    page.click(".bl-group[data-group='Shaman'] button[title='Rename group']")
    page.fill("#build-list .bl-rename", "Shamans")
    page.keyboard.press("Enter")
    page.wait_for_selector(".bl-group[data-group='Shamans']")
    page.hover(".bl-group[data-group='Shamans'] .bl-ghead")
    page.click(".bl-group[data-group='Shamans'] button[title^='Remove group']")
    page.locator("#ask").get_by_role("button", name="Remove group").click()
    page.wait_for_function("!document.querySelector('.bl-group')")
    assert page.locator("#build-list li").count() == 4                 # its builds stay
    assert not page.errors


def test_builds_list_follows_wt_group(page, app):
    """`wt group` (the AI) writes the layout to settings.json; the page picks it up."""
    from wynntools import sidebar
    sidebar.save({"items": [{"group": "Mage", "collapsed": True, "builds": ["gaia.json"]}]},
                 Path(app.builds_dir) / "settings.json")
    page.wait_for_selector(".bl-group.collapsed[data-group='Mage']", timeout=10000)
    assert order(page)[-1] == "Mage"                                    # unplaced builds come first
    assert page.locator("#build-list li:has-text('gaia')").count() == 0
    assert not page.errors


def test_powders_show_in_the_pieces_own_stats(page):
    """Armor powders add health: the Summary counted it, but the slot's own line
    and hover card still showed the bare item."""
    open_build(page, "shaman_105_stormdrain")
    slot = ".slot:has(input[aria-label='chestplate'])"
    hp = lambda: int(page.inner_text(f"{slot} .eq-line .hp").replace("♥", "").replace(",", ""))  # noqa: E731
    bare = hp()

    def card():
        page.mouse.move(0, 0)
        page.hover(f"{slot} .eq-icon-wrap")
        page.wait_for_selector("#tooltip:not([hidden]) .item-card", timeout=5000)
        text = page.inner_text("#tooltip")
        return text, int(re.search(r"♥ Health\n([\d,]+)", text)[1].replace(",", ""))
    _, bare_base = card()
    box = page.locator("input[aria-label='chestplate powders']")
    box.fill("t6")
    box.press("Tab")
    page.wait_for_function(f"!document.querySelector(\"{slot} .eq-line .hp\").textContent.includes('{bare:,}')")
    assert hp() > bare
    text, base = card()
    assert "[1/1] powders" in text and base - bare_base == hp() - bare     # the same health added
    box.fill("")
    box.press("Tab")
    page.wait_for_function(f"document.querySelector(\"{slot} .eq-line .hp\").textContent.includes('{bare:,}')")
    assert not page.errors
