"use client";
import Image from "next/image";
import type { PlayerProfile } from "@/lib/api";
import { SpriteIcon } from "./SpriteIcon";

/**
 * RealmEye renders pets as a crop of one shared sprite sheet rather than a
 * standalone image file, e.g.:
 *   <span class="pet" data-item="32639" title="Reaper"
 *         style="background-position: -336px -288px;"></span>
 * The scraper captures that sheet URL + crop offset directly off the
 * player's page, so we replicate the exact same crop here via CSS instead
 * of guessing at a matching sprite from the wiki.
 */
export function PetSprite({ pet, size = 28 }: { pet: NonNullable<PlayerProfile["top_pet"]>; size?: number }) {
  if (pet.sprite_sheet_url && pet.sprite_x != null && pet.sprite_y != null && pet.sprite_size) {
    return (
      <SpriteIcon
        sheetUrl={pet.sprite_sheet_url}
        x={pet.sprite_x}
        y={pet.sprite_y}
        nativeSize={pet.sprite_size}
        displaySize={size}
        alt={pet.name}
      />
    );
  }
  if (pet.sprite_url) {
    return (
      <Image
        src={pet.sprite_url}
        alt={pet.name}
        width={size}
        height={size}
        style={{ imageRendering: "pixelated" }}
        unoptimized
      />
    );
  }
  return <PawIcon className="text-[#737373]" size={16} />;
}

function PawIcon({ className, size = 14 }: { className?: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden="true"
    >
      <ellipse cx="7" cy="6.5" rx="2.2" ry="2.8" />
      <ellipse cx="12" cy="4.8" rx="2.2" ry="2.8" />
      <ellipse cx="17" cy="6.5" rx="2.2" ry="2.8" />
      <ellipse cx="19.2" cy="11.2" rx="2" ry="2.4" />
      <path d="M12 10.2c-3.6 0-6.4 2.4-6.4 5.2 0 2.2 1.7 3.6 3.6 3.6 1.1 0 2-.5 2.8-1.2.8.7 1.7 1.2 2.8 1.2 1.9 0 3.6-1.4 3.6-3.6 0-2.8-2.8-5.2-6.4-5.2z" />
    </svg>
  );
}

function Spinner({ size = 16 }: { size?: number }) {
  return (
    <div
      className="rounded-full border-2 border-[#333333] border-t-[#8a8a8a] animate-spin flex-shrink-0"
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  );
}

interface Props {
  profile: PlayerProfile | null;
  loading?: boolean;
  lookupError?: string | null;
}

/**
 * Displays the user's top pet sprite in the sidebar/header.
 * The pet "travels with them" through every conversation | personalizes the AI experience.
 */
export function PetCompanion({ profile, loading = false, lookupError = null }: Props) {
  if (loading) {
    return (
      <div
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#1c1c1c] border border-dotted border-[#2e2e2e] text-xs text-[#737373]"
        aria-busy="true"
        aria-label="Loading pet"
      >
        <Spinner size={16} />
        <span>Loading...</span>
      </div>
    );
  }

  if (lookupError || !profile?.top_pet) {
    return (
      <div
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#1c1c1c] border border-dotted border-[#2e2e2e] text-xs text-[#737373]"
        title={lookupError ?? "Enter your IGN to load your pet"}
      >
        <PawIcon className={`flex-shrink-0 ${lookupError ? "text-red-400/80" : "text-[#737373]"}`} size={16} />
        <span className={lookupError ? "text-red-400/90" : undefined}>
          {lookupError ?? "No pet found yet."}
        </span>
      </div>
    );
  }

  const pet = profile.top_pet;

  return (
    <div
      className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#262626] border border-[#404040] hover:border-white transition-colors cursor-default"
      title={`${profile.username}'s companion: ${pet.name}${pet.tier ? ` (${pet.tier})` : ""}`}
      aria-label={`Pet companion: ${pet.name}`}
    >
      <PetSprite pet={pet} size={40} />
      <div>
        <p className="text-xs font-medium text-[#ececec] leading-none">{pet.name}</p>
        {pet.tier && (
          <p className="text-[10px] text-[#737373] mt-0.5">{pet.tier}</p>
        )}
      </div>
    </div>
  );
}
