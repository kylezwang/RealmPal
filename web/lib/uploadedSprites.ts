/**
 * Fan-made / uploaded sprites use the same rarity frames as a wiki loadout.
 * The art is the attachment itself; Unc/Rare/Leg/Div and shiny are overlays.
 */

import type { ItemProfile } from "./api";
import {
  SET_SLOT_COUNT,
  parseLoadoutToken,
  type LoadoutShowcase,
} from "./loadoutShowcase";

export function isUploadedSpriteSrc(src?: string): boolean {
  return Boolean(src && /^(data:|blob:)/i.test(src));
}

export function isUploadedSpriteItem(item: ItemProfile): boolean {
  return isUploadedSpriteSrc(item.sprite_url) || isUploadedSpriteSrc(item.shiny_sprite_url);
}

function spriteName(filename: string): string {
  const base = filename.replace(/\.[a-z0-9]+$/i, "").trim();
  return base || "Sprite";
}

export function uploadedSpriteItems(
  images: Array<{ name: string; thumb: string; src?: string }>,
): ItemProfile[] {
  return images.slice(0, SET_SLOT_COUNT).map((image) => {
    const src = image.src || image.thumb;
    const name = spriteName(image.name);
    return {
      name,
      stats: {},
      drop_locations: [],
      sprite_url: src,
      shiny_sprite_url: src,
      requestedAs: name,
    };
  });
}

export function findRecentUploadedSpriteState(
  messages: Array<{
    role: string;
    content: string;
    items?: ItemProfile[];
  }>,
): { items: ItemProfile[]; showcase: LoadoutShowcase } | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role !== "assistant") continue;
    const showcase = parseLoadoutToken(message.content);
    if (!showcase) continue;
    const items = (message.items || []).filter(isUploadedSpriteItem);
    if (!items.length) return null;
    return { items, showcase };
  }
  return null;
}
