# WynnGPT Chest Export

A client-side Fabric mod for Minecraft 1.21.11. It puts a small WynnGPT button to the right of the player's own inventory, their Account and Character ender chests, and their Mastery Tomes and Aspects menus (recognised by the glyphs Wynncraft titles them with, as Wynntils does). Clicking the button sends that storage's slots, the player's whole inventory and the active character's id to the running WynnGPT app, which records them in `builds/inventory.json`.

## Setup

1. Put `build/libs/wynngpt-chest-export-1.1.0.jar` in your mods folder together with Fabric API. (It's committed ready to use. After changing the mod, rebuild it with `./gradlew build`, which overwrites that jar, and commit the new one.)
2. Start WynnGPT (`wt serve`).
3. On first launch the mod creates `config/wynngpt-chest-export.json`. Set `builds_path` in that file to your WynnGPT `builds` folder, for example `/path/to/wynn-toolbox/builds`.

If your launcher is a Flatpak (Prism Launcher from Flathub, for example), it can't see that folder until you allow it. Run this, then restart the launcher:

    flatpak override --user --filesystem=~/wynn-toolbox/builds:ro org.prismlauncher.PrismLauncher

The mod locates the app through `builds/.server.json`, which holds the port and token. If that file is missing, or hasn't been updated in the last 20 seconds, the button says to open WynnGPT.

## Capturing samples of new screens

Set `"capture": true` in `config/wynngpt-chest-export.json` to show the button on every container screen. The app keeps each raw export in `builds/.imports/` (the newest 30), which is how screen titles, page arrows and item tooltips are checked before the mod relies on them. Exports of containers the mod doesn't recognise never mark anything as owned (only the player's own inventory in them is read).

## Reading every page at once

In an ender chest, the button turns the pages for you: back to page 1 with the previous arrow, forward to the last page you own, then "Storage Type" switches to the other chest (Account or Character) and it reads that one too, and sends everything as one export. Shift-click exports only the open page; `"walk_pages": false` makes that the default.

It clicks nothing but the arrows (slots 51 and 52) and the switch (47), each only when its name and tooltip say so ("Page 3 >>>>>" with "Click to go"; "Storage Type" with "Click to switch"). On the last page you own, the next slot is still called "Page N >>>>>" but offers to buy the page: it never clicks that, and never "Quick Actions" (46), which would dump your inventory into the bank. It waits for each page to arrive, leaves at least `page_delay_ticks` (default 6; 20 ticks is a second) between clicks, and ignores your clicks while it runs. Closing the chest stops it and sends the pages read so far; only a chest read to its last page has pages past that dropped in the app.

## Development

`./gradlew runClient` starts a dev client, which reads its config from `run/config/`. The server side of the export is `POST /api/inventory/import` in `wynntools/web/server.py`, and the slot parsing is in `wynntools/gameimport.py`.
