/**
 * Typed API client for the FastAPI backend.
 * All streaming logic is here | components just consume async iterables.
 */

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Wrap fetch with a timeout - a slow or unresponsive backend (e.g. a
 * scrape queued behind other work) must not leave the UI waiting forever
 * with no feedback. Throws a clear, retryable error instead of hanging. */
async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
  timeoutMessage = "That's taking longer than expected. Please try again.",
): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(timeoutMessage);
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

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
  /** False when class_name was sent and this class cannot equip the item. */
  wearable?: boolean | null;
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

export type PaywallReason = "free_quota" | "claude_pool" | "spend_cap";

export interface PaywallInfo {
  upgrade: true;
  message: string;
  checkout_url?: string;
  /** "ip" means the caller can sign in for a larger allowance instead of paying. */
  scope?: QuotaScope;
  used?: number;
  limit?: number;
  remaining?: number | null;
  reason?: PaywallReason;
  spend_cap_usd?: number;
  resets_in_seconds?: number;
}

export interface ChatUsage {
  used: number;
  limit: number;
  remaining: number;
  scope?: QuotaScope;
  tier?: "guest" | "free" | "paid";
  claude_used?: number;
  claude_limit?: number;
  claude_remaining?: number;
  spend_cap_usd?: number;
  on_demand_spent_usd?: number;
  resets_in_seconds?: number;
}

export interface OnDemandUsage {
  spend_cap_usd: number;
  allowed_caps_usd: number[];
  claude_used: number;
  claude_limit: number;
  claude_remaining: number;
  on_demand_spent_usd: number;
  overage_usd: number;
}

export interface BillingInfo {
  tier: "free" | "paid";
  subscription_status?: string | null;
  plan_name: string;
  plan_price_usd: number;
  claude_used_percent?: number | null;
  spend_cap_usd?: number | null;
  on_demand_spent_usd?: number | null;
  overage_usd?: number | null;
  allowed_caps_usd?: number[] | null;
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

const AUTH_TOKEN_KEY = "realm_pal_token";

/** Chat and account UI listen for this after a token is stored or cleared. */
export const AUTH_CHANGED_EVENT = "realm-pal-auth-changed";

function notifyAuthChanged() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
}

/** Get stored JWT (paid user token) */
export function getAuthToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_KEY) ?? sessionStorage.getItem(AUTH_TOKEN_KEY);
}

export function setAuthToken(token: string, persist = true) {
  if (persist) {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
    sessionStorage.removeItem(AUTH_TOKEN_KEY);
  } else {
    sessionStorage.setItem(AUTH_TOKEN_KEY, token);
    localStorage.removeItem(AUTH_TOKEN_KEY);
  }
  notifyAuthChanged();
}

export function clearAuthToken() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  sessionStorage.removeItem(AUTH_TOKEN_KEY);
  notifyAuthChanged();
}

const TRAIN_ON_DATA_KEY = "realm_pal_train_on_data";

/** Guest default is on; a stored "0"/"false" is the only opt-out. */
export function getLocalTrainOnData(): boolean {
  if (typeof window === "undefined") return true;
  const raw = localStorage.getItem(TRAIN_ON_DATA_KEY);
  if (raw === null) return true;
  return raw !== "0" && raw !== "false";
}

export function setLocalTrainOnData(value: boolean) {
  localStorage.setItem(TRAIN_ON_DATA_KEY, value ? "1" : "0");
}

function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function fetchPreferences(): Promise<{ train_on_data: boolean }> {
  const token = getAuthToken();
  if (!token) return { train_on_data: getLocalTrainOnData() };
  const res = await fetch(`${API_URL}/auth/preferences`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (!res.ok) return { train_on_data: getLocalTrainOnData() };
  return res.json();
}

export async function savePreferences(
  train_on_data: boolean,
): Promise<{ train_on_data: boolean }> {
  setLocalTrainOnData(train_on_data);
  if (!getAuthToken()) return { train_on_data };
  const res = await fetch(`${API_URL}/auth/preferences`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ train_on_data }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Could not save setting");
  }
  return data as { train_on_data: boolean };
}

