"use client";
import type { PlayerProfile } from "@/lib/api";
import { GuestAvatar } from "./GuestAvatar";

export function SidebarAccount({
  pet,
  onClick,
}: {
  pet?: PlayerProfile["top_pet"];
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full flex items-center gap-2.5 rounded-lg px-2 py-1.5 -mx-2 text-left cursor-pointer hover:bg-[#333333] transition-colors"
      aria-label="Guest account"
    >
      <GuestAvatar pet={pet} size={32} />
      <span className="text-sm font-medium text-[#ececec] truncate">Guest</span>
    </button>
  );
}
