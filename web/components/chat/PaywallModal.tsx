"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  createCheckout,
  decodeAuthEmail,
  registerAccount,
  type OnDemandUsage,
  type PaywallReason,
  type PlayerProfile,
} from "@/lib/api";
import { loadSavedAccountProfile, saveSavedAccountProfile } from "@/lib/accountProfile";
import { SWORD_SPRITE } from "@/lib/sprites";
import { PetSprite } from "./PetCompanion";
import { SpendingLimitModal } from "./SpendingLimitModal";
import {
  freeInDepthPromptsHaveLeft,
  freeInDepthPromptsStillLeftToday,
  freeInDepthPromptsUsed,
} from "@/lib/usageCopy";

/** Extra free in-depth responses a guest gets by creating an account. */
export const ACCOUNT_BONUS_MESSAGES = 2;

const LAST_STEP = 2;
const REMINDER_STEP = 3;
const MIN_PASSWORD_LENGTH = 8;

export const PAYWALL_SET_BUILDING_DEMO = "/videos/paywall/set-building-demo.mp4";
export const PAYWALL_VISUALIZER_DEMO = "/videos/paywall/visualizer.mp4";

function formatResetWait(seconds: number): string {
  if (seconds <= 0) return "soon";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours >= 2) return `about ${hours} hours`;
  if (hours === 1) {
    return minutes >= 20 ? "about an hour and a half" : "about an hour";
  }
  if (minutes >= 2) return `about ${minutes} minutes`;
  return "a few minutes";
}

const fieldClass =
  "w-full rounded-lg border border-[#404040] bg-[#262626] px-3 py-2.5 text-sm text-[#ececec] placeholder-[#525252] focus:outline-none focus:border-white transition-colors";

type CheckTone = "gray" | "red" | "yellow" | "green";

function passwordTone(value: string): CheckTone {
  if (!value) return "gray";
  if (value.length >= MIN_PASSWORD_LENGTH) return "green";
  if (value.length >= 4) return "yellow";
  return "red";
}

function confirmTone(password: string, confirm: string): CheckTone {
  if (!confirm) return "gray";
  if (password === confirm && passwordTone(password) === "green") return "green";
  if (password.startsWith(confirm) || confirm.startsWith(password)) return "yellow";
  return "red";
}

const checkToneClass: Record<CheckTone, string> = {
  gray: "border-[#525252] text-[#525252]",
  red: "border-red-400 text-red-400",
  yellow: "border-yellow-400 text-yellow-400",
  green: "border-green-400 text-green-400",
};

function CheckCircle({ tone }: { tone: CheckTone }) {
  return (
    <span
      className={`flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full border-2 transition-colors ${checkToneClass[tone]}`}
      aria-hidden="true"
    >
      <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3.5 8.5 6.5 11.5 12.5 4.5" />
      </svg>
    </span>
  );
}

function PasswordField({
  value,
  onChange,
  placeholder,
  autoComplete,
  ariaLabel,
  tone,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  autoComplete: string;
  ariaLabel: string;
  tone: CheckTone;
}) {
  return (
    <div className="relative">
      <input
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        className={`${fieldClass} pr-11`}
        aria-label={ariaLabel}
      />
      <div className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2">
        <CheckCircle tone={tone} />
      </div>
    </div>
  );
}

function freeMessagesHeading(remaining: number | null, limit: number): string {
  if (remaining == null) return "Upgrade to RealmPal Pro";
  if (remaining <= 0) return freeInDepthPromptsUsed(limit);
  return freeInDepthPromptsHaveLeft(remaining);
}

function CheckRow({
  checked,
  onChange,
  children,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="w-full flex items-center gap-2.5 text-left cursor-pointer"
    >
      <span
        className={`flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-md border transition-colors ${
          checked
            ? "border-white bg-white text-[#1a1a1a]"
            : "border-[#525252] bg-[#262626] text-transparent"
        }`}
        aria-hidden="true"
      >
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3.5 8.5 6.5 11.5 12.5 4.5" />
        </svg>
      </span>
      <span className="text-xs text-[#a3a3a3] leading-5">{children}</span>
    </button>
  );
}

