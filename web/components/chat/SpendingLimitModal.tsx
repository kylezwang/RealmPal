"use client";
import { useEffect, useState } from "react";
import { saveOnDemand, type OnDemandUsage } from "@/lib/api";

const PRESET_CAPS = [20, 50, 100] as const;

interface Props {
  currentCap: number;
  spentSoFar?: number;
  overageUsd?: number;
  exhausted?: boolean;
  onClose: () => void;
  onSaved: (saved: OnDemandUsage) => void;
}

/**
 * Pay-as-you-go spending limit picker. Opens from Billing when included
 * Claude replies are used up, or anytime a Pro user wants to change their cap.
 */
export function SpendingLimitModal({
  currentCap,
  spentSoFar = 0,
  overageUsd = 0.08,
  exhausted = false,
  onClose,
  onSaved,
}: Props) {
  const [selected, setSelected] = useState<number | "custom">(
    PRESET_CAPS.includes(currentCap as (typeof PRESET_CAPS)[number])
      ? currentCap
      : currentCap > 0
        ? "custom"
        : PRESET_CAPS[0],
  );
  const [customValue, setCustomValue] = useState(
    currentCap > 0 && !PRESET_CAPS.includes(currentCap as (typeof PRESET_CAPS)[number])
      ? String(currentCap)
      : "",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function resolveCap(): number | null {
    if (selected === "custom") {
      const parsed = Number(customValue);
      if (!Number.isFinite(parsed) || parsed < 1 || parsed > 200) {
        return null;
      }
      return Math.round(parsed * 100) / 100;
    }
    return selected;
  }

  async function handleSave() {
    const cap = resolveCap();
    if (cap == null) {
      setError("Enter a custom amount between $1 and $200");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const saved = await saveOnDemand(cap);
      onSaved(saved);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save spending limit");
    } finally {
      setSaving(false);
    }
  }

  async function handleStop() {
    setSaving(true);
    setError(null);
    try {
      const saved = await saveOnDemand(0);
      onSaved(saved);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save spending limit");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="spending-limit-title"
    >
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden="true" />
      <div className="relative z-10 w-full max-w-sm rounded-2xl border border-[#404040] bg-[#1e1e1e] p-6 shadow-2xl animate-fade-in">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 rounded p-1 text-[#737373] transition-colors hover:text-[#ececec] cursor-pointer"
          aria-label="Close"
        >
          ✕
        </button>

        <h2 id="spending-limit-title" className="text-lg font-semibold text-[#ececec] mb-1">
          Spending limit
        </h2>
        <p className="text-sm text-[#737373] mb-4">
          {exhausted
            ? "Your included replies are used up. Set a monthly cap to keep going on pay-as-you-go."
            : "Choose how much extra usage to allow each month after your included pool."}
          {" "}
          
        </p>

        {spentSoFar > 0 && (
          <p className="text-xs text-[#a3a3a3] mb-4">
            ${spentSoFar.toFixed(2)} spent on extra usage this month
            {currentCap > 0 ? ` · $${currentCap.toFixed(0)} cap` : ""}.
          </p>
        )}

        <div className="flex flex-wrap gap-2 mb-4">
          {PRESET_CAPS.map((cap) => (
            <button
              key={cap}
              type="button"
              disabled={saving}
              onClick={() => {
                setSelected(cap);
                setError(null);
              }}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors cursor-pointer disabled:opacity-60 ${
                selected === cap
                  ? "bg-white text-[#1a1a1a]"
                  : "bg-[#262626] text-[#a3a3a3] border border-[#404040] hover:text-[#ececec]"
              }`}
            >
              ${cap}
            </button>
          ))}
          <button
            type="button"
            disabled={saving}
            onClick={() => {
              setSelected("custom");
              setError(null);
            }}
            className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors cursor-pointer disabled:opacity-60 ${
              selected === "custom"
                ? "bg-white text-[#1a1a1a]"
                : "bg-[#262626] text-[#a3a3a3] border border-[#404040] hover:text-[#ececec]"
            }`}
          >
            Custom
          </button>
        </div>

        {selected === "custom" && (
          <label className="block mb-4">
            <span className="text-xs text-[#737373]">Custom monthly cap (USD)</span>
            <div className="mt-1.5 flex items-center gap-2">
              <span className="text-sm text-[#a3a3a3]">$</span>
              <input
                type="number"
                min={1}
                max={200}
                step={1}
                value={customValue}
                onChange={(e) => setCustomValue(e.target.value)}
                placeholder="75"
                className="w-full rounded-lg border border-[#404040] bg-[#262626] px-3 py-2 text-sm text-[#ececec] outline-none focus:border-[#737373]"
              />
            </div>
          </label>
        )}

        {error && <p className="text-sm text-red-400 mb-3">{error}</p>}

        <button
          type="button"
          disabled={saving}
          onClick={() => void handleSave()}
          className="w-full rounded-lg bg-white py-2.5 text-sm font-semibold text-[#1a1a1a] transition-colors hover:bg-[#e5e5e5] cursor-pointer disabled:opacity-60"
        >
          {saving ? "Saving…" : "Save spending limit"}
        </button>

        {currentCap > 0 && (
          <button
            type="button"
            disabled={saving}
            onClick={() => void handleStop()}
            className="mt-3 w-full rounded-lg border border-[#404040] py-2.5 text-sm font-medium text-[#a3a3a3] hover:text-[#ececec] hover:bg-[#262626] transition-colors cursor-pointer disabled:opacity-60"
          >
            Stop extra usage ($0 cap)
          </button>
        )}
      </div>
    </div>
  );
}
