"use client";

/**
 * Quest progress indicator for the chat chrome (header + sidebar).
 * Shows percent complete only — no exact counts, no billing link.
 * Paid-tier pool data is a temporary stand-in until the quest system ships.
 */
interface Props {
  percent: number;
  variant?: "sidebar" | "header";
  onClick?: () => void;
}

export function questProgressPercent(used: number, limit: number): number {
  const safeLimit = Math.max(1, limit);
  return Math.min(100, Math.round((Math.max(0, used) / safeLimit) * 100));
}

export function QuestProgressMeter({ percent, variant = "sidebar", onClick }: Props) {
  const label = `${percent}% complete`;
  const className =
    variant === "header"
      ? "flex flex-col items-stretch gap-1 cursor-pointer group"
      : "group w-full text-left px-2 py-1.5 -mx-2 rounded-lg hover:bg-[#333333] transition-colors cursor-pointer";

  return (
    <button
      type="button"
      onClick={onClick}
      className={className}
      aria-label={`Daily quests: ${label}`}
    >
      <span
        className={
          variant === "header"
            ? "text-sm text-[#a3a3a3] group-hover:text-[#ececec] whitespace-nowrap"
            : "block text-sm text-[#a3a3a3] group-hover:text-[#ececec]"
        }
      >
        {variant === "header" ? "Quests" : "Daily quests"}
      </span>
      <div
        className={
          variant === "header"
            ? "flex items-center gap-1.5"
            : "mt-1.5 h-1.5 w-full rounded-full bg-[#404040] overflow-hidden"
        }
      >
        {variant === "header" ? (
          <>
            <div className="h-1.5 flex-1 min-w-[3rem] rounded-full bg-[#404040] overflow-hidden">
              <div className="h-full bg-white transition-all" style={{ width: `${percent}%` }} />
            </div>
            <span className="text-xs leading-none text-[#737373] group-hover:text-[#a3a3a3] tabular-nums">
              {percent}%
            </span>
          </>
        ) : (
          <div className="h-full bg-white transition-all" style={{ width: `${percent}%` }} />
        )}
      </div>
      {variant === "sidebar" && (
        <span className="block text-xs leading-tight text-[#737373] group-hover:text-[#a3a3a3] mt-0.5">
          {label}
        </span>
      )}
    </button>
  );
}
