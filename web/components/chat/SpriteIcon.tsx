"use client";

interface SpriteIconProps {
  /** URL of the shared sprite sheet image this icon is cropped from. */
  sheetUrl: string;
  /** Crop offset (pixel coordinates in the *native*, unscaled sheet). */
  x: number;
  y: number;
  /** Native (unscaled) width/height of one icon in the sheet. Square icons
   * only need `nativeSize`; non-square ones (e.g. character portraits) can
   * pass `nativeWidth`/`nativeHeight` instead. */
  nativeSize?: number;
  nativeWidth?: number;
  nativeHeight?: number;
  /** Rendered size in px. Defaults to the native size (no scaling). */
  displaySize?: number;
  alt?: string;
  className?: string;
  /** Extra styles merged onto the outer (clipped) box, e.g. a rarity-glow
   * `filter: drop-shadow(...)` | applied here rather than the inner scaled
   * div so it's computed off the final clipped/visible shape. */
  style?: React.CSSProperties;
}

/** RealmEye paints the shiny sparkle from the s-tier tiles on slots.png
 * (s2 starts at x=240). The star itself sits at +5,+5 inside that 48px
 * tile (an 8px sparkle), same sheet as the rarity diamond frames. */
export const SLOTS_SHEET = "https://www.realmeye.com/s/ht/img/slots.png";
const SHINY_STAR_X = 245;
const SHINY_STAR_Y = 5;
const SHINY_STAR_NATIVE = 8;
export const SLOT_NATIVE = 48;
/** slots.png y=0 tiles: uncommon 1, rare 2, legendary 3, divine 4. */
export const RARITY_SLOT_X = {
  uncommon: 0,
  rare: 48,
  legendary: 96,
  divine: 144,
} as const;
export const RARITY_GLOW = {
  uncommon: "rgb(80, 170, 80)",
  rare: "rgb(64, 128, 210)",
  legendary: "rgb(160, 90, 200)",
  divine: "rgb(191, 170, 64)",
} as const;
export const RARITY_LABEL = {
  uncommon: "Uncommon",
  rare: "Rare",
  legendary: "Legendary",
  divine: "Divine",
} as const;
/** Plain Divine frame (4 gold diamonds) on slots.png. Shiny Divine is +192. */
export const DIVINE_SLOT_X = RARITY_SLOT_X.divine;
export const DIVINE_GLOW = RARITY_GLOW.divine;
/** Nudge rarity diamonds down-right so they sit on the item corners. */
export const DIAMOND_FRAME_OFFSET_PX = 3;
/** Center of the original slot sparkle, as a % of the icon box. */
const SHINY_STAR_CENTER_PCT = ((SHINY_STAR_Y + SHINY_STAR_NATIVE / 2) / SLOT_NATIVE) * 100;
/** First overlay sat at -1px (too far out). Sit halfway between that and the slot sparkle. */
const SHINY_STAR_OUTER_PX = -1;

export function isShinyTooltip(tooltip?: string): boolean {
  return /\(\s*shiny\s*\)/i.test(tooltip || "");
}

/** Small 4-pointed star tucked into the top-left of a shiny item icon. */
export function ShinyStar({ size = 10 }: { size?: number }) {
  return (
    <SpriteIcon
      sheetUrl={SLOTS_SHEET}
      x={SHINY_STAR_X}
      y={SHINY_STAR_Y}
      nativeWidth={SHINY_STAR_NATIVE}
      nativeHeight={SHINY_STAR_NATIVE}
      displaySize={size}
      alt=""
      className="absolute pointer-events-none z-[2]"
      style={{
        top: `calc((${SHINY_STAR_CENTER_PCT}% - ${size / 2}px + ${SHINY_STAR_OUTER_PX}px) / 2)`,
        left: `calc((${SHINY_STAR_CENTER_PCT}% - ${size / 2}px + ${SHINY_STAR_OUTER_PX}px) / 2)`,
      }}
    />
  );
}

/**
 * Renders one icon cropped out of a RealmEye CSS sprite sheet, e.g.:
 *   <span class="pet" style="background-position: -336px -288px;"></span>
 *   <a class="character" style="background-position: -12100px -550px">
 *   <span class="item" style="background-position:-19536px -0px"></span>
 * All three (pets, character portraits, items) use the same technique |
 * one big shared image, cropped via `background-position`.
 *
 * We don't know each sheet's full intrinsic dimensions (only one icon's
 * native size), so we can't compute a `background-size` scale factor
 * directly. Instead we render an inner box at the *native* icon size (where
 * the plain pixel background-position offset is correct) inside an
 * `overflow: hidden` box, then use a CSS `transform: scale()` to visually
 * resize the whole painted box down to the target display size | this
 * scales the background paint along with the box, without ever needing the
 * sheet's total size.
 */
export function SpriteIcon({
  sheetUrl,
  x,
  y,
  nativeSize,
  nativeWidth,
  nativeHeight,
  displaySize,
  alt,
  className,
  style,
}: SpriteIconProps) {
  const w = nativeWidth ?? nativeSize ?? 48;
  const h = nativeHeight ?? nativeSize ?? 48;
  const size = displaySize ?? Math.max(w, h);
  const scale = size / Math.max(w, h);

  return (
    <div
      className={className}
      style={{
        width: w * scale,
        height: h * scale,
        overflow: "hidden",
        flexShrink: 0,
        display: "inline-block",
        ...style,
      }}
      role="img"
      aria-label={alt}
    >
      <div
        style={{
          width: w,
          height: h,
          transform: `scale(${scale})`,
          transformOrigin: "top left",
          backgroundImage: `url(${sheetUrl})`,
          backgroundPosition: `-${x}px -${y}px`,
          imageRendering: "pixelated",
        }}
      />
    </div>
  );
}
