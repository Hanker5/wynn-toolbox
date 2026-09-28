package com.hankryhays.wynngptchestexport;

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

/** Which of the player's own storages a screen shows: their inventory or one of their ender chests. */
public final class StorageScreens {
	public enum Kind {
		INVENTORY("inventory"), ACCOUNT("account"), CHARACTER("character"), UNKNOWN("unknown");

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

	// The Character Info compass's first tooltip line is the character's id, e.g. "§7a1b2c3d4".
	private static final int CHARACTER_INFO_SLOT = 7;
	private static final Pattern CHARACTER_ID = Pattern.compile("^[a-z0-9]{8}$");

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
		return Kind.UNKNOWN;
	}

	/** The active character's id, or null when the compass isn't where Wynncraft keeps it. */
	public static String characterId(Minecraft mc) {
		List<String> lore = characterLore(mc);
		if (lore.isEmpty()) {
			return null;
		}
		String first = strip(lore.getFirst());
		return CHARACTER_ID.matcher(first).matches() ? first : null;
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
