"use client";
import type { ChatUsage, PlayerProfile } from "@/lib/api";
import { AccountMenu } from "./AccountMenu";

/**
 * Bottom-left sidebar account row. Opens upward (there's no room below it)
 * and shares the AccountMenu component with the top-right header cluster
 * so both mirror each other's avatar and dropdown by construction.
 */
export function SidebarAccount({
  pet,
  onRegister,
  usage,
  onOpenPaywall,
}: {
  pet?: PlayerProfile["top_pet"];
  onRegister?: () => void;
  usage?: ChatUsage | null;
  onOpenPaywall?: () => void;
}) {
  return (
    <AccountMenu
      pet={pet}
      size={32}
      showLabel
      openDirection="up"
      align="left"
      triggerClassName="w-full px-2 py-1.5 -mx-2 hover:bg-[#333333] transition-colors"
      onRegister={onRegister}
      usage={usage}
      onOpenPaywall={onOpenPaywall}
    />
  );
}
