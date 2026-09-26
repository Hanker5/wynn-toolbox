# WynnGPT Chest Export

A client-side Fabric mod for Minecraft 1.21.11. It puts a small WynnGPT button to the right of every container screen: chests, the player inventory, and so on. Clicking the button sends every item in that screen to the running WynnGPT app, which adds the items, tomes and aspects it recognises to `builds/inventory.json`.

## Setup

1. Build with `./gradlew build`. The jar is written to `build/libs/`. Put it in your mods folder together with Fabric API.
2. Start WynnGPT (`wt serve`).
3. On first launch the mod creates `config/wynngpt-chest-export.json`. Set `builds_path` in that file to your WynnGPT `builds` folder, for example `/path/to/wynn-toolbox/builds`.

If your launcher is a Flatpak (Prism Launcher from Flathub, for example), it can't see that folder until you allow it. Run this, then restart the launcher:

    flatpak override --user --filesystem=~/wynn-toolbox/builds:ro org.prismlauncher.PrismLauncher

The mod locates the app through `builds/.server.json`, which holds the port and token. If that file is missing, or hasn't been updated in the last 20 seconds, the button says to open WynnGPT.

## Development

`./gradlew runClient` starts a dev client, which reads its config from `run/config/`. The server side of the export is `POST /api/inventory/import` in `wynntools/web/server.py`, and the slot parsing is in `wynntools/gameimport.py`.
