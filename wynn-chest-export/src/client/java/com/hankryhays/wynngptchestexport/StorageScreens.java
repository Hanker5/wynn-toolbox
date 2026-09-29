package com.hankryhays.wynngptchestexport;

import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.client.gui.screens.inventory.InventoryScreen;
import net.minecraft.core.component.DataComponents;
import net.minecraft.network.chat.Component;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.component.ItemLore;

import java.util.List;
import java.util.regex.Pattern;

/** Which of the player's own screens this is: their inventory, an ender chest, or their tomes or aspects. */
public final class StorageScreens {
	public enum Kind {
		INVENTORY("inventory"), ACCOUNT("account"), CHARACTER("character"), TOMES("tomes"), ASPECTS("aspects"),
		UNKNOWN("unknown");

		public final String id;

		Kind(String id) {
			this.id = id;
		}
	}

	// Wynncraft titles its ender chests with custom-font glyphs, not text. These are the
	// strings Wynntils matches (AccountBankContainer, CharacterBankContainer).
	private static final String BANK_TITLE = "\uDAFF\uDFF0\uE00F\uDAFF\uDF68";
	private static final String ACCOUNT_TITLE = BANK_TITLE + "\uF000";
	private static final String CHARACTER_TITLE = BANK_TITLE + "\uF001";
	// The Mastery Tomes menu (the tomes a character has equipped) and the Aspects menu,
	// as Wynntils matches them (MasteryTomesContainer, AspectsContainer).
	private static final String TOMES_TITLE = "\uDAFF\uDFDB\uE005";
	private static final String ASPECTS_TITLE = "\uDAFF\uDFEA\uE002";

	// The Character Info compass's first tooltip line is the character's id, e.g. "§7a1b2c3d4".
	private static final int CHARACTER_INFO_SLOT = 7;
	private static final Pattern CHARACTER_ID = Pattern.compile("^[a-z0-9]{8}$");
	// Some menus (Aspects) replace the whole inventory, compass included, with their own items:
	// the id last read stands in, kept fresh while no such menu is open.
	private static String lastCharacterId;

	private StorageScreens() {
	}

	/** The kind of storage `screen` shows, UNKNOWN for any other container, null for non-containers. */
	public static Kind kind(Screen screen) {
		if (screen instanceof InventoryScreen) {
			return Kind.INVENTORY;
		}
		if (!(screen instanceof AbstractContainerScreen<?>)) {
			return null;
		}
		String title = screen.getTitle().getString();
		if (title.contains(ACCOUNT_TITLE)) {
			return Kind.ACCOUNT;
		}
		if (title.contains(CHARACTER_TITLE)) {
			return Kind.CHARACTER;
		}
		if (title.contains(TOMES_TITLE)) {
			return Kind.TOMES;
		}
		if (title.contains(ASPECTS_TITLE)) {
			return Kind.ASPECTS;
		}
		return Kind.UNKNOWN;
	}

	/** The active character's id: from the compass, else the one last read there (null if never). */
	public static String characterId(Minecraft mc) {
		List<String> lore = characterLore(mc);
		String first = lore.isEmpty() ? "" : strip(lore.getFirst());
		if (CHARACTER_ID.matcher(first).matches()) {
			lastCharacterId = first;
		}
		return lastCharacterId;
	}

	/** Read the compass once a second while no menu covers the inventory (after a character switch, too). */
	public static void register() {
		int[] ticks = {0};
		ClientTickEvents.END_CLIENT_TICK.register(mc -> {
			if (++ticks[0] % 20 == 0 && mc.player != null && (mc.screen == null || mc.screen instanceof InventoryScreen)) {
				characterId(mc);
			}
		});
	}

	public static List<String> characterLore(Minecraft mc) {
		if (mc.player == null) {
			return List.of();
		}
		ItemStack compass = mc.player.getInventory().getItem(CHARACTER_INFO_SLOT);
		return compass.getOrDefault(DataComponents.LORE, ItemLore.EMPTY).lines().stream().map(Component::getString).toList();
	}

	public static String strip(String text) {
		return Controls.clean(text);
	}
}
