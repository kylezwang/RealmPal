"use client";
import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { registerAccount, requestSignInLink, signInWithPassword, startOAuth } from "@/lib/api";
import { SWORD_SPRITE, SIGNIN_HERO_IMAGE } from "@/lib/sprites";

type Mode = "signin" | "register";
type Status = "idle" | "loading" | "sent" | "error";

const fieldClass =
  "w-full rounded-lg border border-[#404040] bg-[#262626] px-3 py-2.5 text-sm text-[#ececec] placeholder-[#525252] focus:outline-none focus:border-white transition-colors";

const MIN_PASSWORD_LENGTH = 8;

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

function RequirementRow({ ok, label }: { ok: boolean; label: string }) {
  return (
    <li className={`flex items-center gap-2 text-xs ${ok ? "text-green-400" : "text-[#a3a3a3]"}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-green-400" : "bg-[#525252]"}`} />
      {label}
    </li>
  );
}

function PasswordHint({
  title,
  rows,
}: {
  title: string;
  rows: { ok: boolean; label: string }[];
}) {
  return (
    <div
      role="dialog"
      className="rounded-xl border border-[#404040] bg-[#1e1e1e] px-3 py-2.5 shadow-2xl"
    >
      <p className="mb-2 text-xs font-medium text-[#ececec]">{title}</p>
      <ul className="space-y-1.5">
        {rows.map((row) => (
          <RequirementRow key={row.label} ok={row.ok} label={row.label} />
        ))}
      </ul>
    </div>
  );
}

