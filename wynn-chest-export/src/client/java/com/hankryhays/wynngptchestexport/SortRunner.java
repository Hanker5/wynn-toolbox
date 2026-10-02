package com.hankryhays.wynngptchestexport;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.network.chat.Component;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ClickType;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * The Sort button: sorts the open ender chest the way the app planned it.
 *
 * 1. Reads every page of this chest (PageWalker) and sends it to the app, which plans the sort
 *    from exactly what it saw, under the player's rules.
 * 2. Says how many moves that is and waits for a second press of Sort to start.
 * 3. Makes the plan's clicks one at a time (SortSteps checks each against the game first and
 *    waits for the game to show its result), with at least `sort_click_delay_ticks` between
 *    them, turning pages only with the checked arrows and nothing on the cursor. The player's
 *    clicks and keys (except Esc) are ignored meanwhile.
 * 4. On any surprise it puts down what it holds and stops; when done, or stopped, it reads the
 *    chest again for the app. Pressing Sort again plans afresh from wherever things are.
 */
public final class SortRunner {
	private static final int TIMEOUT_TICKS = 60;       // 3 s for the game to show a click or a page
	private static final int CONFIRM_TICKS = 400;      // 20 s to press Sort again
	private static final int SETTLE_TICKS = 2;

	private enum Phase { WALKING, PLANNING, CONFIRM, RUNNING }

	private static SortRunner active;

	private final StorageScreens.Kind kind;
	private Phase phase = Phase.WALKING;
	private SortSteps steps;
	private int reserve = -1;
	private int ticks;               // since the last click, or in the current phase
	private int waiting;             // ticks the game has kept us waiting
	private Integer expectingPage;
	private String signature;
	private int stable;
	private int clicks;
	private int shown;               // clicks / 20 when progress was last shown

	private SortRunner(StorageScreens.Kind kind) {
		this.kind = kind;
	}

	public static void register() {
		ClientTickEvents.END_CLIENT_TICK.register(mc -> {
			if (active != null) {
				active.tick(mc);
			}
		});
	}

	/** Hands off the screen: true while it reads, plans or sorts (not while it waits for the go-ahead). */
	public static boolean running() {
		return active != null && active.phase != Phase.CONFIRM;
	}

	public static boolean confirming() {
		return active != null && active.phase == Phase.CONFIRM;
	}

	/** A press of the Sort button. */
	public static void press(AbstractContainerScreen<?> screen, StorageScreens.Kind kind) {
		Minecraft mc = Minecraft.getInstance();
		if (active != null) {
			if (active.phase == Phase.CONFIRM && active.kind == kind) {
				active.phase = Phase.RUNNING;
				active.ticks = 0;
				say(mc, "WynnGPT: sorting… (Esc stops)", true);
			}
			return;
		}
		SortRunner runner = new SortRunner(kind);
		active = runner;
		if (!PageWalker.start(screen, kind, (body, why) -> runner.walked(mc, body, why))) {
			active = null;
		}
	}

	/** Forget a plan waiting for the go-ahead (the player did something else). */
	public static void cancel() {
		if (confirming()) {
			active = null;
		}
	}

	private void walked(Minecraft mc, JsonObject body, String why) {
		if (active != this) {
			return;
		}
		if (body == null || why != null) {
			active = null;
			say(mc, "WynnGPT: not sorting: " + (why == null ? "no page was read" : why) + ".", false);
			if (body != null) {
				InventoryExporter.send(mc, body);
			}
			return;
		}
		phase = Phase.PLANNING;
		say(mc, "WynnGPT: planning the sort…", true);
		InventoryExporter.sort(mc, body, answer -> planned(mc, answer), () -> {
			if (active == this) {
				active = null;
			}
		});
	}

	private void planned(Minecraft mc, JsonObject answer) {
		if (active != this) {
			return;
		}
		String message = answer.has("message") ? answer.get("message").getAsString() : "";
		JsonObject plan = answer.getAsJsonObject("plan");
		if (plan == null || !plan.get("ready").getAsBoolean()) {
			active = null;
			say(mc, "WynnGPT: " + message, false);
			return;
		}
		steps = new SortSteps(parse(plan.getAsJsonArray("steps")));
		reserve = plan.get("reserve").isJsonNull() ? -1 : plan.get("reserve").getAsInt();
		phase = Phase.CONFIRM;
		ticks = 0;
		say(mc, "WynnGPT: " + message + " Press Sort again within 20 s to start; Esc stops it. "
			+ "Wynncraft's rules don't allow mods that click for you, so sorting is at your own risk.", false);
	}

