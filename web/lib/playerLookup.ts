import { CLASS_NAMES } from "./loadoutShowcase";

/**
 * Best-effort detection of "this chat message is about a specific player"
 * so the UI can fetch that player's profile and attach a rich
 * character/equipment card to the resulting assistant message.
 *
 * This is intentionally simple (regex, not NLP) | it only needs to catch
 * the common phrasings we actually expect ("Look up player X",
 * "/player X", "What characters does X have", "What's the DPS for
 * IGN's bard"), not every possible way of asking about a player. A
 * miss just means the response comes back as plain text with no card,
 * which is the same experience as before this feature existed.
 *
 * Possessive IGN + class must match the backend extract_player_ign so a
 * DPS ask attaches the same Characters card a lookup already uses
 * (sprites, 8/8 hover, item tooltips including on-character enchants).
 */

export const PLAYER_LOOKUP_RE = /(?:\/player|look\s*up\s*player|player)\s+([A-Za-z0-9_]{1,20})\b/i;

/** RotMG IGNs are 1–20 letters, digits, or underscore. Nothing else. */
export const IGN_MAX_LENGTH = 20;
const IGN_SAFE = /[^A-Za-z0-9_]/g;

export const PLAYER_LOOKUP_PREFIX = "Look up player ";
export const DEMO_PLAYER_IGN = "IGN";
export const PLAYER_LOOKUP_EXAMPLE = `${PLAYER_LOOKUP_PREFIX}${DEMO_PLAYER_IGN}`;

/** Strip everything that is not a legal IGN character and cap the length. */
export function sanitizeIgn(raw: string): string {
  return (raw ?? "").replace(IGN_SAFE, "").slice(0, IGN_MAX_LENGTH);
}

/**
 * Build the only player-lookup message this UI is allowed to send.
 * The IGN is sanitized first so pasted instructions, newlines, or markup
 * cannot ride along into the chat request.
 */
export function playerLookupMessage(raw: string): string | null {
  const ign = sanitizeIgn(raw);
  if (!ign) return null;
  return `${PLAYER_LOOKUP_PREFIX}${ign}`;
}

/** Follow-up phrasings like "How many exaltations does IGN have?" */
const EXALT_PLAYER_RE =
  /\bexalt(?:ation)?s?\s+(?:does|do|did)\s+([A-Za-z0-9_]{1,20})\b/i;

/** "IGN's exaltations" / "show IGN exaltations" */
const POSSESSIVE_EXALT_RE =
  /\b([A-Za-z0-9_]{1,20})(?:'?s)?\s+exalt(?:ation)?s?\b/i;

/** "... for IGN" / "... of IGN" when the message is about exaltations */
const EXALT_FOR_PLAYER_RE =
  /\bexalt(?:ation)?s?\b[\s\S]{0,40}\b(?:for|of)\s+([A-Za-z0-9_]{1,20})\b/i;

const CLASS_TOKENS = new Set([
  ...CLASS_NAMES.map((name) => name.toLowerCase()),
  "rog",
  "arch",
  "wiz",
  "pally",
  "sin",
  "necro",
  "hunt",
  "myst",
  "trix",
  "sorc",
  "sam",
  "lute",
  "summ",
  "ken",
]);

const IGN_STOP = new Set([
  "a",
  "an",
  "and",
  "best",
  "build",
  "class",
  "damage",
  "dps",
  "for",
  "from",
  "gear",
  "her",
  "highest",
  "his",
  "how",
  "it",
  "item",
  "its",
  "let",
  "look",
  "max",
  "maximum",
  "much",
  "my",
  "of",
  "or",
  "our",
  "player",
  "potential",
  "set",
  "that",
  "the",
  "their",
  "this",
  "what",
  "with",
  "your",
]);

function isPlausibleIgn(name: string | undefined): name is string {
  const token = (name ?? "").trim();
  if (!token) return false;
  const lower = token.toLowerCase();
  if (IGN_STOP.has(lower) || CLASS_TOKENS.has(lower)) return false;
  return /^[A-Za-z][A-Za-z0-9_]{0,19}$/.test(token);
}

const POSSESSIVE_IGN_RE = /\b([A-Za-z][A-Za-z0-9_]{0,19})'s\b/gi;

export function extractPlayerLookup(message: string): string | null {
  const direct = message.match(PLAYER_LOOKUP_RE);
  if (direct && isPlausibleIgn(direct[1])) return direct[1];

  if (/exalt/i.test(message)) {
    for (const re of [EXALT_PLAYER_RE, POSSESSIVE_EXALT_RE, EXALT_FOR_PLAYER_RE]) {
      const match = message.match(re);
      if (match && isPlausibleIgn(match[1])) return match[1];
    }
  }

  let best: { score: number; name: string } | null = null;
  POSSESSIVE_IGN_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = POSSESSIVE_IGN_RE.exec(message))) {
    const name = match[1];
    if (!isPlausibleIgn(name)) continue;
    const rest = message.slice(match.index + match[0].length, match.index + match[0].length + 32).toLowerCase();
    const followedByClass = [...CLASS_TOKENS].some((token) =>
      new RegExp(`^\\s+${token}\\b`).test(rest),
    );
    const score = followedByClass ? 1 : 0;
    if (!best || score > best.score) best = { score, name };
  }
  if (best) return best.name;

  return null;
}

/** Reuse the last attached card on exalt / DPS / gear follow-ups that omit the IGN. */
export function shouldReusePlayerCard(message: string): boolean {
  if (/exalt/i.test(message)) return true;
  return (
    /\b(dps|dummy|breakdown|reconstruct|enchants?)\b/i.test(message) ||
    /\b(numbers?|math|how did you get|walk me through|prove it|what if|swapped?)\b/i.test(message) ||
    /\b(fame|guild|characters?|pets?|last seen|equipment|gear)\b/i.test(message)
  );
}

/** Full account card (Fame, every class). DPS asks use a single character row. */
export function isAccountPlayerLookup(message: string): boolean {
  if (PLAYER_LOOKUP_RE.test(message)) return true;
  if (/exalt/i.test(message)) return true;
  return (
    /\b(characters?|pets?|fame|guild|last seen)\b/i.test(message) &&
    !/\b(dps|dummy|breakdown|reconstruct)\b/i.test(message)
  );
}

/**
 * The large per-class table is opt-in. A count question such as "How many
 * exaltations does IGN have?" should only get the summary number; show
 * the table when the user explicitly asks to see/list the account's
 * exaltations or requests a full/detailed breakdown.
 */
export function wantsExaltationTable(message: string): boolean {
  if (!/\bexalt(?:ation)?s?\b/i.test(message)) return false;

  return (
    /\b(show|display|view|list|see)\b/i.test(message) ||
    /\b(full|complete|detailed?)\s+(?:account\s+)?exalt(?:ation)?s?\b/i.test(message) ||
    /\bexalt(?:ation)?s?\s+(table|breakdown|details?)\b/i.test(message)
  );
}
