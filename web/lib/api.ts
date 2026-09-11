/**
 * Typed API client for the FastAPI backend.
 * All streaming logic is here | components just consume async iterables.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface EquipmentItem {
  name: string;
  /** Full multi-line tooltip text exactly as RealmEye shows it on hover. */
  tooltip: string;
  wiki_url?: string;
  sprite_sheet_url?: string;
  sprite_x?: number;
  sprite_y?: number;
  sprite_size?: number;
  /** Rarity-tiered "slot" frame behind the icon (e.g. Divine = 4 gold diamonds). */
  slot_sprite_sheet_url?: string;
  slot_sprite_x?: number;
  slot_sprite_y?: number;
  slot_sprite_size?: number;
  /** Rarity-colored glow, e.g. "rgb(191, 170, 64)" for Divine. */
  glow_color?: string;
}

export interface CharacterStats {
  hp?: number;
  mp?: number;
  attack?: number;
  defense?: number;
  speed?: number;
  dexterity?: number;
  vitality?: number;
  wisdom?: number;
}

export interface CharacterSummary {
  class_name: string;
  fame?: number;
  place?: number;
  /** Links the class placement (e.g. "#366") to that class's leaderboard. */
  place_url?: string;
  sprite_sheet_url?: string;
  sprite_x?: number;
  sprite_y?: number;
  sprite_width?: number;
  sprite_height?: number;
  /** "8/8" style maxed-stats readout, as shown on RealmEye. */
  stats_maxed?: string;
  /** Base stats from RealmEye's 8/8 hover data. */
  stats?: CharacterStats;
  /** Item bonuses from RealmEye's 8/8 hover data. */
  stat_bonuses?: CharacterStats;
  equipment: EquipmentItem[];
}

/**
 * One row of RealmEye's "Exaltations" tab | bonuses are earned per-class
 * (via the Cyclic Chest dungeon), so this is keyed by class rather than by
 * individual character. Max HP/MP exalt up to +25 each; the other six
 * stats exalt up to +5 each.
 */
export interface ExaltationEntry {
  class_name: string;
  exaltation_count?: number;
  max_hp?: number;
  max_mp?: number;
  attack?: number;
  defense?: number;
  speed?: number;
  dexterity?: number;
  vitality?: number;
  wisdom?: number;
  sprite_sheet_url?: string;
  sprite_x?: number;
  sprite_y?: number;
  sprite_width?: number;
  sprite_height?: number;
}

export interface PlayerProfile {
  username: string;
  guild?: string;
  guild_rank?: string;
  fame?: number;
  account_fame?: number;
  rank?: number;
  total_exaltations?: number;
  characters: CharacterSummary[];
  exaltations?: ExaltationEntry[];
  top_pet?: {
    name: string;
    tier?: string;
    sprite_url?: string;
    sprite_sheet_url?: string;
    sprite_x?: number;
    sprite_y?: number;
    sprite_size?: number;
  };
  last_seen?: string;
  scraped_at: string;
}

export interface ItemProfile {
  name: string;
  type?: string;
  tier?: string;
  description?: string;
  stats: Record<string, string>;
  sprite_url?: string;
  shiny_sprite_url?: string;
  drop_locations: string[];
  wiki_url?: string;
  /** Nickname the user typed; used to match loadout slots after resolve. */
  requestedAs?: string;
}

export interface DyeChip {
  name: string;
  item_id: number;
  sprite_sheet_url?: string;
  sprite_x?: number;
  sprite_y?: number;
  sprite_size?: number;
}

export interface SkinPortrait {
  class_name: string;
  class_id: number;
  skin_name: string;
  skin_id: number;
  clothing?: DyeChip | null;
  accessory?: DyeChip | null;
  portrait_data_uri: string;
  realmeye_url: string;
}

export interface ChatChunk {
  content: string;
  done: boolean;
  error?: string;
}

/** Which bucket a quota was counted against: an account, or a client IP. */
export type QuotaScope = "user" | "ip";

export interface PaywallInfo {
  upgrade: true;
  message: string;
  checkout_url?: string;
  /** "ip" means the caller can sign in for a larger allowance instead of paying. */
  scope?: QuotaScope;
  used?: number;
  limit?: number;
  remaining?: number | null;
}

export interface ChatUsage {
  used: number;
  limit: number;
  remaining: number;
  scope?: QuotaScope;
}

