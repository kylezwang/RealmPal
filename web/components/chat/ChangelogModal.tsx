"use client";
import { useEffect, useMemo, useState } from "react";
import { CHANGELOG, markChangelogSeen, type ChangelogEntry } from "@/lib/changelog";

interface Props {
  onClose: () => void;
}

const PREVIEW_COUNT = 3;

/** "10:49 AM PT" from an ISO timestamp. Pacific to match the rest of the
 * app's time references (e.g. the daily reset time). */
function formatEntryTime(iso: string): string {
  try {
    const formatted = new Date(iso).toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      timeZone: "America/Los_Angeles",
    });
    return `${formatted} PT`;
  } catch {
    return "";
  }
}

/** Groups already-sorted (newest-first) entries by their display date, so
 * same-day releases (e.g. "-2") sit under one date marker in the timeline. */
function groupByDate(entries: ChangelogEntry[]): { date: string; entries: ChangelogEntry[] }[] {
  const groups: { date: string; entries: ChangelogEntry[] }[] = [];
  for (const entry of entries) {
    const last = groups[groups.length - 1];
    if (last && last.date === entry.date) {
      last.entries.push(entry);
    } else {
      groups.push({ date: entry.date, entries: [entry] });
    }
  }
  return groups;
}

function ItemBullets({ items }: { items: string[] }) {
  return (
    <ul className="space-y-1.5">
      {items.map((item) => (
        <li key={item} className="flex gap-2 text-sm text-[#a3a3a3] leading-relaxed">
          <span className="text-[#ececec]" aria-hidden="true">
            •
          </span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

/** Collapsed (initial popup) view: just the latest entry's date + first few items. */
function PreviewView({ entry, items }: { entry: ChangelogEntry; items: string[] }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-[#737373] mb-1.5">
        {entry.date}
      </p>
      <ItemBullets items={items} />
    </div>
  );
}

/** Expanded view: a real timeline, one marker per calendar day, with a
 * version badge (+ real ship time, when known) for each release under it. */
function TimelineView({ entries }: { entries: ChangelogEntry[] }) {
  const groups = useMemo(() => groupByDate(entries), [entries]);
  return (
    <div className="relative space-y-6 border-l border-[#333333] pl-4">
      {groups.map((group) => {
        const isPhase = group.entries.some((entry) => entry.phase);
        return (
        <div
          key={group.date}
          className={`relative ${isPhase ? "border-t border-[#404040] pt-6 mt-2" : ""}`}
        >
          <span
            className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-white ring-4 ring-[#1e1e1e]"
            aria-hidden="true"
          />
          <p
            className={`mb-3 text-sm font-semibold ${
              isPhase ? "text-[#a3a3a3]" : "text-[#ececec]"
            }`}
          >
            {group.date}
          </p>
          <div className="space-y-4">
            {group.entries.map((entry, i) => (
              <div
                key={entry.version}
                className={i > 0 ? "border-t border-[#2a2a2a] pt-4" : undefined}
              >
                {!entry.phase && (
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="rounded border border-[#333333] bg-[#262626] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[#737373]">
                      {entry.version}
                    </span>
                    {entry.timestamp && (
                      <span className="text-[10px] text-[#525252]">
                        {formatEntryTime(entry.timestamp)}
                      </span>
                    )}
                  </div>
                )}
                <ItemBullets items={entry.items} />
              </div>
            ))}
          </div>
        </div>
        );
      })}
    </div>
  );
}

/**
 * "What's new" popup. Lists recent user-facing updates, newest first.
 * Starts collapsed at a fixed width; "See more" expands into a wider,
 * timestamped timeline of every release grouped by day.
 */
export function ChangelogModal({ onClose }: Props) {
  const [expanded, setExpanded] = useState(false);
  const latest = CHANGELOG[0];
  const previewItems = latest?.items.slice(0, PREVIEW_COUNT) ?? [];
  const hasMore =
    Boolean(latest && latest.items.length > PREVIEW_COUNT) || CHANGELOG.length > 1;

  useEffect(() => {
    markChangelogSeen();
  }, []);

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
      aria-labelledby="changelog-title"
    >
      <div
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className={`relative z-10 w-full max-h-[80vh] overflow-y-auto rounded-2xl border border-[#404040] bg-[#1e1e1e] p-6 shadow-2xl animate-fade-in transition-[max-width] duration-200 ${
          expanded ? "max-w-lg sm:max-w-2xl" : "max-w-sm"
        }`}
      >
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 rounded p-1 text-[#737373] transition-colors hover:text-[#ececec] cursor-pointer"
          aria-label="Close"
        >
          ✕
        </button>

        <h2 id="changelog-title" className="text-lg font-semibold text-[#ececec] mb-1">
          What&rsquo;s new
        </h2>
        <p className="text-sm text-[#737373] mb-5">Recent updates, newest first.</p>

        {expanded ? (
          <TimelineView entries={CHANGELOG} />
        ) : (
          latest && <PreviewView entry={latest} items={previewItems} />
        )}

        {hasMore && !expanded && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="mt-4 text-sm font-medium text-[#ececec] hover:underline cursor-pointer"
          >
            See more
          </button>
        )}

        <button
          type="button"
          onClick={onClose}
          className="mt-6 w-full rounded-lg bg-white py-2.5 text-sm font-semibold text-[#1a1a1a] transition-colors hover:bg-[#e5e5e5] cursor-pointer"
        >
          Got it
        </button>
      </div>
    </div>
  );
}