interface Props {
  checkoutUrl?: string;
  remaining?: number | null;
  limit?: number;
  pet?: PlayerProfile["top_pet"];
  onClose: () => void;
  /** Guests end on create-account. Signed-in free users end on Pro. */
  signedIn?: boolean;
  reason?: PaywallReason;
  /** Prefill the signup IGN from the sidebar lookup. */
  defaultIgn?: string;
  onUsageEnabled?: () => void;
  spendCapUsd?: number;
  onDemandSpentUsd?: number;
  resetsInSeconds?: number;
  /** Optional MP4/WebM URLs once demos are recorded. Empty = placeholder. */
  setBuildingDemoSrc?: string;
  visualizerDemoSrc?: string;
}

function PaywallDemoVideo({
  src,
  label,
  videoRef,
  onEnded,
}: {
  src: string;
  label: string;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  onEnded: () => void;
}) {
  return (
    <div className="relative w-full overflow-hidden rounded-xl border border-[#404040] bg-black h-[min(46vh,460px)] sm:h-[min(48vh,480px)]">
      <video
        ref={videoRef}
        className="absolute inset-0 h-full w-full object-cover"
        controls
        playsInline
        muted
        preload="metadata"
        aria-label={label}
        onEnded={onEnded}
      >
        <source src={src} type="video/mp4" />
      </video>
    </div>
  );
}

function VideoPlaceholder({
  src,
  label,
  videoRef,
  onEnded,
}: {
  src?: string;
  label: string;
  videoRef?: React.RefObject<HTMLVideoElement | null>;
  onEnded?: () => void;
}) {
  if (src && videoRef && onEnded) {
    return (
      <PaywallDemoVideo
        src={src}
        label={label}
        videoRef={videoRef}
        onEnded={onEnded}
      />
    );
  }

  return (
    <div
      className="relative flex aspect-video w-full flex-col items-center justify-center gap-2 overflow-hidden rounded-xl border border-dashed border-[#525252] bg-[#141414]"
      role="img"
      aria-label={`${label}: demo video coming soon`}
    >
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          background:
            "radial-gradient(ellipse at 30% 20%, rgba(255,255,255,0.08), transparent 55%), radial-gradient(ellipse at 80% 90%, rgba(255,255,255,0.04), transparent 50%)",
        }}
      />
      <div className="relative flex h-12 w-12 items-center justify-center rounded-full border border-[#525252] bg-white/5">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className="text-[#ececec] ml-0.5">
          <path d="M8 5v14l11-7z" />
        </svg>
      </div>
      <p className="relative text-sm font-medium text-[#ececec]">Demo coming soon</p>
      <p className="relative text-xs text-[#737373]">Drop a recording here later</p>
    </div>
  );
}

function StepDots({ step, total, onJump }: { step: number; total: number; onJump: (i: number) => void }) {
  return (
    <div className="flex items-center justify-center gap-1.5" role="tablist" aria-label="Paywall steps">
      {Array.from({ length: total }, (_, i) => (
        <button
          key={i}
          type="button"
          role="tab"
          aria-selected={i === step}
          aria-label={`Step ${i + 1} of ${total}`}
          onClick={() => onJump(i)}
          className={`h-1.5 rounded-full transition-all ${
            i === step ? "w-5 bg-white" : "w-1.5 bg-[#525252] hover:bg-[#737373]"
          }`}
        />
      ))}
    </div>
  );
}

/**
 * Two value slides, then the last slide swaps:
 * guests get the full register form, signed-in users get Pro pricing.
 */
