"use client";

import { useEffect } from "react";
import { API_URL, type PlayerProfile } from "@/lib/api";
import { SWORD_SPRITE } from "@/lib/sprites";

function setTabIcon(href: string) {
  if (typeof document === "undefined") return;
  document.querySelectorAll("link[rel*='icon']").forEach((el) => el.remove());
  const link = document.createElement("link");
  link.id = "realmpal-tab-icon";
  link.rel = "icon";
  link.type = "image/png";
  link.href = href;
  document.head.appendChild(link);
}

export function petTabIconUrl(
  pet: NonNullable<PlayerProfile["top_pet"]>,
): string | null {
  if (pet.sprite_url) return pet.sprite_url;
  if (
    !pet.sprite_sheet_url ||
    pet.sprite_x == null ||
    pet.sprite_y == null ||
    !pet.sprite_size
  ) {
    return null;
  }
  const q = new URLSearchParams({
    sheet: pet.sprite_sheet_url,
    x: String(pet.sprite_x),
    y: String(pet.sprite_y),
    size: String(pet.sprite_size),
  });
  return `${API_URL}/sprite/crop?${q}`;
}

/** Browser tab icon: sword by default, the signed-in player's pet when set. */
export function TabIcon({ pet }: { pet?: PlayerProfile["top_pet"] }) {
  useEffect(() => {
    let cancelled = false;
    if (!pet) {
      setTabIcon(SWORD_SPRITE);
      return;
    }
    const href = petTabIconUrl(pet);
    if (!href) {
      setTabIcon(SWORD_SPRITE);
      return;
    }
    if (href === pet.sprite_url) {
      setTabIcon(href);
      return;
    }
    void fetch(href)
      .then((res) => {
        if (!cancelled && res.ok) setTabIcon(href);
        else if (!cancelled) setTabIcon(SWORD_SPRITE);
      })
      .catch(() => {
        if (!cancelled) setTabIcon(SWORD_SPRITE);
      });
    return () => {
      cancelled = true;
    };
  }, [pet]);

  return null;
}
