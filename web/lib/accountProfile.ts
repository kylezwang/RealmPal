/**
 * Per-account sidebar profile (IGN + top pet) in localStorage. Guests do not
 * persist; signed-in users (free or paid) restore on every visit.
 */

import { decodeAuthEmail, type PlayerProfile } from "./api";

export interface SavedAccountProfile {
  ign: string;
  top_pet?: PlayerProfile["top_pet"];
}

const PROFILE_KEY = "realm_pal_account_profile";

function profileKey(email?: string): string | null {
  const target = email ?? decodeAuthEmail();
  if (!target) return null;
  return `${PROFILE_KEY}:${target.trim().toLowerCase()}`;
}

export function loadSavedAccountProfile(email?: string): SavedAccountProfile | null {
  if (typeof window === "undefined") return null;
  const key = profileKey(email);
  if (!key) return null;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as SavedAccountProfile;
    if (!parsed?.ign?.trim()) return null;
    return { ign: parsed.ign.trim(), top_pet: parsed.top_pet };
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
  const key = profileKey(email);
  if (!key) return;
  try {
    localStorage.setItem(
      key,
      JSON.stringify({ ign: profile.ign.trim(), top_pet: profile.top_pet }),
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
