"use client";
import { useState } from "react";
import type { ItemProfile } from "@/lib/api";
import { cleanItemName } from "@/lib/itemLookup";
import { SET_SLOT_COUNT, type LoadoutShowcase } from "@/lib/loadoutShowcase";
import { DIVINE_GLOW, DIVINE_SLOT_X, DIAMOND_FRAME_OFFSET_PX, SLOT_NATIVE, SLOTS_SHEET, ShinyStar, SpriteIcon } from "./SpriteIcon";

const ICON_SIZE = 40;

function findLoadoutItem(loaded: ItemProfile[], rawName: string): ItemProfile | undefined {
  const key = cleanItemName(rawName).toLowerCase();
  const exact = loaded.find((item) => {
    const names = [item.name, item.requestedAs].filter(Boolean) as string[];
    return names.some((name) => cleanItemName(name).toLowerCase() === key);
  });
  if (exact) return exact;
  const prefix = key.split(/\s+/).slice(0, -1).join(" ");
  if (prefix.length < 8) return undefined;
  return loaded.find((item) => cleanItemName(item.name).toLowerCase().startsWith(prefix));
}

function LoadoutSlot({
  item,
  showcase,
}: {
  item?: ItemProfile;
  showcase: LoadoutShowcase;
}) {
  if (!item) {
    return (
      <div
        className="rounded-md border border-dashed border-[#333333]"
        style={{ width: ICON_SIZE, height: ICON_SIZE }}
        aria-hidden="true"
      />
    );
  }
  return <LoadedLoadoutSlot item={item} showcase={showcase} />;
}

function LoadedLoadoutSlot({
  item,
  showcase,
}: {
  item: ItemProfile;
  showcase: LoadoutShowcase;
}) {
  const shinySrc = item.shiny_sprite_url || "";
  const regularSrc = item.sprite_url || "";
  const hasShiny = Boolean(showcase.shiny && shinySrc);
  const [src, setSrc] = useState(hasShiny ? shinySrc : regularSrc);
  const showShiny = hasShiny && src === shinySrc;
  const Stage = item.wiki_url ? "a" : "div";
  const stageProps = item.wiki_url
    ? { href: item.wiki_url, target: "_blank", rel: "noopener noreferrer" }
    : {};
  const glow = showcase.rarity === "divine" ? DIVINE_GLOW : undefined;
  const iconSrc = src || regularSrc;

  return (
    <div className="group relative">
      <Stage
        className="relative block"
        style={{ width: ICON_SIZE, height: ICON_SIZE }}
        {...stageProps}
      >
        {iconSrc ? (
          <img
            src={iconSrc}
            alt={item.name}
            width={ICON_SIZE}
            height={ICON_SIZE}
            className={`absolute inset-0 ${item.wiki_url ? "cursor-pointer" : "cursor-default"}`}
            style={{
              imageRendering: "pixelated",
              width: ICON_SIZE,
              height: ICON_SIZE,
              filter: glow ? `drop-shadow(${glow} 0 0 2px)` : undefined,
            }}
            onError={() => {
              if (regularSrc && iconSrc !== regularSrc) setSrc(regularSrc);
            }}
          />
        ) : (
          <div
            className="absolute inset-0 rounded-md border border-dashed border-[#333333]"
            aria-hidden
          />
        )}
        {showcase.rarity === "divine" && (
          <SpriteIcon
            sheetUrl={SLOTS_SHEET}
            x={DIVINE_SLOT_X}
            y={0}
            nativeSize={SLOT_NATIVE}
            displaySize={ICON_SIZE}
            alt=""
            className="absolute pointer-events-none"
            style={{ top: DIAMOND_FRAME_OFFSET_PX, left: DIAMOND_FRAME_OFFSET_PX }}
          />
        )}
        {showShiny && <ShinyStar size={10} />}
      </Stage>
      <div
        className="pointer-events-none absolute z-20 bottom-full left-1/2 -translate-x-1/2 mb-1.5
          hidden group-hover:block w-max max-w-[200px] rounded-lg bg-[#0d0d0d] border border-[#404040]
          px-2.5 py-1.5 text-[11px] leading-snug text-[#ececec] shadow-xl"
        role="tooltip"
      >
        {showShiny ? `Shiny ${item.name}` : item.name}
        {showcase.rarity === "divine" ? " (Divine)" : ""}
      </div>
    </div>
  );
}

export function LoadoutRow({
  items,
  pendingNames,
  showcase,
}: {
  items?: ItemProfile[];
  pendingNames?: string[];
  showcase: LoadoutShowcase;
}) {
  const loaded = items ?? [];
  const order = (
    pendingNames && pendingNames.length > 0
      ? pendingNames
      : loaded.map((item) => item.name)
  ).slice(0, SET_SLOT_COUNT);
  if (order.length === 0) return null;

  return (
    <div className="mt-3 flex items-center gap-1.5" aria-label="Requested loadout">
      {order.map((rawName, i) => (
        <LoadoutSlot key={`${cleanItemName(rawName).toLowerCase()}-${i}`} item={findLoadoutItem(loaded, rawName)} showcase={showcase} />
      ))}
    </div>
  );
}
