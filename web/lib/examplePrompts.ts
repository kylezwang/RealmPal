import { DEMO_PLAYER_IGN, IGN_MAX_LENGTH, playerLookupMessage, sanitizeIgn } from "./playerLookup";

export type ExamplePromptLayout = "inline" | "stacked";

export interface ExamplePromptField {
  initial: string;
  placeholder: string;
  maxLength: number;
  sanitize: (raw: string) => string;
}

export interface ExamplePromptConfig extends ExamplePromptField {
  id: string;
  prefix: string;
  /** Text between the first and second inputs, e.g. "look like with". */
  infix?: string;
  suffix?: string;
  layout: ExamplePromptLayout;
  /** 0, 1, 2… — each step delays the delete animation by 0.5s. */
  stagger: number;
  second?: ExamplePromptField;
  toMessage: (raw: string, extra?: string) => string | null;
}

function sanitizeWords(raw: string, maxWords: number, maxLen: number): string {
  const cleaned = (raw ?? "").replace(/[^A-Za-z\s]/g, "").replace(/\s+/g, " ");
  const started = cleaned.trimStart();
  const words = started.split(" ").filter(Boolean).slice(0, maxWords);
  let out = words.join(" ");
  if (cleaned.endsWith(" ") && words.length < maxWords && started.length > 0) {
    out += " ";
  }
  return out.slice(0, maxLen);
}

function templatedMessage(prefix: string, raw: string, sanitize: (value: string) => string): string | null {
  const value = sanitize(raw).trim();
  if (!value) return null;
  return `${prefix}${value}`;
}

/** One cloth/dye field means the same color on clothing and accessory. */
function expandClothToBothSlots(cloth: string): string {
  const value = cloth.trim();
  if (!value) return value;
  if (/\blarge\b/i.test(value) && /\bsmall\b/i.test(value)) return value;
  const kind = /\bdye\b/i.test(value) ? "dye" : "cloth";
  const color = value
    .replace(/^(?:large|small)\s+/i, "")
    .replace(/\s+(?:cloths?|dyes?)$/i, "")
    .trim();
  if (!color) return value;
  return `Large and small ${color} ${kind}`;
}

function skinLookMessage(skinRaw: string, clothRaw?: string): string | null {
  const skin = sanitizeWords(skinRaw, 6, 40).trim();
  const cloth = expandClothToBothSlots(sanitizeWords(clothRaw ?? "", 6, 40));
  if (!skin || !cloth) return null;
  return `What does ${skin} look like with ${cloth}?`;
}

export const ANIMATED_EXAMPLE_PROMPTS: ExamplePromptConfig[] = [
  {
    id: "player",
    prefix: "Look up player",
    initial: DEMO_PLAYER_IGN,
    placeholder: "IGN",
    layout: "inline",
    stagger: 0,
    maxLength: IGN_MAX_LENGTH,
    sanitize: sanitizeIgn,
    toMessage: playerLookupMessage,
  },
  {
    id: "skin-look",
    prefix: "What does",
    infix: "look like with",
    suffix: "?",
    initial: "Vampire Slayer Archer",
    placeholder: "Skin",
    layout: "stacked",
    stagger: 1,
    maxLength: 40,
    sanitize: (raw) => sanitizeWords(raw, 6, 40),
    second: {
      initial: "Crown cloth",
      placeholder: "Cloth / dye",
      maxLength: 40,
      sanitize: (raw) => sanitizeWords(raw, 6, 40),
    },
    toMessage: skinLookMessage,
  },
  {
    id: "dungeon",
    prefix: "Guide to complete",
    initial: "Hardmode Shatters",
    placeholder: "Dungeon",
    layout: "stacked",
    stagger: 2,
    maxLength: 40,
    sanitize: (raw) => sanitizeWords(raw, 4, 40),
    toMessage: (raw) => templatedMessage("Guide to complete ", raw, (value) => sanitizeWords(value, 4, 40)),
  },
  {
    id: "stat-class",
    prefix: "Best items for a",
    initial: "Vitality Rogue",
    placeholder: "Stat + Class",
    layout: "stacked",
    stagger: 3,
    maxLength: 40,
    sanitize: (raw) => sanitizeWords(raw, 2, 40),
    toMessage: (raw) => templatedMessage("Best items for a ", raw, (value) => sanitizeWords(value, 2, 40)),
  },
];

/** Sidebar: same order as the source array, minus the stat+class builder
 * (the landing grid still shows it — it's just too cramped for the rail). */
export const SIDEBAR_EXAMPLE_PROMPTS: ExamplePromptConfig[] = ANIMATED_EXAMPLE_PROMPTS.filter(
  (config) => config.id !== "stat-class",
);

/** Landing grid only: swap the two right-column cards. Sidebar keeps source order. */
const LANDING_ORDER = ["player", "stat-class", "dungeon", "skin-look"] as const;

export const LANDING_EXAMPLE_PROMPTS: ExamplePromptConfig[] = LANDING_ORDER.map((id, stagger) => {
  const config = ANIMATED_EXAMPLE_PROMPTS.find((prompt) => prompt.id === id);
  if (!config) throw new Error(`Missing example prompt: ${id}`);
  return { ...config, stagger };
});
