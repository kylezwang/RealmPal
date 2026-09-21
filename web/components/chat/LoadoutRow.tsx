"use client";
import { useEffect, useState } from "react";
import type { ItemProfile } from "@/lib/api";
import { cleanItemName } from "@/lib/itemLookup";
import { SET_SLOT_COUNT, type LoadoutShowcase } from "@/lib/loadoutShowcase";
import { RARITY_GLOW, RARITY_LABEL, RARITY_SLOT_X, DIAMOND_FRAME_OFFSET_PX, SLOT_NATIVE, SLOTS_SHEET, ShinyStar, SpriteIcon } from "./SpriteIcon";
import { SpriteZoomTrigger } from "./SpriteZoom";

const ICON_SIZE = 40;

function statValue(item: ItemProfile, key: string): string | undefined {
  const stats = item.stats || {};
  const found = Object.entries(stats).find(
    ([name]) => name.toLowerCase() === key.toLowerCase(),
  );
  const value = found?.[1];
  if (value == null || String(value).trim() === "") return undefined;
  return String(value).trim();
}

function awakenedLine(item: ItemProfile): string | undefined {
  if (item.awakened_enchant) return item.awakened_enchant;
  const fromStats = statValue(item, "Awakened Enchantment");
  if (!fromStats) return undefined;
  return /^awakened\b/i.test(fromStats) ? fromStats : `Awakened: ${fromStats}`;
}

function loadoutHoverBody(item: ItemProfile): string {
  const bits: string[] = [];
  const onEquip = statValue(item, "On Equip");
  if (onEquip) bits.push(`On Equip: ${onEquip}`);
  const awakened = awakenedLine(item);
  if (awakened) bits.push(awakened);
  else if (!onEquip && item.description) bits.push(item.description);
  return bits.join("\n");
}

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
        className="glimmer rounded-md"
        style={{ width: ICON_SIZE, height: ICON_SIZE }}
        aria-busy="true"
        aria-label="Loading item"
      />
    );
  }
  return <LoadoutItemIcon item={item} showcase={showcase} />;
}

/** One shiny/divine item icon. Quests and visualize-set share this. */
export function LoadoutItemIcon({
  item,
  showcase,
}: {
  item: ItemProfile;
  showcase: LoadoutShowcase;
}) {
  const shinySrc = item.shiny_sprite_url || "";
  const regularSrc = item.sprite_url || "";
  const hasShiny = Boolean(showcase.shiny && shinySrc);
  const preferred = hasShiny ? shinySrc : regularSrc;
  const [src, setSrc] = useState(preferred);
  useEffect(() => {
    setSrc(preferred);
  }, [preferred]);
  const showShiny = hasShiny && src === shinySrc;
  const glow = showcase.rarity ? RARITY_GLOW[showcase.rarity] : undefined;
  const iconSrc = src || regularSrc;
  const hoverTitle = [
    showShiny ? "Shiny" : "",
    item.name,
    showcase.rarity ? `(${RARITY_LABEL[showcase.rarity]})` : "",
  ]
    .filter(Boolean)
    .join(" ");
  const hoverBody = loadoutHoverBody(item);

  return (
    <div className="group relative">
      <div className="relative block" style={{ width: ICON_SIZE, height: ICON_SIZE }}>
        {iconSrc ? (
          <SpriteZoomTrigger
            source={{ kind: "url", src: iconSrc, alt: item.name }}
            details={{
              title: hoverTitle,
              wikiUrl: item.wiki_url,
              caption: hoverBody || undefined,
              divine: showcase.rarity === "divine",
              rarity: showcase.rarity,
              shiny: showShiny,
              glow,
            }}
            className="absolute inset-0"
          >
            <span className="relative block" style={{ width: ICON_SIZE, height: ICON_SIZE }}>
              <img
                src={iconSrc}
                alt=""
                width={ICON_SIZE}
                height={ICON_SIZE}
                className="absolute inset-0 pointer-events-none"
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
              {showcase.rarity && (
                <SpriteIcon
                  sheetUrl={SLOTS_SHEET}
                  x={RARITY_SLOT_X[showcase.rarity]}
                  y={0}
                  nativeSize={SLOT_NATIVE}
                  displaySize={ICON_SIZE}
                  alt=""
                  className="absolute pointer-events-none"
                  style={{ top: DIAMOND_FRAME_OFFSET_PX, left: DIAMOND_FRAME_OFFSET_PX }}
                />
              )}
              {showShiny && <ShinyStar size={10} />}
            </span>
          </SpriteZoomTrigger>
        ) : (
          <div
            className="absolute inset-0 glimmer rounded-md"
            aria-hidden
          />
        )}
      </div>
      <div
        className="pointer-events-none absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-1.5
          hidden group-hover:block w-max max-w-[240px] rounded-lg bg-[#0d0d0d] border border-[#404040]
          px-2.5 py-1.5 text-[11px] leading-snug text-[#ececec] shadow-xl whitespace-pre-line"
        role="tooltip"
      >
        {hoverTitle}
        {hoverBody ? <span className="block mt-1 text-[#c4c4c4]">{hoverBody}</span> : null}
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