function PasswordField({
  value,
  onChange,
  placeholder,
  autoComplete,
  ariaLabel,
  tone,
  hintTitle,
  hintRows,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  autoComplete: string;
  ariaLabel: string;
  tone: CheckTone;
  hintTitle: string;
  hintRows: { ok: boolean; label: string }[];
}) {
  return (
    <div className="group relative">
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
      <div className="pointer-events-none invisible absolute left-full top-1/2 z-50 ml-3 w-52 -translate-y-1/2 group-focus-within:visible">
        <PasswordHint title={hintTitle} rows={hintRows} />
      </div>
    </div>
  );
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

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors cursor-pointer ${
        active ? "bg-white text-[#1a1a1a]" : "text-[#a3a3a3] hover:text-[#ececec]"
      }`}
    >
      {children}
    </button>
  );
}

function GoogleIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.258c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332C2.438 15.983 5.482 18 9 18z" />
      <path fill="#FBBC05" d="M3.964 10.707c-.18-.54-.282-1.117-.282-1.707s.102-1.167.282-1.707V4.961H.957C.348 6.175 0 7.55 0 9s.348 2.825.957 4.039l3.007-2.332z" />
      <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0 5.482 0 2.438 2.017.957 4.961L3.964 7.293C4.672 5.163 6.656 3.58 9 3.58z" />
    </svg>
  );
}

function MicrosoftIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#F25022" d="M1 1h7.5v7.5H1z" />
      <path fill="#7FBA00" d="M9.5 1H17v7.5H9.5z" />
      <path fill="#00A4EF" d="M1 9.5h7.5V17H1z" />
      <path fill="#FFB900" d="M9.5 9.5H17V17H9.5z" />
    </svg>
  );
}

const oauthIconClass =
  "w-10 h-10 rounded-lg bg-[#3a3a3a] text-[#c4c4c4] hover:bg-white hover:text-[#1a1a1a] disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center transition-colors cursor-pointer";

function OAuthIcons({
  disabled,
  onPick,
}: {
  disabled: boolean;
  onPick: (provider: "google" | "microsoft") => void;
}) {
  return (
    <div className="flex items-center justify-center gap-2">
      <button
        type="button"
        disabled={disabled}
        onClick={() => onPick("google")}
        className={oauthIconClass}
        aria-label="Continue with Google"
      >
        <GoogleIcon size={16} />
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={() => onPick("microsoft")}
        className={oauthIconClass}
        aria-label="Continue with Microsoft"
      >
        <MicrosoftIcon size={16} />
      </button>
    </div>
  );
}

function OAuthModal({
  disabled,
  error,
  onPick,
  onClose,
}: {
  disabled: boolean;
  error: string | null;
  onPick: (provider: "google" | "microsoft") => void;
  onClose: () => void;
}) {
  return (
    <div className="fixed top-6 right-8 z-50 flex flex-col items-end gap-2">
      <button
        type="button"
        onClick={onClose}
        className={oauthIconClass}
        aria-label="Back to guest session"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
          <path d="M2 2l10 10M12 2L2 12" />
        </svg>
      </button>
      <div
        role="dialog"
        aria-label="Continue with Google or Microsoft"
        className="w-[min(18rem,calc(100vw-2rem))] rounded-2xl border border-[#404040] bg-[#1e1e1e] p-4 shadow-2xl"
      >
        <p className="mb-3 text-sm font-medium text-[#ececec]">Continue with</p>
        <div className="space-y-2">
          <button
            type="button"
            disabled={disabled}
            onClick={() => onPick("google")}
            className="w-full flex items-center justify-center gap-2.5 rounded-full border border-[#d4d4d4] bg-white py-2.5 text-sm font-medium text-[#1a1a1a] hover:bg-[#f5f5f5] disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
          >
            <GoogleIcon />
            Continue with Google
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onPick("microsoft")}
            className="w-full flex items-center justify-center gap-2.5 rounded-full border border-[#d4d4d4] bg-white py-2.5 text-sm font-medium text-[#1a1a1a] hover:bg-[#f5f5f5] disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
          >
            <MicrosoftIcon />
            Continue with Microsoft
          </button>
        </div>
        {error && <p className="mt-3 text-xs text-red-400">{error}</p>}
      </div>
    </div>
  );
}

/**
 * Email + password is the primary path. Google / Microsoft live in a
 * corner card that stays up on both tabs; they talk to
 * /auth/oauth/{provider}, which 501s until Entra External ID is wired.
 */
export default function SignInPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("signin");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("mode") === "register") setMode("register");
    const prefill = params.get("email")?.trim();
    if (prefill) setEmail(prefill);
  }, []);
  const [ign, setIgn] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [oauthError, setOauthError] = useState<string | null>(null);
  const [oauthLoading, setOauthLoading] = useState(false);
  const [showForgot, setShowForgot] = useState(false);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [staySignedIn, setStaySignedIn] = useState(true);

  function resetStatus() {
    setStatus("idle");
    setError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = email.trim();
    if (mode === "register" && !ign.trim()) {
      setError("Enter your in-game name");
      return;
    }
    if (mode === "register") {
      if (!trimmed || !trimmed.includes("@")) {
        setError("Enter a valid email address");
        return;
      }
    } else if (!trimmed) {
      setError("Enter your email or IGN");
      return;
    }
    if (mode === "register") {
      if (passwordTone(password) !== "green") {
        setError("Password must be at least 8 characters");
        return;
      }
      if (confirmTone(password, confirmPassword) !== "green") {
        setError("Passwords do not match");
        return;
      }
      if (!acceptedTerms) {
        setError("Accept the privacy policy and terms to create an account");
        return;
      }
    } else if (password.length < MIN_PASSWORD_LENGTH) {
      setError("Password must be at least 8 characters");
      return;
    }
    setStatus("loading");
    setError(null);
    try {
      if (mode === "register") {
        await registerAccount(trimmed, password, {
          ign: ign.trim(),
          confirmPassword,
        });
      } else {
        await signInWithPassword(trimmed, password, { persist: staySignedIn });
      }
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setStatus("error");
    }
  }

  async function handleForgotLink() {
    const trimmed = email.trim();
    if (!trimmed || !trimmed.includes("@")) {
      setError("Enter your email above first");
      return;
    }
    setStatus("loading");
    setError(null);
    try {
      await requestSignInLink(trimmed);
      setStatus("sent");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setStatus("error");
    }
  }

  async function handleOAuth(provider: "google" | "microsoft") {
    setOauthLoading(true);
    setOauthError(null);
    try {
      await startOAuth(provider);
    } catch (err) {
      setOauthError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setOauthLoading(false);
    }
  }

  return (
    <div className="relative min-h-screen flex bg-[#1a1a1a] text-[#ececec]">
      <OAuthModal
        disabled={oauthLoading}
        error={oauthError}
        onPick={(p) => void handleOAuth(p)}
        onClose={() => router.push("/")}
      />
      <div className="relative z-20 w-full lg:w-2/5 flex flex-col items-center justify-center px-8 py-12">
        <div className="w-full max-w-sm overflow-visible">
          <button
            type="button"
            onClick={() => router.push("/")}
            className="mb-4 flex items-center gap-2 cursor-pointer"
            aria-label="Back to RealmPal"
          >
            <Image
              src={SWORD_SPRITE}
              alt="RealmPal"
              width={34}
              height={34}
              style={{ imageRendering: "pixelated" }}
              unoptimized
            />
            <span className="text-[1.35rem] font-semibold">RealmPal</span>
          </button>
          <div className="flex items-center gap-1 mb-6 rounded-lg bg-[#262626] p-1 w-fit">
            <TabButton active={mode === "signin"} onClick={() => { setMode("signin"); resetStatus(); }}>
              Sign in
            </TabButton>
            <TabButton active={mode === "register"} onClick={() => { setMode("register"); resetStatus(); }}>
              Register
            </TabButton>
          </div>

          <h1 className="text-2xl font-semibold mb-2">
            {mode === "signin" ? "Welcome back" : "Create your account"}
          </h1>
          <p className="text-sm text-[#a3a3a3] mb-6">
            {mode === "signin"
              ? "Sign in with your email or IGN and password."
              : "Just your IGN, email, and a password to get started."}
          </p>

          {status === "sent" ? (
            <div className="rounded-lg border border-[#404040] bg-[#262626] px-4 py-3 text-sm text-[#ececec]">
              Check <span className="font-medium">{email.trim()}</span> for a sign-in link.
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-3">
              {mode === "register" && (
                <input
                  type="text"
                  value={ign}
                  onChange={(e) => setIgn(e.target.value)}
                  placeholder="IGN"
                  maxLength={20}
                  autoFocus
                  autoComplete="username"
                  className={fieldClass}
                  aria-label="In-game name"
                />
              )}
              <input
                type={mode === "signin" ? "text" : "email"}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={mode === "signin" ? "Email or IGN" : "Email"}
                autoFocus={mode === "signin"}
                autoComplete={mode === "signin" ? "username" : "email"}
                className={fieldClass}
                aria-label={mode === "signin" ? "Email or IGN" : "Email address"}
              />
              {mode === "register" ? (
                <>
                  <PasswordField
                    value={password}
                    onChange={setPassword}
                    placeholder="Password"
                    autoComplete="new-password"
                    ariaLabel="Password"
                    tone={passwordTone(password)}
                    hintTitle="A usable password"
                    hintRows={[
                      { ok: password.length >= MIN_PASSWORD_LENGTH, label: "At least 8 characters" },
                    ]}
                  />
                  <PasswordField
                    value={confirmPassword}
                    onChange={setConfirmPassword}
                    placeholder="Confirm password"
                    autoComplete="new-password"
                    ariaLabel="Confirm password"
                    tone={confirmTone(password, confirmPassword)}
                    hintTitle="Confirm it"
                    hintRows={[
                      { ok: confirmPassword.length > 0 && password === confirmPassword, label: "Matches the password above" },
                    ]}
                  />
                </>
              ) : (
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Password"
                  autoComplete="current-password"
                  className={fieldClass}
                  aria-label="Password"
                />
              )}
              {error && <p className="text-xs text-red-400">{error}</p>}
              {mode === "register" ? (
                <CheckRow checked={acceptedTerms} onChange={setAcceptedTerms}>
                  I agree to the{" "}
                  <Link href="/legal/privacy" className="text-[#ececec] hover:underline" onClick={(e) => e.stopPropagation()}>
                    Privacy Policy
                  </Link>
                  {" "}and{" "}
                  <Link href="/legal/terms" className="text-[#ececec] hover:underline" onClick={(e) => e.stopPropagation()}>
                    Terms
                  </Link>
                </CheckRow>
              ) : (
                <CheckRow checked={staySignedIn} onChange={setStaySignedIn}>
                  Stay signed in?
                </CheckRow>
              )}
              <button
                type="submit"
                disabled={status === "loading"}
                className="w-full rounded-lg bg-white py-2.5 text-sm font-semibold text-[#1a1a1a] hover:bg-[#e5e5e5] disabled:cursor-not-allowed disabled:opacity-50 transition-colors cursor-pointer"
              >
                {status === "loading"
                  ? mode === "register"
                    ? "Creating account..."
                    : "Signing in..."
                  : mode === "signin"
                    ? "Sign in"
                    : "Create account"}
              </button>
              <OAuthIcons disabled={oauthLoading} onPick={(p) => void handleOAuth(p)} />
              {oauthError && <p className="text-xs text-red-400 text-center">{oauthError}</p>}
            </form>
          )}

          {mode === "signin" && (
            <div className="mt-5 text-center">
              <button
                type="button"
                onClick={() => setShowForgot((v) => !v)}
                className="text-xs text-[#737373] hover:text-[#a3a3a3] transition-colors cursor-pointer"
              >
                Forgot password?
              </button>
              {showForgot && (
                <div className="mt-2 space-y-2">
                  <p className="text-xs text-[#737373]">
                    We can email a one-time sign-in link instead.
                  </p>
                  <button
                    type="button"
                    onClick={() => void handleForgotLink()}
                    disabled={status === "loading"}
                    className="text-xs font-medium text-[#ececec] hover:underline disabled:opacity-50 cursor-pointer"
                  >
                    Email me a sign-in link
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="hidden lg:block w-3/5 relative overflow-hidden border-l border-[#303030] bg-[#141414]">
        <Image
          src={SIGNIN_HERO_IMAGE}
          alt=""
          fill
          style={{ objectFit: "cover", objectPosition: "left bottom", imageRendering: "pixelated" }}
          unoptimized
          priority
        />
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "linear-gradient(180deg, rgba(20,20,20,0.05) 0%, rgba(20,20,20,0.1) 55%, rgba(20,20,20,0.55) 100%)",
          }}
        />
        <div className="absolute left-[6%] bottom-[42%] w-[44%] flex flex-col items-start gap-2 px-4 text-left">
          <h2 className="text-3xl font-extrabold text-[#ececec] max-w-md" style={{ fontWeight: 800 }}>
            RealmPal
          </h2>
          <p className="text-[#a3a3a3] max-w-sm text-sm">
            DPS Set-building, Enchanting, and Set/Skin visualizers. <br /> Sign in to save your chats
            and unlock the full experience.
          </p>
        </div>
      </div>
    </div>
  );
}
