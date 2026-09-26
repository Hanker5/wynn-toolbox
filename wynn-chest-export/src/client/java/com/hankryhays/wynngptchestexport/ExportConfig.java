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
		Path file = file();
		try {
			if (!Files.exists(file)) {
				JsonObject fresh = new JsonObject();
				fresh.addProperty("builds_path", "");
				Files.writeString(file, GSON.toJson(fresh));
				return "";
			}
			JsonObject json = GSON.fromJson(Files.readString(file), JsonObject.class);
			if (json == null || !json.has("builds_path") || json.get("builds_path").isJsonNull()) {
				return "";
			}
			return json.get("builds_path").getAsString().trim();
		} catch (IOException | RuntimeException e) {
			WynnGPTChestExportClient.LOGGER.warn("Could not read {}", file, e);
			return "";
		}
	}
}
