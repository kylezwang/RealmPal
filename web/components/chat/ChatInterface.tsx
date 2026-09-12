"use client";
import { useState, useRef, useEffect, useLayoutEffect, useCallback } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { streamChat, fetchPlayer, fetchItem, fetchDungeon, fetchChatUsage, uploadChatImage, confirmCheckout, decodeAuthEmail, AUTH_CHANGED_EVENT, type PlayerProfile, type ItemProfile, type DungeonGuide, type PaywallInfo, type ChatUsage, type FeedbackRating } from "@/lib/api";
import { extractPlayerLookup, wantsExaltationTable } from "@/lib/playerLookup";
import { extractDungeonLookup } from "@/lib/dungeonLookup";
import { LANDING_EXAMPLE_PROMPTS, SIDEBAR_EXAMPLE_PROMPTS } from "@/lib/examplePrompts";
import { ExamplePrompt } from "./ExamplePrompt";
import { extractItemNames, skipDungeonItemCard, ITEM_CARD_ROW_SIZE } from "@/lib/itemLookup";
import { extractNamedSetItems, extractClassFromPrompt, inferLoadoutShowcase, SET_SLOT_COUNT } from "@/lib/loadoutShowcase";
import { inferSkinVisualize } from "@/lib/skinShowcase";
import { MessageBubble } from "./MessageBubble";
import { PetCompanion, PetSprite } from "./PetCompanion";
import { PaywallModal } from "./PaywallModal";
import { ChatOptionsModal } from "./ChatOptionsModal";
import { SidebarAccount } from "./SidebarAccount";
import { AccountMenu } from "./AccountMenu";
import { SWORD_SPRITE, USER_SPRITE } from "@/lib/sprites";
import { type ChatSession, loadSessions, saveSessions, deriveTitle } from "@/lib/chatHistory";

// Minimal shape for the Web Speech API | not in the default TS DOM lib.
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onresult: ((event: any) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  id?: string;
  feedback?: FeedbackRating;
  /** Attached once resolved, when this exchange was about a specific
   * player | lets MessageBubble render a rich character/equipment card. */
  playerProfile?: PlayerProfile;
  /** Whether the user's own message actually asked about exaltations |
   * PlayerCard only renders the full per-class breakdown table when this
   * is true, since it's a lot of extra detail nobody wants by default. */
  showExaltationTable?: boolean;
  /** Wiki infobox cards for items named in the assistant reply. */
  items?: ItemProfile[];
  /** Unique item names spotted in the reply, in order | drives card
   * skeletons until each fetchItem() resolves. */
  pendingItemNames?: string[];
  dungeonGuide?: DungeonGuide;
}


/** Most recent player IGN mentioned in this chat | used for follow-ups like
 * "How many exaltations does Turbine have?" where the name isn't in the
 * standard "/player X" / "look up player X" phrasing. */
function findRecentPlayerName(messages: Message[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.playerProfile?.username) return msg.playerProfile.username;
    const fromText = extractPlayerLookup(msg.content);
    if (fromText) return fromText;
  }
  return null;
}

