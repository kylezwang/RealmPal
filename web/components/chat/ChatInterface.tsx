"use client";
import { useState, useRef, useEffect, useLayoutEffect, useCallback } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { streamChat, fetchPlayer, fetchPlayerPet, fetchItem, fetchItemSuggest, fetchDungeon, fetchChatUsage, uploadChatImage, confirmCheckout, decodeAuthEmail, decodeAuthIgn, AUTH_CHANGED_EVENT, claimDailyQuestBonus, fetchQuestArt, type PlayerProfile, type ItemProfile, type DungeonGuide, type PaywallInfo, type ChatUsage, type FeedbackRating } from "@/lib/api";
import { extractPlayerLookup, isAccountPlayerLookup, shouldReusePlayerCard, wantsExaltationTable } from "@/lib/playerLookup";
import { extractDungeonLookup } from "@/lib/dungeonLookup";
import { LANDING_EXAMPLE_PROMPTS } from "@/lib/examplePrompts";
import { ExamplePrompt } from "./ExamplePrompt";
import { extractItemNames, skipDungeonItemCard, ITEM_CARD_ROW_SIZE } from "@/lib/itemLookup";
import { extractNamedSetItems, extractClassFromPrompt, inferLoadoutShowcase, inferUploadedSpriteShowcase, formatLoadoutToken, loadoutCaption, SET_SLOT_COUNT, isSameSetFollowup } from "@/lib/loadoutShowcase";
import { uploadedSpriteItems, findRecentUploadedSpriteState } from "@/lib/uploadedSprites";
import { inferSkinVisualize } from "@/lib/skinShowcase";
import { farmItemNamesFromContent } from "@/lib/farmTldr";
import { MessageBubble } from "./MessageBubble";
import { PetSprite } from "./PetCompanion";
import { PaywallModal } from "./PaywallModal";
import { ChangelogModal } from "./ChangelogModal";
import { FeedbackModal } from "./FeedbackModal";
import { hasUnseenChangelog } from "@/lib/changelog";
import { LeftoverAskBar } from "./LeftoverAskBar";
import { ComposerImages } from "./ComposerImages";
import { applySuggest, ComposerSuggest, pickGhostHit, type SuggestHit } from "./ComposerSuggest";
import {
  CHAT_IMAGE_ACCEPT,
  CHAT_IMAGE_MAX,
  chatImagePreviewUrl,
  encodeChatImage,
  filesFromClipboard,
  filesFromDrop,
  isChatImageFile,
  type PendingChatImage,
} from "@/lib/chatImages";
import { QuestProgressMeter } from "./QuestProgressMeter";
import { QuestsModal } from "./QuestsModal";
import {
  allDailyQuestsDone,
  dailyQuestPercent,
  getDailyQuestState,
  hasClaimedDailyBonus,
  markDailyBonusClaimed,
  fallbackQuestArt,
  incrementQuestShift,
  markQuestsFromMessage,
  mergeQuestArt,
  questShift,
  stripWikiTitle,
  syncQuestWindow,
  type DailyQuestState,
  type QuestArt,
} from "@/lib/quests";
import { ChatOptionsModal } from "./ChatOptionsModal";
import { ChatSidebar } from "./ChatSidebar";
import { AccountMenu } from "./AccountMenu";
import { TabIcon } from "../TabIcon";
import { SWORD_SPRITE } from "@/lib/sprites";
import {
  type ChatSession,
  loadSessions,
  saveSessions,
  deriveTitle,
  currentHistoryEmail,
  pushSessionToServer,
  removeSessionFromServer,
  syncSessionsFromServer,
} from "@/lib/chatHistory";
import {
  cachedPlayerProfile,
  loadSavedAccountProfile,
  saveSavedAccountProfile,
} from "@/lib/accountProfile";

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

const SUGGESTIONS_HIDDEN_KEY = "realm_pal_suggestions_hidden";
const LEFTOVER_HIDDEN_KEY = "realm_pal_leftover_suggestions_hidden";

function clearLeftoverHideIfRefreshed(remaining: number) {
  if (remaining > 0) {
    try {
      window.localStorage.removeItem(LEFTOVER_HIDDEN_KEY);
    } catch {
      // ignore
    }
  }
}

function SidebarIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9 4v16" />
    </svg>
  );
}

function NewChatIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

/** Pin the chat shell to the visible Safari viewport so the composer stays
 *  above the browser toolbar and the software keyboard. */
function useAppViewport() {
  useEffect(() => {
    const root = document.documentElement;
    const sync = () => {
      const vv = window.visualViewport;
      root.style.setProperty("--app-height", `${vv?.height ?? window.innerHeight}px`);
      root.style.setProperty("--app-offset", `${vv?.offsetTop ?? 0}px`);
    };
    sync();
    window.visualViewport?.addEventListener("resize", sync);
    window.visualViewport?.addEventListener("scroll", sync);
    window.addEventListener("resize", sync);
    window.addEventListener("orientationchange", sync);
    const htmlOverflow = root.style.overflow;
    const bodyOverflow = document.body.style.overflow;
    root.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    return () => {
      window.visualViewport?.removeEventListener("resize", sync);
      window.visualViewport?.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
      window.removeEventListener("orientationchange", sync);
      root.style.removeProperty("--app-height");
      root.style.removeProperty("--app-offset");
      root.style.overflow = htmlOverflow;
      document.body.style.overflow = bodyOverflow;
    };
  }, []);
}