export async function uploadChatImage(file: File): Promise<{
  id: string;
  filename: string;
  expires_at: number;
  train_on_data: boolean;
}> {
  const form = new FormData();
  form.append("file", file);
  form.append("session_id", getSessionId());
  form.append("train_on_data", getLocalTrainOnData() ? "true" : "false");
  const res = await fetch(`${API_URL}/uploads`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Could not upload image");
  }
  return data;
}

/**
 * Best-effort read of the `email` claim off the stored JWT, for display
 * only (e.g. showing who's signed in in the account menu). The signature
 * is never checked here | the API independently verifies it on every
 * request that actually uses it, so nothing security-relevant depends on
 * this decode succeeding or being accurate.
 */
export function decodeAuthEmail(): string | null {
  const token = getAuthToken();
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const claims = JSON.parse(json) as { email?: string };
    return typeof claims.email === "string" ? claims.email : null;
  } catch {
    return null;
  }
}

/** Best-effort read of the `ign` claim off the stored JWT, for display only. */
export function decodeAuthIgn(): string | null {
  const token = getAuthToken();
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const claims = JSON.parse(json) as { ign?: string };
    const ign = typeof claims.ign === "string" ? claims.ign.trim() : "";
    return ign || null;
  } catch {
    return null;
  }
}

export interface AuthSession {
  token: string;
  email: string;
  paid: boolean;
  ign?: string | null;
}

const AUTH_TIMEOUT_MS = 20_000;

async function postAuth(
  path: string,
  body: Record<string, string>,
  persist = true,
): Promise<AuthSession> {
  const res = await fetchWithTimeout(
    `${API_URL}${path}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    AUTH_TIMEOUT_MS,
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Could not sign in");
  }
  setAuthToken(data.token, persist);
  return data as AuthSession;
}

export async function signInWithPassword(
  email: string,
  password: string,
  opts?: { persist?: boolean },
): Promise<AuthSession> {
  return postAuth("/auth/signin", { email, password }, opts?.persist !== false);
}

export async function registerAccount(
  email: string,
  password: string,
  opts: { ign: string; confirmPassword: string },
): Promise<AuthSession> {
  return postAuth("/auth/register", {
    email,
    password,
    ign: opts.ign,
    confirm_password: opts.confirmPassword,
  });
}

export async function startOAuth(provider: "google" | "microsoft"): Promise<void> {
  const res = await fetch(`${API_URL}/auth/oauth/${provider}`, { cache: "no-store" });
  const data = await res.json().catch(() => ({}));
  throw new Error(
    typeof data.detail === "string" ? data.detail : "That sign-in option isn't available yet",
  );
}

/** Optional fallback. Always resolves for a well-formed address | the
 * backend never reports whether that email "exists". */
export async function requestSignInLink(email: string): Promise<void> {
  const res = await fetch(`${API_URL}/auth/request-link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Could not send sign-in link");
  }
}

// Scrape-backed, not a pure DB read | a cache miss means a live RealmEye
// fetch, slower than auth calls. Generous, but must still fail visibly
// rather than leave the sidebar's pet selector (or an item/dungeon card)
// waiting forever. Shared by fetchPlayer/fetchDungeon/fetchItem below.
const SCRAPE_LOOKUP_TIMEOUT_MS = 45_000;
const PET_LOOKUP_TIMEOUT_MS = 10_000;
export const PET_NOT_FOUND_MESSAGE = "Sorry, I wasn't able to find a pet. Please try again later.";

/** Sidebar IGN field only | Pet Yard tab, not the full profile scrape. */
export async function fetchPlayerPet(username: string): Promise<PlayerProfile> {
  const res = await fetchWithTimeout(
    `${API_URL}/players/${encodeURIComponent(username)}/pet`,
    { cache: "no-store", headers: authHeaders() },
    PET_LOOKUP_TIMEOUT_MS,
    PET_NOT_FOUND_MESSAGE,
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? PET_NOT_FOUND_MESSAGE);
  }
  return res.json();
}

