/**
 * Client-side chat history persistence (localStorage). There's no backend
 * chat-storage model yet, so conversations live entirely in the browser.
 */

import { decodeAuthEmail } from "./api";

export type StoredFeedback = "up" | "down";

export interface StoredMessage {
  role: "user" | "assistant";
  content: string;
  id?: string;
  feedback?: StoredFeedback;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: StoredMessage[];
  updatedAt: number;
}

const SESSIONS_KEY = "realm_pal_sessions";

function sessionsKey(): string {
  const email = decodeAuthEmail();
  return email ? `${SESSIONS_KEY}:${email.trim().toLowerCase()}` : SESSIONS_KEY;
}

export function loadSessions(): ChatSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(sessionsKey());
    return raw ? (JSON.parse(raw) as ChatSession[]) : [];
  } catch {
    return [];
  }
}

export function saveSessions(sessions: ChatSession[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(sessionsKey(), JSON.stringify(sessions));
  } catch {
    // storage disabled/full | history just won't persist, not fatal
  }
}

/** Derive a short auto-title from the first user message. */
export function deriveTitle(messages: StoredMessage[]): string {
  const first = messages.find((m) => m.role === "user")?.content.trim() ?? "New chat";
  return first.length > 40 ? `${first.slice(0, 40)}...` : first;
}
