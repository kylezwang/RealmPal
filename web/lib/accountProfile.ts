/**
 * Per-account sidebar profile (IGN + top pet) in localStorage. Guests do not
 * persist; signed-in users (free or paid) restore on every visit.
 */

import { decodeAuthEmail, decodeAuthIgn, type PlayerProfile } from "./api";

export interface SavedAccountProfile {
  ign: string;
  top_pet?: PlayerProfile["top_pet"];
}

const PROFILE_KEY = "realm_pal_account_profile";
const LAST_KEY = "realm_pal_account_profile:last";

function sameName(a?: string | null, b?: string | null): boolean {
  return Boolean(a && b && a.trim().toLowerCase() === b.trim().toLowerCase());
}

function profileKey(email?: string): string | null {
  const target = email ?? decodeAuthEmail();
  if (!target) return null;
  return `${PROFILE_KEY}:${target.trim().toLowerCase()}`;
}

function readProfile(raw: string | null): SavedAccountProfile | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as SavedAccountProfile & { email?: string };
    if (!parsed?.ign?.trim()) return null;
    return { ign: parsed.ign.trim(), top_pet: parsed.top_pet };
  } catch {
    return null;
  }
}

export function loadSavedAccountProfile(email?: string): SavedAccountProfile | null {
  if (typeof window === "undefined") return null;
  const key = profileKey(email);
  if (key) {
    const keyed = readProfile(localStorage.getItem(key));
    if (keyed) return keyed;
  }
  // Same browser, JWT decode missed the email key, or an older save only
  // landed in the last-used slot. Restore when IGN or email still matches.
  const lastRaw = localStorage.getItem(LAST_KEY);
  if (!lastRaw) return null;
  try {
    const last = JSON.parse(lastRaw) as SavedAccountProfile & { email?: string };
    const profile = readProfile(JSON.stringify(last));
    if (!profile) return null;
    const jwtEmail = (email ?? decodeAuthEmail())?.trim().toLowerCase();
    const lastEmail = typeof last.email === "string" ? last.email.trim().toLowerCase() : "";
    if (jwtEmail && lastEmail && jwtEmail === lastEmail) return profile;
    if (sameName(profile.ign, decodeAuthIgn())) return profile;
    return null;
  } catch {
    return null;
  }
}

/**
 * `email` lets a caller save this before the auth token exists yet, e.g.
 * right before account creation, so the IGN is already there in storage the
 * instant the auth-changed event fires and the sidebar reads it back.
 */
export function saveSavedAccountProfile(
  profile: SavedAccountProfile,
  email?: string,
): void {
  if (typeof window === "undefined") return;
  const ign = profile.ign.trim();
  if (!ign) return;
  const payload = { ign, top_pet: profile.top_pet };
  const accountEmail = (email ?? decodeAuthEmail() ?? "").trim().toLowerCase();
  try {
    const key = profileKey(email);
    if (key) {
      localStorage.setItem(key, JSON.stringify(payload));
    }
    localStorage.setItem(
      LAST_KEY,
      JSON.stringify({ ...payload, email: accountEmail || undefined }),
    );
  } catch {
    // storage disabled/full | profile just won't persist, not fatal
  }
}

/** Minimal PlayerProfile shell for instant pet restore before a fresh fetch. */
export function cachedPlayerProfile(saved: SavedAccountProfile): PlayerProfile | null {
  if (!saved.top_pet) return null;
  return {
    username: saved.ign,
    top_pet: saved.top_pet,
    characters: [],
    scraped_at: "",
  };
}
