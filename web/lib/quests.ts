import { decodeAuthEmail } from "./api";

export interface DailyQuest {
  id: "dungeon" | "lookup" | "shiny-divine";
  title: string;
  hint: string;
  /** Prefills chat when the visitor starts the quest from the modal. */
  prompt: string;
  match: (message: string) => boolean;
  icon?: "user" | "dungeon" | "shiny";
}

export interface DailyQuestState extends DailyQuest {
  done: boolean;
}

export interface QuestArt {
  dungeon_name: string;
  dungeon_prompt: string;
  dungeon_portal_url?: string | null;
  shiny_name: string;
  /** Only set when the item has a real shiny recast. */
  shiny_sprite_url?: string | null;
  /** Regular wiki sprite, used when there is no shiny. */
  item_sprite_url?: string | null;
}

const WIKI_IMG = "https://www.realmeye.com/s/a/img/wiki/i/";

/** RealmEye dungeon-index sprites. Hardmode Shatters uses The Source dome. */
const DUNGEON_PORTALS: { match: (name: string) => boolean; url: string }[] = [
  { match: (name) => /shatter/.test(name) && /hard\s*mode|hardmode/.test(name), url: `${WIKI_IMG}bdfzUM2.png` },
  { match: (name) => /shatter/.test(name), url: `${WIKI_IMG}yA4tlry.png` },
  { match: (name) => /moonlight|\bmv\b/.test(name), url: `${WIKI_IMG}CHqjDCE.png` },
  { match: (name) => /sanctuary|\bo3\b/.test(name), url: `${WIKI_IMG}JGnMCv2.png` },
  { match: (name) => /\bnest\b/.test(name), url: `${WIKI_IMG}FgpEOel.png` },
  { match: (name) => /cultist/.test(name), url: `${WIKI_IMG}on1ykYB.png` },
];

export function portalForDungeon(name: string, fallback?: string | null): string | undefined {
  const text = stripWikiTitle(name || "").toLowerCase();
  const known = DUNGEON_PORTALS.find((row) => row.match(text));
  return known?.url || fallback || undefined;
}

/** Same order as api/services/daily_quests.py — keep in sync. */
const DUNGEON_ROTATION = [
  "Hardmode Shatters",
  "Moonlight Village",
  "Oryx's Sanctuary",
  "The Nest",
  "Cultist Hideout",
  "Carboniferous",
  "Floral Escape",
  "Sanguine Forest",
  "Runic Tundra",
  "Deep Sea Abyss",
  "The Shatters",
];

const SHINY_DIVINE_CANDIDATES = [
  "Snake Eye Ring",
  "The Twilight Gemstone",
  "Crown",
  "Ring of the Nile",
  "Bracer of the Guardian",
  "Omnipotence Ring",
  "The Forgotten Crown",
  "Chrysalis of Eternity",
  "Tablet of the King's Avatar",
  "Sentinel's Sidearm",
];

const DAILY_COUNT = 3;
const STORAGE_KEY = "realm_pal_daily_quests";
const SHIFT_KEY = "realm_pal_quest_shift";

function questOwner(): string | null {
  const email = decodeAuthEmail()?.trim().toLowerCase();
  return email || null;
}

function scopedKey(base: string): string {
  const owner = questOwner();
  return owner ? `${base}:${owner}` : base;
}

function readScopedOrLegacy(base: string): string | null {
  if (typeof window === "undefined") return null;
  const scoped = window.localStorage.getItem(scopedKey(base));
  if (scoped) return scoped;
  if (!questOwner()) return window.localStorage.getItem(base);
  const legacy = window.localStorage.getItem(base);
  if (legacy) {
    window.localStorage.setItem(scopedKey(base), legacy);
  }
  return legacy;
}

function utcDateStamp(): string {
  return new Date().toISOString().slice(0, 10);
}

function daysBetween(a: string, b: string): number {
  const t1 = Date.parse(`${a}T00:00:00Z`);
  const t2 = Date.parse(`${b}T00:00:00Z`);
  if (!Number.isFinite(t1) || !Number.isFinite(t2)) return 0;
  return Math.abs(t2 - t1) / 86_400_000;
}

