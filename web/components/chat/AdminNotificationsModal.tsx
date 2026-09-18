"use client";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import {
  fetchAdminNotifications,
  type AdminFeedItem,
  type AdminFeedKind,
  type AdminNotificationsFeed,
} from "@/lib/api";

interface Props {
  onClose: () => void;
}

type Filter = "all" | AdminFeedKind;

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "chat", label: "Messages" },
  { id: "feedback", label: "Feedback" },
  { id: "account", label: "Accounts" },
  { id: "subscription", label: "Stripe" },
];

const KIND_LABEL: Record<AdminFeedKind, string> = {
  chat: "Message",
  feedback: "Feedback",
  account: "Account",
  subscription: "Stripe",
};

const TIER_LABEL: Record<string, string> = {
  guest: "Guest",
  free: "Free",
  paid: "Pro",
};

function formatWhen(iso: string): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return iso || "";
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (sec < 45) return "just now";
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  if (sec < 86400 * 7) return `${Math.round(sec / 86400)}d ago`;
  return new Date(t).toLocaleString();
}

function formatUsd(value: number | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n) || n <= 0) return "$0";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function who(item: AdminFeedItem): string {
  return item.ign || item.email || "Unknown";
}

function FeedCard({ item }: { item: AdminFeedItem }) {
  if (item.kind === "chat") {
    return (
      <div className="rounded-xl border border-[#404040] bg-[#262626] px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-[#ececec]">
            {TIER_LABEL[item.tier || ""] || "Message"} · {formatUsd(item.cost_usd)}
          </p>
          <p className="text-xs text-[#737373] whitespace-nowrap">{formatWhen(item.created_at)}</p>
        </div>
        <p className="text-xs text-[#a3a3a3] mt-1 truncate">{who(item)}</p>
      </div>
    );
  }
  if (item.kind === "account") {
    return (
      <div className="rounded-xl border border-[#404040] bg-[#262626] px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-[#ececec]">New account</p>
          <p className="text-xs text-[#737373] whitespace-nowrap">{formatWhen(item.created_at)}</p>
        </div>
        <p className="text-xs text-[#a3a3a3] mt-1 truncate">
          {item.ign || "No IGN"} · {item.email || "No email"}
        </p>
      </div>
    );
  }
  if (item.kind === "subscription") {
    return (
      <div className="rounded-xl border border-[#404040] bg-[#262626] px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-[#ececec]">
            Stripe · {item.status || "unknown"}
          </p>
          <p className="text-xs text-[#737373] whitespace-nowrap">{formatWhen(item.created_at)}</p>
        </div>
        <p className="text-xs text-[#a3a3a3] mt-1 truncate">{item.email || "No email"}</p>
        {item.stripe_subscription_id ? (
          <p className="text-[11px] text-[#737373] mt-0.5 truncate">{item.stripe_subscription_id}</p>
        ) : null}
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-[#404040] bg-[#262626] px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-[#ececec]">
          Feedback · {item.rating || "unrated"}
        </p>
        <p className="text-xs text-[#737373] whitespace-nowrap">{formatWhen(item.created_at)}</p>
      </div>
      <p className="text-xs text-[#a3a3a3] mt-1 truncate">
        {item.ign || "Guest"} {item.email ? `· ${item.email}` : ""}
      </p>
      {item.what_works ? (
        <p className="text-xs text-[#ececec] mt-2">
          <span className="text-[#737373]">Works: </span>
          {item.what_works}
        </p>
      ) : null}
      {item.what_to_improve ? (
        <p className="text-xs text-[#ececec] mt-1">
          <span className="text-[#737373]">Improve: </span>
          {item.what_to_improve}
        </p>
      ) : null}
      {item.anything_else ? (
        <p className="text-xs text-[#ececec] mt-1">
          <span className="text-[#737373]">Else: </span>
          {item.anything_else}
        </p>
      ) : null}
      {item.mailto ? (
        <a
          href={item.mailto}
          className="mt-3 inline-flex w-full items-center justify-center rounded-lg border border-[#404040] bg-[#1a1a1a] py-2 text-xs font-medium text-[#ececec] hover:bg-[#333333] transition-colors"
        >
          Reply by email
        </a>
      ) : (
        <p className="text-xs text-[#737373] mt-2">No email on this feedback.</p>
      )}
    </div>
  );
}

/**
 * Admin-only feed. Overlay matches Billing/Paywall: fixed inset, dim
 * backdrop, rounded card. The API re-checks the role on every load.
 */
export function AdminNotificationsModal({ onClose }: Props) {
  const [feed, setFeed] = useState<AdminNotificationsFeed | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const next = await fetchAdminNotifications();
        if (!cancelled) setFeed(next);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load notifications");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const items = useMemo(() => {
    const all = feed?.items ?? [];
    if (filter === "all") return all;
    return all.filter((item) => item.kind === filter);
  }, [feed, filter]);

  const counts = useMemo(() => {
    const all = feed?.items ?? [];
    const byKind: Record<Filter, number> = {
      all: all.length,
      chat: 0,
      feedback: 0,
      account: 0,
      subscription: 0,
    };
    for (const item of all) {
      if (item.kind === "chat" || item.kind === "feedback" || item.kind === "account" || item.kind === "subscription") {
        byKind[item.kind] += 1;
      }
    }
    return byKind;
  }, [feed]);

  if (!mounted || typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="admin-notifications-title"
    >
      <div className="absolute inset-0 bg-black/60" onClick={onClose} aria-hidden="true" />
      <div className="relative z-10 w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-2xl border border-[#404040] bg-[#1e1e1e] p-6 shadow-2xl animate-fade-in">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 rounded p-1 text-[#737373] transition-colors hover:text-[#ececec] cursor-pointer"
          aria-label="Close"
        >
          ✕
        </button>

        <h2 id="admin-notifications-title" className="text-lg font-semibold text-[#ececec] mb-1">
          Admin notifications
        </h2>
        <p className="text-sm text-[#737373] mb-4">
          Feedback, new accounts, Stripe, and estimated Claude spend.
        </p>

        {feed && (
          <div className="rounded-xl border border-[#404040] bg-[#262626] px-4 py-3 mb-4">
            <p className="text-sm font-medium text-[#ececec]">Today&apos;s Claude spend</p>
            <p className="text-xs text-[#737373] mt-1">
              {formatUsd(feed.spend_today_usd)} of {formatUsd(feed.spend_budget_usd)} budget
            </p>
          </div>
        )}

        <div className="flex flex-wrap gap-1.5 mb-4">
          {FILTERS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setFilter(tab.id)}
              className={`rounded-full px-3 py-1 text-xs font-medium cursor-pointer transition-colors ${
                filter === tab.id
                  ? "bg-white text-[#1a1a1a]"
                  : "border border-[#404040] text-[#a3a3a3] hover:text-[#ececec]"
              }`}
            >
              {tab.label}
              {counts[tab.id] ? ` ${counts[tab.id]}` : ""}
            </button>
          ))}
        </div>

        {loading && <p className="text-sm text-[#a3a3a3]">Loading…</p>}
        {error && <p className="text-sm text-red-400">{error}</p>}

        {!loading && !error && items.length === 0 && (
          <p className="text-sm text-[#a3a3a3]">
            Nothing in {filter === "all" ? "the feed" : KIND_LABEL[filter].toLowerCase()} yet.
            Per-turn costs start after this ships. Feedback, accounts, and Stripe rows
            already in production still show up here.
          </p>
        )}

        <div className="space-y-2">
          {items.map((item, index) => (
            <FeedCard key={`${item.kind}-${item.created_at}-${index}`} item={item} />
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}
