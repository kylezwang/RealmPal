/**
 * Client-side chat history persistence (localStorage). There's no backend
 * chat-storage model yet, so conversations live entirely in the browser.
 */

import {
  decodeAuthEmail,
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
  const first = messages.find((m) => m.role === "user")?.content.trim() ?? "New chat";
  return first.length > 40 ? `${first.slice(0, 40)}...` : first;
}
