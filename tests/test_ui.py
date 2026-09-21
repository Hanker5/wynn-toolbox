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


def test_solver_offers_spell_damage_minimum(page):
    page.click("text=New build from goals")
    page.select_option("#solver select >> nth=0", "Mage")
    spell = page.locator("select[aria-label='Spell for the damage minimum']")
    assert spell.is_disabled()                              # no preset yet
    page.select_option("select[aria-label='Tree preset']", "mage-poison-lightbender")
    page.wait_for_function("!document.querySelector(\"select[aria-label='Spell for the damage minimum']\").disabled")
    options = spell.locator("option").all_inner_texts()
    assert "Wand Melee (DPS)" in options and "Ophanim" in options
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
    page.wait_for_selector("table.cmp")
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
    page.get_by_role("spinbutton", name="Health").fill("15000")
    page.get_by_role("spinbutton", name="Mana regen").fill("20")
    page.get_by_role("combobox", name="Required major IDs").select_option("PLAGUE")
    page.get_by_role("textbox", name="Weapon (optional)").fill("Gaia")
    page.get_by_role("textbox", name="Name").fill("ui exact test")
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
    assert json.loads((tmp_path / "settings.json").read_text()) == {"ai": "shell"}
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
    assert json.loads((tmp_path / "settings.json").read_text()) == {"ai": "claude"}
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
