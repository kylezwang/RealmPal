"use client";
import Image from "next/image";
import type { PlayerProfile } from "@/lib/api";
import { SIDEBAR_EXAMPLE_PROMPTS } from "@/lib/examplePrompts";
import { SWORD_SPRITE, USER_SPRITE } from "@/lib/sprites";
import type { ChatSession } from "@/lib/chatHistory";
import { ExamplePrompt } from "./ExamplePrompt";
import { PetCompanion } from "./PetCompanion";
import { QuestProgressMeter } from "./QuestProgressMeter";
import { SidebarAccount } from "./SidebarAccount";
import { ChevronToggle } from "./ChevronToggle";

interface Props {
  className?: string;
  isEmpty: boolean;
  onHome: () => void;
  onClose?: () => void;
  ign: string;
  onIgnChange: (value: string) => void;
  onLoadPlayer: (name: string) => void;
  ignError: string | null;
  playerProfile: PlayerProfile | null;
  isLoadingPlayer: boolean;
  sessions: ChatSession[];
  activeSessionId: string | null;
  onLoadSession: (id: string) => void;
  onOpenSessionOptions: (id: string) => void;
  showSuggestions: boolean;
  onToggleSuggestions: () => void;
  isStreaming: boolean;
  onSubmitPrompt: (message: string) => void;
  onRegister?: () => void;
  questPercent: number;
  onOpenQuests: () => void;
  unseenChangelog: boolean;
  onOpenChangelog: () => void;
  onOpenFeedback: () => void;
}

function CloseIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
      <path d="M18 6L6 18M6 6l12 12" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function ChatSidebar({
  className = "",
  isEmpty,
  onHome,
  onClose,
  ign,
  onIgnChange,
  onLoadPlayer,
  ignError,
  playerProfile,
  isLoadingPlayer,
  sessions,
  activeSessionId,
  onLoadSession,
  onOpenSessionOptions,
  showSuggestions,
  onToggleSuggestions,
  isStreaming,
  onSubmitPrompt,
  onRegister,
  questPercent,
  onOpenQuests,
  unseenChangelog,
  onOpenChangelog,
  onOpenFeedback,
}: Props) {
  return (
    <div className={className}>
      <div className="flex items-center gap-1 mb-3">
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg text-[#ececec] hover:bg-[#2a2a2a] transition-colors"
            aria-label="Close sidebar"
          >
            <CloseIcon />
          </button>
        )}
        <button
          onClick={onHome}
          disabled={isEmpty}
          className="flex min-w-0 items-center gap-2 cursor-pointer disabled:cursor-default"
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
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (ign.trim()) onLoadPlayer(ign.trim());
        }}
        className="mb-3"
      >
        <p className="text-xs text-[#6b6b6b] mb-2">Find your pet by entering your IGN</p>
        <div className="relative">
          <input
            type="text"
            value={ign}
            onChange={(e) => onIgnChange(e.target.value)}
            placeholder="Turbine"
            maxLength={20}
            className="w-full rounded-lg bg-[#262626] border border-[#404040] pl-2.5 pr-8 py-1.5 text-base md:text-xs text-[#ececec] placeholder-[#525252] focus:outline-none focus:border-white"
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
      </form>

      <PetCompanion profile={playerProfile} loading={isLoadingPlayer} lookupError={ignError} />

      <button
        type="button"
        onClick={onHome}
        className="mt-3 flex-shrink-0 w-full flex items-center justify-center gap-1.5 rounded-lg bg-[#3a3a3a] border border-[#404040] px-2.5 py-2 text-sm md:text-xs text-[#ececec] hover:border-white transition-colors cursor-pointer"
        aria-label="New chat"
      >
        <PlusIcon />
        New chat
      </button>

      <div className="flex-1 overflow-y-auto min-h-0 -mx-1 px-1 mt-3">
        <p className="text-xs text-[#525252] mb-2 px-1">Chats</p>
        {sessions.length > 0 && (
          <ul className="space-y-1">
            {[...sessions]
              .sort((a, b) => b.updatedAt - a.updatedAt)
              .map((session) => (
                <li key={session.id} className="group relative">
                  <button
                    onClick={() => onLoadSession(session.id)}
                    className={`w-full text-left text-sm md:text-xs truncate rounded-lg pl-2.5 pr-8 py-2 md:py-1.5 transition-colors duration-150 cursor-pointer ${
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
                      onOpenSessionOptions(session.id);
                    }}
                    className="absolute right-1 top-1/2 -translate-y-1/2 w-7 h-7 md:w-5 md:h-5 flex items-center justify-center rounded text-[#737373] opacity-100 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100 hover:text-[#ececec] hover:bg-[#454545] transition-colors duration-150 cursor-pointer"
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
        )}
      </div>

      <div className="mt-3 flex-shrink-0">
        <div className="flex justify-center">
          <ChevronToggle
            expanded={showSuggestions}
            onToggle={onToggleSuggestions}
            hideLabel="Hide quick suggestions"
            showLabel="Show quick suggestions"
          />
        </div>
        {showSuggestions && (
          <div className="space-y-2 min-h-0 overflow-y-auto mt-1">
            {SIDEBAR_EXAMPLE_PROMPTS.map((config) => (
              <ExamplePrompt
                key={config.id}
                config={config}
                variant="sidebar"
                disabled={isStreaming}
                onSubmit={onSubmitPrompt}
              />
            ))}
          </div>
        )}
      </div>

      <div className="flex-shrink-0 pt-3 mt-3 border-t border-[#303030] space-y-2">
        <button
          type="button"
          onClick={onOpenFeedback}
          className="group w-full text-left px-2 py-1 -mx-2 rounded-lg hover:bg-[#333333] transition-colors cursor-pointer"
        >
          <span className="block text-sm text-[#a3a3a3] group-hover:text-[#ececec]">
            Feedback
          </span>
        </button>
        <button
          type="button"
          onClick={onOpenChangelog}
          className="relative group w-full text-left px-2 py-1.5 -mx-2 rounded-lg hover:bg-[#333333] transition-colors cursor-pointer md:hidden"
        >
          <span className="block text-sm text-[#a3a3a3] group-hover:text-[#ececec]">
            What&rsquo;s new
          </span>
          {unseenChangelog && (
            <span
              className="absolute top-2.5 right-2 h-1.5 w-1.5 rounded-full bg-white"
              aria-hidden="true"
            />
          )}
        </button>
        <QuestProgressMeter
          variant="sidebar"
          percent={questPercent}
          onClick={onOpenQuests}
        />
        <SidebarAccount pet={playerProfile?.top_pet} onRegister={onRegister} />
      </div>
    </div>
  );
}