	private void tick(Minecraft mc) {
		ticks++;
		if (phase == Phase.CONFIRM) {
			if (ticks > CONFIRM_TICKS || !(mc.screen instanceof AbstractContainerScreen<?> s) || StorageScreens.kind(s) != kind) {
				active = null;
				say(mc, "WynnGPT: sort not started.", true);
			}
			return;
		}
		if (phase != Phase.RUNNING) {
			return;
		}
		if (!(mc.screen instanceof AbstractContainerScreen<?> screen) || StorageScreens.kind(screen) != kind) {
			active = null;
			say(mc, "WynnGPT: sorting stopped (the chest was closed) after " + clicks + " clicks. "
				+ "Open it and press Sort to carry on from where things are.", false);
			return;
		}
		AbstractContainerMenu menu = screen.getMenu();
		if (ticks < Math.max(ExportConfig.sortClickDelayTicks(), 1)) {
			return;
		}
		SortSteps.View view = view(menu);
		if (expectingPage != null) {
			Integer page = view.page();
			if (page == null || !page.equals(expectingPage) || !settled(menu)) {
				if (ticks > TIMEOUT_TICKS) {
					stop(mc, screen, "page " + expectingPage + " didn't open");
				}
				return;
			}
			expectingPage = null;
		}
		SortSteps.Action action = steps.next(view);
		if (action instanceof SortSteps.Wait wait) {
			if (++waiting > TIMEOUT_TICKS) {
				String problem = steps.problem(view);
				stop(mc, screen, problem != null ? problem : "waited too long for " + wait.what());
			}
			return;
		}
		waiting = 0;
		switch (action) {
			case SortSteps.ClickChest c -> click(mc, screen, chestSlot(menu, c.slot()));
			case SortSteps.ClickInventory c -> click(mc, screen, inventorySlot(menu, c.slot()));
			case SortSteps.TurnPage t -> {
				int arrowSlot = t.next() ? Controls.NEXT_SLOT : Controls.PREVIOUS_SLOT;
				Integer to = PageWalker.arrow(menu, arrowSlot, t.next() ? ">" : "<");
				if (to == null) {
					stop(mc, screen, "couldn't find the page arrow");
					return;
				}
				expectingPage = to;
				signature = null;
				stable = 0;
				click(mc, screen, PageWalker.slot(menu, arrowSlot));
			}
			case SortSteps.Done d -> {
				active = null;
				say(mc, "WynnGPT: sorted (" + clicks + " clicks). Reading the chest again for the app…", false);
				reread(mc, screen);
			}
			case SortSteps.Stop s -> stop(mc, screen, s.why());
			default -> {
			}
		}
		if (clicks / 20 != shown && active == this) {
			shown = clicks / 20;
			say(mc, "WynnGPT: sorting… step " + steps.done() + " of " + steps.size() + " (Esc stops)", true);
		}
	}

	private void click(Minecraft mc, AbstractContainerScreen<?> screen, Slot slot) {
		if (slot == null || mc.gameMode == null || mc.player == null) {
			stop(mc, screen, "couldn't find the slot to click");
			return;
		}
		ticks = 0;
		clicks++;
		mc.gameMode.handleInventoryMouseClick(screen.getMenu().containerId, slot.index, 0, ClickType.PICKUP, mc.player);
	}

	/** Put down whatever the cursor holds, say why it stopped, and read the chest again for the app. */
	private void stop(Minecraft mc, AbstractContainerScreen<?> screen, String why) {
		active = null;
		AbstractContainerMenu menu = screen.getMenu();
		SortSteps.Action rescue = SortSteps.rescue(view(menu), reserve);
		Slot slot = rescue instanceof SortSteps.ClickInventory c ? inventorySlot(menu, c.slot())
			: rescue instanceof SortSteps.ClickChest c ? chestSlot(menu, c.slot()) : null;
		if (slot != null && mc.gameMode != null && mc.player != null) {
			mc.gameMode.handleInventoryMouseClick(menu.containerId, slot.index, 0, ClickType.PICKUP, mc.player);
		}
		boolean holding = !menu.getCarried().isEmpty();
		say(mc, "WynnGPT: sorting stopped after " + clicks + " clicks: " + why + "."
			+ (holding ? " You're still holding an item: put it down." : "")
			+ " Press Sort to plan again from where things are.", false);
		if (!holding) {
			reread(mc, screen);
		}
	}