export async function fetchPlayer(username: string): Promise<PlayerProfile> {
  // Redis (server-side, TTL'd) is the source of truth for caching | the
  // browser's own HTTP cache must be bypassed, otherwise looking up the
  // same player twice in one session can silently replay a stale response
  // (missing fields from a since-updated API, or a since-changed profile).
  const res = await fetchWithTimeout(
    `${API_URL}/players/${encodeURIComponent(username)}`,
    { cache: "no-store", headers: authHeaders() },
    SCRAPE_LOOKUP_TIMEOUT_MS,
  );
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
  const res = await fetchWithTimeout(
    `${API_URL}/dungeons/${encodeURIComponent(name)}`,
    { cache: "no-store", headers: authHeaders() },
    SCRAPE_LOOKUP_TIMEOUT_MS,
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Dungeon '${name}' not found`);
  }
  return res.json();
}

export async function fetchItem(name: string, className?: string): Promise<ItemProfile> {
  const params = className ? `?class_name=${encodeURIComponent(className)}` : "";
  const res = await fetchWithTimeout(
    `${API_URL}/items/${encodeURIComponent(name)}${params}`,
    { cache: "no-store", headers: authHeaders() },
    SCRAPE_LOOKUP_TIMEOUT_MS,
  );
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
    headers: authHeaders(),
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

export interface QuestArtResponse {
  dungeon_name: string;
  dungeon_prompt: string;
  dungeon_portal_url?: string | null;
  shiny_name: string;
  shiny_sprite_url?: string | null;
  item_sprite_url?: string | null;
}

export async function fetchQuestArt(shift = 0): Promise<QuestArtResponse> {
  const params = shift > 0 ? `?shift=${encodeURIComponent(String(shift))}` : "";
  const res = await fetch(`${API_URL}/chat/quests/art${params}`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Could not load quest art");
  }
  return data as QuestArtResponse;
}

export async function claimDailyQuestBonus(): Promise<{ granted: boolean; bonus: number }> {
  const res = await fetch(`${API_URL}/chat/quests/claim`, {
    method: "POST",
    headers: authHeaders(),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Could not claim quest bonus");
  }
  return data as { granted: boolean; bonus: number };
}

export async function fetchChatUsage(): Promise<ChatUsage> {
  const sessionId = getSessionId();
  const res = await fetch(
    `${API_URL}/chat/usage?session_id=${encodeURIComponent(sessionId)}`,
    { cache: "no-store", headers: authHeaders() },
  );
  if (!res.ok) throw new Error("Failed to load usage");
  return res.json();
}

export async function createCheckout(email?: string): Promise<string> {
  const sessionId = getSessionId();
  const res = await fetch(`${API_URL}/payments/checkout`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      session_id: sessionId,
      email: email ?? decodeAuthEmail() ?? "",
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Failed to create checkout");
  }
  return data.checkout_url;
}

export async function fetchOnDemand(): Promise<OnDemandUsage> {
  const res = await fetch(`${API_URL}/payments/on-demand`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Could not load usage");
  }
  return data as OnDemandUsage;
}

export async function fetchBilling(): Promise<BillingInfo> {
  const res = await fetch(`${API_URL}/payments/billing`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Could not load billing");
  }
  return data as BillingInfo;
}

export async function saveOnDemand(spendCapUsd: number): Promise<OnDemandUsage> {
  const res = await fetch(`${API_URL}/payments/on-demand`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ spend_cap_usd: spendCapUsd }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Could not save usage cap");
  }
  return data as OnDemandUsage;
}

/** Stripe Customer Portal link so a paid user can cancel or update payment
 * method themselves. Requires the Portal to be configured once in the
 * Stripe Dashboard (Settings -> Billing -> Customer portal). */
export async function openBillingPortal(): Promise<string> {
  const res = await fetch(`${API_URL}/payments/portal`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Could not open billing portal");
  }
  return data.portal_url;
}

export async function confirmCheckout(sessionId: string): Promise<AuthSession> {
  const res = await fetch(`${API_URL}/payments/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ session_id: sessionId }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Could not confirm upgrade");
  }
  if (typeof data.token === "string") {
    setAuthToken(data.token, Boolean(localStorage.getItem(AUTH_TOKEN_KEY)));
  }
  return data as AuthSession;
}
