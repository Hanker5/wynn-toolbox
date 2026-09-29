package com.hankryhays.wynngptchestexport;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.network.chat.Component;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ClickType;
import net.minecraft.world.inventory.Slot;

import java.util.ArrayList;
import java.util.List;

/**
 * Walks through every page of the Aspects menu and exports them all at once: back to the
 * first page with "Previous Page", then forward with "Next Page" until there is none. The
 * arrows carry no page number, so pages are counted from the first. It clicks nothing but
 * those two items (in the player-inventory part of the screen, where the game puts them),
 * and waits for each page's aspects to arrive before the next click. Closing the menu stops
 * it; what was read is still sent, marked incomplete (the app then only raises tiers).
 */
public final class AspectWalker {
	private static final int TIMEOUT_TICKS = 60;      // 3 s for a page to arrive
	private static final int SETTLE_TICKS = 2;        // its slots unchanged this long

	private static AspectWalker active;

	private final int delay;
	private final List<JsonArray> pages = new ArrayList<>();
	private boolean forward;
	private boolean waiting;
	private String before;          // the page's aspects when the last click went out
	private String signature;
	private int stable;
	private int sinceClick;
	private JsonObject source;

	private AspectWalker(int delay) {
		this.delay = delay;
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

	public static void start(AbstractContainerScreen<?> screen) {
		Minecraft mc = Minecraft.getInstance();
		if (active != null) {
			return;
		}
		if (!screen.getMenu().getCarried().isEmpty()) {
			say(mc, "WynnGPT: put down the item you're holding first.", false);
			return;
		}
		active = new AspectWalker(Math.max(ExportConfig.pageDelayTicks(), 2));
		active.source = InventoryExporter.collect(mc, screen, StorageScreens.Kind.ASPECTS).getAsJsonObject("source");
		active.sinceClick = active.delay;          // the first click can go right away
	}

	private void tick(Minecraft mc) {
		if (!(mc.screen instanceof AbstractContainerScreen<?> screen) || StorageScreens.kind(screen) != StorageScreens.Kind.ASPECTS) {
			finish(mc, "the Aspects menu was closed", false);
			return;
		}
		AbstractContainerMenu menu = screen.getMenu();
		sinceClick++;
		if (waiting) {
			String now = aspects(menu);
			if (now.equals(before)) {                 // the page hasn't turned yet
				if (sinceClick > TIMEOUT_TICKS) {
					// The last page still shows "Next Page", which then leads nowhere: a page that
					// isn't full was the last one. A full one might not be, so the walk stays incomplete.
					if (forward && count(menu) < Controls.ASPECTS_LAST - Controls.ASPECTS_FIRST + 1) {
						finish(mc, null, true);
					} else {
						finish(mc, "the next page didn't open", false);
					}
				}
				return;
			}
			if (!now.equals(signature)) {
				signature = now;
				stable = 0;
				return;
			}
			if (++stable < SETTLE_TICKS) {
				return;
			}
			waiting = false;
			if (forward) {
				capture(mc, menu);
			}
		}
		if (sinceClick < delay) {
			return;
		}
		if (!forward) {
			Slot previous = arrow(menu, Controls.ASPECTS_PREVIOUS_SLOT, "<");
			if (previous != null) {
				click(mc, menu, previous);
				return;
			}
			forward = true;                          // on the first page now
			capture(mc, menu);
		}
		Slot next = arrow(menu, Controls.ASPECTS_NEXT_SLOT, ">");
		if (next != null) {
			click(mc, menu, next);
			return;
		}
		finish(mc, null, true);
	}

	private void capture(Minecraft mc, AbstractContainerMenu menu) {
		pages.add(InventoryExporter.storage(mc, menu));
		say(mc, "WynnGPT: aspects page " + pages.size() + " read…", true);
	}

	private void click(Minecraft mc, AbstractContainerMenu menu, Slot slot) {
		if (mc.gameMode == null || mc.player == null) {
			finish(mc, "couldn't click the page arrow", false);
			return;
		}
		before = aspects(menu);
		signature = null;
		stable = 0;
		sinceClick = 0;
		waiting = true;
		mc.gameMode.handleInventoryMouseClick(menu.containerId, slot.index, 0, ClickType.PICKUP, mc.player);
	}

	private void finish(Minecraft mc, String why, boolean complete) {
		active = null;
		if (pages.isEmpty()) {
			if (why != null) {
				say(mc, "WynnGPT: nothing read (" + why + ").", false);
			}
			return;
		}
		JsonObject body = new JsonObject();
		body.addProperty("version", 2);
		body.addProperty("kind", "aspects_all");
		JsonArray done = new JsonArray();
		if (complete) {
			done.add("aspects");
		}
		body.add("complete", done);
		body.add("character", InventoryExporter.character(mc));
		body.add("source", source);
		body.add("storage", new JsonArray());
		body.add("inventory", new JsonArray());     // the game shows menu items there, not the player's
		JsonArray list = new JsonArray();
		for (int k = 0; k < pages.size(); k++) {
			JsonObject page = new JsonObject();
			page.addProperty("kind", "aspects");
			page.addProperty("page", k + 1);
			page.add("storage", pages.get(k));
			list.add(page);
		}
		body.add("pages", list);
		if (why != null) {
			say(mc, "WynnGPT: stopped after " + pages.size() + " aspect pages (" + why + "); sending those.", false);
		}
		InventoryExporter.send(mc, body);
	}

	/** The arrow item in the player-inventory slot `inventorySlot`, if it is one; else null. */
	private static Slot arrow(AbstractContainerMenu menu, int inventorySlot, String direction) {
		for (Slot slot : menu.slots) {
			if (slot.container instanceof Inventory && slot.getContainerSlot() == inventorySlot && !slot.getItem().isEmpty()
				&& Controls.aspectsArrow(slot.getItem().getHoverName().getString(), direction)) {
				return slot;
			}
		}
		return null;
	}

	/** How many aspects the page shows. */
	private static int count(AbstractContainerMenu menu) {
		int n = 0;
		for (Slot slot : menu.slots) {
			int k = slot.getContainerSlot();
			if (!(slot.container instanceof Inventory) && k >= Controls.ASPECTS_FIRST && k <= Controls.ASPECTS_LAST
				&& !slot.getItem().isEmpty()) {
				n++;
			}
		}
		return n;
	}

	/** The aspects the page shows, to tell when a new page has arrived. */
	private static String aspects(AbstractContainerMenu menu) {
		StringBuilder out = new StringBuilder();
		for (Slot slot : menu.slots) {
			int k = slot.getContainerSlot();
			if (!(slot.container instanceof Inventory) && k >= Controls.ASPECTS_FIRST && k <= Controls.ASPECTS_LAST
				&& !slot.getItem().isEmpty()) {
				out.append(k).append(':').append(Controls.clean(slot.getItem().getHoverName().getString())).append(';');
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
