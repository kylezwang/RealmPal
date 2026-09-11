/**
 * Client-side chat history persistence (localStorage). There's no backend
 * chat-storage model yet, so conversations live entirely in the browser.
 */

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

export function loadSessions(): ChatSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    return raw ? (JSON.parse(raw) as ChatSession[]) : [];
  } catch {
    return [];
  }
}

export function saveSessions(sessions: ChatSession[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
  } catch {
    // storage disabled/full | history just won't persist, not fatal
  }
}

/** Derive a short auto-title from the first user message. */
export function deriveTitle(messages: StoredMessage[]): string {
  const first = messages.find((m) => m.role === "user")?.content.trim() ?? "New chat";
  return first.length > 40 ? `${first.slice(0, 40)}...` : first;
}
