"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { PlayerProfile } from "@/lib/api";
import { AUTH_CHANGED_EVENT, clearAuthToken, decodeAuthEmail, decodeAuthIgn } from "@/lib/api";
import { BillingModal } from "./BillingModal";
import { GuestAvatar } from "./GuestAvatar";

function SettingsIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function BellIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  );
}

function BillingIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
      <line x1="1" y1="10" x2="23" y2="10" />
    </svg>
  );
}

function LogoutIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  );
}

function SignInIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
      <polyline points="10 17 15 12 10 7" />
      <line x1="15" y1="12" x2="3" y2="12" />
    </svg>
  );
}

function RegisterIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="8.5" cy="7" r="4" />
      <line x1="20" y1="8" x2="20" y2="14" />
      <line x1="23" y1="11" x2="17" y2="11" />
    </svg>
  );
}

function MenuItem({
  icon,
  label,
  onClick,
  danger = false,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-4 py-2 text-sm text-left transition-colors cursor-pointer ${
        danger ? "text-red-400 hover:bg-[#3a1f1f]" : "text-[#ececec] hover:bg-[#2a2a2a]"
      }`}
    >
      <span className={`flex-shrink-0 ${danger ? "text-red-400" : "text-[#a3a3a3]"}`}>{icon}</span>
      {label}
    </button>
  );
}

interface Props {
  pet?: PlayerProfile["top_pet"];
  size?: number;
  /** Shows a name/email label next to the avatar, for the sidebar row. */
  showLabel?: boolean;
  /** Which way the dropdown opens relative to the trigger. */
  openDirection?: "up" | "down";
  /** Which edge of the trigger the dropdown aligns to. */
  align?: "left" | "right";
  /** Extra classes for the trigger button, e.g. sidebar hover/padding. */
  triggerClassName?: string;
}

/**
 * Account avatar + dropdown, used both in the bottom-left sidebar row and
 * the top-right header cluster | same component so the two stay in sync by
 * construction rather than by convention. Renders the user's pet sprite the
 * same way PetCompanion does everywhere else in the chat (via GuestAvatar).
 */
export function AccountMenu({
  pet,
  size = 32,
  showLabel = false,
  openDirection = "down",
  align = "right",
  triggerClassName = "",
}: Props) {
  const [open, setOpen] = useState(false);
  const [showBilling, setShowBilling] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const [ign, setIgn] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    function syncAuth() {
      setEmail(decodeAuthEmail());
      setIgn(decodeAuthIgn());
    }
    syncAuth();
    window.addEventListener(AUTH_CHANGED_EVENT, syncAuth);
    return () => window.removeEventListener(AUTH_CHANGED_EVENT, syncAuth);
  }, []);

  useEffect(() => {
    if (!open) return;
    function onClickAway(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("mousedown", onClickAway);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onClickAway);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const goToSignIn = useCallback(() => {
    setOpen(false);
    router.push("/auth/signin");
  }, [router]);

  const goToRegister = useCallback(() => {
    setOpen(false);
    router.push("/auth/signin?mode=register");
  }, [router]);

  function handleLogout() {
    clearAuthToken();
    setEmail(null);
    setIgn(null);
    setOpen(false);
  }

  const isSignedIn = Boolean(email);
  const primaryLabel = isSignedIn ? ign || email || "Account" : "Guest";

  return (
    <div ref={containerRef} className="relative inline-flex w-full">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-2.5 rounded-lg cursor-pointer ${triggerClassName}`}
        aria-label={isSignedIn ? "Account menu" : "Guest account menu"}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <GuestAvatar pet={pet} size={size} />
        {showLabel && (
          <div className="min-w-0 flex-1 text-left">
            <p className="text-sm font-medium text-[#ececec] truncate">{primaryLabel}</p>
            {isSignedIn && ign && email ? (
              <p className="text-xs text-[#737373] truncate">{email}</p>
            ) : null}
          </div>
        )}
      </button>

      {open && (
        <div
          role="menu"
          className={`absolute z-50 w-64 rounded-xl border border-[#404040] bg-[#1e1e1e] shadow-2xl py-2 animate-fade-in ${
            openDirection === "up" ? "bottom-full mb-2" : "top-full mt-2"
          } ${align === "right" ? "right-0" : "left-0"}`}
        >
          <div className="flex items-center gap-3 px-4 py-3">
            <GuestAvatar pet={pet} size={40} />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-[#ececec] truncate">
                {isSignedIn ? primaryLabel : "Guest"}
              </p>
              {isSignedIn && ign && email ? (
                <p className="text-xs text-[#737373] truncate">{email}</p>
              ) : !isSignedIn ? (
                <p className="text-xs text-[#737373] truncate">Not signed in</p>
              ) : null}
            </div>
          </div>

          <div className="border-t border-[#303030] my-1" />

          {isSignedIn ? (
            <>
              <MenuItem icon={<SettingsIcon />} label="Settings" onClick={() => { setOpen(false); router.push("/account/settings"); }} />
              <MenuItem icon={<BillingIcon />} label="Billing" onClick={() => { setOpen(false); setShowBilling(true); }} />
              <MenuItem icon={<BellIcon />} label="Notifications" onClick={() => { setOpen(false); router.push("/account/notifications"); }} />
              <div className="border-t border-[#303030] my-1" />
              <MenuItem icon={<LogoutIcon />} label="Log out" onClick={handleLogout} danger />
            </>
          ) : (
            <>
              <MenuItem icon={<SignInIcon />} label="Sign in" onClick={goToSignIn} />
              <MenuItem icon={<RegisterIcon />} label="Register" onClick={goToRegister} />
            </>
          )}
        </div>
      )}

      {showBilling && <BillingModal onClose={() => setShowBilling(false)} />}
    </div>
  );
}
