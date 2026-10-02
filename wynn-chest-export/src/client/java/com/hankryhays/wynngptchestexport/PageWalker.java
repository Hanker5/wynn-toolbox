package com.hankryhays.wynngptchestexport;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.core.component.DataComponents;
import net.minecraft.network.chat.Component;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ClickType;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.component.ItemLore;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.BiConsumer;

/**
 * Walks through every page of both ender chests and exports them all at once: back to
 * page 1 with the previous arrow, forward with the next arrow until there is none, then
 * "Storage Type" switches to the other chest (Account or Character) and it walks that one.
 * It only ever clicks the page arrows (slots 51, 52) and the switch (47), each only when
 * named exactly so, one click at a time, and waits for each page to arrive before the next.
 * It never touches anything else (46, "Quick Actions", would dump the player's inventory
 * into the bank). Closing the chest stops it; what was read so far is still sent, and only
 * chests walked to the end count as complete (the app drops no pages of the others).
 * For sorting it walks only the open chest and hands the export to the sort instead of
 * sending it.
 */
public final class PageWalker {
	private static final int SWITCH_SLOT = Controls.SWITCH_SLOT;
	private static final int PREVIOUS_SLOT = Controls.PREVIOUS_SLOT;
	private static final int NEXT_SLOT = Controls.NEXT_SLOT;
	private static final int STORAGE_SLOTS = Controls.STORAGE_SLOTS;
	private static final int TIMEOUT_TICKS = 60;      // 3 s for a page to arrive
	private static final int SETTLE_TICKS = 2;        // its slots unchanged this long

	private static PageWalker active;

	private StorageScreens.Kind kind;
	private final int delay;
	private final Map<String, JsonObject> pages = new LinkedHashMap<>();
	private final JsonArray complete = new JsonArray();
	private boolean forward;
	private StorageScreens.Kind switchingTo;      // after clicking "Storage Type"
	private int sinceClick;
	private Integer expecting;        // the page the last click leads to
	private String signature;
	private int stable;
	private JsonObject source;
	private final BiConsumer<JsonObject, String> then;     // only this chest, then this (export or null, why it stopped)

	private PageWalker(StorageScreens.Kind kind, int delay, BiConsumer<JsonObject, String> then) {
		this.kind = kind;
		this.delay = delay;
		this.then = then;
	}

	public static void register() {
		ClientTickEvents.END_CLIENT_TICK.register(mc -> {
			if (active != null) {
				active.tick(mc);
			}
		});
	}

	public static boolean running() {
		return active != null;
	}

	public static void start(AbstractContainerScreen<?> screen, StorageScreens.Kind kind) {
		start(screen, kind, null);
	}

	/**
	 * Walk the open chest only, and give `then` the export (null if no page was read) and why it
	 * stopped early (null if it read every page). Returns whether the walk started.
	 */
	public static boolean start(AbstractContainerScreen<?> screen, StorageScreens.Kind kind, BiConsumer<JsonObject, String> then) {
		Minecraft mc = Minecraft.getInstance();
		if (active != null) {
			return false;
		}
		if (!screen.getMenu().getCarried().isEmpty()) {
			say(mc, "WynnGPT: put down the item you're holding first.", false);
			return false;
		}
		Integer page = page(screen.getMenu());
		if (page == null) {
			if (then != null) {
				say(mc, "WynnGPT: can't tell which page this is.", false);
				return false;
			}
			say(mc, "WynnGPT: can't tell which page this is; exporting just this page.", false);
			InventoryExporter.export(screen, kind);
			return false;
		}
		active = new PageWalker(kind, Math.max(ExportConfig.pageDelayTicks(), 2), then);
		active.capture(mc, screen, page);
		return true;
	}

	private void tick(Minecraft mc) {
		sinceClick++;
		StorageScreens.Kind now = mc.screen == null ? null : StorageScreens.kind(mc.screen);
		if (switchingTo != null && now == switchingTo && mc.screen instanceof AbstractContainerScreen<?> other) {
			Integer page = page(other.getMenu());
			if (page != null && settled(other.getMenu())) {
				kind = switchingTo;
				switchingTo = null;
				forward = false;
				sinceClick = 0;
				capture(mc, other, page);
			}
			return;
		}
		if (switchingTo != null) {
			if (sinceClick > TIMEOUT_TICKS) {
				finish(mc, "the other ender chest didn't open");
			}
			return;
		}
		if (!(mc.screen instanceof AbstractContainerScreen<?> screen) || now != kind) {
			finish(mc, "the ender chest was closed");
			return;
		}
		AbstractContainerMenu menu = screen.getMenu();
		if (expecting != null) {
			Integer page = page(menu);
			if (page == null || !page.equals(expecting)) {
				if (sinceClick > TIMEOUT_TICKS) {
					finish(mc, "page " + expecting + " didn't open");
				}
				return;
			}
			if (!settled(menu)) {
				return;
			}
			expecting = null;
			capture(mc, screen, page);
		}
		if (sinceClick < delay) {
			return;
		}
		if (!forward) {
			Integer to = arrow(menu, PREVIOUS_SLOT, "<");
			if (to != null) {
				click(mc, menu, PREVIOUS_SLOT, to);
				return;
			}
			forward = true;
		}
		Integer to = arrow(menu, NEXT_SLOT, ">");
		if (to != null) {
			click(mc, menu, NEXT_SLOT, to);
			return;
		}
		Slot next = slot(menu, NEXT_SLOT);
		if (next != null && !next.getItem().isEmpty() && Controls.unreadableArrow(rawName(next.getItem()), lore(next.getItem()))) {
			finish(mc, "couldn't read the next-page arrow");     // not complete: the app drops nothing
			return;
		}
		complete.add(kind.id);                      // this chest is read to its last page
		StorageScreens.Kind other = kind == StorageScreens.Kind.ACCOUNT ? StorageScreens.Kind.CHARACTER : StorageScreens.Kind.ACCOUNT;
		if (then == null && complete.size() < 2 && isSwitch(menu)) {
			switchingTo = other;
			click(mc, menu, SWITCH_SLOT, null);
			return;
		}
		finish(mc, null);
	}

