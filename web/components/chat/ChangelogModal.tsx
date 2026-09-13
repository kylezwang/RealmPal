"use client";
import { useEffect, useState } from "react";
import { CHANGELOG, markChangelogSeen, type ChangelogEntry } from "@/lib/changelog";

interface Props {
  onClose: () => void;
}

const PREVIEW_COUNT = 3;

function EntryList({ entry, items }: { entry: ChangelogEntry; items: string[] }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-[#737373] mb-1.5">
        {entry.date}
      </p>
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
    </div>
  );
}

/**
 * "What's new" popup. Lists recent user-facing updates, newest first.
 * Starts collapsed; "See more" reveals the rest.
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
      <div className="relative z-10 w-full max-w-sm max-h-[80vh] overflow-y-auto rounded-2xl border border-[#404040] bg-[#1e1e1e] p-6 shadow-2xl animate-fade-in">
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

        <div className="space-y-5">
          {latest && (
            <EntryList
              entry={latest}
              items={expanded ? latest.items : previewItems}
            />
          )}
          {expanded &&
            CHANGELOG.slice(1).map((entry) => (
              <EntryList key={entry.version} entry={entry} items={entry.items} />
            ))}
        </div>

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
