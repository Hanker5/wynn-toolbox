package com.hankryhays.wynngptchestexport;

import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * What the page walker may click in an ender chest, read from item names and tooltips
 * alone (no Minecraft classes, so tests can run it against real exports).
 *
 * Page arrows sit in slots 51 and 52 ("Page 3 >>>>>", as Wynntils reads them), the
 * Account/Character switch in 47 ("Storage Type"). Each is clicked only when its tooltip
 * says so ("Click to go", "Click to switch"): on the last page bought, slot 52 is still
 * named "Page N >>>>>" but offers to buy the page, and 46 ("Quick Actions") would dump
 * the player's inventory into the bank.
 */
public final class Controls {
	public static final int STORAGE_SLOTS = 45;
	public static final int SWITCH_SLOT = 47;
	public static final int PREVIOUS_SLOT = 51;
	public static final int NEXT_SLOT = 52;

	private static final Pattern ARROW = Pattern.compile("^Page (\\d+)\\s*([<>])");
	private static final String ARROW_HINT = "Click to go";
	private static final String PURCHASE = "Purchase";
	private static final String SWITCH_NAME = "Storage Type";
	private static final String SWITCH_HINT = "Click to switch";
	private static final Pattern FORMAT = Pattern.compile("\u00A7.");
	private static final Pattern WIDE_SPACE = Pattern.compile("\u00C0+");     // the font draws "À" as a gap

	private Controls() {
	}

	/**
	 * Text as a player reads it: formatting codes and Wynncraft's invisible glyphs (private-use
	 * icons such as the mouse before "Click to go", spacing) removed. The app's
	 * gameimport.clean does the same.
	 */
	public static String clean(String text) {
		String plain = FORMAT.matcher(text == null ? "" : text).replaceAll("");
		StringBuilder out = new StringBuilder();
		plain.codePoints().filter(c -> switch (Character.getType(c)) {
			case Character.PRIVATE_USE, Character.UNASSIGNED, Character.SURROGATE, Character.CONTROL, Character.FORMAT -> false;
			default -> true;
		}).forEach(out::appendCodePoint);
		return WIDE_SPACE.matcher(out).replaceAll(" ").trim().replaceAll("\\s+", " ");
	}

	/** The page a real arrow pointing `direction` (">" or "<") leads to; null for anything else. */
	public static Integer arrow(String name, List<String> lore, String direction) {
		Matcher m = ARROW.matcher(clean(name));
		List<String> lines = lore.stream().map(Controls::clean).toList();
		boolean real = lines.contains(ARROW_HINT) && lines.stream().noneMatch(line -> line.contains(PURCHASE));
		return m.find() && m.group(2).equals(direction) && real ? Integer.parseInt(m.group(1)) : null;
	}

	/** Named like an arrow, yet neither one to click nor the offer to buy a page: unreadable. */
	public static boolean unreadableArrow(String name, List<String> lore) {
		List<String> lines = lore.stream().map(Controls::clean).toList();
		return ARROW.matcher(clean(name)).find() && arrow(name, lore, ">") == null && arrow(name, lore, "<") == null
			&& lines.stream().noneMatch(line -> line.contains(PURCHASE));
	}

	public static boolean isSwitch(String name, List<String> lore) {
		return clean(name).equals(SWITCH_NAME) && lore.stream().map(Controls::clean).toList().contains(SWITCH_HINT);
	}

	/** The page shown, from where its arrows lead; 1 with none, null if they disagree. */
	public static Integer page(Integer next, Integer previous) {
		if (next != null) {
			return previous != null && previous + 2 != next ? null : next - 1;
		}
		return previous != null ? previous + 1 : 1;
	}
}