	private boolean settled(AbstractContainerMenu menu) {
		String now = contents(menu);
		if (!now.equals(signature)) {
			signature = now;
			stable = 0;
			return false;
		}
		return ++stable >= SETTLE_TICKS;
	}

	private void capture(Minecraft mc, AbstractContainerScreen<?> screen, int page) {
		JsonObject entry = new JsonObject();
		entry.addProperty("kind", kind.id);
		entry.addProperty("page", page);
		entry.add("storage", InventoryExporter.storage(mc, screen.getMenu()));
		pages.put(kind.id + ":" + page, entry);
		if (source == null) {
			source = InventoryExporter.collect(mc, screen, kind).getAsJsonObject("source");
		}
		say(mc, "WynnGPT: " + label() + " page " + page + " read (" + pages.size() + " so far)…", true);
	}

	private void click(Minecraft mc, AbstractContainerMenu menu, int containerSlot, Integer to) {
		Slot slot = slot(menu, containerSlot);
		boolean allowed = containerSlot == SWITCH_SLOT ? isSwitch(menu)
			: (containerSlot == PREVIOUS_SLOT || containerSlot == NEXT_SLOT) && to != null;
		if (!allowed || slot == null || mc.gameMode == null || mc.player == null) {
			finish(mc, "couldn't find the page arrow");
			return;
		}
		expecting = to;
		signature = null;
		stable = 0;
		sinceClick = 0;
		mc.gameMode.handleInventoryMouseClick(menu.containerId, slot.index, 0, ClickType.PICKUP, mc.player);
	}

	private void finish(Minecraft mc, String why) {
		active = null;
		if (pages.isEmpty()) {
			if (then != null) {
				then.accept(null, why);
			}
			return;
		}
		JsonObject body = new JsonObject();
		body.addProperty("version", 2);
		body.addProperty("kind", "ender_all");
		body.add("complete", complete);            // the chests read to their last page
		body.add("character", InventoryExporter.character(mc));
		if (source != null) {
			body.add("source", source);
		}
		body.add("storage", new JsonArray());
		body.add("inventory", InventoryExporter.inventory(mc));
		JsonArray list = new JsonArray();
		pages.values().forEach(list::add);
		body.add("pages", list);
		if (then != null) {
			then.accept(body, why);
			return;
		}
		if (why != null) {
			say(mc, "WynnGPT: stopped after " + pages.size() + " pages (" + why + "); sending those.", false);
		}
		InventoryExporter.send(mc, body);
	}

	private String label() {
		return kind == StorageScreens.Kind.ACCOUNT ? "Account ender chest" : "Character ender chest";
	}

	/** The page the menu shows, from its arrows; 1 with none, null if they make no sense. */
	static Integer page(AbstractContainerMenu menu) {
		return Controls.page(arrow(menu, NEXT_SLOT, ">"), arrow(menu, PREVIOUS_SLOT, "<"));
	}

	/** The page a real arrow in `containerSlot` leads to, or null. */
	static Integer arrow(AbstractContainerMenu menu, int containerSlot, String direction) {
		Slot slot = slot(menu, containerSlot);
		return slot == null || slot.getItem().isEmpty() ? null
			: Controls.arrow(rawName(slot.getItem()), lore(slot.getItem()), direction);
	}

	private static boolean isSwitch(AbstractContainerMenu menu) {
		Slot slot = slot(menu, SWITCH_SLOT);
		return slot != null && !slot.getItem().isEmpty() && Controls.isSwitch(rawName(slot.getItem()), lore(slot.getItem()));
	}

	private static String rawName(ItemStack stack) {
		return stack.getHoverName().getString();
	}

	private static List<String> lore(ItemStack stack) {
		return stack.getOrDefault(DataComponents.LORE, ItemLore.EMPTY).lines().stream().map(Component::getString).toList();
	}

	static Slot slot(AbstractContainerMenu menu, int containerSlot) {
		for (Slot slot : menu.slots) {
			if (!(slot.container instanceof Inventory) && slot.getContainerSlot() == containerSlot) {
				return slot;
			}
		}
		return null;
	}

	private static String name(ItemStack stack) {
		return StorageScreens.strip(stack.getHoverName().getString());
	}

	/** What a page holds, to tell when its items have all arrived. */
	static String contents(AbstractContainerMenu menu) {
		StringBuilder out = new StringBuilder();
		for (Slot slot : menu.slots) {
			if (!(slot.container instanceof Inventory) && slot.getContainerSlot() < STORAGE_SLOTS && !slot.getItem().isEmpty()) {
				out.append(slot.getContainerSlot()).append(':').append(name(slot.getItem())).append('x').append(slot.getItem().getCount()).append(';');
			}
		}
		return out.toString();
	}

	private static void say(Minecraft mc, String text, boolean actionBar) {
		if (mc.player != null) {
			mc.player.displayClientMessage(Component.literal(text), actionBar);
		}
	}
}