function dailySeed(stamp = utcDateStamp()): number {
  let seed = 0;
  for (let i = 0; i < stamp.length; i++) seed = (seed * 31 + stamp.charCodeAt(i)) >>> 0;
  return seed;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function dungeonMatcher(name: string): (message: string) => boolean {
  const pattern = escapeRegExp(name).replace(/\s+/g, "\\s+");
  const extra = /moonlight/i.test(name) ? "|\\bmv\\b" : "";
  const re = new RegExp(`${pattern}${extra}`, "i");
  return (message) => re.test(message);
}

function readShift(): number {
  if (typeof window === "undefined") return 0;
  const today = utcDateStamp();
  try {
    const raw = readScopedOrLegacy(SHIFT_KEY);
    if (!raw) return 0;
    const parsed = JSON.parse(raw) as { date?: string; shift?: number };
    if (parsed.date !== today) return 0;
    return Math.max(0, Math.floor(Number(parsed.shift) || 0));
  } catch {
    return 0;
  }
}

function writeShift(shift: number): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      scopedKey(SHIFT_KEY),
      JSON.stringify({ date: utcDateStamp(), shift }),
    );
  } catch {
    // Private mode / storage disabled.
  }
}

export function questShift(): number {
  return readShift();
}

/** Advance today's dungeon and shiny pick. Returns the new shift. */
export function incrementQuestShift(): number {
  const next = readShift() + 1;
  writeShift(next);
  return next;
}

export function fallbackQuestArt(shift = readShift()): QuestArt {
  const seed = dailySeed() + shift;
  const dungeon = DUNGEON_ROTATION[seed % DUNGEON_ROTATION.length];
  const shiny = SHINY_DIVINE_CANDIDATES[seed % SHINY_DIVINE_CANDIDATES.length];
  return {
    dungeon_name: dungeon,
    dungeon_prompt: `Guide to complete ${dungeon}`,
    dungeon_portal_url: portalForDungeon(dungeon),
    shiny_name: shiny,
  };
}

export function stripWikiTitle(name: string): string {
  return (name || "")
    .replace(/\s*[-–—]\s*the RotMG Wiki.*$/gi, "")
    .replace(/\s+the RotMG Wiki/gi, "")
    .trim();
}

function sameDungeon(a: string, b: string): boolean {
  const left = stripWikiTitle(a).toLowerCase();
  const right = stripWikiTitle(b).toLowerCase();
  if (!left || !right) return false;
  if (left === right) return true;
  const hard = (value: string) => /hard\s*mode|hardmode/.test(value);
  if (hard(left) !== hard(right)) return false;
  return left.includes(right) || right.includes(left);
}

/** Local pick wins after a refresh. Server only supplies matching portal/shiny art. */
export function mergeQuestArt(server?: QuestArt | null, shift = readShift()): QuestArt {
  const fallback = fallbackQuestArt(shift);
  if (!server) {
    return {
      ...fallback,
      dungeon_portal_url: portalForDungeon(fallback.dungeon_name),
    };
  }
  const dungeonMatch = sameDungeon(server.dungeon_name || "", fallback.dungeon_name);
  const shinyMatch = sameDungeon(server.shiny_name || "", fallback.shiny_name);
  const useServerShiny = shinyMatch || shift === 0;
  return {
    dungeon_name: stripWikiTitle(fallback.dungeon_name),
    dungeon_prompt: stripWikiTitle(fallback.dungeon_prompt),
    dungeon_portal_url: portalForDungeon(
      fallback.dungeon_name,
      dungeonMatch ? server.dungeon_portal_url || undefined : undefined,
    ),
    shiny_name: stripWikiTitle(
      useServerShiny ? server.shiny_name || fallback.shiny_name : fallback.shiny_name,
    ),
    shiny_sprite_url: useServerShiny ? server.shiny_sprite_url || undefined : undefined,
    item_sprite_url: server.item_sprite_url || undefined,
  };
}

/** Today's three quests. Pass server art so titles/sprites match the cache. */
export function todaysQuests(art: QuestArt = fallbackQuestArt()): DailyQuest[] {
  const dungeon = stripWikiTitle(art.dungeon_name);
  const shiny = stripWikiTitle(art.shiny_name);
  return [
    {
      id: "dungeon",
      title: `Ask about ${dungeon}`,
      hint: `Any question about ${dungeon}.`,
      prompt: stripWikiTitle(art.dungeon_prompt || `Guide to complete ${dungeon}`),
      match: dungeonMatcher(dungeon),
      icon: "dungeon",
    },
    {
      id: "lookup",
      title: "Look up a player",
      hint: "Look up any in-game name.",
      prompt: "Look up player Turbine",
      match: (message) =>
        /(?:look\s*up|lookup)\s+player\b/i.test(message) || /^\/player\s+\S+/i.test(message),
      icon: "user",
    },
    {
      id: "shiny-divine",
      title: "See a shiny divine item",
      hint: "Ask to see any item or set as shiny divine.",
      prompt: `Show me a shiny divine ${shiny}`,
      match: (message) => /\bshiny\b/i.test(message) && /\bdivine\b/i.test(message),
      icon: "shiny",
    },
  ];
}

