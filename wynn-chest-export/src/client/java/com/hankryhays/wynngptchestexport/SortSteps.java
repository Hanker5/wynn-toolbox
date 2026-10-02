package com.hankryhays.wynngptchestexport;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Carries out a sort plan from the app one click at a time, checking the game before every
 * click (no Minecraft classes, so tests can run it against a simulated chest).
 *
 * A plan is a list of steps: go to a page (and find it exactly as the plan expects), or click
 * one slot of the page or of the player's inventory. Each click names what that slot and the
 * cursor hold before it; the click trades the two (pick up, put down or swap), and the next
 * step waits until the game shows that. Anything else (a different item, a page that isn't as
 * expected, a slot outside the page's 45 or the inventory's carrying rows) stops the sort.
 * Pages are only turned with nothing on the cursor. When it stops holding an item, `rescue`
 * says where to put it down.
 */
public final class SortSteps {
	public static final int STORAGE_SLOTS = Controls.STORAGE_SLOTS;
	public static final int CARRY_FIRST = 13;     // the inventory's main rows, past the accessories (9-12)
	public static final int CARRY_LAST = 35;

	/** What a slot or the cursor holds: the stack's id (see `sig`), how many, and its name for messages. */
	public record Stack(String sig, int count, String name) {
		boolean same(Stack other) {
			return other != null && sig.equals(other.sig) && count == other.count;
		}
	}

	public sealed interface Step permits Page, Click {
	}

	/** Go to `page`; on arrival its 45 slots hold exactly `expect` (slot -> stack; missing = empty). */
	public record Page(int page, Map<Integer, Stack> expect) implements Step {
	}

	/** Click a slot of the open page (`chest`) or of the player's inventory, holding `cursorHas`, the slot holding `slotHas`. */
	public record Click(boolean chest, int slot, Stack slotHas, Stack cursorHas) implements Step {
	}

	/** What the game shows now. */
	public interface View {
		/** The page shown, or null while it can't be told. */
		Integer page();

		Stack chest(int slot);

		Stack inventory(int slot);

		Stack cursor();
	}

	public sealed interface Action permits ClickChest, ClickInventory, TurnPage, Wait, Done, Stop {
	}

	public record ClickChest(int slot) implements Action {
	}

	public record ClickInventory(int slot) implements Action {
	}

	/** Click the next (true) or previous (false) page arrow. */
	public record TurnPage(boolean next) implements Action {
	}

	/** Nothing to do until the game shows more. */
	public record Wait(String what) implements Action {
	}

	public record Done() implements Action {
	}

	public record Stop(String why) implements Action {
	}

	private final List<Step> steps;
	private int at;
	private Click pending;          // the click made, until the game shows its result

	public SortSteps(List<Step> steps) {
		this.steps = List.copyOf(steps);
	}

	public int done() {
		return at;
	}

	public int size() {
		return steps.size();
	}

	/** The next thing to do, given what the game shows now. */
	public Action next(View view) {
		if (pending != null) {
			Stack slot = pending.chest ? view.chest(pending.slot) : view.inventory(pending.slot);
			if (!same(slot, pending.cursorHas) || !same(view.cursor(), pending.slotHas)) {
				return new Wait("the click on " + where(pending) + " to show");
			}
			pending = null;
			at++;
		}
		if (at >= steps.size()) {
			return view.cursor() == null ? new Done() : new Stop("the sort ended holding " + view.cursor().name());
		}
		Step step = steps.get(at);
		if (step instanceof Page p) {
			Integer page = view.page();
			if (page == null) {
				return new Wait("the page to load");
			}
			if (view.cursor() != null) {
				return new Stop("an item is on the cursor before a page turn");
			}
			if (page != p.page) {
				return new TurnPage(p.page > page);
			}
			String wrong = pageProblem(view, p);
			if (wrong != null) {
				return new Wait(wrong);
			}
			at++;
			return next(view);
		}
		Click c = (Click) step;
		if (c.chest ? c.slot < 0 || c.slot >= STORAGE_SLOTS : c.slot < CARRY_FIRST || c.slot > CARRY_LAST) {
			return new Stop("the plan clicks a slot it must not (" + where(c) + ")");
		}
		Stack slot = c.chest ? view.chest(c.slot) : view.inventory(c.slot);
		if (!same(slot, c.slotHas)) {
			return new Stop(where(c) + " holds " + describe(slot) + ", not " + describe(c.slotHas));
		}
		if (!same(view.cursor(), c.cursorHas)) {
			return new Stop("the cursor holds " + describe(view.cursor()) + ", not " + describe(c.cursorHas));
		}
		if (slot != null && view.cursor() != null && slot.sig.equals(view.cursor().sig)) {
			return new Stop("clicking " + where(c) + " would merge two stacks of " + slot.name());
		}
		pending = c;
		return c.chest ? new ClickChest(c.slot) : new ClickInventory(c.slot);
	}

