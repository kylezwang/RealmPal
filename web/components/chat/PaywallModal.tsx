"use client";
import { useState } from "react";
import Image from "next/image";
import { createCheckout, type PlayerProfile } from "@/lib/api";
import { SWORD_SPRITE } from "@/lib/sprites";
import { PetSprite } from "./PetCompanion";

function freeMessagesHeading(remaining: number | null, limit: number): string {
  if (remaining == null) return "Upgrade to RealmPal Pro";
  if (remaining <= 0) return `You've used your ${limit} free messages`;
  if (remaining === 1) return "You have 1 free message left";
  return `You have ${remaining} free messages left`;
}

interface Props {
  checkoutUrl?: string;
  remaining?: number | null;
  limit?: number;
  pet?: PlayerProfile["top_pet"];
  onClose: () => void;
}

/**
 * Claude-inspired upgrade modal.
 * Dark overlay, clean card, single CTA.
 * Appears after 3 free messages.
 */
export function PaywallModal({ checkoutUrl, remaining = 0, limit = 3, pet, onClose }: Props) {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleUpgrade() {
    if (!email.trim() || !email.includes("@")) {
      setError("Please enter a valid email address");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const url = checkoutUrl ?? (await createCheckout(email));
      window.location.href = url;
    } catch (e) {
      setError("Couldn't start checkout. Try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="paywall-title"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Card */}
      <div className="relative z-10 w-full max-w-sm rounded-2xl bg-[#1e1e1e] border border-[#404040] p-6 shadow-2xl animate-slide-up">
        {/* Close */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-[#737373] hover:text-[#ececec] transition-colors p-1 rounded"
          aria-label="Close"
        >
          ✕
        </button>

        {/* Icon | guest IGN pet replaces the default sword */}
        <div className="flex justify-center mb-4">
          <div className="w-12 h-12 rounded-xl bg-white/10 border border-white/30 flex items-center justify-center">
            {pet ? (
              <PetSprite pet={pet} size={32} />
            ) : (
              <Image src={SWORD_SPRITE} alt="RealmPal" width={28} height={28} style={{ imageRendering: "pixelated" }} unoptimized />
            )}
          </div>
        </div>

        {/* Heading */}
        <h2 id="paywall-title" className="text-center text-lg font-semibold text-[#ececec] mb-1">
          {freeMessagesHeading(remaining, limit)}
        </h2>
        <p className="text-center text-sm text-[#a3a3a3] mb-6">
          Upgrade to RealmPal Pro to support the project and continue | Hosting and AI costs are expensive, your support helps keep the project alive.
        </p>

        {/* Price */}
        <div className="flex items-center justify-center gap-2 mb-6">
          <span className="text-3xl font-bold text-[#ececec]">$7</span>
          <span className="text-[#737373] text-sm">/month</span>
        </div>

        {/* Feature list */}
        <ul className="space-y-2 mb-6 text-sm text-[#a3a3a3]">
          {[
            "All RotMG questions",
            "Set-building AI for DPS",
            "Skin customization preview (Cloths and Dyes)",
            "Account & character details",
            "Item/Dungeon guides",
          ].map((f) => (
            <li key={f} className="flex items-center gap-2">
              <span className="text-white text-xs">✓</span>
              {f}
            </li>
          ))}
        </ul>

        {/* Email input */}
        <input
          type="email"
          placeholder="your@email.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleUpgrade()}
          className="w-full rounded-lg bg-[#262626] border border-[#404040] px-3 py-2.5 text-sm text-[#ececec] placeholder-[#525252] focus:outline-none focus:border-white transition-colors mb-3"
          aria-label="Email address for account"
        />

        {error && <p className="text-red-400 text-xs mb-3">{error}</p>}

        {/* CTA */}
        <button
          onClick={handleUpgrade}
          disabled={loading}
          className="w-full rounded-lg bg-white hover:bg-[#e5e5e5] disabled:opacity-50 disabled:cursor-not-allowed text-[#1a1a1a] font-semibold py-2.5 text-sm transition-colors"
        >
          {loading ? "Redirecting to checkout..." : "Upgrade for $7/month"}
        </button>

        <p className="text-center text-xs text-[#525252] mt-3">
          Secure checkout via Stripe. Cancel anytime.
        </p>
      </div>
    </div>
  );
}
