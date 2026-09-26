package com.hankryhays.wynngptchestexport;

import com.google.gson.Gson;
import com.google.gson.JsonObject;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;

/** Finds the running WynnGPT app through builds/.server.json, which the app touches every 5 seconds. */
public final class AppLocator {
	private static final Duration STALE = Duration.ofSeconds(20);
	private static final Gson GSON = new Gson();

	public record Server(int port, String token) {
	}

	public sealed interface Result permits Found, NotConfigured, FolderMissing, NotRunning {
	}

	public record Found(Server server) implements Result {
	}

	public record NotConfigured() implements Result {
	}

	public record FolderMissing(Path folder) implements Result {
	}

	public record NotRunning() implements Result {
	}

	private AppLocator() {
	}

	public static Result locate() {
		String buildsPath = ExportConfig.buildsPath();
		if (buildsPath.isEmpty()) {
			return new NotConfigured();
		}
		Path folder = Path.of(buildsPath);
		if (!Files.isDirectory(folder)) {
			return new FolderMissing(folder);
		}
		Path file = folder.resolve(".server.json");
		try {
			Instant modified = Files.getLastModifiedTime(file).toInstant();
			if (Duration.between(modified, Instant.now()).compareTo(STALE) > 0) {
				return new NotRunning();
			}
			JsonObject json = GSON.fromJson(Files.readString(file), JsonObject.class);
			return new Found(new Server(json.get("port").getAsInt(), json.get("token").getAsString()));
		} catch (IOException | RuntimeException e) {
			return new NotRunning();
		}
	}
}
