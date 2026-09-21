"""Drive the web app in headless Chromium (Playwright).

Each check here was a real bug found by looking at the page in a browser:
hidden panels showing anyway, an empty preset dropdown, and every browser save
failing with a conflict because nanosecond file stamps rounded in JavaScript.

    uv run pytest -m ui        # needs: uv run playwright install chromium
"""
import json
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


def test_outside_edit_appears_in_page(page, app):
    open_build(page, "shaman_105_stormdrain")
    f = Path(app.builds_dir) / "stormdrain.json"
    doc = json.loads(f.read_text())
    buildfile.write(f, {**doc, "notes": "edited by the AI"})
    page.wait_for_function(
        "document.querySelector('#editor textarea').value === 'edited by the AI'", timeout=15000)


def test_solver_form_runs_and_opens_result(page):
    page.click("#new-build")
    page.get_by_role("combobox", name="Class").select_option("Mage")
    page.get_by_role("combobox", name="Maximize").select_option("poison")
    page.get_by_role("combobox", name="Tree preset").select_option("mage-poison-riftwalker")
    page.get_by_role("spinbutton", name="Health").fill("15000")
    page.get_by_role("spinbutton", name="Mana regen").fill("20")
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
