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

public final class InventoryExporter {
	private static final Gson GSON = new Gson();
	private static final HttpClient HTTP = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(3)).build();

	private InventoryExporter() {
	}

	public static void export(AbstractContainerScreen<?> screen) {
		Minecraft mc = Minecraft.getInstance();
		AppLocator.Result located = AppLocator.locate();
		if (located instanceof AppLocator.NotConfigured) {
			say(mc, Component.literal("WynnGPT export: set \"builds_path\" to your WynnGPT builds folder in " + ExportConfig.file()));
			return;
		}
		if (located instanceof AppLocator.FolderMissing missing) {
			say(mc, Component.literal("WynnGPT export: can't see the folder " + missing.folder()
				+ ". Check builds_path in " + ExportConfig.file()
				+ ". If Minecraft runs from a Flatpak launcher, give it access to that folder."));
			return;
		}
		if (!(located instanceof AppLocator.Found found)) {
			say(mc, Component.literal("WynnGPT isn't running. Open the WynnGPT app and try again."));
			return;
		}

		String body = GSON.toJson(collect(mc, screen));
		HttpRequest request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + found.server().port() + "/api/inventory/import"))
			.timeout(Duration.ofSeconds(10))
			.header("Content-Type", "application/json")
			.header("x-wt-token", found.server().token())
			.POST(HttpRequest.BodyPublishers.ofString(body))
			.build();

		HTTP.sendAsync(request, HttpResponse.BodyHandlers.ofString()).whenComplete((response, error) -> mc.execute(() -> {
			if (error != null) {
				say(mc, Component.literal("WynnGPT isn't running. Open the WynnGPT app and try again."));
			} else if (response.statusCode() / 100 == 2) {
				say(mc, Component.literal("Exported to WynnGPT: " + summary(response.body())));
			} else {
				WynnGPTChestExportClient.LOGGER.warn("WynnGPT returned {}: {}", response.statusCode(), response.body());
				say(mc, Component.literal("WynnGPT rejected the export (HTTP " + response.statusCode() + "): " + detail(response.body())));
			}
		}));
	}

	private static String summary(String responseBody) {
		try {
			JsonObject json = GSON.fromJson(responseBody, JsonObject.class);
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

	private static JsonObject collect(Minecraft mc, AbstractContainerScreen<?> screen) {
		AbstractContainerMenu menu = screen.getMenu();
		JsonObject source = new JsonObject();
		source.addProperty("title", screen.getTitle().getString());
		source.addProperty("menu", menuName(menu));

		var ops = mc.level.registryAccess().createSerializationContext(JsonOps.INSTANCE);
		JsonArray slots = new JsonArray();
		for (Slot slot : menu.slots) {
			ItemStack stack = slot.getItem();
			if (stack.isEmpty()) {
				continue;
			}
			JsonObject entry = new JsonObject();
			entry.addProperty("slot", slot.index);
			entry.addProperty("container", slot.container instanceof Inventory ? "player" : "container");
			entry.addProperty("item_id", BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
			entry.addProperty("count", stack.getCount());
			entry.addProperty("name", stack.getHoverName().getString());
			JsonArray lore = new JsonArray();
			for (Component line : stack.getOrDefault(DataComponents.LORE, ItemLore.EMPTY).lines()) {
				lore.add(line.getString());
			}
			entry.add("lore", lore);
			JsonElement raw = ItemStack.CODEC.encodeStart(ops, stack).result().orElse(null);
			if (raw != null) {
				entry.add("raw", raw);
			}
			slots.add(entry);
		}

		JsonObject root = new JsonObject();
		root.add("source", source);
		root.add("slots", slots);
		return root;
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
