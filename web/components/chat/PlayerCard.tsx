"use client";
import { useEffect, useState } from "react";
import type { CharacterStats, CharacterSummary, EquipmentItem, ExaltationEntry, PlayerProfile } from "@/lib/api";
import { fetchPlayer } from "@/lib/api";
import { SpriteIcon, ShinyStar, isShinyTooltip, DIAMOND_FRAME_OFFSET_PX } from "./SpriteIcon";
import { SpriteZoomTrigger } from "./SpriteZoom";
import { PetSprite } from "./PetCompanion";
import { FAME_SPRITE } from "@/lib/sprites";

// RotMG characters have a fixed loadout: weapon, ability, armor, ring, bag.
// Characters missing a slot (nothing equipped there) come back from the
// scraper with fewer than 5 equipment entries | always rendering exactly
// this many icon slots (blank ones for the missing gear) keeps the
// equipment column's width constant, so the maxed-stats badge next to it
// doesn't shift left/right depending on how many items a character has.
const EQUIPMENT_SLOTS = 5;
const EQUIPMENT_ICON_SIZE = 40;
/** slots.png is one 9-tile strip (48px tiles, all y=0): tiles at x=0/48/96/144
 * are the four plain rarity-diamond frames (0-pip green, 2-pip blue, 2-pip
 * purple, 4-pip gold); x=192/240/288/336 are those exact same four frames
 * again with RealmEye's own star baked into the top-left corner; x=384 is a
 * fifth, diamond-less shiny frame — just the star, no pips, with no plain
 * counterpart at all. We paint our own `<ShinyStar>` on every shiny item
 * ourselves (so it looks and sits the same everywhere), so the frame drawn
 * underneath should always be a *plain* one — naively subtracting 192 from
 * x=384 lands back on x=192, which is itself a baked-star tile, so
 * top-rarity shiny items ended up with a wrong diamond *and* two stars. */
const SHINY_SLOT_OFFSET = 192;
const SLOT_TILE_WIDTH = 48;
const PLAIN_SLOT_MAX_X = SHINY_SLOT_OFFSET - SLOT_TILE_WIDTH;

/** Plain (star-free) diamond tile for a scraped slot-frame x, or null when
 * the item has no rarity pips at all (shiny-only sparkle, x=384). */
function diamondSlotX(slotX: number): number | null {
  if (slotX < SHINY_SLOT_OFFSET) return slotX;
  const plain = slotX - SHINY_SLOT_OFFSET;
  return plain <= PLAIN_SLOT_MAX_X ? plain : null;
}

/**
 * Rich character/equipment card rendered under an assistant chat message
 * when it's about a specific player | mirrors RealmEye's own characters
 * table (portrait, fame, placement, equipped items, maxed-stats badge),
 * including hovering an item to see its full tooltip, plus a per-class
 * Exaltations breakdown below the character list.
 */
