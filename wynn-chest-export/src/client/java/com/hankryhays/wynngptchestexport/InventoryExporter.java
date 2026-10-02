package com.hankryhays.wynngptchestexport;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.mojang.serialization.JsonOps;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.ComponentSerialization;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.component.ItemLore;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.function.Consumer;

public final class InventoryExporter {
	private static final Gson GSON = new Gson();
	private static final HttpClient HTTP = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(3)).build();

	private InventoryExporter() {
	}

	public static void export(AbstractContainerScreen<?> screen, StorageScreens.Kind kind) {
		Minecraft mc = Minecraft.getInstance();
		send(mc, collect(mc, screen, kind));
	}

	/** Posts an export to the running app and reports the result in chat. */
	public static void send(Minecraft mc, JsonObject export) {
		post(mc, "/api/inventory/import", export, json -> say(mc, Component.literal("Exported to WynnGPT: " + summary(json))), () -> {
		});
	}

	/**
	 * Posts a walk through one ender chest to the app's sorting endpoint; `then` gets its
	 * answer ({"plan", "message"}), `failed` runs when there is none (said in chat).
	 */
	public static void sort(Minecraft mc, JsonObject export, Consumer<JsonObject> then, Runnable failed) {
		post(mc, "/api/inventory/sort", export, json -> {
			try {
				then.accept(GSON.fromJson(json, JsonObject.class));
			} catch (RuntimeException e) {
				WynnGPTChestExportClient.LOGGER.warn("WynnGPT's sort plan couldn't be read", e);
				say(mc, Component.literal("WynnGPT: couldn't read the sort plan."));
				failed.run();
			}
		}, failed);
	}

	private static void post(Minecraft mc, String path, JsonObject export, Consumer<String> ok, Runnable failed) {
		AppLocator.Result located = AppLocator.locate();
		if (located instanceof AppLocator.NotConfigured) {
			say(mc, Component.literal("WynnGPT export: set \"builds_path\" to your WynnGPT builds folder in " + ExportConfig.file()));
			failed.run();
			return;
		}
		if (located instanceof AppLocator.FolderMissing missing) {
			say(mc, Component.literal("WynnGPT export: can't see the folder " + missing.folder()
				+ ". Check builds_path in " + ExportConfig.file()
				+ ". If Minecraft runs from a Flatpak launcher, give it access to that folder."));
			failed.run();
			return;
		}
		if (!(located instanceof AppLocator.Found found)) {
			say(mc, Component.literal("WynnGPT isn't running. Open the WynnGPT app and try again."));
			failed.run();
			return;
		}

		String body = GSON.toJson(export);
		HttpRequest request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + found.server().port() + path))
			.timeout(Duration.ofSeconds(10))
			.header("Content-Type", "application/json")
			.header("x-wt-token", found.server().token())
			.POST(HttpRequest.BodyPublishers.ofString(body))
			.build();

		HTTP.sendAsync(request, HttpResponse.BodyHandlers.ofString()).whenComplete((response, error) -> mc.execute(() -> {
			if (error != null) {
				say(mc, Component.literal("WynnGPT isn't running. Open the WynnGPT app and try again."));
				failed.run();
			} else if (response.statusCode() / 100 == 2) {
				ok.accept(response.body());
			} else {
				WynnGPTChestExportClient.LOGGER.warn("WynnGPT returned {}: {}", response.statusCode(), response.body());
				say(mc, Component.literal("WynnGPT rejected the export (HTTP " + response.statusCode() + "): " + detail(response.body())));
				failed.run();
			}
		}));
	}

	private static String summary(String responseBody) {
		try {
			JsonObject json = GSON.fromJson(responseBody, JsonObject.class);
			if (json.has("message")) {
				return json.get("message").getAsString();
			}
			JsonObject imported = json.getAsJsonObject("imported");
			int unknown = json.getAsJsonArray("unknown").size();
			return imported.get("items").getAsInt() + " new items, " + imported.get("rolls").getAsInt() + " with updated rolls, "
				+ imported.get("tomes").getAsInt() + " tomes, "
				+ imported.get("aspects").getAsInt() + " aspects (" + unknown + " unrecognised)";
		} catch (RuntimeException e) {
			return "done";
		}
	}

	private static String detail(String responseBody) {
		try {
			return GSON.fromJson(responseBody, JsonObject.class).get("detail").getAsString();
		} catch (RuntimeException e) {
			String text = responseBody == null ? "" : responseBody.strip();
			return text.length() > 120 ? text.substring(0, 120) + "..." : text;
		}
	}

	private static void say(Minecraft mc, Component message) {
		if (mc.player != null) {
			mc.player.displayClientMessage(message, false);
		}
	}

	/**
	 * Export format 2: the storage's own slots (numbered as the game does, page arrows included),
	 * the player's whole inventory whatever screen is open, and the active character.
	 */
	public static JsonObject collect(Minecraft mc, AbstractContainerScreen<?> screen, StorageScreens.Kind kind) {
		AbstractContainerMenu menu = screen.getMenu();
		var ops = mc.level.registryAccess().createSerializationContext(JsonOps.INSTANCE);
		JsonObject source = new JsonObject();
		source.addProperty("title", screen.getTitle().getString());
		ComponentSerialization.CODEC.encodeStart(ops, screen.getTitle()).result().ifPresent(t -> source.add("title_json", t));
		source.addProperty("menu", menuName(menu));

		JsonObject root = new JsonObject();
		root.addProperty("version", 2);
		root.addProperty("kind", kind.id);
		root.add("character", character(mc));
		root.add("source", source);
		root.add("storage", kind == StorageScreens.Kind.INVENTORY ? new JsonArray() : storage(mc, menu));
		// In the Aspects menu the game shows its own items where the player's inventory goes.
		root.add("inventory", kind == StorageScreens.Kind.ASPECTS ? new JsonArray() : inventory(mc));
		return root;
	}

	public static JsonObject character(Minecraft mc) {
		JsonObject character = new JsonObject();
		String id = StorageScreens.characterId(mc);
		if (id != null) {
			character.addProperty("id", id);
		}
		JsonArray lore = new JsonArray();
		StorageScreens.characterLore(mc).forEach(lore::add);
		character.add("lore", lore);
		return character;
	}

	/** The container's own slots (not the player's), by their slot number in the container. */
	public static JsonArray storage(Minecraft mc, AbstractContainerMenu menu) {
		var ops = mc.level.registryAccess().createSerializationContext(JsonOps.INSTANCE);
		JsonArray slots = new JsonArray();
		for (Slot slot : menu.slots) {
			if (!(slot.container instanceof Inventory) && !slot.getItem().isEmpty()) {
				slots.add(stack(ops, slot.getContainerSlot(), slot.getItem()));
			}
		}
		return slots;
	}

	/** The player's inventory: 0-8 hotbar, 9-35 main, 36-39 armor, 40 offhand. */
	public static JsonArray inventory(Minecraft mc) {
		var ops = mc.level.registryAccess().createSerializationContext(JsonOps.INSTANCE);
		Inventory inventory = mc.player.getInventory();
		JsonArray slots = new JsonArray();
		for (int i = 0; i < inventory.getContainerSize(); i++) {
			ItemStack stack = inventory.getItem(i);
			if (!stack.isEmpty()) {
				slots.add(stack(ops, i, stack));
			}
		}
		return slots;
	}

	private static JsonObject stack(com.mojang.serialization.DynamicOps<JsonElement> ops, int slot, ItemStack stack) {
		JsonObject entry = new JsonObject();
		entry.addProperty("slot", slot);
		entry.addProperty("item_id", BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
		entry.addProperty("count", stack.getCount());
		entry.addProperty("name", stack.getHoverName().getString());
		JsonArray lore = new JsonArray();
		for (Component line : stack.getOrDefault(DataComponents.LORE, ItemLore.EMPTY).lines()) {
			lore.add(line.getString());
		}
		entry.add("lore", lore);
		entry.addProperty("sig", sig(stack));
		JsonElement raw = ItemStack.CODEC.encodeStart(ops, stack).result().orElse(null);
		if (raw != null) {
			entry.add("raw", raw);
		}
		return entry;
	}

	/** The stack's id for sorting (SortSteps.sig): its item, name and tooltip. */
	public static String sig(ItemStack stack) {
		return SortSteps.sig(BuiltInRegistries.ITEM.getKey(stack.getItem()).toString(), stack.getHoverName().getString(), lore(stack));
	}

	public static List<String> lore(ItemStack stack) {
		return stack.getOrDefault(DataComponents.LORE, ItemLore.EMPTY).lines().stream().map(Component::getString).toList();
	}

	private static String menuName(AbstractContainerMenu menu) {
		try {
			var key = BuiltInRegistries.MENU.getKey(menu.getType());
			return key == null ? menu.getClass().getSimpleName() : key.toString();
		} catch (RuntimeException e) {
			return menu.getClass().getSimpleName();
		}
	}
}