	private static void reread(Minecraft mc, AbstractContainerScreen<?> screen) {
		StorageScreens.Kind kind = StorageScreens.kind(screen);
		PageWalker.start(screen, kind, (body, why) -> {
			if (body != null) {
				InventoryExporter.send(mc, body);
			}
		});
	}

	private boolean settled(AbstractContainerMenu menu) {
		String now = PageWalker.contents(menu);
		if (!now.equals(signature)) {
			signature = now;
			stable = 0;
			return false;
		}
		return ++stable >= SETTLE_TICKS;
	}

	private static SortSteps.View view(AbstractContainerMenu menu) {
		return new SortSteps.View() {
			public Integer page() {
				return PageWalker.page(menu);
			}

			public SortSteps.Stack chest(int slot) {
				Slot s = chestSlot(menu, slot);
				return s == null ? null : stack(s.getItem());
			}

			public SortSteps.Stack inventory(int slot) {
				Slot s = inventorySlot(menu, slot);
				return s == null ? null : stack(s.getItem());
			}

			public SortSteps.Stack cursor() {
				return stack(menu.getCarried());
			}
		};
	}

	private static SortSteps.Stack stack(ItemStack item) {
		return item.isEmpty() ? null
			: new SortSteps.Stack(InventoryExporter.sig(item), item.getCount(), Controls.clean(item.getHoverName().getString()));
	}

	/** One of the page's own 45 slots: never the arrows, the switch or Quick Actions. */
	private static Slot chestSlot(AbstractContainerMenu menu, int containerSlot) {
		return containerSlot >= 0 && containerSlot < SortSteps.STORAGE_SLOTS ? PageWalker.slot(menu, containerSlot) : null;
	}

	/** One of the player's inventory slots the plan carries items in (13-35). */
	private static Slot inventorySlot(AbstractContainerMenu menu, int inventorySlot) {
		if (inventorySlot < SortSteps.CARRY_FIRST || inventorySlot > SortSteps.CARRY_LAST) {
			return null;
		}
		for (Slot slot : menu.slots) {
			if (slot.container instanceof Inventory && slot.getContainerSlot() == inventorySlot) {
				return slot;
			}
		}
		return null;
	}

	private static List<SortSteps.Step> parse(JsonArray raw) {
		List<SortSteps.Step> out = new ArrayList<>();
		for (JsonElement e : raw) {
			JsonObject step = e.getAsJsonObject();
			if (step.get("op").getAsString().equals("page")) {
				Map<Integer, SortSteps.Stack> expect = new HashMap<>();
				for (JsonElement x : step.getAsJsonArray("expect")) {
					JsonArray a = x.getAsJsonArray();
					expect.put(a.get(0).getAsInt(), new SortSteps.Stack(a.get(1).getAsString(), a.get(2).getAsInt(), a.get(3).getAsString()));
				}
				out.add(new SortSteps.Page(step.get("page").getAsInt(), expect));
			} else {
				out.add(new SortSteps.Click(step.get("area").getAsString().equals("chest"), step.get("slot").getAsInt(),
					stackOf(step.get("slot_has")), stackOf(step.get("cursor_has"))));
			}
		}
		return out;
	}

	private static SortSteps.Stack stackOf(JsonElement e) {
		if (e == null || e.isJsonNull()) {
			return null;
		}
		JsonArray a = e.getAsJsonArray();
		return new SortSteps.Stack(a.get(0).getAsString(), a.get(1).getAsInt(), a.get(2).getAsString());
	}

	private static void say(Minecraft mc, String text, boolean actionBar) {
		if (mc.player != null) {
			mc.player.displayClientMessage(Component.literal(text), actionBar);
		}
	}
}