export function PlayerCard({
  profile,
  showExaltationTable,
  highlightClass,
  focusCharacter,
}: {
  profile: PlayerProfile;
  /** Render the full per-class exaltations breakdown | only when the user
   * actually asked about exaltations, since it's a lot of extra detail
   * nobody wants tacked onto every player lookup by default. */
  showExaltationTable?: boolean;
  /** Class named in this turn. The full character list still renders with
   * the same hover tooltips; this row just gets a ring so a DPS ask does
   * not look like a generic account lookup. */
  highlightClass?: string;
  /** DPS asks: render only this class's row, not the rest of the account. */
  focusCharacter?: boolean;
}) {
  const [live, setLive] = useState(profile);
  const needsStats = (live.characters ?? []).some(
    (character) => character.stats_maxed && !character.stats,
  );

  useEffect(() => {
    setLive(profile);
  }, [profile]);

  useEffect(() => {
    if (!needsStats) return;
    let cancelled = false;
    fetchPlayer(live.username)
      .then((fresh) => {
        if (!cancelled && fresh.characters?.some((character) => character.stats)) {
          setLive(fresh);
        }
      })
      .catch(() => {
        // Keep the card we already have; hover just won't have a breakdown.
      });
    return () => {
      cancelled = true;
    };
  }, [needsStats, live.username]);

  if (!live.characters || live.characters.length === 0) return null;

  const classKey = (highlightClass || "").toLowerCase();
  const focused = (live.characters ?? []).filter(
    (character) =>
      Boolean(focusCharacter) &&
      Boolean(classKey) &&
      (character.class_name || "").toLowerCase() === classKey,
  );
  const rows = focused.length > 0 ? focused : live.characters;
  const heading =
    focusCharacter && highlightClass && focused.length > 0 ? highlightClass : "Characters";

  return (
    <div className="mt-3 flex flex-col gap-1.5 max-w-full">
      {/* Same size/weight as the player name heading above the AI's reply |
       * this is the section label for the character rows below, which sit
       * at the very end of the message (after the reply text and Sources). */}
      <p className="text-lg font-semibold text-[#ececec] leading-tight mb-1">{heading}</p>
      {rows.map((character, i) => (
        <CharacterRow
          key={i}
          character={character}
          pet={live.top_pet}
          highlighted={
            Boolean(classKey) &&
            (character.class_name || "").toLowerCase() === classKey
          }
        />
      ))}
      {!focusCharacter && showExaltationTable && live.exaltations && live.exaltations.length > 0 && (
        <div className="mt-2">
          <div className="text-[11px] font-semibold text-[#8a8a8a] uppercase tracking-wide mb-1.5 px-1">
            Exaltations
          </div>
          <div className="flex flex-col gap-1.5">
            {live.exaltations.map((exaltation, i) => (
              <ExaltationRow key={i} exaltation={exaltation} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CharacterRow({
  character,
  pet,
  highlighted,
}: {
  character: CharacterSummary;
  pet?: PlayerProfile["top_pet"];
  highlighted?: boolean;
}) {
  const hasSprite =
    character.sprite_sheet_url != null &&
    character.sprite_x != null &&
    character.sprite_y != null &&
    character.sprite_width != null;

  const row = (
    <div
      className={`flex items-center gap-3 rounded-xl px-3 py-2.5 border ${
        highlighted
          ? "bg-[#2a261c] border-[#7c6a46]"
          : "bg-[#212121] border-[#333333]"
      }`}
    >
      {hasSprite ? (
        <SpriteIcon
          sheetUrl={character.sprite_sheet_url!}
          x={character.sprite_x!}
          y={character.sprite_y!}
          nativeWidth={character.sprite_width!}
          nativeHeight={character.sprite_height ?? character.sprite_width!}
          displaySize={44}
          alt=""
        />
      ) : (
        <div className="w-11 h-11 flex items-center justify-center text-xl flex-shrink-0" aria-hidden="true">
          ⚔️
        </div>
      )}

      <div className="min-w-[92px]">
        <div className="font-medium text-sm text-[#ececec]">{character.class_name}</div>
        <div className="text-[11px] text-[#8a8a8a] flex gap-2.5 flex-wrap">
          {character.fame != null && (
            <span className="inline-flex items-center gap-1 align-middle">
              <span>Fame</span>
              <img
                src={FAME_SPRITE}
                alt=""
                width={12}
                height={12}
                style={{ imageRendering: "pixelated", width: 12, height: 12 }}
              />
              <span>{character.fame.toLocaleString()}</span>
            </span>
          )}
          {character.place != null && (
            character.place_url ? (
              <a
                href={character.place_url}
                target="_blank"
                rel="noopener noreferrer"
                className="relative z-10 hover:text-[#ececec] hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                Rank #{character.place.toLocaleString()}
              </a>
            ) : (
              <span>Rank #{character.place.toLocaleString()}</span>
            )
          )}
        </div>
      </div>

      {/* Pet is its own column immediately left of x/8, then equipment
       * stays grouped on the far right. */}
      <div className="flex items-center gap-10 ml-auto">
        <div className="flex items-center gap-8 flex-shrink-0">
          {pet ? <PetSprite pet={pet} size={32} /> : null}
          {character.stats_maxed && (
            <StatsBadge
              label={character.stats_maxed}
              stats={character.stats}
              bonuses={character.stat_bonuses}
            />
          )}
        </div>
        <div className="flex gap-1.5 relative z-10">
          {Array.from({ length: EQUIPMENT_SLOTS }, (_, i) => character.equipment?.[i]).map((item, i) =>
            item ? <EquipmentIcon key={i} item={item} /> : <EmptyEquipmentSlot key={i} />
          )}
        </div>
      </div>
    </div>
  );

  return (
    <SpriteZoomTrigger
      details={{ title: character.class_name }}
      direct
      preview="card"
      className="block w-full"
    >
      {row}
    </SpriteZoomTrigger>
  );
}

function EquipmentIcon({ item }: { item: EquipmentItem }) {
  // Missing sprite data (bad scrape) still reserves its slot's width via
  // EmptyEquipmentSlot, rather than collapsing to nothing.
  if (item.sprite_sheet_url == null || item.sprite_x == null || item.sprite_y == null || !item.sprite_size) {
    return <EmptyEquipmentSlot />;
  }

  const hasSlot =
    item.slot_sprite_sheet_url != null &&
    item.slot_sprite_x != null &&
    item.slot_sprite_y != null &&
    !!item.slot_sprite_size;
  const diamondX = hasSlot ? diamondSlotX(item.slot_sprite_x!) : null;

  return (
    <div className="group relative z-10">
      <SpriteZoomTrigger
        source={{
          kind: "sheet",
          sheetUrl: item.sprite_sheet_url,
          x: item.sprite_x,
          y: item.sprite_y,
          nativeSize: item.sprite_size,
          alt: item.name,
        }}
        details={{
          title: item.name,
          wikiUrl: item.wiki_url,
          caption: item.tooltip,
          glow: item.glow_color,
          shiny: isShinyTooltip(item.tooltip),
          slotFrame:
            diamondX != null
              ? {
                  sheetUrl: item.slot_sprite_sheet_url!,
                  x: diamondX,
                  y: item.slot_sprite_y!,
                  nativeSize: item.slot_sprite_size!,
                }
              : undefined,
        }}
        className="relative z-10 block"
      >
        <span
          className="relative block"
          style={{ width: EQUIPMENT_ICON_SIZE, height: EQUIPMENT_ICON_SIZE }}
        >
          <SpriteIcon
            sheetUrl={item.sprite_sheet_url}
            x={item.sprite_x}
            y={item.sprite_y}
            nativeSize={item.sprite_size}
            displaySize={EQUIPMENT_ICON_SIZE}
            alt=""
            className="absolute inset-0 pointer-events-none"
            style={item.glow_color ? { filter: `drop-shadow(${item.glow_color} 0 0 2px)` } : undefined}
          />
          {diamondX != null && (
            <SpriteIcon
              sheetUrl={item.slot_sprite_sheet_url!}
              x={diamondX}
              y={item.slot_sprite_y!}
              nativeSize={item.slot_sprite_size!}
              displaySize={EQUIPMENT_ICON_SIZE}
              alt=""
              className="absolute pointer-events-none"
              style={{ top: DIAMOND_FRAME_OFFSET_PX, left: DIAMOND_FRAME_OFFSET_PX }}
            />
          )}
          {isShinyTooltip(item.tooltip) && <ShinyStar size={10} />}
        </span>
      </SpriteZoomTrigger>
      {/* Hover tooltip, same idea as RealmEye's own item hover popover */}
      <div
        className="pointer-events-none absolute z-20 bottom-full left-1/2 -translate-x-1/2 mb-1.5
          hidden group-hover:block w-max max-w-[240px] rounded-lg bg-[#0d0d0d] border border-[#404040]
          px-2.5 py-1.5 text-[11px] leading-snug text-[#ececec] shadow-xl whitespace-pre-line"
        role="tooltip"
      >
        {item.tooltip}
      </div>
    </div>
  );
}

/** Reserves the same footprint as a real equipped item, for an unequipped
 * slot | keeps every character row's equipment column the same width so
 * the maxed-stats badge next to it stays put regardless of loadout size. */
function EmptyEquipmentSlot() {
  return (
    <div
      className="rounded-md border border-dashed border-[#333333]"
      style={{ width: EQUIPMENT_ICON_SIZE, height: EQUIPMENT_ICON_SIZE }}
      aria-hidden="true"
    />
  );
}

const CHARACTER_STATS: Array<{ key: keyof CharacterStats; label: string }> = [
  { key: "hp", label: "HP" },
  { key: "mp", label: "MP" },
  { key: "attack", label: "ATT" },
  { key: "defense", label: "DEF" },
  { key: "speed", label: "SPD" },
  { key: "dexterity", label: "DEX" },
  { key: "vitality", label: "VIT" },
  { key: "wisdom", label: "WIS" },
];

function formatBonus(value: number): string {
  return value > 0 ? `+${value}` : String(value);
}

function StatsBadge({
  label,
  stats,
  bonuses,
}: {
  label: string;
  stats?: CharacterStats;
  bonuses?: CharacterStats;
}) {
  const rows = CHARACTER_STATS.map(({ key, label: name }) => {
    const value = stats?.[key];
    if (value == null) return null;
    const bonus = bonuses?.[key] ?? 0;
    return { key, name, value, bonus };
  }).filter((row): row is { key: keyof CharacterStats; name: string; value: number; bonus: number } => row != null);

  const badge = (
    <span className="text-[11px] font-medium text-amber-400/90 whitespace-nowrap">
      {label}
    </span>
  );

  if (rows.length === 0) return badge;

  return (
    <div className="group relative">
      <span
        className="cursor-help"
        aria-label={`${label}: ${rows.map((row) => `${row.name} ${row.value}`).join(", ")}`}
      >
        {badge}
      </span>
      <div
        className="pointer-events-none absolute z-20 bottom-full right-0 mb-1.5
          hidden group-hover:block w-max rounded-lg bg-[#0d0d0d] border border-[#404040]
          px-2.5 py-1.5 text-[11px] leading-snug text-[#ececec] shadow-xl"
        role="tooltip"
      >
        <div className="grid grid-cols-[2.5rem_2.75rem_2.25rem] gap-x-2 gap-y-0.5 tabular-nums">
          {rows.map((row) => (
            <div key={row.key} className="contents">
              <span className="text-[#8a8a8a]">{row.name}</span>
              <span className="text-right text-[#ececec]">{row.value.toLocaleString()}</span>
              <span className={`text-right ${row.bonus ? "text-amber-400/90" : "text-transparent"}`}>
                {row.bonus ? formatBonus(row.bonus) : "0"}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// RotMG exalts Max HP/MP up to +25 each, the other six stats up to +5 each
// | a stat hitting its cap gets called out in gold, same treatment as the
// per-character maxed-stats badge above.
const EXALT_STATS: Array<{ key: keyof ExaltationEntry; label: string; max: number }> = [
  { key: "max_hp", label: "HP", max: 25 },
  { key: "max_mp", label: "MP", max: 25 },
  { key: "attack", label: "ATT", max: 5 },
  { key: "defense", label: "DEF", max: 5 },
  { key: "speed", label: "SPD", max: 5 },
  { key: "dexterity", label: "DEX", max: 5 },
  { key: "vitality", label: "VIT", max: 5 },
  { key: "wisdom", label: "WIS", max: 5 },
];

function ExaltationRow({ exaltation }: { exaltation: ExaltationEntry }) {
  const hasSprite =
    exaltation.sprite_sheet_url != null &&
    exaltation.sprite_x != null &&
    exaltation.sprite_y != null &&
    exaltation.sprite_width != null;

  const row = (
    <div className="flex items-center gap-3 rounded-xl bg-[#212121] border border-[#333333] px-3 py-2">
      {hasSprite ? (
        <SpriteIcon
          sheetUrl={exaltation.sprite_sheet_url!}
          x={exaltation.sprite_x!}
          y={exaltation.sprite_y!}
          nativeWidth={exaltation.sprite_width!}
          nativeHeight={exaltation.sprite_height ?? exaltation.sprite_width!}
          displaySize={36}
          alt=""
        />
      ) : (
        <div className="w-9 h-9 flex items-center justify-center text-lg flex-shrink-0" aria-hidden="true">
          ✨
        </div>
      )}

      <div className="min-w-[76px]">
        <div className="font-medium text-sm text-[#ececec]">{exaltation.class_name}</div>
        {exaltation.exaltation_count != null && (
          <div className="text-[11px] text-[#8a8a8a]">{exaltation.exaltation_count} exalted</div>
        )}
      </div>

      <div className="flex items-center gap-2.5 flex-wrap ml-auto">
        {EXALT_STATS.map(({ key, label, max }) => {
          const value = exaltation[key] as number | undefined;
          if (value == null) return null;
          const maxed = value >= max;
          return (
            <span
              key={key}
              className={`text-[11px] font-medium whitespace-nowrap ${
                maxed ? "text-amber-400/90" : "text-[#a3a3a3]"
              }`}
            >
              {label} +{value}
            </span>
          );
        })}
      </div>
    </div>
  );

  return (
    <SpriteZoomTrigger
      details={{ title: exaltation.class_name }}
      direct
      preview="card"
      className="block w-full"
    >
      {row}
    </SpriteZoomTrigger>
  );
}
