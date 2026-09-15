/**
 * Detects "show me this exact set, shiny/divine" prompts so the UI can
 * render a character-style equipment row instead of the item-card grid.
 */

export type LoadoutRarity = "divine";

export interface LoadoutShowcase {
  shiny: boolean;
  rarity?: LoadoutRarity;
}

const LOADOUT_TOKEN = /\[loadout([^\]]*)\]/i;

export function parseLoadoutToken(content: string): LoadoutShowcase | null {
  const match = content.match(LOADOUT_TOKEN);
  if (!match) return null;
  const flags = match[1].toLowerCase();
  return {
    shiny: /\bshiny\b/.test(flags),
    rarity: /\bdivine\b/.test(flags) ? "divine" : undefined,
  };
}

export const SET_SLOT_COUNT = 4;

const CLASS_NAMES = [
  "Rogue",
  "Archer",
  "Wizard",
  "Priest",
  "Warrior",
  "Knight",
  "Paladin",
  "Assassin",
  "Necromancer",
  "Huntress",
  "Mystic",
  "Trickster",
  "Sorcerer",
  "Ninja",
  "Samurai",
  "Bard",
  "Summoner",
  "Kensei",
  "Druid",
] as const;

export function extractClassFromPrompt(prompt: string): string | undefined {
  const hits = CLASS_NAMES.filter((name) => new RegExp(`\\b${name}\\b`, "i").test(prompt));
  return hits.length === 1 ? hits[0] : undefined;
}

export function inferLoadoutShowcase(
  prompt: string | undefined,
  itemCount = 0,
): LoadoutShowcase | null {
  if (!prompt) return null;
  if (itemCount > SET_SLOT_COUNT) return null;
  const shiny = /\b(?:all\s+)?shiny\b/i.test(prompt);
  const divine = /\b(?:all\s+)?divine\b/i.test(prompt);
  const wantsSet = /\b(?:set|loadout|build me|show me|visualize|equip(?:ped)?)\b/i.test(prompt);
  if ((!wantsSet && !(shiny && divine)) || (!shiny && !divine)) return null;
  return { shiny, rarity: divine ? "divine" : undefined };
}

/** "with Fractal Blades, Cloak of X, and Snake Eye ring" → those four names. */
export function extractNamedSetItems(prompt: string): string[] {
  const match = prompt.match(/\bwith\s+([\s\S]+?)(?:[.!?]|$)/i);
  if (!match) return [];
  const names = match[1]
    .split(/,\s*(?:and\s+)?|\s+and\s+/i)
    .map((part) =>
      part
        .replace(/\b(?:all\s+)?(?:shiny|divine)\b/gi, "")
        .replace(/^(?:and|&)\s+/i, "")
        .trim()
        .replace(/\s+/g, " "),
    )
    .filter((name) => name.length >= 3 && name.length <= 60);
  // A real set names 2+ items. `\bwith\s+...` matches any trailing "with
  // <phrase>" in the message, not just an item list - so an ordinary
  // question that happens to use "with" (e.g. "Is it insane with the
  // awakened enchantment?") returned a one-item "set" here. That bogus
  // single name then got speculatively fetched as a real item lookup by
  // the caller, guaranteeing a 404. Mirrors the same fix applied to the
  // backend's extract_set_item_names (api/services/item_aliases.py) -
  // found live Sep 14 for the identical message on both sides.
  if (names.length < 2) return [];
  return names.slice(0, SET_SLOT_COUNT);
}

export function resolveLoadoutShowcase(
  prompt: string | undefined,
  content: string,
  itemCount: number,
): LoadoutShowcase | null {
  return parseLoadoutToken(content) ?? inferLoadoutShowcase(prompt, itemCount);
}

export function stripLoadoutToken(content: string): string {
  return content.replace(LOADOUT_TOKEN, "").replace(/\n{3,}/g, "\n\n").trim();
}
