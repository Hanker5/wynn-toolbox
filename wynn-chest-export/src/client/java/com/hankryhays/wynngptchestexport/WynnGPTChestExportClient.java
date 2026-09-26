package com.hankryhays.wynngptchestexport;

import com.hankryhays.wynngptchestexport.mixin.AbstractContainerScreenAccessor;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents;
import net.fabricmc.fabric.api.client.screen.v1.ScreenMouseEvents;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.client.renderer.RenderPipelines;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class WynnGPTChestExportClient implements ClientModInitializer {
	public static final String MOD_ID = "wynngpt-chest-export";
	public static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

	private static final Identifier ICON = Identifier.fromNamespaceAndPath(MOD_ID, "export_button");
	private static final int SIZE = 16;
	private static final int GAP = 4;
	private static final int NO_TINT = 0xFFFFFFFF;
	private static final int HOVER_TINT = 0xFFB0B0B0;
	private static final int PRESSED_TINT = 0xFF787878;

	@Override
	public void onInitializeClient() {
		ExportConfig.buildsPath();
		ScreenEvents.AFTER_INIT.register((client, screen, width, height) -> {
			if (!(screen instanceof AbstractContainerScreen<?> container)) {
				return;
			}
			AbstractContainerScreenAccessor pos = (AbstractContainerScreenAccessor) container;
			boolean[] pressed = {false};
			ScreenEvents.afterRender(screen).register((s, graphics, mouseX, mouseY, tickDelta) -> {
				int x = buttonX(pos), y = pos.wynngpt$topPos();
				boolean hovered = inside(mouseX, mouseY, x, y);
				pressed[0] &= client.mouseHandler.isLeftPressed();
				int tint = pressed[0] && hovered ? PRESSED_TINT : hovered ? HOVER_TINT : NO_TINT;
				graphics.blitSprite(RenderPipelines.GUI_TEXTURED, ICON, x, y, SIZE, SIZE, tint);
				if (hovered) {
					graphics.setTooltipForNextFrame(client.font, Component.literal("Export to WynnGPT"), mouseX, mouseY);
				}
			});
			ScreenMouseEvents.allowMouseClick(screen).register((s, event) -> {
				if (event.button() == 0 && inside(event.x(), event.y(), buttonX(pos), pos.wynngpt$topPos())) {
					pressed[0] = true;
					InventoryExporter.export(container);
					return false;
				}
				return true;
			});
		});
	}

	// Read every frame: the recipe book shifts leftPos without re-initialising the screen.
	private static int buttonX(AbstractContainerScreenAccessor pos) {
		return pos.wynngpt$leftPos() + pos.wynngpt$imageWidth() + GAP;
	}

	private static boolean inside(double mx, double my, int x, int y) {
		return mx >= x && mx < x + SIZE && my >= y && my < y + SIZE;
	}
}
