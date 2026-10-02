package com.hankryhays.wynngptchestexport;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import net.fabricmc.loader.api.FabricLoader;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

public final class ExportConfig {
	private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

	private ExportConfig() {
	}

	public static Path file() {
		return FabricLoader.getInstance().getConfigDir().resolve(WynnGPTChestExportClient.MOD_ID + ".json");
	}

	/** Path to the WynnGPT repo's builds/ folder, or an empty string when unset. Creates the file on first use. */
	public static String buildsPath() {
		JsonObject json = read();
		if (json == null || !json.has("builds_path") || json.get("builds_path").isJsonNull()) {
			return "";
		}
		return json.get("builds_path").getAsString().trim();
	}

	/** "capture": true shows the button on every container, to record samples of screens the mod doesn't know yet. */
	public static boolean capture() {
		JsonObject json = read();
		try {
			return json != null && json.has("capture") && json.get("capture").getAsBoolean();
		} catch (RuntimeException e) {
			return false;
		}
	}

	/** The button in an ender chest reads every page of both chests, unless "walk_pages" is false. */
	public static boolean walkPages() {
		JsonObject json = read();
		try {
			return json == null || !json.has("walk_pages") || json.get("walk_pages").getAsBoolean();
		} catch (RuntimeException e) {
			return true;
		}
	}

	/** "page_delay_ticks": the least time between two page clicks (20 ticks = 1 s). */
	public static int pageDelayTicks() {
		JsonObject json = read();
		try {
			return json != null && json.has("page_delay_ticks") ? json.get("page_delay_ticks").getAsInt() : 6;
		} catch (RuntimeException e) {
			return 6;
		}
	}

	/** "sort_click_delay_ticks": the least time between two clicks while sorting (20 ticks = 1 s). */
	public static int sortClickDelayTicks() {
		JsonObject json = read();
		try {
			return json != null && json.has("sort_click_delay_ticks") ? json.get("sort_click_delay_ticks").getAsInt() : 5;
		} catch (RuntimeException e) {
			return 5;
		}
	}

	private static JsonObject read() {
		Path file = file();
		try {
			if (!Files.exists(file)) {
				JsonObject fresh = new JsonObject();
				fresh.addProperty("builds_path", "");
				Files.writeString(file, GSON.toJson(fresh));
				return fresh;
			}
			return GSON.fromJson(Files.readString(file), JsonObject.class);
		} catch (IOException | RuntimeException e) {
			WynnGPTChestExportClient.LOGGER.warn("Could not read {}", file, e);
			return null;
		}
	}
}
