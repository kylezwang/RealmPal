"use client";
import { useEffect, useState } from "react";
import {
  createCheckout,
  fetchBilling,
  fetchChatUsage,
  openBillingPortal,
  type BillingInfo,
  type ChatUsage,
  type OnDemandUsage,
} from "@/lib/api";
import { SpendingLimitModal } from "./SpendingLimitModal";

interface Props {
  onClose: () => void;
}

function usagePercent(used: number, limit: number): number {
  const safeLimit = Math.max(1, limit);
  return Math.min(100, Math.round((Math.max(0, used) / safeLimit) * 100));
}

function formatResetWait(seconds: number): string {
  if (seconds <= 0) return "soon";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function UsageProgressBar({
  label,
  percent,
  hint,
  barColor,
}: {
  label: string;
  percent: number;
  hint?: string;
  barColor: string;
}) {
  return (
    <div className="rounded-xl border border-[#404040] bg-[#262626] px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-[#ececec]">{label}</p>
        <p className="text-xs text-[#737373] whitespace-nowrap">{percent}% used</p>
      </div>
      <div className="mt-2.5 h-2 w-full rounded-full bg-[#1a1a1a] overflow-hidden">
        <div className={`h-full transition-all ${barColor}`} style={{ width: `${percent}%` }} />
      </div>
      {hint ? <p className="text-xs text-[#737373] mt-1.5">{hint}</p> : null}
    </div>
  );
}

/**
 * Billing popup: subscription status, usage % bar, and on-demand controls.
 * Opened from the account menu under Settings.
 */
export function BillingModal({ onClose }: Props) {
  const [billing, setBilling] = useState<BillingInfo | null>(null);
  const [usage, setUsage] = useState<ChatUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [portalLoading, setPortalLoading] = useState(false);
  const [showSpendLimit, setShowSpendLimit] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !showSpendLimit) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, showSpendLimit]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const chatUsage = await fetchChatUsage().catch(() => null);
        let billingInfo: BillingInfo | null = null;
        try {
          billingInfo = await fetchBilling();
        } catch {
          if (chatUsage) {
            billingInfo = {
              tier: chatUsage.tier === "paid" ? "paid" : "free",
              plan_name: chatUsage.tier === "paid" ? "RealmPal Pro" : "Free",
              plan_price_usd: chatUsage.tier === "paid" ? 7 : 0,
              claude_used_percent:
                chatUsage.tier === "paid"
                  ? usagePercent(chatUsage.claude_used ?? 0, chatUsage.claude_limit ?? 1)
                  : null,
              spend_cap_usd: chatUsage.spend_cap_usd ?? 0,
              on_demand_spent_usd: chatUsage.on_demand_spent_usd ?? 0,
              overage_usd: 0.08,
              allowed_caps_usd: [0, 20, 50, 100],
            };
          }
        }
        if (!cancelled) {
          setBilling(billingInfo);
          setUsage(chatUsage);
          if (!billingInfo) setError("Could not load billing");
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load billing");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function applyOnDemandSaved(saved: OnDemandUsage) {
    setBilling((prev) =>
      prev
        ? {
            ...prev,
            spend_cap_usd: saved.spend_cap_usd,
            claude_used_percent: usagePercent(saved.claude_used, saved.claude_limit),
            on_demand_spent_usd: saved.on_demand_spent_usd,
            allowed_caps_usd: saved.allowed_caps_usd,
            overage_usd: saved.overage_usd,
          }
        : prev,
    );
  }

  async function handleUpgrade() {
    setCheckoutLoading(true);
    setError(null);
    try {
      const url = await createCheckout();
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start checkout");
      setCheckoutLoading(false);
    }
  }

  async function handleManageSubscription() {
    setPortalLoading(true);
    setError(null);
    try {
      const url = await openBillingPortal();
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not open billing portal");
      setPortalLoading(false);
    }
  }

  const isPaid = billing?.tier === "paid";
  const monthlyPercent = billing?.claude_used_percent ?? 0;
  const freePercent = usage ? usagePercent(usage.used, usage.limit) : 0;
  const displayPercent = isPaid ? monthlyPercent : freePercent;
  const exhausted = isPaid ? monthlyPercent >= 100 : (usage?.remaining ?? 1) <= 0;
  const onDemandActive = isPaid && exhausted && (billing?.spend_cap_usd ?? 0) > 0;
  const barColor = onDemandActive
    ? "bg-amber-400"
    : exhausted
      ? "bg-red-400"
      : "bg-white";

  const usageHint = isPaid
    ? exhausted
      ? onDemandActive
        ? "Included plan used. Extra usage bills on demand."
        : "Included plan used. Set a spending limit to keep going."
      : "Stored wiki and build answers never count toward this."
    : undefined;

  return (
    <>
      <div
        className="fixed inset-0 z-50 flex items-center justify-center p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="billing-title"
      >
        <div className="absolute inset-0 bg-black/30" onClick={onClose} aria-hidden="true" />
        <div className="relative z-10 w-full max-w-sm max-h-[85vh] overflow-y-auto rounded-2xl border border-[#404040] bg-[#1e1e1e] p-6 shadow-2xl animate-fade-in">
          <button
            type="button"
            onClick={onClose}
            className="absolute top-4 right-4 rounded p-1 text-[#737373] transition-colors hover:text-[#ececec] cursor-pointer"
            aria-label="Close"
          >
            ✕
          </button>

          <h2 id="billing-title" className="text-lg font-semibold text-[#ececec] mb-1">
            Billing
          </h2>
          <p className="text-sm text-[#737373] mb-5">Plan, usage, and payment.</p>

          {loading && <p className="text-sm text-[#a3a3a3]">Loading…</p>}

          {!loading && billing && (
            <div className="space-y-4">
              <UsageProgressBar
                label={isPaid ? "Usage this month" : "Daily messages"}
                percent={displayPercent}
                hint={usageHint}
                barColor={barColor}
              />

              {isPaid && (
                <div className="rounded-xl border border-[#404040] bg-[#262626] px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-[#ececec]">{billing.plan_name}</p>
                    <p className="text-xs text-[#737373] whitespace-nowrap">
                      ${billing.plan_price_usd.toFixed(0)}/mo
                    </p>
                  </div>
                  <p className="text-xs text-[#737373] mt-1">
                    Subscription{" "}
                    <span className="text-[#ececec] capitalize">
                      {billing.subscription_status === "active"
                        ? "active"
                        : billing.subscription_status ?? "active"}
                    </span>
                    . Billed through Stripe.
                  </p>
                  <button
                    type="button"
                    disabled={portalLoading}
                    onClick={() => void handleManageSubscription()}
                    className="mt-3 w-full rounded-lg border border-[#404040] bg-[#1a1a1a] py-2 text-xs font-medium text-[#ececec] hover:bg-[#333333] transition-colors cursor-pointer disabled:opacity-60"
                  >
                    {portalLoading ? "Opening..." : "Manage subscription or cancel"}
                  </button>
                </div>
              )}

              {!isPaid && (
                <div className="rounded-xl border border-[#404040] bg-[#262626] px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-[#ececec]">Free</p>
                    <p className="text-xs text-[#737373] whitespace-nowrap">$0/mo</p>
                  </div>
                  <p className="text-xs text-[#737373] mt-1">
                    {usage
                      ? `${usage.remaining} free message${usage.remaining === 1 ? "" : "s"} left today`
                      : "Limited daily messages"}
                    {usage?.resets_in_seconds ? (
                      <>
                        {" · refreshes in "}
                        <span className="text-[#D4AF37]">
                          {formatResetWait(usage.resets_in_seconds)}
                        </span>
                      </>
                    ) : null}
                    .
                  </p>
                </div>
              )}

              {isPaid && (
                <div className="rounded-xl border border-[#404040] bg-[#262626] px-4 py-3">
                  <p className="text-sm font-medium text-[#ececec]">Pay-as-you-go</p>
                  <p className="text-xs text-[#737373] mt-0.5 mb-3">
                    7x AI usage included. Afterwards, pay as you go.
                    {(billing.on_demand_spent_usd ?? 0) > 0 && (
                      <>
                        {" "}
                        <span className="text-[#ececec]">
                          ${billing.on_demand_spent_usd?.toFixed(2)} spent so far.
                        </span>
                      </>
                    )}
                    {(billing.spend_cap_usd ?? 0) > 0 && (
                      <>
                        {" "}
                        <span className="text-[#ececec]">
                          ${billing.spend_cap_usd?.toFixed(0)} cap active.
                        </span>
                      </>
                    )}
                  </p>
                  <button
                    type="button"
                    onClick={() => setShowSpendLimit(true)}
                    className="w-full rounded-lg border border-[#404040] bg-[#1a1a1a] py-2.5 text-sm font-medium text-[#ececec] hover:bg-[#333333] transition-colors cursor-pointer"
                  >
                    {exhausted && !onDemandActive ? "Set a new limit" : "Manage spending limit"}
                  </button>
                </div>
              )}

              {!isPaid && (
                <button
                  type="button"
                  disabled={checkoutLoading}
                  onClick={() => void handleUpgrade()}
                  className="w-full rounded-lg bg-white py-2.5 text-sm font-semibold text-[#1a1a1a] transition-colors hover:bg-[#e5e5e5] cursor-pointer disabled:opacity-60"
                >
                  {checkoutLoading
                    ? "Opening checkout…"
                    : `Upgrade to Pro, $${billing.plan_price_usd.toFixed(0)}/mo`}
                </button>
              )}
            </div>
          )}

          {error && <p className="text-sm text-red-400 mt-3">{error}</p>}

          <button
            type="button"
            onClick={onClose}
            className="mt-6 w-full rounded-lg border border-[#404040] py-2.5 text-sm font-medium text-[#ececec] hover:bg-[#262626] transition-colors cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>

      {showSpendLimit && billing && isPaid && (
        <SpendingLimitModal
          currentCap={billing.spend_cap_usd ?? 0}
          spentSoFar={billing.on_demand_spent_usd ?? 0}
          overageUsd={billing.overage_usd ?? 0.08}
          exhausted={exhausted}
          onClose={() => setShowSpendLimit(false)}
          onSaved={applyOnDemandSaved}
        />
      )}
    </>
  );
}