interface Message {
  role: "user" | "assistant";
  content: string;
  id?: string;
  feedback?: FeedbackRating;
  /** Attached once resolved, when this exchange was about a specific
   * player | lets MessageBubble render a rich character/equipment card. */
  playerProfile?: PlayerProfile;
  /** True once both the initial fetch and one retry failed to load the
   * player card (the text summary above still comes from the backend's
   * own independent scrape, so it can succeed even when this failed). */
  playerLookupFailed?: boolean;
  /** Whether the user's own message actually asked about exaltations |
   * PlayerCard only renders the full per-class breakdown table when this
   * is true, since it's a lot of extra detail nobody wants by default. */
  showExaltationTable?: boolean;
  /** Class named in this turn (or the last DPS turn), so the Characters
   * card can highlight that row the way a lookup already shows every
   * character with item hover tooltips. */
  highlightClass?: string;
  /** "character" is a DPS ask: one class row, no Fame/Guild account chrome. */
  playerCardScope?: "account" | "character";
  /** Wiki infobox cards for items named in the assistant reply. */
  items?: ItemProfile[];
  /** Unique item names spotted in the reply, in order | drives card
   * skeletons until each fetchItem() resolves. */
  pendingItemNames?: string[];
  dungeonGuide?: DungeonGuide;
  images?: Array<{ name: string; thumb: string; src?: string }>;
}