/** Generate a stable session ID persisted in localStorage */
export function getSessionId(): string {
  const key = "realm_pal_session";
  let id = localStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(key, id);
  }
  return id;
}

/** Get stored JWT (paid user token) */
export function getAuthToken(): string | null {
  return localStorage.getItem("realm_pal_token");
}

export function setAuthToken(token: string) {
  localStorage.setItem("realm_pal_token", token);
}

export async function fetchPlayer(username: string): Promise<PlayerProfile> {
  // Redis (server-side, TTL'd) is the source of truth for caching | the
  // browser's own HTTP cache must be bypassed, otherwise looking up the
  // same player twice in one session can silently replay a stale response
  // (missing fields from a since-updated API, or a since-changed profile).
  const res = await fetch(`${API_URL}/players/${encodeURIComponent(username)}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Player '${username}' not found`);
  }
  return res.json();
}

export interface DungeonLayout {
  caption: string;
  url: string;
}

export interface DungeonDrop {
  name: string;
  sprite_url?: string;
  wiki_url?: string;
  wiki_slug?: string;
  drops_from?: string;
}

export interface DungeonGuide {
  title: string;
  url: string;
  portal_url?: string;
  difficulty?: number;
  graves_url?: string;
  layouts: DungeonLayout[];
  drops: DungeonDrop[];
  tips?: string[];
  large_portal?: boolean;
}

export async function fetchDungeon(name: string): Promise<DungeonGuide> {
  const res = await fetch(`${API_URL}/dungeons/${encodeURIComponent(name)}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Dungeon '${name}' not found`);
  }
  return res.json();
}

export async function fetchItem(name: string, className?: string): Promise<ItemProfile> {
  const params = className ? `?class_name=${encodeURIComponent(className)}` : "";
  const res = await fetch(`${API_URL}/items/${encodeURIComponent(name)}${params}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Item '${name}' not found`);
  }
  return res.json();
}

export async function fetchSkinPortrait(spec: {
  className?: string;
  skinName?: string;
  clothing?: string;
  accessory?: string;
}): Promise<SkinPortrait> {
  const params = new URLSearchParams();
  if (spec.className) params.set("class_name", spec.className);
  if (spec.skinName) params.set("skin", spec.skinName);
  if (spec.clothing) params.set("clothing", spec.clothing);
  if (spec.accessory) params.set("accessory", spec.accessory);
  const res = await fetch(`${API_URL}/skins/render?${params.toString()}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Could not render that skin");
  }
  return res.json();
}

/**
 * Stream a chat response. Yields ChatChunk objects.
 * Throws { paywall: PaywallInfo } if the rate limit is hit.
 */
export async function* streamChat(
  message: string,
  history: Array<{ role: string; content: string }>,
  ign?: string,
  signal?: AbortSignal
): AsyncGenerator<ChatChunk> {
  const sessionId = getSessionId();
  const token = getAuthToken();

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}/chat/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message, history, session_id: sessionId, ign }),
    signal,
  });

  if (res.status === 402) {
    const body = await res.json();
    throw Object.assign(new Error("Rate limited"), { paywall: body.detail as PaywallInfo });
  }

  if (!res.ok) {
    throw new Error(`Chat error: ${res.statusText}`);
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const json = line.slice(6);
        try {
          const chunk: ChatChunk = JSON.parse(json);
          yield chunk;
          if (chunk.done) return;
        } catch {
          // malformed chunk | skip
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export type FeedbackRating = "up" | "down";

export async function sendFeedback(payload: {
  rating: FeedbackRating;
  message_id: string;
  response: string;
  prompt?: string;
  what_went_wrong?: string;
  improvement?: string;
}): Promise<void> {
  const sessionId = getSessionId();
  const token = getAuthToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}/chat/feedback`, {
    method: "POST",
    headers,
    body: JSON.stringify({ ...payload, session_id: sessionId }),
  });
  if (!res.ok) throw new Error("Failed to send feedback");
}

export async function fetchChatUsage(): Promise<ChatUsage> {
  const sessionId = getSessionId();
  const res = await fetch(
    `${API_URL}/chat/usage?session_id=${encodeURIComponent(sessionId)}`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error("Failed to load usage");
  return res.json();
}

export async function createCheckout(email: string): Promise<string> {
  const sessionId = getSessionId();
  const res = await fetch(`${API_URL}/payments/checkout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, email }),
  });
  if (!res.ok) throw new Error("Failed to create checkout");
  const data = await res.json();
  return data.checkout_url;
}
