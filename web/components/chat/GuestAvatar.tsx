"use client";
import type { PlayerProfile } from "@/lib/api";
import { PetSprite } from "./PetCompanion";

export function UserIcon({ className, size = 16 }: { className?: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden="true"
    >
      <circle cx="12" cy="8" r="4" />
      <path d="M5.5 20.2c.9-3.6 3.5-5.7 6.5-5.7s5.6 2.1 6.5 5.7c.1.5-.2 1-0.8 1H6.3c-.6 0-.9-.5-.8-1z" />
    </svg>
  );
}

export function GuestAvatar({
  pet,
  size = 32,
}: {
  pet?: PlayerProfile["top_pet"];
  size?: number;
}) {
  const iconSize = Math.round(size * 0.5);
  const petSize = Math.round(size * 0.875);

  return (
    <div
      className="rounded-full bg-white border border-[#d4d4d4] overflow-hidden flex items-center justify-center flex-shrink-0"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {pet ? (
        <PetSprite pet={pet} size={petSize} />
      ) : (
        <UserIcon className="text-[#a3a3a3]" size={iconSize} />
      )}
    </div>
  );
}