	/** Why the page shown isn't the one the next step expects, or null. */
	public String problem(View view) {
		if (pending != null) {
			Stack slot = pending.chest ? view.chest(pending.slot) : view.inventory(pending.slot);
			return "after clicking " + where(pending) + " it holds " + describe(slot) + " and the cursor "
				+ describe(view.cursor()) + "; expected " + describe(pending.cursorHas) + " and " + describe(pending.slotHas);
		}
		if (at < steps.size() && steps.get(at) instanceof Page p) {
			return view.page() == null ? "couldn't tell which page is open" : pageProblem(view, p);
		}
		return null;
	}

	/**
	 * Where to put down what the cursor holds after a stop: the reserved inventory slot if
	 * empty, else any empty carrying slot, else any empty slot of the page. Null when the
	 * cursor is empty or there is nowhere.
	 */
	public static Action rescue(View view, int reserve) {
		if (view.cursor() == null) {
			return null;
		}
		if (reserve >= CARRY_FIRST && reserve <= CARRY_LAST && view.inventory(reserve) == null) {
			return new ClickInventory(reserve);
		}
		for (int s = CARRY_FIRST; s <= CARRY_LAST; s++) {
			if (view.inventory(s) == null) {
				return new ClickInventory(s);
			}
		}
		for (int s = 0; s < STORAGE_SLOTS; s++) {
			if (view.chest(s) == null) {
				return new ClickChest(s);
			}
		}
		return null;
	}

	/**
	 * The id the app keeps for a stack: its item, name and tooltip (hashed), so two stacks
	 * with the same id look exactly alike and would merge if clicked together. The count is
	 * kept apart.
	 */
	public static String sig(String itemId, String name, List<String> lore) {
		StringBuilder text = new StringBuilder(Objects.toString(itemId, "")).append('\n').append(Objects.toString(name, ""));
		for (String line : lore) {
			text.append('\n').append(line);
		}
		try {
			byte[] hash = MessageDigest.getInstance("SHA-1").digest(text.toString().getBytes(StandardCharsets.UTF_8));
			return HexFormat.of().formatHex(hash, 0, 6);
		} catch (NoSuchAlgorithmException e) {
			throw new IllegalStateException(e);
		}
	}

	private static String pageProblem(View view, Page p) {
		for (int s = 0; s < STORAGE_SLOTS; s++) {
			Stack want = p.expect.get(s);
			Stack got = view.chest(s);
			if (!same(got, want)) {
				return "page " + p.page + " slot " + s + " holds " + describe(got) + ", not " + describe(want);
			}
		}
		return null;
	}

	private static boolean same(Stack a, Stack b) {
		return a == null ? b == null : a.same(b);
	}

	private static String where(Click c) {
		return c.chest ? "page slot " + c.slot : "inventory slot " + c.slot;
	}

	private static String describe(Stack s) {
		return s == null ? "nothing" : s.count == 1 ? s.name : s.count + " " + s.name;
	}
}
