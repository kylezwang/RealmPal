import { DEMO_PLAYER_IGN, IGN_MAX_LENGTH, playerLookupMessage, sanitizeIgn } from "./playerLookup";

export type ExamplePromptLayout = "inline" | "stacked";

export interface ExamplePromptConfig {
  id: string;
  prefix: string;
  initial: string;
  placeholder: string;
  layout: ExamplePromptLayout;
  /** 0, 1, 2… — each step delays the delete animation by 0.5s. */
  stagger: number;
  maxLength: number;
  sanitize: (raw: string) => string;
  toMessage: (raw: string) => string | null;
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
    id: "attack-class",
    prefix: "Best attack build for",
    initial: "Bard",
    placeholder: "Class",
    layout: "inline",
    stagger: 1,
    maxLength: 20,
    sanitize: (raw) => sanitizeWords(raw, 1, 20),
    toMessage: (raw) => templatedMessage("Best attack build for ", raw, (value) => sanitizeWords(value, 1, 20)),
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
const LANDING_ORDER = ["player", "stat-class", "dungeon", "attack-class"] as const;

export const LANDING_EXAMPLE_PROMPTS: ExamplePromptConfig[] = LANDING_ORDER.map((id, stagger) => {
  const config = ANIMATED_EXAMPLE_PROMPTS.find((prompt) => prompt.id === id);
  if (!config) throw new Error(`Missing example prompt: ${id}`);
  return { ...config, stagger };
});