export function PaywallModal({
  checkoutUrl,
  remaining = 0,
  limit = 3,
  pet,
  onClose,
  signedIn = false,
  reason = "free_quota",
  defaultIgn = "",
  onUsageEnabled,
  spendCapUsd = 0,
  onDemandSpentUsd = 0,
  resetsInSeconds = 0,
  setBuildingDemoSrc = PAYWALL_SET_BUILDING_DEMO,
  visualizerDemoSrc = PAYWALL_VISUALIZER_DEMO,
}: Props) {
  const isOnDemand = reason === "claude_pool" || reason === "spend_cap";
  const startOnSignup = reason === "create_account";
  const [step, setStep] = useState(isOnDemand || startOnSignup ? LAST_STEP : 0);
  const setBuildingRef = useRef<HTMLVideoElement>(null);
  const visualizerRef = useRef<HTMLVideoElement>(null);
  const [setBuildingDone, setSetBuildingDone] = useState(false);
  const [visualizerDone, setVisualizerDone] = useState(false);
  const [ign, setIgn] = useState(
    () => defaultIgn.trim() || loadSavedAccountProfile()?.ign || "",
  );
  const [email, setEmail] = useState(() => decodeAuthEmail() ?? "");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSpendLimit, setShowSpendLimit] = useState(false);

  const goNext = useCallback(() => {
    setStep((s) => Math.min(LAST_STEP, s + 1));
    setError(null);
  }, []);

  const goBack = useCallback(() => {
    setStep((s) => Math.max(0, s - 1));
    setError(null);
  }, []);

  const isLast = step === LAST_STEP;
  const isReminder = step === REMINDER_STEP;
  const isVideoSlide = step === 0 || step === 1;
  const isSignup = isLast && !signedIn && !isOnDemand;
  const isPricing = isLast && signedIn && !isOnDemand;

  const leavePricing = useCallback(() => {
    setStep(REMINDER_STEP);
    setError(null);
  }, []);

  useEffect(() => {
    if (isOnDemand || isReminder) return;

    const first = setBuildingRef.current;
    const second = visualizerRef.current;

    if (step === 0) {
      second?.pause();
      if (first && !setBuildingDone) {
        void first.play().catch(() => {});
      }
      return;
    }

    if (step === 1) {
      if (first && !setBuildingDone) {
        first.pause();
      }
      if (second && !visualizerDone) {
        void second.play().catch(() => {});
      }
      return;
    }

    first?.pause();
    second?.pause();
  }, [step, setBuildingDone, visualizerDone, isOnDemand, isReminder]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        if (isPricing) {
          leavePricing();
          return;
        }
        if (isLast || isReminder) onClose();
      }
      if (e.key === "ArrowRight" && !isReminder) goNext();
      if (e.key === "ArrowLeft" && !isReminder) goBack();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isLast, isPricing, isReminder, goNext, goBack, leavePricing, onClose]);

  async function handleCreateAccount() {
    if (!ign.trim()) {
      setError("Enter your in-game name");
      return;
    }
    const trimmed = email.trim();
    if (!trimmed || !trimmed.includes("@")) {
      setError("Enter a valid email address");
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError("Password must be at least 8 characters");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (!acceptedTerms) {
      setError("Accept the privacy policy and terms to create an account");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      // Save the IGN under this email *before* registering. registerAccount
      // stores the new auth token and fires the auth-changed event as part
      // of the same call, and the sidebar reads the saved profile back the
      // instant that event fires. Without this, it finds nothing yet (this
      // is the account's first ever sign-in) and clears the IGN box even
      // though the user just typed it, so the pet never gets scraped. Skip
      // if this browser already has a saved profile for that email (e.g.
      // registration fails because the email is taken) so a failed attempt
      // can't clobber an existing account's cached IGN/pet.
      const trimmedIgn = ign.trim();
      saveSavedAccountProfile({ ign: trimmedIgn }, trimmed);
      await registerAccount(trimmed, password, {
        ign: trimmedIgn,
        confirmPassword,
      });
      saveSavedAccountProfile({ ign: trimmedIgn }, trimmed);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create account");
    } finally {
      setLoading(false);
    }
  }

  async function handleUpgrade() {
    const accountEmail = decodeAuthEmail() ?? email.trim();
    if (!accountEmail || !accountEmail.includes("@")) {
      setError("Sign in to upgrade");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const url = checkoutUrl ?? (await createCheckout(accountEmail));
      window.location.href = url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't start checkout. Try again.");
    } finally {
      setLoading(false);
    }
  }

  function handleSpendLimitSaved(_saved: OnDemandUsage) {
    onUsageEnabled?.();
    onClose();
  }

  function handleBackdropClick(e: React.MouseEvent<HTMLDivElement>) {
    if (isPricing) {
      leavePricing();
      return;
    }
    if (isLast || isReminder) {
      onClose();
      return;
    }
    // Steps 0/1 are the value-prop carousel (video demo slides, no form
    // inputs to protect) - clicking the dimmed backdrop advances or goes
    // back, Stories-style, instead of doing nothing. Left half of the
    // backdrop goes back, right half goes next.
    const rect = e.currentTarget.getBoundingClientRect();
    const clickedRightHalf = e.clientX - rect.left > rect.width / 2;
    if (clickedRightHalf) {
      goNext();
    } else {
      goBack();
    }
  }

  return (
    <>
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="paywall-title"
    >
      <div
        className="absolute inset-0 bg-black/30"
        onClick={handleBackdropClick}
        aria-hidden="true"
      />

      <div
        className={`relative z-10 w-full rounded-2xl border border-[#404040] bg-[#1e1e1e] shadow-2xl animate-slide-up ${
          isLast || isReminder
            ? "max-w-sm p-6"
            : isVideoSlide
              ? "max-w-3xl p-6 max-h-[94vh] overflow-y-auto"
              : "max-w-md p-6"
        }`}
      >
        {(isLast || isReminder) && (
          <button
            type="button"
            onClick={isPricing ? leavePricing : onClose}
            className="absolute top-4 right-4 rounded p-1 text-[#737373] transition-colors hover:text-[#ececec]"
            aria-label="Close"
          >
            ✕
          </button>
        )}

        {step === 0 && (
          <div key="slide-sets" className="animate-fade-in">
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-[#737373]">
              RealmPal Pro
            </p>
            <h2 id="paywall-title" className="mb-2 text-xl font-semibold text-[#ececec]">
              This type of question can be answered with in-depth responses, such as items, set-building, & enchanting guides
            </h2>
            <p className="mb-4 text-sm leading-relaxed text-[#a3a3a3]">
              Ask for a class and a stat. Get a real loadout tailored to your playstyle. Enchant rolls that
              matter for your build land next to the gear, so you stop guessing which UTs to
              keep.
            </p>
            <VideoPlaceholder
              src={setBuildingDemoSrc}
              label="Set-building and enchanting demo"
              videoRef={setBuildingRef}
              onEnded={() => setSetBuildingDone(true)}
            />
          </div>
        )}

        {step === 1 && (
          <div key="slide-viz" className="animate-fade-in">
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-[#737373]">
              See it before you farm it
            </p>
            <h2 id="paywall-title" className="mb-2 text-xl font-semibold text-[#ececec]">
              Set, skin, and item visualizers. See it before you decide if it's worth the farm.
            </h2>
            <p className="mb-4 text-sm leading-relaxed text-[#a3a3a3]">
              Shiny and divine sets render as a four-slot loadout. Dye a class skin with cloths
              and accessories the way RealmEye outfits do, for people who care how it looks
              in-game.
            </p>
            <VideoPlaceholder
              src={visualizerDemoSrc}
              label="Set and skin visualizer demo"
              videoRef={visualizerRef}
              onEnded={() => setVisualizerDone(true)}
            />
          </div>
        )}

        {isSignup && (
          <div key="slide-signup" className="animate-fade-in">
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-[#737373]">
              Free account
            </p>
            <h2 id="paywall-title" className="mb-2 text-xl font-semibold text-[#ececec]">
              Make a free account
            </h2>
            <p className="mb-5 text-sm leading-relaxed text-[#a3a3a3]">
              A free RealmPal account increases your in-depth response limit to{" "}
              {limit + ACCOUNT_BONUS_MESSAGES}/day and saves your chat history.
            </p>
            <div className="space-y-3">
              <input
                type="text"
                value={ign}
                onChange={(e) => setIgn(e.target.value)}
                placeholder="IGN"
                maxLength={20}
                autoComplete="username"
                className={fieldClass}
                aria-label="In-game name"
                autoFocus
              />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Email"
                autoComplete="email"
                className={fieldClass}
                aria-label="Email address"
              />
              <PasswordField
                value={password}
                onChange={setPassword}
                placeholder="Password"
                autoComplete="new-password"
                ariaLabel="Password"
                tone={passwordTone(password)}
              />
              <PasswordField
                value={confirmPassword}
                onChange={setConfirmPassword}
                placeholder="Confirm password"
                autoComplete="new-password"
                ariaLabel="Confirm password"
                tone={confirmTone(password, confirmPassword)}
              />
              <CheckRow checked={acceptedTerms} onChange={setAcceptedTerms}>
                I agree to the{" "}
                <Link
                  href="/legal/privacy"
                  className="text-[#ececec] hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  Privacy Policy
                </Link>
                {" "}and{" "}
                <Link
                  href="/legal/terms"
                  className="text-[#ececec] hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  Terms
                </Link>
              </CheckRow>
              {error && <p className="text-xs text-red-400">{error}</p>}
              <button
                type="button"
                onClick={() => void handleCreateAccount()}
                disabled={loading}
                className="w-full rounded-lg bg-white py-2.5 text-sm font-semibold text-[#1a1a1a] transition-colors hover:bg-[#e5e5e5] disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
              >
                {loading ? "Creating account..." : "Create account"}
              </button>
            </div>
          </div>
        )}

        {isOnDemand && isLast && (
          <div key="slide-ondemand" className="animate-fade-in">
            <h2 id="paywall-title" className="mb-1 text-center text-lg font-semibold text-[#ececec]">
              {reason === "spend_cap" ? "Usage cap reached" : "Included Claude replies used"}
            </h2>
            <p className="mb-6 text-center text-sm text-[#a3a3a3]">
              Stored builds, drops, and dungeon guides stay free. Extra Claude
              replies are $0.08 each. Set a monthly spending limit to keep going.
            </p>
            {error && <p className="mb-3 text-xs text-red-400">{error}</p>}
            <button
              type="button"
              onClick={() => setShowSpendLimit(true)}
              className="w-full rounded-lg bg-white py-2.5 text-sm font-semibold text-[#1a1a1a] transition-colors hover:bg-[#e5e5e5] cursor-pointer"
            >
              Manage spending limit
            </button>
            <p className="mt-3 text-center text-xs text-[#525252]">
              Pick $20, $50, $100, or a custom cap. Change it anytime in Billing.
            </p>
          </div>
        )}

        {isPricing && (
          <div key="slide-pricing" className="animate-fade-in">
            <div className="mb-4 flex justify-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-white/30 bg-white/10">
                {pet ? (
                  <PetSprite pet={pet} size={32} />
                ) : (
                  <Image
                    src={SWORD_SPRITE}
                    alt="RealmPal"
                    width={28}
                    height={28}
                    style={{ imageRendering: "pixelated" }}
                    unoptimized
                  />
                )}
              </div>
            </div>

            <h2 id="paywall-title" className="mb-1 text-center text-lg font-semibold text-[#ececec]">
              {freeMessagesHeading(remaining, limit)}
            </h2>
            <p className="mb-6 text-center text-sm text-[#a3a3a3]">
              RealmPal Pro includes a 7x usage increase for

            </p>

            <div className="mb-6 flex items-center justify-center gap-2">
              <span className="text-3xl font-bold text-[#ececec]">$7</span>
              <span className="text-sm text-[#737373]">/month</span>
            </div>

            <ul className="mb-6 space-y-2 text-sm text-[#a3a3a3]">
              {[
                "7x usage & AI credits included each month",
                "Stored builds, drops, and all RotMG information",
                "Instant set-building, skins, item cards, and dungeon guides",
                "Enchanting, DPS calculations, and more",
              ].map((f) => (
                <li key={f} className="flex items-center gap-2">
                  <span className="text-xs text-white">✓</span>
                  {f}
                </li>
              ))}
            </ul>

            {error && <p className="mb-3 text-xs text-red-400">{error}</p>}

            <button
              type="button"
              onClick={() => void handleUpgrade()}
              disabled={loading}
              className="w-full rounded-lg bg-white py-2.5 text-sm font-semibold text-[#1a1a1a] transition-colors hover:bg-[#e5e5e5] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "Redirecting to checkout..." : "Upgrade for $7/month"}
            </button>

            <p className="mt-3 text-center text-xs text-[#525252]">
              Secure checkout via Stripe. Cancel anytime.
            </p>
          </div>
        )}

        {isReminder && (
          <div key="slide-refresh" className="animate-fade-in">
            {remaining != null && remaining > 0 ? (
              <>
                <h2 id="paywall-title" className="mb-2 text-center text-lg font-semibold text-[#ececec]">
                  {freeInDepthPromptsStillLeftToday(remaining)}
                </h2>
                <p className="text-center text-sm leading-relaxed text-[#a3a3a3]">
                  Keep chatting for free, or go Pro for $7/month whenever
                  you're ready.
                </p>
              </>
            ) : (
              <>
                <h2 id="paywall-title" className="mb-2 text-center text-lg font-semibold text-[#ececec]">
                  Your {limit} daily in-depth responses refresh in <br />{" "}
                  <span className="text-[#D4AF37]">{formatResetWait(resetsInSeconds)}</span>
                </h2>
                <p className="text-center text-sm leading-relaxed text-[#a3a3a3]">
                  Come back then for another {limit} free in-depth responses. Pro is $7/month if you
                  want to keep going now.
                </p>
              </>
            )}
            <button
              type="button"
              onClick={onClose}
              className="mt-6 w-full rounded-lg bg-white py-2.5 text-sm font-semibold text-[#1a1a1a] transition-colors hover:bg-[#e5e5e5]"
            >
              Got it
            </button>
          </div>
        )}

        {!isReminder && (
        <div className="mt-6 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={goBack}
            disabled={step === 0}
            className="rounded-lg px-3 py-2 text-sm text-[#a3a3a3] transition-colors hover:text-[#ececec] disabled:invisible"
          >
            Back
          </button>

          <StepDots step={step} total={LAST_STEP + 1} onJump={setStep} />

          {!isLast ? (
            <button
              type="button"
              onClick={goNext}
              className="rounded-lg bg-white px-4 py-2 text-sm font-semibold text-[#1a1a1a] transition-colors hover:bg-[#e5e5e5] cursor-pointer"
            >
              Next
            </button>
          ) : (
            <button
              type="button"
              onClick={isPricing ? leavePricing : onClose}
              className="rounded-lg px-3 py-2 text-sm text-[#737373] transition-colors hover:text-[#a3a3a3] cursor-pointer"
            >
              Not now
            </button>
          )}
        </div>
        )}
      </div>
    </div>

    {showSpendLimit && isOnDemand && (
      <SpendingLimitModal
        currentCap={spendCapUsd}
        spentSoFar={onDemandSpentUsd}
        exhausted
        onClose={() => setShowSpendLimit(false)}
        onSaved={handleSpendLimitSaved}
      />
    )}
    </>
  );
}