interface StoredProgress {
  date: string;
  done: string[];
  claimed: boolean;
}

function readProgress(): StoredProgress {
  const today = utcDateStamp();
  try {
    const raw = readScopedOrLegacy(STORAGE_KEY);
    if (!raw) return { date: today, done: [], claimed: false };
    const parsed = JSON.parse(raw) as StoredProgress;
    // The real reset trigger is syncQuestWindow, tied to the caller's
    // actual (rolling) message-quota timer, the same one the paywall
    // shows. A UTC-midnight calendar flip can land hours before or after
    // that timer resets, so it must not clear the "quests done" credit on
    // its own. This is only a safety net for when syncQuestWindow never
    // ran (e.g. usage stayed unreachable for a couple of days).
    if (!parsed.date || daysBetween(parsed.date, today) >= 2) {
      return { date: today, done: [], claimed: false };
    }
    return {
      date: parsed.date,
      done: Array.isArray(parsed.done) ? parsed.done : [],
      claimed: Boolean(parsed.claimed),
    };
  } catch {
    return { date: today, done: [], claimed: false };
  }
}

function writeProgress(progress: StoredProgress): void {
  try {
    window.localStorage.setItem(scopedKey(STORAGE_KEY), JSON.stringify(progress));
  } catch {
    // Private mode / storage disabled — progress just won't persist.
  }
}

const WINDOW_KEY = "realm_pal_quest_window";

function readLastResetsInSeconds(): number | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = readScopedOrLegacy(WINDOW_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { resetsInSeconds?: number };
    const value = Number(parsed.resetsInSeconds);
    return Number.isFinite(value) ? value : null;
  } catch {
    return null;
  }
}

function writeLastResetsInSeconds(value: number): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      scopedKey(WINDOW_KEY),
      JSON.stringify({ resetsInSeconds: value }),
    );
  } catch {
    // Private mode / storage disabled.
  }
}

/**
 * Call whenever fresh `/chat/usage` data loads. `resetsInSeconds` only ever
 * counts down within one quota window; an increase means the window just
 * rolled over for real. That is the only moment quest progress (and the
 * bonus credit it unlocks) should clear locally, matching the same fix
 * applied server-side in `daily_quests.claim_daily_bonus`. Returns true if
 * a rollover was detected and progress was cleared.
 */
export function syncQuestWindow(resetsInSeconds: number): boolean {
  if (typeof window === "undefined") return false;
  const last = readLastResetsInSeconds();
  writeLastResetsInSeconds(resetsInSeconds);
  if (last == null || resetsInSeconds <= last) return false;
  const progress = readProgress();
  if (progress.done.length === 0 && !progress.claimed) return false;
  writeProgress({ date: utcDateStamp(), done: [], claimed: false });
  return true;
}

export function getDailyQuestState(art?: QuestArt): DailyQuestState[] {
  const progress = typeof window === "undefined" ? { done: [] as string[] } : readProgress();
  const done = new Set(progress.done);
  return todaysQuests(art ?? fallbackQuestArt()).map((quest) => ({
    ...quest,
    done: done.has(quest.id),
  }));
}

export function dailyQuestPercent(quests: DailyQuestState[] = getDailyQuestState()): number {
  if (quests.length === 0) return 0;
  const done = quests.filter((quest) => quest.done).length;
  return Math.min(100, Math.round((done / quests.length) * 100));
}

export function allDailyQuestsDone(quests: DailyQuestState[] = getDailyQuestState()): boolean {
  return quests.length > 0 && quests.every((quest) => quest.done);
}

export function markQuestsFromMessage(message: string, art?: QuestArt): string[] {
  if (typeof window === "undefined") return [];
  const progress = readProgress();
  const newly: string[] = [];
  for (const quest of todaysQuests(art ?? fallbackQuestArt())) {
    if (progress.done.includes(quest.id)) continue;
    if (quest.match(message)) {
      progress.done.push(quest.id);
      newly.push(quest.id);
    }
  }
  if (newly.length) writeProgress(progress);
  return newly;
}

export function hasClaimedDailyBonus(): boolean {
  if (typeof window === "undefined") return false;
  return readProgress().claimed;
}

export function markDailyBonusClaimed(): void {
  if (typeof window === "undefined") return;
  const progress = readProgress();
  progress.claimed = true;
  writeProgress(progress);
}

export { DAILY_COUNT };
