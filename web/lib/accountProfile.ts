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

function profileKey(): string | null {
  const email = decodeAuthEmail();
  if (!email) return null;
  return `${PROFILE_KEY}:${email.trim().toLowerCase()}`;
}

export function loadSavedAccountProfile(): SavedAccountProfile | null {
  if (typeof window === "undefined") return null;
  const key = profileKey();
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

export function saveSavedAccountProfile(profile: SavedAccountProfile): void {
  if (typeof window === "undefined") return;
  const key = profileKey();
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