/** Most recent player IGN mentioned in this chat | used for follow-ups like
 * "How many exaltations does IGN have?" where the name isn't in the
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

function findRecentCharacterSet(messages: Message[]): string[] {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    const cls = msg.highlightClass;
    const profile = msg.playerProfile;
    if (profile && cls) {
      const character = (profile.characters ?? []).find(
        (row) => row.class_name.toLowerCase() === cls.toLowerCase(),
      );
      const names = (character?.equipment ?? [])
        .slice(0, SET_SLOT_COUNT)
        .map((item) => item.name)
        .filter(Boolean);
      if (names.length >= 2) return names;
    }
    const fromItems = (msg.items ?? [])
      .map((item) => item.name)
      .filter(Boolean)
      .slice(0, SET_SLOT_COUNT);
    if (msg.role === "assistant" && fromItems.length >= 2) return fromItems;
    const fromPending = (msg.pendingItemNames ?? []).slice(0, SET_SLOT_COUNT);
    if (msg.role === "assistant" && fromPending.length >= 2) return fromPending;
  }
  return [];
}

function findRecentHighlightClass(messages: Message[]): string | undefined {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].highlightClass) return messages[i].highlightClass;
  }
  return undefined;
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
  const [showChangelog, setShowChangelog] = useState(false);
  const [showFeedback, setShowFeedback] = useState(false);
  const [unseenChangelog, setUnseenChangelog] = useState(false);
  const [showQuests, setShowQuests] = useState(false);
  const [dailyQuests, setDailyQuests] = useState<DailyQuestState[]>([]);
  const [questArt, setQuestArt] = useState<QuestArt | undefined>(() => mergeQuestArt());
  const [questBonusClaimed, setQuestBonusClaimed] = useState(false);
  const [questRefreshing, setQuestRefreshing] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [leftoverExpanded, setLeftoverExpanded] = useState(true);
  const [leftoverArmed, setLeftoverArmed] = useState(false);

  // Phone: start collapsed. Desktop: start open unless they hid them.
  // A hide or show is stored and reused on the next visit.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(SUGGESTIONS_HIDDEN_KEY);
      if (stored === "1") {
        setShowSuggestions(false);
        return;
      }
      if (stored === "0") {
        setShowSuggestions(true);
        return;
      }
      setShowSuggestions(!window.matchMedia("(max-width: 767px)").matches);
    } catch {
      // Private mode / storage disabled: stay collapsed.
    }
  }, []);

  useEffect(() => {
    try {
      setLeftoverExpanded(window.localStorage.getItem(LEFTOVER_HIDDEN_KEY) !== "1");
    } catch {
      setLeftoverExpanded(true);
    }
  }, []);

  // Pop the "what's new" modal once per new release, on first load.
  useEffect(() => {
    if (hasUnseenChangelog()) {
      setUnseenChangelog(true);
      setShowChangelog(true);
    }
  }, []);
  const [usage, setUsage] = useState<ChatUsage>({
    used: 0,
    limit: 3,
    remaining: 3,
    scope: "ip",
  });
  const [ignError, setIgnError] = useState<string | null>(null);
  const [pendingImages, setPendingImages] = useState<PendingChatImage[]>([]);
  const [dragOverComposer, setDragOverComposer] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [suggestHits, setSuggestHits] = useState<SuggestHit[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [optionsSessionId, setOptionsSessionId] = useState<string | null>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useAppViewport();

  const lastUserMsgRef = useRef<HTMLDivElement>(null);
  const pinToSentMessageRef = useRef(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const historyOwnerRef = useRef<string | null>(null);
  const persistPausedRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pendingImagesRef = useRef<PendingChatImage[]>([]);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    pendingImagesRef.current = pendingImages;
  }, [pendingImages]);

  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SpeechRecognitionCtor = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    setSpeechSupported(!!SpeechRecognitionCtor);
  }, []);

  // Ref, not a refreshUsage dependency: hydrateQuestArt sets questArt after
  // refreshUsage's own effect runs, and refreshUsage feeds that same
  // effect's dependency array, so depending on questArt directly would
  // re-create refreshUsage -> re-run the effect -> re-hydrate art -> loop.
  const questArtRef = useRef<QuestArt | undefined>(questArt);
  useEffect(() => {
    questArtRef.current = questArt;
  }, [questArt]);

  const refreshUsage = useCallback(async () => {
    try {
      const fresh = await fetchChatUsage();
      setUsage(fresh);
      clearLeftoverHideIfRefreshed(fresh.remaining);
      if (fresh.remaining > 0) {
        setLeftoverArmed(false);
        setLeftoverExpanded(true);
      }
      // Only clear today's quest checkmarks (and the bonus they unlock)
      // once the caller's actual quota timer rolls over, not at a
      // UTC-midnight calendar flip, which can land hours off from it.
      if (syncQuestWindow(fresh.resets_in_seconds ?? 0)) {
        setDailyQuests(getDailyQuestState(questArtRef.current));
        setQuestBonusClaimed(false);
      }
    } catch {
      // Keep the last known count (or the guest default) so the
      // counter does not vanish when the API is briefly unreachable.
    }
  }, []);

  const applyQuestArt = useCallback((art: QuestArt) => {
    setQuestArt(art);
    setDailyQuests(getDailyQuestState(art));
    return art;
  }, []);

  const hydrateQuestArt = useCallback(async (shift = questShift(), base?: QuestArt) => {
    const pick = base ?? fallbackQuestArt(shift);
    const [artResult, itemResult] = await Promise.allSettled([
      fetchQuestArt(shift),
      fetchItem(pick.shiny_name),
    ]);
    const serverArt = artResult.status === "fulfilled" ? artResult.value : null;
    const merged = mergeQuestArt(serverArt, shift);
    if (itemResult.status === "fulfilled") {
      const item = itemResult.value;
      merged.shiny_name = stripWikiTitle(item.name || merged.shiny_name);
      merged.shiny_sprite_url = item.shiny_sprite_url || undefined;
      merged.item_sprite_url = item.sprite_url || undefined;
    }
    return applyQuestArt(merged);
  }, [applyQuestArt]);

  useEffect(() => {
    setDailyQuests(getDailyQuestState());
    setQuestBonusClaimed(hasClaimedDailyBonus());
    let cancelled = false;
    void hydrateQuestArt().catch(() => {
      if (!cancelled) applyQuestArt(fallbackQuestArt());
    });
    return () => {
      cancelled = true;
    };
  }, [applyQuestArt, hydrateQuestArt]);

  const refreshQuests = useCallback(async () => {
    if (questRefreshing) return;
    setQuestRefreshing(true);
    const shift = incrementQuestShift();
    const next = fallbackQuestArt(shift);
    applyQuestArt(next);
    try {
      await hydrateQuestArt(shift, next);
    } catch {
      applyQuestArt(next);
    } finally {
      setQuestRefreshing(false);
    }
  }, [applyQuestArt, hydrateQuestArt, questRefreshing]);

  const noteQuestProgress = useCallback(
    (message: string) => {
      markQuestsFromMessage(message, questArt);
      const next = getDailyQuestState(questArt);
      setDailyQuests(next);
      if (!allDailyQuestsDone(next) || hasClaimedDailyBonus()) return;
      void (async () => {
        try {
          await claimDailyQuestBonus();
          markDailyBonusClaimed();
          setQuestBonusClaimed(true);
          await refreshUsage();
        } catch {
          // Chat still works; they can reopen quests and finish later.
        }
      })();
    },
    [refreshUsage, questArt],
  );

  const applyAuthState = useCallback(() => {
    // Pause persist until this account's history is loaded. Otherwise a
    // leftover message update can write the previous list into the new key.
    persistPausedRef.current = true;
    abortRef.current?.abort();
    setIsStreaming(false);
    setMessages([]);
    setActiveSessionId(null);
    const owner = currentHistoryEmail();
    historyOwnerRef.current = owner;
    const signedIn = Boolean(owner);
    setIsSignedIn(signedIn);
    if (!signedIn) {
      setUsage({ used: 0, limit: 3, remaining: 3, scope: "ip" });
      setIgn("");
      setPlayerProfile(null);
      setIgnError(null);
    } else {
      const saved = loadSavedAccountProfile();
      // The account's IGN is registered server-side at signup and is
      // already embedded in every JWT this account gets issued (see
      // api/routers/auth.py's create_jwt call) - it isn't tied to one
      // browser's localStorage. Without this fallback, a browser that never
      // ran the local "save the IGN before registering" flow in
      // PaywallModal.tsx (a different browser/device, or an account created
      // before this cache existed) found nothing in loadSavedAccountProfile
      // and the sidebar just stayed blank forever with "No pet found yet.",
      // even though the account has a real registered IGN the whole time.
      // Found live Sep 14.
      const accountIgn = saved?.ign || decodeAuthIgn();
      if (accountIgn) {
        setIgn(accountIgn);
        const sameIgn =
          Boolean(saved?.ign) &&
          saved!.ign.trim().toLowerCase() === accountIgn.trim().toLowerCase();
        setPlayerProfile(sameIgn && saved ? cachedPlayerProfile(saved) : null);
        void loadPlayer(accountIgn, { silent: true });
      } else {
        setIgn("");
        setPlayerProfile(null);
      }
    }
    setSessions(loadSessions(owner));
    if (signedIn) {
      // Local read above is the fast path (instant first paint); merge in
      // whatever the account has server-side (other devices, or chats from
      // an incognito session that has since been wiped) once it resolves.
      void syncSessionsFromServer(owner).then((merged) => {
        if (historyOwnerRef.current === owner) setSessions(merged);
      });
    }
    setDailyQuests(getDailyQuestState());
    setQuestBonusClaimed(hasClaimedDailyBonus());
    persistPausedRef.current = false;
    void hydrateQuestArt(questShift()).catch(() => {
      applyQuestArt(fallbackQuestArt());
    });
    void refreshUsage();
  }, [applyQuestArt, hydrateQuestArt, refreshUsage]);

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

  // Persist after the stream settles, and again when dungeon cards / item
  // sprites attach, so reopening a chat keeps the same styling.
  // Do NOT re-order sessions; only update the message content and keep the
  // original position in the sidebar. Sessions move to the top only when a
  // new message is actually sent, not on every render.
  useEffect(() => {
    if (persistPausedRef.current || messages.length === 0 || isStreaming) return;
    const id = activeSessionId ?? crypto.randomUUID();
    if (!activeSessionId) setActiveSessionId(id);
    const owner = historyOwnerRef.current;

    setSessions((prev) => {
      const existing = prev.find((s) => s.id === id);
      const updated: ChatSession = {
        id,
        title: existing?.title ?? deriveTitle(messages),
        messages,
        updatedAt: existing?.updatedAt ?? Date.now(),
      };
      // Update in place to keep its current position; don't move to top.
      // But .map() only ever transforms existing elements | if this session
      // doesn't exist yet (brand new chat, e.g. started from a quest or a
      // sidebar quick-suggestion rather than the composer), it must be
      // inserted instead or it silently never appears in the sidebar.
      const next = existing
        ? prev.map((s) => (s.id === id ? updated : s))
        : [updated, ...prev];
      saveSessions(next, owner);
      pushSessionToServer(updated, owner);
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, isStreaming]);

  // Move to top only when a new message is added (message count increases).
  // Track the previous message count to detect when a message was added.
  const prevMessageCountRef = useRef(messages.length);
  useEffect(() => {
    const currentCount = messages.length;
    const prevCount = prevMessageCountRef.current;
    prevMessageCountRef.current = currentCount;

    if (currentCount <= prevCount || !activeSessionId) return;

    // A new message was added; move this session to the top and update timestamp.
    setSessions((prev) => {
      const updated = prev.map((s) => {
        if (s.id === activeSessionId) {
          return { ...s, updatedAt: Date.now() };
        }
        return s;
      });
      // Re-sort to move this session to the top.
      const withReorder = [
        updated.find((s) => s.id === activeSessionId)!,
        ...updated.filter((s) => s.id !== activeSessionId),
      ];
      saveSessions(withReorder, historyOwnerRef.current);
      pushSessionToServer(withReorder[0], historyOwnerRef.current);
      return withReorder;
    });
  }, [messages.length, activeSessionId]);

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

  useEffect(() => {
    if (isStreaming || input.trim().length < 2) {
      setSuggestHits([]);
      return;
    }
    const handle = window.setTimeout(() => {
      void fetchItemSuggest(input)
        .then(setSuggestHits)
        .catch(() => setSuggestHits([]));
    }, 150);
    return () => window.clearTimeout(handle);
  }, [input, isStreaming]);

  // Load player profile when IGN is set
  async function loadPlayer(name: string, options?: { silent?: boolean }) {
    setIgnError(null);
    if (!options?.silent) setIsLoadingPlayer(true);
    try {
      const profile = await fetchPlayerPet(name);
      setPlayerProfile((prev) => {
        const top_pet =
          profile.top_pet ??
          (prev?.username.trim().toLowerCase() === name.trim().toLowerCase()
            ? prev.top_pet
            : undefined);
        const next = { ...profile, top_pet };
        saveSavedAccountProfile({ ign: name, top_pet: next.top_pet });
        return next;
      });
    } catch (e) {
      if (!options?.silent) {
        setIgnError(e instanceof Error ? e.message : "Player not found");
        setPlayerProfile(null);
      }
    } finally {
      if (!options?.silent) setIsLoadingPlayer(false);
    }
  }

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    const readyImages = pendingImages.filter((image) => image.data);
    if (isStreaming || (!trimmed && readyImages.length === 0)) return;
    if (pendingImages.some((image) => !image.data && !image.error)) return;

    // Handle /player command | this is a client-side lookup only. It should
    // never reach Claude: sending the literal "/player <ign>" text as a chat
    // message burned one of the user's free in-depth responses for a request the AI
    // can't meaningfully answer anyway, since the profile just loads into the
    // sidebar via loadPlayer().
    const playerMatch = trimmed.match(/^\/player\s+(\S+)/i);
    if (playerMatch && readyImages.length === 0) {
      const username = playerMatch[1];
      setIgn(username);
      void loadPlayer(username);
      setInput("");
      noteQuestProgress(trimmed);
      return;
    }

    if (trimmed) noteQuestProgress(trimmed);

    const apiMessage = trimmed || (
      readyImages.length === 1
        ? "Look at this RotMG screenshot and help with what it shows."
        : "Look at these RotMG screenshots and help with what they show."
    );
    const historyContent = trimmed || (
      readyImages.length === 1
        ? "Attached a screenshot"
        : `Attached ${readyImages.length} screenshots`
    );
    const attachments = readyImages.map((image) => ({
      filename: image.name,
      media_type: image.mediaType,
      data: image.data,
    }));
    const userMsg: Message = {
      role: "user",
      content: historyContent,
      images: readyImages.map((image) => ({
        name: image.name,
        thumb: image.thumb,
        src: chatImagePreviewUrl(image),
      })),
    };
    const previousUpload = findRecentUploadedSpriteState(messages);
    const spriteShowcase = inferUploadedSpriteShowcase(trimmed, {
      freshUpload: readyImages.length > 0,
      previous: previousUpload?.showcase ?? null,
    });
    const spriteItems = readyImages.length
      ? uploadedSpriteItems(userMsg.images || [])
      : previousUpload?.items;
    if (spriteShowcase && spriteItems && spriteItems.length > 0) {
      pinToSentMessageRef.current = true;
      setMessages((prev) => [
        ...prev,
        userMsg,
        {
          role: "assistant",
          content: `${loadoutCaption(spriteShowcase)}\n\n${formatLoadoutToken(spriteShowcase)}`,
          id: crypto.randomUUID(),
          items: spriteItems,
        },
      ]);
      setInput("");
      clearImages();
      inputRef.current?.focus();
      return;
    }
    const history = messages.map((m) => ({ role: m.role, content: m.content }));

    pinToSentMessageRef.current = true;
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    clearImages();
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

    // If this looks like a player lookup ("Look up player IGN", "/player
    // IGN", "What characters does IGN have?") or a named-character
    // DPS ask ("What's the DPS for IGN's bard?"), fetch that player's
    // profile in parallel so we can attach the same character/equipment card
    // (sprites + hover tooltips including on-character enchants) the lookup
    // path already uses. The model then does not have to reprint that loadout.
    const asksAboutExaltations = /exalt/i.test(trimmed);
    const showExaltationTable = wantsExaltationTable(trimmed);
    const accountLookup = isAccountPlayerLookup(trimmed);
    const highlightClass =
      extractClassFromPrompt(trimmed) ??
      (!accountLookup ? findRecentHighlightClass(messages) : undefined);
    // Player name in this message, or fall back to the most recent player
    // looked up in this chat (e.g. "How many exaltations does IGN have?"
    // or "what do the numbers look like?" after an earlier "IGN's bard").
    const lookupName =
      extractPlayerLookup(trimmed) ??
      (asksAboutExaltations || shouldReusePlayerCard(trimmed)
        ? findRecentPlayerName(messages)
        : null);
    const playerCardScope: "account" | "character" | undefined = lookupName
      ? accountLookup || !highlightClass
        ? "account"
        : "character"
      : undefined;
    if (lookupName) {
      // The backend's own player-brief scrape (for the text summary above)
      // and this card fetch hit the same short-TTL cache but race the same
      // single shared Playwright browser | when this one loses that race
      // and times out, the brief's scrape has usually finished and cached
      // the profile within a couple seconds, so one delayed retry is a fast
      // cache hit instead of a second live scrape. Only surface a visible
      // failure (rather than silently dropping the card) once that retry
      // also fails.
      const attemptFetchPlayer = (attempt: number) => {
        fetchPlayer(lookupName)
          .then((profile) => {
            setMessages((prev) => {
              if (assistantMsgIndex < 0 || assistantMsgIndex >= prev.length) return prev;
              const updated = [...prev];
              updated[assistantMsgIndex] = {
                ...updated[assistantMsgIndex],
                playerProfile: profile,
                showExaltationTable,
                highlightClass: playerCardScope === "character" ? highlightClass : undefined,
                playerCardScope,
              };
              return updated;
            });
          })
          .catch(() => {
            if (attempt < 1) {
              window.setTimeout(() => attemptFetchPlayer(attempt + 1), 2500);
              return;
            }
            setMessages((prev) => {
              if (assistantMsgIndex < 0 || assistantMsgIndex >= prev.length) return prev;
              const updated = [...prev];
              updated[assistantMsgIndex] = {
                ...updated[assistantMsgIndex],
                playerLookupFailed: true,
              };
              return updated;
            });
          });
      };
      attemptFetchPlayer(0);
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
    const loadoutMode = Boolean(inferLoadoutShowcase(trimmed) || isSameSetFollowup(trimmed));
    const skinMode = inferSkinVisualize(trimmed);
    const DUNGEON_ITEM_CARD_CAP = 8;
    const queueItemFetch = (name: string) => {
      if (skinMode) return;
      if (dungeonName && skipDungeonItemCard(name)) return;
      const key = name.toLowerCase();
      if (queuedItems.has(key)) return;
      if (loadoutMode && queuedItems.size >= SET_SLOT_COUNT) return;
      // Dungeon cards already list drops. Cap extra item cards so a
      // Hardmode Shatters guide cannot fire 30 lookups and 429 the grid.
      if (dungeonName && queuedItems.size >= DUNGEON_ITEM_CARD_CAP) return;
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
      const named = extractNamedSetItems(trimmed);
      const names = named.length >= 2 ? named : findRecentCharacterSet(messages);
      for (const name of names) {
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
          // Drops render on the dungeon card. Do not also fetch each one
          // as an item profile — HMS has 20+ uniques and trips the lookup cap.
        })
        .catch(() => {
          // Text guide still streams from the dungeon specialist.
        });
    }

    let assembled = "";
    try {
      for await (const chunk of streamChat(
        apiMessage,
        history,
        ign || undefined,
        abortRef.current.signal,
        attachments,
      )) {
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
          for (const name of farmItemNamesFromContent(assembled)) {
            queueItemFetch(name);
          }
        }
        if (chunk.done) break;
      }

      if (!lookupName) {
        for (const name of extractItemNames(assembled)) {
          queueItemFetch(name);
        }
        for (const name of farmItemNamesFromContent(assembled)) {
          queueItemFetch(name);
        }
      }
    } catch (e: unknown) {
      if (e && typeof e === "object" && "paywall" in e) {
        const info = (e as { paywall: PaywallInfo }).paywall;
        const freeQuota = (info.reason ?? "free_quota") === "free_quota";
        if (freeQuota) {
          setPaywall(info);
          setLeftoverArmed(true);
          setMessages((prev) => prev.slice(0, -1));
        } else {
          setMessages((prev) => prev.slice(0, -1));
          setPaywall(info);
        }
      } else if (e && typeof e === "object" && "tooMany" in e) {
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content:
              e instanceof Error
                ? e.message
                : "Too many questions. Try again in a minute.",
          };
          return updated;
        });
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
    const ghostHit = pickGhostHit(input, suggestHits);
    if (e.key === "Tab" && ghostHit && !e.shiftKey) {
      e.preventDefault();
      setInput(applySuggest(input, ghostHit));
      setSuggestHits([]);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage(input);
    }
  }

  function handleAttachClick() {
    fileInputRef.current?.click();
  }

  async function addImageFiles(files: File[]) {
    const images = files.filter(isChatImageFile);
    if (files.length && images.length === 0) {
      setAttachError("Attach a PNG, JPEG, WebP, or GIF");
      return;
    }
    const prev = pendingImagesRef.current;
    const room = CHAT_IMAGE_MAX - prev.length;
    if (room <= 0) {
      setAttachError(`You can attach up to ${CHAT_IMAGE_MAX} images`);
      return;
    }
    const chosen = images.slice(0, room);
    setAttachError(
      images.length > chosen.length ? `You can attach up to ${CHAT_IMAGE_MAX} images` : null,
    );
    const next: PendingChatImage[] = chosen.map((file) => ({
      id: crypto.randomUUID(),
      name: file.name || "screenshot.png",
      thumb: URL.createObjectURL(file),
      mediaType: file.type || "image/png",
      data: "",
    }));
    pendingImagesRef.current = [...prev, ...next];
    setPendingImages(pendingImagesRef.current);
    for (let i = 0; i < next.length; i++) {
      const item = next[i];
      try {
        const encoded = await encodeChatImage(chosen[i]);
        pendingImagesRef.current = pendingImagesRef.current.map((image) =>
          image.id === item.id ? { ...encoded, id: item.id } : image,
        );
        setPendingImages(pendingImagesRef.current);
        if (item.thumb.startsWith("blob:")) URL.revokeObjectURL(item.thumb);
        void uploadChatImage(chosen[i]).catch(() => {});
      } catch {
        pendingImagesRef.current = pendingImagesRef.current.map((image) =>
          image.id === item.id ? { ...image, error: "Could not read image" } : image,
        );
        setPendingImages(pendingImagesRef.current);
      }
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    void addImageFiles(files);
    e.target.value = "";
  }

  function handleComposerPaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    const files = filesFromClipboard(e);
    if (!files.length) return;
    e.preventDefault();
    void addImageFiles(files);
  }

  function handleComposerDragOver(e: React.DragEvent<HTMLDivElement>) {
    if (![...e.dataTransfer.types].includes("Files")) return;
    e.preventDefault();
    setDragOverComposer(true);
  }

  function handleComposerDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOverComposer(false);
    void addImageFiles(filesFromDrop(e));
  }

  function openPaywall() {
    setPaywall({
      upgrade: true,
      message: "Upgrade to keep chatting",
      used: usage.used,
      limit: usage.limit,
      remaining: usage.remaining,
      scope: usage.scope,
      resets_in_seconds: usage.resets_in_seconds,
    });
  }

  function openSignup() {
    setPaywall({
      upgrade: true,
      message: "Create a free account",
      used: usage?.used ?? 0,
      limit: usage?.limit ?? 5,
      remaining: usage?.remaining ?? 5,
      scope: usage?.scope ?? "ip",
      reason: "create_account",
      resets_in_seconds: usage?.resets_in_seconds ?? 0,
    });
  }

  function closeChangelog() {
    setShowChangelog(false);
    setUnseenChangelog(false);
  }

  function toggleLeftover() {
    setLeftoverExpanded((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(LEFTOVER_HIDDEN_KEY, next ? "0" : "1");
      } catch {
        // Private mode / storage disabled.
      }
      return next;
    });
  }

  function toggleSuggestions() {
    setShowSuggestions((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(SUGGESTIONS_HIDDEN_KEY, next ? "0" : "1");
      } catch {
        // Private mode / storage disabled — not worth failing over.
      }
      return next;
    });
  }

  function removeImage(id: string) {
    const target = pendingImagesRef.current.find((image) => image.id === id);
    if (target?.thumb.startsWith("blob:")) URL.revokeObjectURL(target.thumb);
    pendingImagesRef.current = pendingImagesRef.current.filter((image) => image.id !== id);
    setPendingImages(pendingImagesRef.current);
    setAttachError(null);
  }

  function clearImages() {
    for (const image of pendingImagesRef.current) {
      if (image.thumb.startsWith("blob:")) URL.revokeObjectURL(image.thumb);
    }
    pendingImagesRef.current = [];
    setPendingImages([]);
    setAttachError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function goHome() {
    abortRef.current?.abort();
    setIsStreaming(false);
    setMessages([]);
    setInput("");
    clearImages();
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
    clearImages();
  }

  function renameSession(id: string, title: string) {
    setSessions((prev) => {
      const next = prev.map((s) => (s.id === id ? { ...s, title } : s));
      saveSessions(next, historyOwnerRef.current);
      const renamed = next.find((s) => s.id === id);
      if (renamed) pushSessionToServer(renamed, historyOwnerRef.current);
      return next;
    });
  }

  function deleteSession(id: string) {
    setSessions((prev) => {
      const next = prev.filter((s) => s.id !== id);
      saveSessions(next, historyOwnerRef.current);
      return next;
    });
    removeSessionFromServer(id, historyOwnerRef.current);
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
            updatedAt: existing?.updatedAt ?? Date.now(),
          };
          // Keep the session in its current position; don't move to top.
          const next = sessionsPrev.map((s) => (s.id === id ? session : s));
          saveSessions(next, historyOwnerRef.current);
          pushSessionToServer(session, historyOwnerRef.current);
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

  const closeMobileNav = useCallback(() => setMobileNavOpen(false), []);

  useEffect(() => {
    if (!mobileNavOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") closeMobileNav();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileNavOpen, closeMobileNav]);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    const onChange = () => {
      if (mq.matches) closeMobileNav();
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [closeMobileNav]);

  const sidebarProps = {
    isEmpty,
    ign,
    onIgnChange: setIgn,
    onLoadPlayer: (name: string) => void loadPlayer(name),
    ignError,
    playerProfile,
    isLoadingPlayer,
    sessions,
    activeSessionId,
    onOpenSessionOptions: setOptionsSessionId,
    showSuggestions,
    onToggleSuggestions: toggleSuggestions,
    isStreaming,
    onRegister: () => {
      openSignup();
      closeMobileNav();
    },
    usage,
    onOpenPaywall: () => {
      openPaywall();
      closeMobileNav();
    },
    questPercent: dailyQuestPercent(dailyQuests),
    unseenChangelog,
    onHome: () => {
      goHome();
      closeMobileNav();
    },
    onLoadSession: (id: string) => {
      loadSession(id);
      closeMobileNav();
    },
    onSubmitPrompt: (message: string) => {
      void sendMessage(message);
      closeMobileNav();
    },
    onOpenQuests: () => {
      setShowQuests(true);
      closeMobileNav();
    },
    onOpenChangelog: () => {
      setShowChangelog(true);
      closeMobileNav();
    },
    onOpenFeedback: () => {
      setShowFeedback(true);
      closeMobileNav();
    },
  };

  const leftoverActive =
    usage.tier !== "paid" && (leftoverArmed || usage.remaining <= 0);
  const encodingImages = pendingImages.some((image) => !image.data && !image.error);
  const composerGhost = pickGhostHit(input, suggestHits);
  const canSend =
    !isStreaming &&
    !encodingImages &&
    Boolean(input.trim() || pendingImages.some((image) => image.data));

  return (
    <div className="app-shell flex bg-[#1a1a1a] text-[#ececec] overflow-hidden">
      <TabIcon pet={playerProfile?.top_pet} />
      {/* Sidebar (desktop) */}
      <aside className="hidden md:flex flex-col w-64 xl:w-72 flex-shrink-0 min-h-0 overflow-hidden border-r border-[#303030]">
        <ChatSidebar className="flex flex-col flex-1 min-h-0 overflow-hidden p-4" {...sidebarProps} />
      </aside>

      {mobileNavOpen && (
        <div
          className="md:hidden fixed z-50 flex flex-col bg-[#1a1a1a]"
          style={{
            top: "var(--app-offset, 0px)",
            left: 0,
            width: "100%",
            height: "var(--app-height, 100svh)",
          }}
          role="dialog"
          aria-modal="true"
          aria-label="Sidebar"
        >
          <ChatSidebar
            className="flex flex-col flex-1 min-h-0 overflow-hidden px-4 pt-2 pb-[max(1rem,env(safe-area-inset-bottom))]"
            onClose={closeMobileNav}
            {...sidebarProps}
          />
        </div>
      )}

      {/* Main chat area */}
      <main className="relative flex-1 flex flex-col min-w-0 min-h-0">
        {/* Account cluster (desktop) | signed out shows "Sign in" next to the
            avatar, signed in just shows the avatar. Mirrors the sidebar's
            account row (same AccountMenu, kept in sync by construction). */}
        <div className="hidden md:flex absolute top-0 right-0 z-40 items-center gap-5 rounded-bl-xl bg-[#1a1a1a] border-b border-l border-[#303030] px-4 py-2">
          <button
            type="button"
            onClick={() => setShowFeedback(true)}
            className="text-sm text-[#a3a3a3] hover:text-[#ececec] transition-colors cursor-pointer whitespace-nowrap"
          >
            Feedback
          </button>
          <button
            type="button"
            onClick={() => setShowChangelog(true)}
            className="relative text-sm text-[#a3a3a3] hover:text-[#ececec] transition-colors cursor-pointer whitespace-nowrap"
          >
            What&rsquo;s new
            {unseenChangelog && (
              <span
                className="absolute -top-0.5 -right-1.5 h-1.5 w-1.5 rounded-full bg-white"
                aria-hidden="true"
              />
            )}
          </button>
          <QuestProgressMeter
            variant="header"
            percent={dailyQuestPercent(dailyQuests)}
            onClick={() => setShowQuests(true)}
          />
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
          <AccountMenu
            pet={playerProfile?.top_pet}
            size={32}
            openDirection="down"
            align="right"
            onRegister={openSignup}
            usage={usage}
            onOpenPaywall={openPaywall}
          />
        </div>

        {/* Compact chrome (mobile): sidebar toggle, optional new chat, account */}
        <header className="md:hidden flex items-center justify-between gap-2 px-2 py-1.5 flex-shrink-0">
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            className="flex h-10 w-10 items-center justify-center rounded-lg text-[#ececec] hover:bg-[#2a2a2a] transition-colors"
            aria-label="Open sidebar"
            aria-expanded={mobileNavOpen}
          >
            <SidebarIcon />
          </button>
          <div className="flex items-center gap-1.5">
            {!isEmpty && (
              <button
                type="button"
                onClick={goHome}
                className="flex h-10 w-10 items-center justify-center rounded-lg text-[#ececec] hover:bg-[#2a2a2a] transition-colors"
                aria-label="New chat"
              >
                <NewChatIcon />
              </button>
            )}
            {!isSignedIn && (
              <button
                type="button"
                onClick={() => router.push("/auth/signin")}
                className="px-3 py-1.5 rounded-md text-sm font-medium bg-white text-[#1a1a1a] hover:bg-[#e5e5e5] transition-colors"
              >
                Sign in
              </button>
            )}
            <AccountMenu
              pet={playerProfile?.top_pet}
              size={28}
              openDirection="down"
              align="right"
              onRegister={openSignup}
              usage={usage}
              onOpenPaywall={openPaywall}
            />
          </div>
        </header>

        {/* Messages */}
        <div className="flex-1 min-h-0 min-w-0 overflow-y-auto overscroll-contain" role="log" aria-live="polite" aria-label="Chat messages">
          {isEmpty ? (
            <div className="flex flex-col items-center justify-center min-h-full gap-5 px-4 py-4 md:gap-6 md:pt-14">
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
                  Look up players, items, and dungeon guides. Build/Visualize DPS, sets, <br /> skins, enchants, and more!
                </p>
              </div>
              {/* Example prompt cards */}
              {!(leftoverActive && leftoverExpanded) && (
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
              )}
            </div>
          ) : (
            <div className="max-w-3xl xl:max-w-4xl 2xl:max-w-5xl mx-auto w-full min-w-0 pb-4 md:pt-16">
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
                    playerLookupFailed={msg.playerLookupFailed}
                    showExaltationTable={msg.showExaltationTable}
                    highlightClass={msg.highlightClass}
                    playerCardScope={msg.playerCardScope}
                    items={msg.items}
                    pendingItemNames={msg.pendingItemNames}
                    dungeonGuide={msg.dungeonGuide}
                    images={msg.images}
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

        {/* Input bar | pinned above Safari's toolbar via the visual viewport shell */}
        <div className="flex-shrink-0 border-t border-[#303030] bg-[#1a1a1a] px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] md:p-4">
          <div className="max-w-3xl xl:max-w-4xl 2xl:max-w-5xl mx-auto">
            {leftoverActive && (
              <LeftoverAskBar
                signedIn={isSignedIn}
                expanded={leftoverExpanded}
                onToggle={toggleLeftover}
                disabled={isStreaming}
                onSubmit={(message) => void sendMessage(message)}
              />
            )}
            {attachError && (
              <p className="mb-2 px-1 text-xs text-red-300">{attachError}</p>
            )}
            <div
              className={`rounded-2xl bg-[#262626] border transition-colors ${
                dragOverComposer
                  ? "border-white"
                  : "border-[#404040] focus-within:border-[#525252]"
              }`}
              onDragOver={handleComposerDragOver}
              onDragLeave={() => setDragOverComposer(false)}
              onDrop={handleComposerDrop}
            >
              <ComposerImages images={pendingImages} onRemove={removeImage} />
              <div className="flex items-end gap-2 px-4 py-3">
              <div className="relative min-h-[24px] min-w-0 flex-1">
              <ComposerSuggest input={input} hit={composerGhost} />
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                onPaste={handleComposerPaste}
                placeholder={
                  isStreaming
                    ? "Thinking..."
                    : pendingImages.length
                      ? "Ask about this screenshot..."
                      : "Ask about a player, item, or dungeon..."
                }
                rows={1}
                style={{ resize: "none" }}
                className={`relative z-0 w-full appearance-none bg-transparent p-0 text-base md:text-sm leading-5 placeholder-[#525252] caret-[#ececec] focus:outline-none min-h-[24px] max-h-[200px] overflow-y-auto ${
                  composerGhost ? "text-transparent" : "text-[#ececec]"
                }`}
                aria-label="Message input"
                enterKeyHint="send"
                disabled={isStreaming}
              />
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={CHAT_IMAGE_ACCEPT}
                  multiple
                  onChange={handleFileChange}
                  className="hidden"
                  aria-hidden="true"
                />
                <button
                  onClick={handleAttachClick}
                  disabled={isStreaming || pendingImages.length >= CHAT_IMAGE_MAX}
                  className="w-8 h-8 rounded-xl border border-[#404040] hover:border-white text-[#737373] hover:text-white disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center transition-colors"
                  aria-label="Attach screenshot"
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
                  disabled={!canSend}
                  className="w-8 h-8 rounded-xl bg-white hover:bg-[#e5e5e5] disabled:opacity-40 disabled:cursor-not-allowed text-[#1a1a1a] flex items-center justify-center transition-colors"
                  aria-label="Send message"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M2 21L23 12 2 3v7l15 2-15 2z"/>
                  </svg>
                </button>
              </div>
              </div>
            </div>
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
          reason={paywall.reason}
          defaultIgn={ign}
          spendCapUsd={paywall.spend_cap_usd ?? usage?.spend_cap_usd ?? 0}
          onDemandSpentUsd={usage?.on_demand_spent_usd ?? 0}
          resetsInSeconds={paywall.resets_in_seconds ?? usage?.resets_in_seconds ?? 0}
          onUsageEnabled={() => void refreshUsage()}
          onClose={() => setPaywall(null)}
        />
      )}

      {/* What's new modal */}
      {showChangelog && <ChangelogModal onClose={closeChangelog} />}

      {showFeedback && (
        <FeedbackModal ign={ign} onClose={() => setShowFeedback(false)} />
      )}

      {showQuests && (
        <QuestsModal
          quests={dailyQuests}
          art={questArt}
          claimed={questBonusClaimed}
          refreshing={questRefreshing}
          onRefresh={() => void refreshQuests()}
          onStart={(prompt) => void sendMessage(prompt)}
          onClose={() => setShowQuests(false)}
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
