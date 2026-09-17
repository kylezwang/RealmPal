/**
 * Client-side chat history persistence (localStorage), mirrored to the
 * account server-side for signed-in users (api/services/chat_sessions.py).
 *
 * Until Sep 14, 2026 this was localStorage-only. An incognito window's
 * localStorage is wiped as soon as the last incognito window closes, so
 * "sign in, start a few chats, close incognito, sign back in" looked like
 * chat history vanishing even though the account itself was untouched -
 * found live that day. Anonymous/guest sessions still stay local-only
 * (there's no email to key a server row on); localStorage also remains the
 * fast path for first paint even when signed in.
 */

import {
  API_URL,
  decodeAuthEmail,
  getAuthToken,
  type DungeonGuide,
  type ItemProfile,
  type PlayerProfile,
} from "./api";

export type StoredFeedback = "up" | "down";

export interface StoredMessage {
  role: "user" | "assistant";
  content: string;
  id?: string;
  feedback?: StoredFeedback;
  playerProfile?: PlayerProfile;
  showExaltationTable?: boolean;
  items?: ItemProfile[];
  dungeonGuide?: DungeonGuide;
  images?: Array<{ name: string; thumb: string; src?: string }>;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: StoredMessage[];
  updatedAt: number;
}

const SESSIONS_KEY = "realm_pal_sessions";

function normalizeEmail(email?: string | null): string | null {
  const trimmed = (email ?? "").trim().toLowerCase();
  return trimmed || null;
}

export function currentHistoryEmail(): string | null {
  return normalizeEmail(decodeAuthEmail());
}

export function sessionsKey(email?: string | null): string {
  const owner = normalizeEmail(email) ?? currentHistoryEmail();
  return owner ? `${SESSIONS_KEY}:${owner}` : SESSIONS_KEY;
}

function readKey(key: string): ChatSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as ChatSession[]) : [];
  } catch {
    return [];
  }
}

export function loadSessions(email?: string | null): ChatSession[] {
  const owner = normalizeEmail(email) ?? currentHistoryEmail();
  const scoped = readKey(sessionsKey(owner));
  if (scoped.length > 0 || !owner) return scoped;
  // First sign-in: keep chats that were saved before we keyed by email.
  const legacy = readKey(SESSIONS_KEY);
  if (legacy.length > 0) {
    saveSessions(legacy, owner);
    return legacy;
  }
  return [];
}

export function saveSessions(sessions: ChatSession[], email?: string | null) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(sessionsKey(email), JSON.stringify(sessions));
  } catch {
    // storage disabled/full | history just won't persist, not fatal
  }
}

/** Derive a short auto-title from the first user message. */
export function deriveTitle(messages: StoredMessage[]): string {
  const first = messages.find((m) => m.role === "user");
  if (!first) return "New chat";
  const text = first.content.trim();
  if (text) return text.length > 40 ? `${text.slice(0, 40)}...` : text;
  if (first.images?.length === 1) return first.images[0].name || "Screenshot";
  if (first.images && first.images.length > 1) return `${first.images.length} screenshots`;
  return "New chat";
}

// --- Server-side sync (signed-in accounts only) -----------------------------

function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Best-effort - never blocks the UI and never throws. A dropped sync
 * request just means the account mirror is briefly behind localStorage;
 * the next save (or the next sign-in's merge) catches it back up. */
function fireAndForget(promise: Promise<unknown>) {
  promise.catch(() => {});
}

/** Push one session to the account mirror. Call after a session's messages
 * settle (stream done), same as when saveSessions() is called locally. */
export function pushSessionToServer(session: ChatSession, email?: string | null) {
  if (typeof window === "undefined") return;
  const owner = normalizeEmail(email) ?? currentHistoryEmail();
  if (!owner) return; // anonymous/guest - local-only, no account to mirror to
  fireAndForget(
    fetch(`${API_URL}/chat/sessions/${encodeURIComponent(session.id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        id: session.id,
        title: session.title,
        messages: session.messages,
        updatedAt: session.updatedAt,
      }),
    }),
  );
}

export function removeSessionFromServer(sessionId: string, email?: string | null) {
  if (typeof window === "undefined") return;
  const owner = normalizeEmail(email) ?? currentHistoryEmail();
  if (!owner) return;
  fireAndForget(
    fetch(`${API_URL}/chat/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
      headers: authHeaders(),
    }),
  );
}

function mergeById(local: ChatSession[], server: ChatSession[]): ChatSession[] {
  const byId = new Map<string, ChatSession>();
  for (const session of local) byId.set(session.id, session);
  for (const session of server) {
    const existing = byId.get(session.id);
    // Newer updatedAt wins - covers both "server has a session this
    // browser never saw" and "another device has a newer edit."
    if (!existing || session.updatedAt > existing.updatedAt) {
      byId.set(session.id, session);
    }
  }
  return Array.from(byId.values()).sort((a, b) => b.updatedAt - a.updatedAt);
}

/**
 * Called once right after sign-in resolves. Pushes whatever this browser
 * only has locally (e.g. chats from before this account ever synced, or
 * from a session the server never saw), then merges in anything the
 * server has that this browser doesn't (e.g. chats from a different
 * device, or from an incognito session that has since been wiped).
 * Saves the merged result back to localStorage and returns it.
 */
export async function syncSessionsFromServer(email?: string | null): Promise<ChatSession[]> {
  const owner = normalizeEmail(email) ?? currentHistoryEmail();
  if (!owner) return loadSessions(owner);
  const local = loadSessions(owner);
  try {
    const res = await fetch(`${API_URL}/chat/sessions/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ sessions: local }),
    });
    if (!res.ok) return local;
    const data = (await res.json()) as { sessions: ChatSession[] };
    const merged = mergeById(local, data.sessions ?? []);
    saveSessions(merged, owner);
    return merged;
  } catch {
    // Offline, or the backend is briefly unreachable - local history still
    // works, it just won't reflect other devices until the next sync.
    return local;
  }
}
