"use client";
import { useEffect } from "react";
import Image from "next/image";
import { portalForDungeon, type DailyQuestState, type QuestArt } from "@/lib/quests";
import { EYEBALL_SPRITE } from "@/lib/sprites";
import { LoadoutItemIcon } from "./LoadoutRow";

const QUEST_ICON_SIZE = 40;

interface Props {
  quests: DailyQuestState[];
  art?: QuestArt;
  claimed: boolean;
  refreshing?: boolean;
  onRefresh: () => void;
  onStart: (prompt: string) => void;
  onClose: () => void;
}

function QuestIcon({
  quest,
  art,
}: {
  quest: DailyQuestState;
  art?: QuestArt;
}) {
  if (quest.icon === "user") {
    return (
      <Image
        src={EYEBALL_SPRITE}
        alt=""
        width={QUEST_ICON_SIZE}
        height={QUEST_ICON_SIZE}
        className="h-10 w-10"
        style={{ imageRendering: "pixelated" }}
        unoptimized
      />
    );
  }
  const dungeonPortal =
    quest.icon === "dungeon"
      ? art?.dungeon_portal_url || portalForDungeon(art?.dungeon_name || quest.title)
      : undefined;
  if (quest.icon === "dungeon" && dungeonPortal) {
    return (
      <img
        src={dungeonPortal}
        alt=""
        width={QUEST_ICON_SIZE}
        height={QUEST_ICON_SIZE}
        className="h-10 w-10 object-contain"
        style={{ imageRendering: "pixelated" }}
      />
    );
  }
  if (quest.icon === "shiny") {
    const shinySrc = art?.shiny_sprite_url || undefined;
    const regularSrc = art?.item_sprite_url || undefined;
    return (
      <LoadoutItemIcon
        key={`${art?.shiny_name ?? ""}:${shinySrc ?? ""}:${regularSrc ?? ""}`}
        item={{
          name: art?.shiny_name || "Shiny divine item",
          stats: {},
          drop_locations: [],
          shiny_sprite_url: shinySrc,
          sprite_url: regularSrc || shinySrc,
        }}
        showcase={{ shiny: Boolean(shinySrc), rarity: "divine" }}
      />
    );
  }
  return null;
}

/**
 * Daily quests: three short Realm tasks that refresh each UTC day.
 * Finishing all of them grants one extra message on free and paid.
 */
export function QuestsModal({
  quests,
  art,
  claimed,
  refreshing = false,
  onRefresh,
  onStart,
  onClose,
}: Props) {
  const done = quests.filter((quest) => quest.done).length;
  const complete = quests.length > 0 && done === quests.length;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="quests-title"
    >
      <div
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="relative z-10 w-full max-w-sm max-h-[80vh] overflow-visible rounded-2xl border border-[#404040] bg-[#1e1e1e] p-6 shadow-2xl animate-fade-in">
        <div className="absolute top-4 right-4 flex items-center gap-0.5">
          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            className="rounded p-1 text-[#737373] transition-colors hover:text-[#ececec] cursor-pointer disabled:cursor-wait"
            aria-label="Refresh quests"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={refreshing ? "animate-spin" : undefined}
              aria-hidden="true"
            >
              <path d="M13.5 8a5.5 5.5 0 1 1-1.4-3.6" />
              <path d="M12 2.5v2.8h-2.8" />
            </svg>
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[#737373] transition-colors hover:text-[#ececec] cursor-pointer"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <h2 id="quests-title" className="text-lg font-semibold text-[#ececec] mb-1">
          Daily quests
        </h2>
        <p className="text-sm text-[#737373] mb-5">
          {complete
            ? claimed
              ? "All done. Extra message unlocked for today."
              : "All done. Unlocking your extra message…"
            : "Finish all three for one extra message today."}
        </p>

        <ul className="space-y-3">
          {quests.map((quest) => (
            <li key={quest.id}>
              <div
                role="button"
                tabIndex={0}
                onClick={() => {
                  onClose();
                  onStart(quest.prompt);
                }}
                onKeyDown={(e) => {
                  if (e.key !== "Enter" && e.key !== " ") return;
                  e.preventDefault();
                  onClose();
                  onStart(quest.prompt);
                }}
                className={`w-full text-left overflow-visible rounded-xl border px-4 py-3 transition-colors cursor-pointer ${
                  quest.done
                    ? "border-[#303030] bg-[#1a1a1a] hover:bg-[#222222]"
                    : "border-[#404040] bg-[#262626] hover:bg-[#2a2a2a]"
                }`}
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full border ${
                      quest.done
                        ? "border-white bg-white text-[#1a1a1a]"
                        : "border-[#737373] text-transparent"
                    }`}
                    aria-hidden="true"
                  >
                    {quest.done ? "✓" : ""}
                  </span>
                  <div className="min-w-0 flex-1 overflow-hidden">
                    <p
                      className={`truncate text-sm font-medium ${
                        quest.done ? "text-[#737373] line-through" : "text-[#ececec]"
                      }`}
                    >
                      {quest.title}
                    </p>
                    <p className="mt-0.5 truncate text-xs text-[#737373]">{quest.hint}</p>
                  </div>
                  <span
                    className="relative z-20 flex h-12 w-12 flex-shrink-0 items-center justify-center overflow-visible"
                    aria-hidden="true"
                  >
                    <QuestIcon quest={quest} art={art} />
                  </span>
                </div>
              </div>
            </li>
          ))}
        </ul>

        <p className="text-xs text-[#737373] mt-5">
          {quests.length === 0
            ? "New set tomorrow"
            : `${Math.round((done / quests.length) * 100)}% complete · new set tomorrow`}
        </p>

        <button
          type="button"
          onClick={onClose}
          className="mt-4 w-full rounded-lg bg-white py-2.5 text-sm font-semibold text-[#1a1a1a] transition-colors hover:bg-[#e5e5e5] cursor-pointer"
        >
          Close
        </button>
      </div>
    </div>
  );
}
