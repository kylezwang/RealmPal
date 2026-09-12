"use client";
import { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { createCheckout, decodeAuthEmail, registerAccount, type PlayerProfile } from "@/lib/api";
import { SWORD_SPRITE } from "@/lib/sprites";
import { PetSprite } from "./PetCompanion";

/** Extra free messages a guest gets by creating an account. */
export const ACCOUNT_BONUS_MESSAGES = 2;

const LAST_STEP = 2;
const MIN_PASSWORD_LENGTH = 8;

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
  if (remaining <= 0) return `You've used your ${limit} free messages`;
  if (remaining === 1) return "You have 1 free message left";
  return `You have ${remaining} free messages left`;
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
  /** Optional MP4/WebM URLs once demos are recorded. Empty = placeholder. */
  setBuildingDemoSrc?: string;
  visualizerDemoSrc?: string;
}

function VideoPlaceholder({
  src,
  label,
}: {
  src?: string;
  label: string;
}) {
  if (src) {
    return (
      <div className="relative w-full overflow-hidden rounded-xl border border-[#404040] bg-black aspect-video">
        <video
          className="h-full w-full object-cover"
          src={src}
          controls
          playsInline
          preload="metadata"
          aria-label={label}
        />
      </div>
    );
  }

  return (
    <div
      className="relative flex aspect-video w-full flex-col items-center justify-center gap-2 overflow-hidden rounded-xl border border-dashed border-[#525252] bg-[#141414]"
      role="img"
      aria-label={`${label} — demo video coming soon`}
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
  setBuildingDemoSrc,
  visualizerDemoSrc,
}: Props) {
  const [step, setStep] = useState(0);
  const [ign, setIgn] = useState("");
  const [email, setEmail] = useState(() => decodeAuthEmail() ?? "");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const goNext = useCallback(() => {
    setStep((s) => Math.min(LAST_STEP, s + 1));
    setError(null);
  }, []);

  const goBack = useCallback(() => {
    setStep((s) => Math.max(0, s - 1));
    setError(null);
  }, []);

  const isLast = step === LAST_STEP;
  const isSignup = isLast && !signedIn;
  const isPricing = isLast && signedIn;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && isLast) onClose();
      if (e.key === "ArrowRight") goNext();
      if (e.key === "ArrowLeft") goBack();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, goNext, goBack, isLast]);

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
      await registerAccount(trimmed, password, {
        ign: ign.trim(),
        confirmPassword,
      });
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="paywall-title"
    >
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={isLast ? onClose : undefined}
        aria-hidden="true"
      />

      <div
        className={`relative z-10 w-full rounded-2xl border border-[#404040] bg-[#1e1e1e] p-6 shadow-2xl animate-slide-up ${
          isLast ? "max-w-sm" : "max-w-md"
        }`}
      >
        {isLast && (
          <button
            type="button"
            onClick={onClose}
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
              Set-building AI, with enchanting guides
            </h2>
            <p className="mb-4 text-sm leading-relaxed text-[#a3a3a3]">
              Ask for a class and a stat — get a real loadout, not vibes. Enchant rolls that
              matter for your build land next to the gear, so you stop guessing which UT to
              keep.
            </p>
            <VideoPlaceholder
              src={setBuildingDemoSrc}
              label="Set-building and enchanting demo"
            />
          </div>
        )}

        {step === 1 && (
          <div key="slide-viz" className="animate-fade-in">
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-[#737373]">
              See it before you farm it
            </p>
            <h2 id="paywall-title" className="mb-2 text-xl font-semibold text-[#ececec]">
              Set and skin visualizers
            </h2>
            <p className="mb-4 text-sm leading-relaxed text-[#a3a3a3]">
              Shiny and divine sets render as a four-slot loadout. Dye a class skin with cloths
              and accessories the way RealmEye outfits do — for people who care how it looks
              in-game.
            </p>
            <VideoPlaceholder
              src={visualizerDemoSrc}
              label="Set and skin visualizer demo"
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
              A free RealmPal account increases your message limit to{" "}
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
              Upgrade to RealmPal Pro to support the project and continue | Hosting and AI
              costs are expensive, <br /> your support helps keeps it alive!
            </p>

            <div className="mb-6 flex items-center justify-center gap-2">
              <span className="text-3xl font-bold text-[#ececec]">$7</span>
              <span className="text-sm text-[#737373]">/month</span>
            </div>

            <ul className="mb-6 space-y-2 text-sm text-[#a3a3a3]">
              {[
                "All RotMG questions",
                "Set-building AI for DPS",
                "Enchanting guides & DPS Calculation",
                "Skin customization preview (Cloths and Dyes)",
                "Account & character details",
                "Item/Dungeon guides",
                "And more",
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
              onClick={onClose}
              className="rounded-lg px-3 py-2 text-sm text-[#737373] transition-colors hover:text-[#a3a3a3] cursor-pointer"
            >
              Not now
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
