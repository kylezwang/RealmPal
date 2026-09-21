/**
 * Detects "show me this exact set, shiny/divine" prompts so the UI can
 * render a character-style equipment row instead of the item-card grid.
 */

export type LoadoutRarity = "uncommon" | "rare" | "legendary" | "divine";

export const LOADOUT_RARITIES: LoadoutRarity[] = [
  "divine",
  "legendary",
  "rare",
  "uncommon",
];

/** Short chat names for the same slots.png diamond frames. Highest first. */
export const RARITY_ALIASES: Record<LoadoutRarity, readonly string[]> = {
  divine: ["divine", "div"],
  legendary: ["legendary", "legend", "legen", "leg"],
  rare: ["rare"],
  uncommon: ["uncommon", "uncomm", "unco", "unc"],
};

export const RARITY_LABEL: Record<LoadoutRarity, string> = {
  uncommon: "Uncommon",
  rare: "Rare",
  legendary: "Legendary",
  divine: "Divine",
};

export interface LoadoutShowcase {
  shiny: boolean;
  rarity?: LoadoutRarity;
}

const LOADOUT_TOKEN = /\[loadout([^\]]*)\]/i;

export function parseRarity(text: string): LoadoutRarity | undefined {
  const lower = (text || "").toLowerCase();
  return LOADOUT_RARITIES.find((tier) =>
    RARITY_ALIASES[tier].some((name) => new RegExp(`\\b${name}\\b`).test(lower)),
  );
}

export function parseShiny(text: string): boolean {
  return /\b(?:all\s+)?shiny\b/i.test(text || "");
}

export function isMakeThisVisual(prompt: string): boolean {
  return /\bmake\s+(?:it|them|this|that)\b/i.test(prompt);
}

/** Keep shiny from the last framed sprite when a follow-up only names a tier. */
export function mergeLoadoutShowcase(
  prompt: string,
  previous?: LoadoutShowcase | null,
): LoadoutShowcase | null {
  const shiny = parseShiny(prompt) || Boolean(previous?.shiny);
  const rarity = parseRarity(prompt) ?? previous?.rarity;
  if (!shiny && !rarity) return null;
  return { shiny, rarity };
}

export function formatLoadoutToken(showcase: LoadoutShowcase): string {
  const flags = [showcase.shiny ? "shiny" : "", showcase.rarity ?? ""].filter(Boolean).join(" ");
  return flags ? `[loadout ${flags}]` : "[loadout]";
}

export function loadoutCaption(showcase: LoadoutShowcase): string {
  const bits = [
    showcase.shiny ? "Shiny" : "",
    showcase.rarity ? RARITY_LABEL[showcase.rarity] : "",
  ].filter(Boolean);
  if (!bits.length) return "Here is your sprite.";
  return `Here it is as ${bits.join(" ")}.`;
}

export function inferUploadedSpriteShowcase(
  prompt: string,
  options: { freshUpload: boolean; previous?: LoadoutShowcase | null },
): LoadoutShowcase | null {
  if (options.freshUpload) return inferLoadoutShowcase(prompt);
  if (!isMakeThisVisual(prompt) || !options.previous) return null;
  return mergeLoadoutShowcase(prompt, options.previous);
}

export function parseLoadoutToken(content: string): LoadoutShowcase | null {
  const match = content.match(LOADOUT_TOKEN);
  if (!match) return null;
  const flags = match[1].toLowerCase();
  return {
    shiny: /\bshiny\b/.test(flags),
    rarity: parseRarity(flags),
  };
}

export const SET_SLOT_COUNT = 4;

export const CLASS_NAMES = [
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
  const shiny = parseShiny(prompt);
  const rarity = parseRarity(prompt);
  const wantsVisual =
    /\b(?:set|loadout|build me|show me|visualize|equip(?:ped)?|make\s+(?:it|them|this|that)|looks?\s+like)\b/i.test(
      prompt,
    );
  if (!shiny && !rarity) return null;
  if (!wantsVisual && !(shiny && rarity)) return null;
  return { shiny, rarity };
}

/** "with Fractal Blades, Cloak of X, and Snake Eye ring" → those four names. */
export function extractNamedSetItems(prompt: string): string[] {
  const match = prompt.match(/\bwith\s+([\s\S]+?)(?:[.!?]|$)/i);
  if (!match) return [];
  const names = match[1]
    .split(/,\s*(?:and\s+)?|\s+and\s+/i)
    .map((part) =>
      part
        .replace(/\b(?:all\s+)?(?:shiny|divine|legendary|rare|uncommon)\b/gi, "")
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