export function ChatInterface() {
  const router = useRouter();
  const [isSignedIn, setIsSignedIn] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [ign, setIgn] = useState("");
  const [playerProfile, setPlayerProfile] = useState<PlayerProfile | null>(null);
  const [isLoadingPlayer, setIsLoadingPlayer] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [paywall, setPaywall] = useState<PaywallInfo | null>(null);
  const [usage, setUsage] = useState<ChatUsage>({
    used: 0,
    limit: 3,
    remaining: 3,
    scope: "ip",
  });
  const [ignError, setIgnError] = useState<string | null>(null);
  const [attachedFile, setAttachedFile] = useState<File | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [optionsSessionId, setOptionsSessionId] = useState<string | null>(null);

  const lastUserMsgRef = useRef<HTMLDivElement>(null);
  const pinToSentMessageRef = useRef(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SpeechRecognitionCtor = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    setSpeechSupported(!!SpeechRecognitionCtor);
  }, []);

  const refreshUsage = useCallback(async () => {
    try {
      setUsage(await fetchChatUsage());
    } catch {
      // Keep the last known count (or the guest default) so the
      // counter does not vanish when the API is briefly unreachable.
    }
  }, []);

  const applyAuthState = useCallback(() => {
    // Drop in-memory messages first so the persist effect cannot write
    // the previous account's chat into the newly selected storage key.
    setMessages([]);
    setActiveSessionId(null);
    const signedIn = Boolean(decodeAuthEmail());
    setIsSignedIn(signedIn);
    if (!signedIn) {
      setUsage({ used: 0, limit: 3, remaining: 3, scope: "ip" });
    }
    setSessions(loadSessions());
    void refreshUsage();
  }, [refreshUsage]);

  useEffect(() => {
    applyAuthState();
    window.addEventListener(AUTH_CHANGED_EVENT, applyAuthState);
    return () => window.removeEventListener(AUTH_CHANGED_EVENT, applyAuthState);
  }, [applyAuthState]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("upgraded") !== "true") return;
    const checkoutSession = params.get("session_id");
    window.history.replaceState({}, "", window.location.pathname);
    void (async () => {
      if (checkoutSession && decodeAuthEmail()) {
        try {
          await confirmCheckout(checkoutSession);
        } catch {
          // Webhook may already have opened the row; usage refresh still runs.
        }
      }
      await refreshUsage();
    })();
  }, [refreshUsage]);

  // Persist the active conversation whenever a message is added/removed, or
  // once streaming finishes (so the final assistant text gets saved | not
  // every individual streamed token).
  useEffect(() => {
    if (messages.length === 0) return;
    const id = activeSessionId ?? crypto.randomUUID();
    if (!activeSessionId) setActiveSessionId(id);

    setSessions((prev) => {
      const existing = prev.find((s) => s.id === id);
      const updated: ChatSession = {
        id,
        title: existing?.title ?? deriveTitle(messages),
        messages,
        updatedAt: Date.now(),
      };
      const next = [updated, ...prev.filter((s) => s.id !== id)];
      saveSessions(next);
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, isStreaming]);

  // After send, pin the user's just-sent message to the top of the transcript
  // so the reply can grow below without yanking the viewport to the bottom.
  useLayoutEffect(() => {
    if (!pinToSentMessageRef.current) return;
    const el = lastUserMsgRef.current;
    if (!el) return;
    pinToSentMessageRef.current = false;
    el.scrollIntoView({ block: "start", behavior: "instant" });
  }, [messages.length]);

  const resizeComposer = useCallback(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 24), 200)}px`;
  }, []);

  useLayoutEffect(() => {
    resizeComposer();
  }, [input, resizeComposer]);

  // Load player profile when IGN is set
  async function loadPlayer(name: string) {
    setIgnError(null);
    setIsLoadingPlayer(true);
    try {
      const profile = await fetchPlayer(name);
      setPlayerProfile(profile);
    } catch (e) {
      setIgnError(e instanceof Error ? e.message : "Player not found");
      setPlayerProfile(null);
    } finally {
      setIsLoadingPlayer(false);
    }
  }

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || isStreaming) return;

    // Handle /player command | this is a client-side lookup only. It should
    // never reach Claude: sending the literal "/player <ign>" text as a chat
    // message burned one of the user's 3 free messages for a request the AI
    // can't meaningfully answer anyway, since the profile just loads into the
    // sidebar via loadPlayer().
    const playerMatch = trimmed.match(/^\/player\s+(\S+)/i);
    if (playerMatch) {
      const username = playerMatch[1];
      setIgn(username);
      void loadPlayer(username);
      setInput("");
      return;
    }

    const outgoingText = attachedFile ? `${trimmed}\n\n[Attached file: ${attachedFile.name}]` : trimmed;
    const userMsg: Message = { role: "user", content: outgoingText };
    const history = messages.map((m) => ({ role: m.role, content: m.content }));

    pinToSentMessageRef.current = true;
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    removeAttachment();
    setIsStreaming(true);

    // Placeholder for streaming assistant message. Capture its index (set
    // synchronously by the functional updater below) so a later, possibly
    // slower-resolving player profile fetch can find and attach itself to
    // the *same* message even if more messages get added in the meantime.
    let assistantMsgIndex = -1;
    setMessages((prev) => {
      assistantMsgIndex = prev.length;
      return [...prev, { role: "assistant", content: "", id: crypto.randomUUID() }];
    });

    // If this looks like a player lookup ("Look up player Turbine", "/player
    // Turbine", "What characters does Turbine have?"), fetch that player's
    // profile in parallel so we can attach a rich character/equipment card
    // (sprites + hover tooltips) to the response once it resolves. This is
    // independent of the text stream | whichever finishes first, the other
    // just fills in afterward.
    const asksAboutExaltations = /exalt/i.test(trimmed);
    const showExaltationTable = wantsExaltationTable(trimmed);
    // Player name in this message, or fall back to the most recent player
    // looked up in this chat (e.g. "How many exaltations does Turbine have?"
    // after an earlier "Look up player Turbine").
    const lookupName =
      extractPlayerLookup(trimmed) ??
      (asksAboutExaltations ? findRecentPlayerName(messages) : null);
    if (lookupName) {
      fetchPlayer(lookupName)
        .then((profile) => {
          setMessages((prev) => {
            if (assistantMsgIndex < 0 || assistantMsgIndex >= prev.length) return prev;
            const updated = [...prev];
            updated[assistantMsgIndex] = {
              ...updated[assistantMsgIndex],
              playerProfile: profile,
              showExaltationTable,
            };
            return updated;
          });
        })
        .catch(() => {});
    }

    const dungeonName = extractDungeonLookup(trimmed);
    abortRef.current = new AbortController();

    const queuedItems = new Set<string>();
    const fetchWait: string[] = [];
    let fetchInFlight = 0;
    const className = extractClassFromPrompt(trimmed);
    const startItemFetches = () => {
      while (fetchInFlight < ITEM_CARD_ROW_SIZE && fetchWait.length > 0) {
        const name = fetchWait.shift()!;
        const key = name.toLowerCase();
        fetchInFlight += 1;
        fetchItem(name, dungeonName ? undefined : className)
          .then((item) => {
            setMessages((prev) => {
              if (assistantMsgIndex < 0 || assistantMsgIndex >= prev.length) return prev;
              const updated = [...prev];
              const current = updated[assistantMsgIndex];
              const existing = current.items ?? [];
              if (
                existing.some(
                  (row) =>
                    row.name.toLowerCase() === key ||
                    row.name.toLowerCase() === item.name.toLowerCase() ||
                    (row.requestedAs ?? "").toLowerCase() === key,
                )
              ) {
                return prev;
              }
              updated[assistantMsgIndex] = {
                ...current,
                items: [...existing, { ...item, requestedAs: name }],
              };
              return updated;
            });
          })
          .catch(() => {
            queuedItems.delete(key);
            setMessages((prev) => {
              if (assistantMsgIndex < 0 || assistantMsgIndex >= prev.length) return prev;
              const updated = [...prev];
              const current = updated[assistantMsgIndex];
              updated[assistantMsgIndex] = {
                ...current,
                pendingItemNames: (current.pendingItemNames ?? []).filter(
                  (n) => n.toLowerCase() !== key
                ),
              };
              return updated;
            });
          })
          .finally(() => {
            fetchInFlight -= 1;
            startItemFetches();
          });
      }
    };
    const loadoutMode = Boolean(inferLoadoutShowcase(trimmed));
    const skinMode = inferSkinVisualize(trimmed);
    const queueItemFetch = (name: string) => {
      if (skinMode) return;
      if (dungeonName && skipDungeonItemCard(name)) return;
      const key = name.toLowerCase();
      if (queuedItems.has(key)) return;
      if (loadoutMode && queuedItems.size >= SET_SLOT_COUNT) return;
      queuedItems.add(key);
      setMessages((prev) => {
        if (assistantMsgIndex < 0 || assistantMsgIndex >= prev.length) return prev;
        const updated = [...prev];
        const current = updated[assistantMsgIndex];
        const pending = current.pendingItemNames ?? [];
        if (pending.some((n) => n.toLowerCase() === key)) return prev;
        updated[assistantMsgIndex] = {
          ...current,
          pendingItemNames: [...pending, name],
        };
        return updated;
      });
      fetchWait.push(name);
      startItemFetches();
    };

    if (loadoutMode) {
      for (const name of extractNamedSetItems(trimmed)) {
        queueItemFetch(name);
      }
    }

    if (dungeonName) {
      fetchDungeon(dungeonName)
        .then((guide) => {
          setMessages((prev) => {
            if (assistantMsgIndex < 0 || assistantMsgIndex >= prev.length) return prev;
            const updated = [...prev];
            updated[assistantMsgIndex] = {
              ...updated[assistantMsgIndex],
              dungeonGuide: guide,
            };
            return updated;
          });
          for (const drop of guide.drops) {
            if (drop.name) queueItemFetch(drop.name);
          }
        })
        .catch(() => {
          // Text guide still streams from the dungeon specialist.
        });
    }

    let assembled = "";
    try {
      for await (const chunk of streamChat(outgoingText, history, ign || undefined, abortRef.current.signal)) {
        if (chunk.error) {
          // Backend streamed a mid-response failure | surface it instead of
          // leaving the placeholder bubble blank with no explanation.
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = {
              ...updated[updated.length - 1],
              content: "Something went wrong. Please try again.",
            };
            return updated;
          });
          break;
        }
        assembled += chunk.content;
        setMessages((prev) => {
          const updated = [...prev];
          // Spread the existing message rather than replacing it outright |
          // a player profile can attach itself to this same message
          // (asynchronously, via the fetchPlayer() call above) at any point
          // during the stream, and a bare `{ role, content }` object here
          // would silently wipe that out on the very next token.
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: updated[updated.length - 1].content + chunk.content,
          };
          return updated;
        });
        if (!lookupName) {
          for (const name of extractItemNames(assembled)) {
            queueItemFetch(name);
          }
        }
        if (chunk.done) break;
      }

      if (!lookupName) {
        for (const name of extractItemNames(assembled)) {
          queueItemFetch(name);
        }
      }
    } catch (e: unknown) {
      if (e && typeof e === "object" && "paywall" in e) {
        // Rate limit hit | remove empty placeholder, show modal
        setMessages((prev) => prev.slice(0, -1));
        setPaywall((e as { paywall: PaywallInfo }).paywall);
      } else if ((e as Error)?.name !== "AbortError") {
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: "Something went wrong. Please try again.",
          };
          return updated;
        });
      }
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
      inputRef.current?.focus();
      void refreshUsage();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage(input);
    }
  }

  function handleAttachClick() {
    fileInputRef.current?.click();
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    setAttachedFile(file);
    if (file && file.type.startsWith("image/")) {
      void uploadChatImage(file).catch(() => {
        // Keep the local chip so the message can still mention the file.
      });
    }
  }

  function openPaywall() {
    if (!usage) return;
    setPaywall({
      upgrade: true,
      message: "Upgrade to keep chatting",
      used: usage.used,
      limit: usage.limit,
      remaining: usage.remaining,
      scope: usage.scope,
    });
  }

  function removeAttachment() {
    setAttachedFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function goHome() {
    abortRef.current?.abort();
    setIsStreaming(false);
    setMessages([]);
    setInput("");
    removeAttachment();
    setActiveSessionId(null);
  }

  function loadSession(id: string) {
    const session = sessions.find((s) => s.id === id);
    if (!session) return;
    abortRef.current?.abort();
    setIsStreaming(false);
    setActiveSessionId(id);
    setMessages(session.messages as Message[]);
    setInput("");
    removeAttachment();
  }

  function renameSession(id: string, title: string) {
    setSessions((prev) => {
      const next = prev.map((s) => (s.id === id ? { ...s, title } : s));
      saveSessions(next);
      return next;
    });
  }

  function deleteSession(id: string) {
    setSessions((prev) => {
      const next = prev.filter((s) => s.id !== id);
      saveSessions(next);
      return next;
    });
    if (activeSessionId === id) goHome();
  }

  function handleFeedback(index: number, rating: FeedbackRating) {
    setMessages((prev) => {
      if (index < 0 || index >= prev.length) return prev;
      const updated = [...prev];
      updated[index] = { ...updated[index], feedback: rating };
      const id = activeSessionId;
      if (id) {
        setSessions((sessionsPrev) => {
          const existing = sessionsPrev.find((s) => s.id === id);
          const session: ChatSession = {
            id,
            title: existing?.title ?? deriveTitle(updated),
            messages: updated,
            updatedAt: Date.now(),
          };
          const next = [session, ...sessionsPrev.filter((s) => s.id !== id)];
          saveSessions(next);
          return next;
        });
      }
      return updated;
    });
  }

  function toggleRecording() {
    if (isRecording) {
      recognitionRef.current?.stop();
      setIsRecording(false);
      return;
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SpeechRecognitionCtor = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    if (!SpeechRecognitionCtor) return;
    const recognition: SpeechRecognitionLike = new SpeechRecognitionCtor();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const transcript = event.results?.[0]?.[0]?.transcript as string | undefined;
      if (transcript) {
        setInput((prev) => (prev ? `${prev.trim()} ${transcript}` : transcript));
      }
    };
    recognition.onend = () => setIsRecording(false);
    recognition.onerror = () => setIsRecording(false);
    recognitionRef.current = recognition;
    recognition.start();
    setIsRecording(true);
  }

  const isEmpty = messages.length === 0;
  const lastUserIndex = messages.findLastIndex((m) => m.role === "user");

  return (
    <div className="flex h-screen bg-[#1a1a1a] text-[#ececec]">
      {/* Sidebar */}
      <aside className="hidden md:flex flex-col w-64 xl:w-72 flex-shrink-0 min-h-0 overflow-hidden border-r border-[#303030] p-4">
        <button
          onClick={goHome}
          disabled={isEmpty}
          className="flex items-center gap-2 mb-3 cursor-pointer disabled:cursor-default"
          aria-label="Back to home"
        >
          <Image
            src={isEmpty ? SWORD_SPRITE : USER_SPRITE}
            alt={isEmpty ? "RealmPal" : "Your companion"}
            width={34}
            height={34}
            style={{ imageRendering: "pixelated" }}
            unoptimized
          />
          <span className="text-lg font-semibold text-[#ececec]">RealmPal</span>
        </button>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (ign.trim()) void loadPlayer(ign.trim());
          }}
          className="mb-3"
        >
          <p className="text-xs text-[#6b6b6b] mb-2">Your IGN</p>
          <div className="relative">
            <input
              type="text"
              value={ign}
              onChange={(e) => setIgn(e.target.value)}
              placeholder="Turbine"
              maxLength={20}
              className="w-full rounded-lg bg-[#262626] border border-[#404040] pl-2.5 pr-8 py-1.5 text-xs text-[#ececec] placeholder-[#525252] focus:outline-none focus:border-white"
              aria-label="In-game name"
            />
            <button
              type="submit"
              disabled={!ign.trim()}
              aria-label="Look up player"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 w-5 h-5 flex items-center justify-center rounded text-[#737373] hover:text-[#ececec] disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <path d="M2 21L23 12 2 3v7l15 2-15 2z" />
              </svg>
            </button>
          </div>
          {ignError && <p className="text-[11px] text-red-400 mt-1">{ignError}</p>}
        </form>

        <PetCompanion profile={playerProfile} loading={isLoadingPlayer} />

        {sessions.length > 0 && (
          <div className="flex-1 overflow-y-auto min-h-0 -mx-1 px-1 mt-3">
            <p className="text-xs text-[#525252] mb-2">Chats</p>
            <ul className="space-y-1">
              {[...sessions]
                .sort((a, b) => b.updatedAt - a.updatedAt)
                .map((session) => (
                  <li key={session.id} className="group relative">
                    <button
                      onClick={() => loadSession(session.id)}
                      className={`w-full text-left text-xs truncate rounded-lg pl-2.5 pr-7 py-1.5 transition-colors duration-150 cursor-pointer ${
                        session.id === activeSessionId
                          ? "bg-[#2f2f2f] text-[#ececec]"
                          : "text-[#a3a3a3] hover:bg-[#454545] hover:text-[#ececec]"
                      }`}
                    >
                      {session.title}
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setOptionsSessionId(session.id);
                      }}
                      className="absolute right-1 top-1/2 -translate-y-1/2 w-5 h-5 flex items-center justify-center rounded text-[#737373] opacity-0 group-hover:opacity-100 hover:text-[#ececec] hover:bg-[#454545] transition-colors duration-150 cursor-pointer"
                      aria-label="Chat options"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                        <circle cx="12" cy="5" r="2" />
                        <circle cx="12" cy="12" r="2" />
                        <circle cx="12" cy="19" r="2" />
                      </svg>
                    </button>
                  </li>
                ))}
            </ul>
          </div>
        )}

        <div className={`${sessions.length > 0 ? "mt-3" : "mt-auto"} space-y-2 min-h-0 overflow-y-auto`}>
          {SIDEBAR_EXAMPLE_PROMPTS.map((config) => (
            <ExamplePrompt
              key={config.id}
              config={config}
              variant="sidebar"
              disabled={isStreaming}
              onSubmit={(message) => void sendMessage(message)}
            />
          ))}
        </div>

        <div className="flex-shrink-0 pt-3 mt-3 border-t border-[#303030] space-y-2">
          {usage && (usage.scope === "ip" || usage.limit <= 5) && (
            <button
              type="button"
              onClick={openPaywall}
              className="group w-full text-left px-2 py-1 -mx-2 rounded-lg hover:bg-[#333333] transition-colors cursor-pointer"
            >
              <span className="block text-sm text-[#a3a3a3] group-hover:text-[#ececec]">
                {usage.remaining === 1
                  ? "1 free message left"
                  : `${usage.remaining} free messages left`}
              </span>
              {!isSignedIn && (
                <span className="block text-xs leading-tight text-[#737373] group-hover:text-[#a3a3a3]">
                  Sign in for 2 more today
                </span>
              )}
            </button>
          )}
          <SidebarAccount pet={playerProfile?.top_pet} />
        </div>
      </aside>

      {/* Main chat area */}
      <main className="relative flex-1 flex flex-col min-w-0">
        {/* Account cluster | signed out shows "Sign in" next to the avatar,
            signed in just shows the avatar. Mirrors the sidebar's account
            row (same AccountMenu component, kept in sync by construction). */}
        <div className="absolute top-3 right-3 z-40 flex items-center gap-3">
          {usage && (usage.scope === "ip" || usage.limit <= 5) && (
            <button
              type="button"
              onClick={openPaywall}
              className="text-sm text-[#a3a3a3] hover:text-[#ececec] transition-colors cursor-pointer whitespace-nowrap"
            >
              {usage.remaining === 1
                ? "1 free message left"
                : `${usage.remaining} free messages left`}
            </button>
          )}
          {!isSignedIn && (
            <div className="rounded-lg bg-[#262626] p-1">
              <button
                type="button"
                onClick={() => router.push("/auth/signin")}
                className="px-3 py-1.5 rounded-md text-sm font-medium bg-white text-[#1a1a1a] hover:bg-[#e5e5e5] transition-colors cursor-pointer whitespace-nowrap"
              >
                Sign in
              </button>
            </div>
          )}
          <AccountMenu pet={playerProfile?.top_pet} size={32} openDirection="down" align="right" />
        </div>

        {/* Top bar (mobile) */}
        <header className="md:hidden flex items-center gap-2 px-4 py-3 border-b border-[#303030]">
          <button
            onClick={goHome}
            disabled={isEmpty}
            className="flex items-center gap-2 cursor-pointer disabled:cursor-default"
            aria-label="Back to home"
          >
            <Image
              src={isEmpty ? SWORD_SPRITE : USER_SPRITE}
              alt={isEmpty ? "RealmPal" : "Your companion"}
              width={26}
              height={26}
              style={{ imageRendering: "pixelated" }}
              unoptimized
            />
            <span className="text-xl font-semibold">RealmPal</span>
          </button>
          {usage && (usage.scope === "ip" || usage.limit <= 5) && (
            <button
              type="button"
              onClick={openPaywall}
              className="ml-auto text-sm text-[#a3a3a3] hover:text-[#ececec] transition-colors cursor-pointer"
            >
              {usage.remaining === 1
                ? "1 free message left"
                : `${usage.remaining} free messages left`}
            </button>
          )}
        </header>

        {/* Messages */}
        <div className="flex-1 min-w-0 overflow-y-auto" role="log" aria-live="polite" aria-label="Chat messages">
          {isEmpty ? (
            <div className="flex flex-col items-center justify-center h-full gap-6 px-4">
              <div className="text-center">
                <div className="mx-auto mb-3 flex h-[56px] w-[56px] items-center justify-center">
                  {playerProfile?.top_pet ? (
                    <PetSprite pet={playerProfile.top_pet} size={56} />
                  ) : (
                    <Image
                      src={SWORD_SPRITE}
                      alt="RealmPal"
                      width={56}
                      height={56}
                      style={{ imageRendering: "pixelated" }}
                      unoptimized
                    />
                  )}
                </div>
                <h1 className="text-2xl font-semibold text-[#ececec] mb-2">RealmPal</h1>
                <p className="text-[#737373] max-w-xs">
                  Look up players, items, and dungeon guides. Build/Visualize DPS sets, <br /> enchants, and more!
                </p>
              </div>
              {/* Example prompt cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-md">
                {LANDING_EXAMPLE_PROMPTS.map((config) => (
                  <ExamplePrompt
                    key={config.id}
                    config={config}
                    variant="card"
                    disabled={isStreaming}
                    onSubmit={(message) => void sendMessage(message)}
                  />
                ))}
              </div>
            </div>
          ) : (
            <div className="max-w-3xl xl:max-w-4xl 2xl:max-w-5xl mx-auto w-full min-w-0 pb-4">
              {messages.map((msg, i) => (
                <div
                  key={msg.id ?? i}
                  ref={i === lastUserIndex ? lastUserMsgRef : undefined}
                  className="scroll-mt-2 min-w-0"
                >
                  <MessageBubble
                    role={msg.role}
                    content={msg.content}
                    isStreaming={isStreaming && i === messages.length - 1 && msg.role === "assistant"}
                    playerProfile={msg.playerProfile}
                    showExaltationTable={msg.showExaltationTable}
                    items={msg.items}
                    pendingItemNames={msg.pendingItemNames}
                    dungeonGuide={msg.dungeonGuide}
                    userPet={playerProfile?.top_pet}
                    messageId={msg.id ?? `${activeSessionId ?? "chat"}:${i}`}
                    prompt={i > 0 && messages[i - 1].role === "user" ? messages[i - 1].content : undefined}
                    feedback={msg.feedback}
                    onFeedback={msg.role === "assistant" ? (rating) => handleFeedback(i, rating) : undefined}
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Input bar */}
        <div className="border-t border-[#303030] bg-[#1a1a1a] p-4">
          <div className="max-w-3xl xl:max-w-4xl 2xl:max-w-5xl mx-auto">
            {attachedFile && (
              <div className="flex items-center gap-2 mb-2 px-3 py-1.5 rounded-lg bg-[#262626] border border-[#404040] text-xs text-[#a3a3a3] w-fit">
                <span className="truncate max-w-[200px]">{attachedFile.name}</span>
                <button
                  onClick={removeAttachment}
                  className="text-[#737373] hover:text-[#ececec] transition-colors"
                  aria-label="Remove attachment"
                >
                  ✕
                </button>
              </div>
            )}
            <div className="flex items-end gap-2 rounded-2xl bg-[#262626] border border-[#404040] focus-within:border-[#525252] px-4 py-3 transition-colors">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={isStreaming ? "Thinking..." : "Ask about a player, item, or dungeon... or type /player <ign>"}
                rows={1}
                style={{ resize: "none" }}
                className="flex-1 bg-transparent text-sm leading-5 text-[#ececec] placeholder-[#525252] focus:outline-none min-h-[24px] max-h-[200px] overflow-y-auto"
                aria-label="Message input"
                disabled={isStreaming}
              />
              <div className="flex items-center gap-2 flex-shrink-0">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  onChange={handleFileChange}
                  className="hidden"
                  aria-hidden="true"
                />
                <button
                  onClick={handleAttachClick}
                  disabled={isStreaming}
                  className="w-8 h-8 rounded-xl border border-[#404040] hover:border-white text-[#737373] hover:text-white disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center transition-colors"
                  aria-label="Attach file"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                  </svg>
                </button>
                <button
                  onClick={toggleRecording}
                  disabled={isStreaming || !speechSupported}
                  title={speechSupported ? "Voice input" : "Voice input not supported in this browser"}
                  className={`w-8 h-8 rounded-xl border flex items-center justify-center transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                    isRecording
                      ? "border-red-500 text-red-500"
                      : "border-[#404040] hover:border-white text-[#737373] hover:text-white"
                  }`}
                  aria-label={isRecording ? "Stop voice input" : "Start voice input"}
                  aria-pressed={isRecording}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                    <line x1="12" y1="19" x2="12" y2="23" />
                    <line x1="8" y1="23" x2="16" y2="23" />
                  </svg>
                </button>
                {isStreaming && (
                  <button
                    onClick={() => abortRef.current?.abort()}
                    className="text-xs text-[#737373] hover:text-[#ececec] transition-colors px-2 py-1 rounded border border-[#404040] hover:border-[#525252]"
                    aria-label="Stop generating"
                  >
                    Stop
                  </button>
                )}
                <button
                  onClick={() => void sendMessage(input)}
                  disabled={isStreaming || !input.trim()}
                  className="w-8 h-8 rounded-xl bg-white hover:bg-[#e5e5e5] disabled:opacity-40 disabled:cursor-not-allowed text-[#1a1a1a] flex items-center justify-center transition-colors"
                  aria-label="Send message"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M2 21L23 12 2 3v7l15 2-15 2z"/>
                  </svg>
                </button>
              </div>
            </div>
            <p className="text-center text-xs text-[#404040] mt-2">
              Data via realmeye.com & umienjoyers.com · Not affiliated with DECA Games
            </p>
          </div>
        </div>
      </main>

      {/* Paywall modal */}
      {paywall && (
        <PaywallModal
          checkoutUrl={paywall.checkout_url}
          remaining={paywall.remaining}
          limit={paywall.limit}
          pet={playerProfile?.top_pet}
          signedIn={isSignedIn}
          onClose={() => setPaywall(null)}
        />
      )}

      {/* Chat history options modal (rename / delete) */}
      {optionsSessionId && (
        <ChatOptionsModal
          title={sessions.find((s) => s.id === optionsSessionId)?.title ?? ""}
          onRename={(newTitle) => renameSession(optionsSessionId, newTitle)}
          onDelete={() => deleteSession(optionsSessionId)}
          onClose={() => setOptionsSessionId(null)}
        />
      )}
    </div>
  );
}
