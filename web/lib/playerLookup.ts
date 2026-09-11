/**
 * Best-effort detection of "this chat message is about a specific player"
 * so the UI can fetch that player's profile and attach a rich
 * character/equipment card to the resulting assistant message.
 *
 * This is intentionally simple (regex, not NLP) | it only needs to catch
 * the common phrasings we actually expect ("Look up player X",
 * "/player X", "What characters does X have", etc.), not every possible
 * way of asking about a player. A miss just means the response comes back
 * as plain text with no card, which is the same experience as before this
 * feature existed.
 */
export const PLAYER_LOOKUP_RE = /(?:\/player|look\s*up\s*player|player)\s+([A-Za-z0-9_]{1,20})\b/i;

/** RotMG IGNs are 1–20 letters, digits, or underscore. Nothing else. */
export const IGN_MAX_LENGTH = 20;
const IGN_SAFE = /[^A-Za-z0-9_]/g;

export const PLAYER_LOOKUP_PREFIX = "Look up player ";
export const DEMO_PLAYER_IGN = "Turbine";
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

/** Follow-up phrasings like "How many exaltations does Turbine have?" */
const EXALT_PLAYER_RE =
  /\bexalt(?:ation)?s?\s+(?:does|do|did)\s+([A-Za-z0-9_]{1,20})\b/i;

/** "Turbine's exaltations" / "show Turbine exaltations" */
const POSSESSIVE_EXALT_RE =
  /\b([A-Za-z0-9_]{1,20})(?:'?s)?\s+exalt(?:ation)?s?\b/i;

/** "... for Turbine" / "... of Turbine" when the message is about exaltations */
const EXALT_FOR_PLAYER_RE =
  /\bexalt(?:ation)?s?\b[\s\S]{0,40}\b(?:for|of)\s+([A-Za-z0-9_]{1,20})\b/i;

export function extractPlayerLookup(message: string): string | null {
  const direct = message.match(PLAYER_LOOKUP_RE);
  if (direct) return direct[1];

  if (!/exalt/i.test(message)) return null;

  for (const re of [EXALT_PLAYER_RE, POSSESSIVE_EXALT_RE, EXALT_FOR_PLAYER_RE]) {
    const match = message.match(re);
    if (match) return match[1];
  }

  return null;
}

/**
 * The large per-class table is opt-in. A count question such as "How many
 * exaltations does Turbine have?" should only get the summary number; show
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
