package com.hankryhays.wynngptchestexport;

import com.hankryhays.wynngptchestexport.mixin.AbstractContainerScreenAccessor;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents;
import net.fabricmc.fabric.api.client.screen.v1.ScreenKeyboardEvents;
import net.fabricmc.fabric.api.client.screen.v1.ScreenMouseEvents;
import net.fabricmc.fabric.api.client.screen.v1.Screens;
import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.client.gui.components.AbstractWidget;
import net.minecraft.client.gui.narration.NarrationElementOutput;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.client.renderer.RenderPipelines;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import org.lwjgl.glfw.GLFW;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class WynnGPTChestExportClient implements ClientModInitializer {
	public static final String MOD_ID = "wynngpt-chest-export";
	public static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

	private static final Identifier ICON = Identifier.fromNamespaceAndPath(MOD_ID, "export_button");
	private static final Identifier SORT_ICON = Identifier.fromNamespaceAndPath(MOD_ID, "sort_button");
	private static final int SIZE = 16;
	private static final int GAP = 4;
	private static final int DROP = 31;          // below the top edge, clear of the button Wynncraft puts there
	private static final int SHIFT = 24;         // right of the window, clear of Wynncraft's chest texture
	private static final int NO_TINT = 0xFFFFFFFF;
	private static final int HOVER_TINT = 0xFFB0B0B0;
	private static final int PRESSED_TINT = 0xFF787878;

	@Override
	public void onInitializeClient() {
		ExportConfig.buildsPath();
		PageWalker.register();
		AspectWalker.register();
		SortRunner.register();
		StorageScreens.register();
		ScreenEvents.AFTER_INIT.register((client, screen, width, height) -> {
			StorageScreens.Kind kind = StorageScreens.kind(screen);
			// Only the player's own storages: never loot chests, trades or shops (unless capturing samples).
			if (!(screen instanceof AbstractContainerScreen<?> container) || kind == null
				|| (kind == StorageScreens.Kind.UNKNOWN && !ExportConfig.capture())) {
				return;
			}
			AbstractContainerScreenAccessor pos = (AbstractContainerScreenAccessor) container;
			boolean[] pressed = {false};
			boolean sorts = kind == StorageScreens.Kind.ACCOUNT || kind == StorageScreens.Kind.CHARACTER;
			// Drawn with the screen's own widgets, so item tooltips cover the buttons.
			Screens.getButtons(screen).add(new Painter((graphics, mouseX, mouseY) -> {
				int x = buttonX(pos), y = exportY(pos);
				boolean hovered = inside(mouseX, mouseY, x, y);
				pressed[0] &= client.mouseHandler.isLeftPressed();
				int tint = pressed[0] && hovered ? PRESSED_TINT : hovered ? HOVER_TINT : NO_TINT;
				graphics.blitSprite(RenderPipelines.GUI_TEXTURED, ICON, x, y, SIZE, SIZE, tint);
				if (hovered) {
					graphics.setTooltipForNextFrame(client.font, Component.literal(walks(kind)
						? "Export every page to WynnGPT (shift-click: this page only)" : "Export to WynnGPT"), mouseX, mouseY);
				}
				if (sorts) {
					int sy = sortY(pos);
					boolean over = inside(mouseX, mouseY, x, sy);
					int sortTint = SortRunner.confirming() ? (over ? NO_TINT : HOVER_TINT) : over ? HOVER_TINT : NO_TINT;
					graphics.blitSprite(RenderPipelines.GUI_TEXTURED, SORT_ICON, x, sy, SIZE, SIZE, sortTint);
					if (over) {
						graphics.setTooltipForNextFrame(client.font, Component.literal(SortRunner.confirming()
							? "Start sorting this chest" : "Sort this chest the way WynnGPT plans it"), mouseX, mouseY);
					}
				}
			}));
			ScreenKeyboardEvents.allowKeyPress(screen).register((s, key) ->
				!SortRunner.running() || key.key() == GLFW.GLFW_KEY_ESCAPE);      // Esc stops a sort
			ScreenMouseEvents.allowMouseClick(screen).register((s, event) -> {
				if (PageWalker.running() || AspectWalker.running() || SortRunner.running()) {
					return false;                  // hands off while it turns the pages or sorts
				}
				if (sorts && event.button() == 0 && inside(event.x(), event.y(), buttonX(pos), sortY(pos))) {
					SortRunner.press(container, kind);
					return false;
				}
				SortRunner.cancel();               // anything else drops a sort waiting to start
				if (event.button() == 0 && inside(event.x(), event.y(), buttonX(pos), exportY(pos))) {
					pressed[0] = true;
					if (walks(kind) && !event.hasShiftDown()) {
						if (kind == StorageScreens.Kind.ASPECTS) {
							AspectWalker.start(container);
						} else {
							PageWalker.start(container, kind);
						}
					} else {
						InventoryExporter.export(container, kind);
					}
					return false;
				}
				return true;
			});
		});
	}

	private static boolean walks(StorageScreens.Kind kind) {
		return (kind == StorageScreens.Kind.ACCOUNT || kind == StorageScreens.Kind.CHARACTER || kind == StorageScreens.Kind.ASPECTS)
			&& ExportConfig.walkPages();
	}

	// Read every frame: the recipe book shifts leftPos without re-initialising the screen.
	private static int buttonX(AbstractContainerScreenAccessor pos) {
		return pos.wynngpt$leftPos() + pos.wynngpt$imageWidth() + GAP + SHIFT;
	}

	private static int exportY(AbstractContainerScreenAccessor pos) {
		return pos.wynngpt$topPos() + DROP;
	}

	private static int sortY(AbstractContainerScreenAccessor pos) {
		return exportY(pos) + SIZE + GAP;
	}

	private static boolean inside(double mx, double my, int x, int y) {
		return mx >= x && mx < x + SIZE && my >= y && my < y + SIZE;
	}

	private interface Draw {
		void draw(GuiGraphics graphics, int mouseX, int mouseY);
	}

	/**
	 * Draws the buttons in the screen's widget pass, before the tooltips (Fabric's afterRender
	 * runs after them, so the buttons covered item tooltips). It takes no focus or clicks:
	 * allowMouseClick handles those.
	 */
	private static final class Painter extends AbstractWidget {
		private final Draw draw;

		Painter(Draw draw) {
			super(0, 0, 0, 0, Component.empty());
			this.draw = draw;
			this.active = false;
		}

		@Override
		protected void renderWidget(GuiGraphics graphics, int mouseX, int mouseY, float delta) {
			draw.draw(graphics, mouseX, mouseY);
		}

		@Override
		protected void updateWidgetNarration(NarrationElementOutput output) {
		}
	}
}
