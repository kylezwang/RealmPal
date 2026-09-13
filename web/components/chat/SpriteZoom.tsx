"use client";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  DIVINE_GLOW,
  DIVINE_SLOT_X,
  DIAMOND_FRAME_OFFSET_PX,
  SLOT_NATIVE,
  SLOTS_SHEET,
  ShinyStar,
  SpriteIcon,
} from "./SpriteIcon";

const ZOOM_SIZE = 128;

export type SpriteZoomSource =
  | { kind: "url"; src: string; alt: string }
  | {
      kind: "sheet";
      sheetUrl: string;
      x: number;
      y: number;
      alt: string;
      nativeSize?: number;
      nativeWidth?: number;
      nativeHeight?: number;
    };

export interface SpriteZoomDetails {
  title?: string;
  wikiUrl?: string;
  /** Tooltip or stat lines shown under the title in the zoom view. */
  caption?: string;
  glow?: string;
  divine?: boolean;
  shiny?: boolean;
  slotFrame?: {
    sheetUrl: string;
    x: number;
    y: number;
    nativeSize: number;
  };
}

function ExpandCornersIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
    </svg>
  );
}

function ExternalLinkIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <path d="M15 3h6v6" />
      <path d="M10 14 21 3" />
    </svg>
  );
}

function DecoratedItemSprite({
  source,
  details,
  size,
}: {
  source: SpriteZoomSource;
  details?: SpriteZoomDetails;
  size: number;
}) {
  const glow = details?.glow ?? (details?.divine ? DIVINE_GLOW : undefined);
  const diamond = details?.slotFrame ?? (details?.divine
    ? { sheetUrl: SLOTS_SHEET, x: DIVINE_SLOT_X, y: 0, nativeSize: SLOT_NATIVE }
    : undefined);
  const starSize = Math.max(12, Math.round(size * 0.12));
  const diamondOffset = Math.round(DIAMOND_FRAME_OFFSET_PX * (size / 40));

  return (
    <span className="relative block" style={{ width: size, height: size }}>
      {source.kind === "url" ? (
        <img
          src={source.src}
          alt=""
          width={size}
          height={size}
          className="absolute inset-0 pointer-events-none"
          style={{
            imageRendering: "pixelated",
            width: size,
            height: size,
            filter: glow ? `drop-shadow(${glow} 0 0 3px)` : undefined,
          }}
        />
      ) : (
        <SpriteIcon
          sheetUrl={source.sheetUrl}
          x={source.x}
          y={source.y}
          nativeSize={source.nativeSize}
          nativeWidth={source.nativeWidth}
          nativeHeight={source.nativeHeight}
          displaySize={size}
          alt=""
          className="absolute inset-0 pointer-events-none"
          style={glow ? { filter: `drop-shadow(${glow} 0 0 3px)` } : undefined}
        />
      )}
      {diamond && (
        <SpriteIcon
          sheetUrl={diamond.sheetUrl}
          x={diamond.x}
          y={diamond.y}
          nativeSize={diamond.nativeSize}
          displaySize={size}
          alt=""
          className="absolute pointer-events-none"
          style={{ top: diamondOffset, left: diamondOffset }}
        />
      )}
      {details?.shiny && <ShinyStar size={starSize} />}
    </span>
  );
}

function MenuIconButton({
  label,
  onClick,
  href,
}: {
  label: string;
  onClick?: () => void;
  href?: string;
}) {
  const className =
    "rounded p-1 text-[#a3a3a3] transition-colors hover:text-[#ececec] cursor-pointer";

  if (href) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={className}
        aria-label={label}
        onClick={(e) => e.stopPropagation()}
      >
        <ExternalLinkIcon />
      </a>
    );
  }

  return (
    <span
      role="button"
      tabIndex={0}
      className={className}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
      onKeyDown={(e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        e.stopPropagation();
        onClick?.();
      }}
    >
      <ExpandCornersIcon />
    </span>
  );
}

const NESTED_CONTROL =
  "a[href], button, input, textarea, select, [data-zoom-priority], [role='button'], [role='menuitem']";

function isNestedControl(e: { target: EventTarget; currentTarget: EventTarget }) {
  const target = e.target;
  const root = e.currentTarget;
  if (!(target instanceof Element) || !(root instanceof Element)) return false;
  const nested = target.closest(NESTED_CONTROL);
  return Boolean(nested && nested !== root && root.contains(nested));
}

function ZoomModal({
  title,
  children,
  onClose,
  frame = "sprite",
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  frame?: "sprite" | "card";
}) {
  return createPortal(
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/65 cursor-default"
        aria-label="Close zoom"
        onClick={onClose}
      />
      <div
        className={
          frame === "card"
            ? "relative z-10 animate-fade-in"
            : "relative z-10 flex w-full max-w-sm flex-col items-center rounded-2xl border border-[#404040] bg-[#1e1e1e] px-6 py-5 shadow-2xl animate-fade-in"
        }
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}

function cardZoomScale(width: number, height: number) {
  if (typeof window === "undefined") return 1.2;
  const maxW = Math.max(160, window.innerWidth - 32);
  const maxH = Math.max(120, window.innerHeight - 32);
  const preferred = width < 240 ? Math.min(2, 280 / Math.max(width, 1)) : 1.25;
  return Math.max(1.05, Math.min(preferred, maxW / Math.max(width, 1), maxH / Math.max(height, 1)));
}

/** Click a sprite, open a tiny popunder, then expand to a dismissible zoom view. */
export function SpriteZoomTrigger({
  source,
  details,
  children,
  className = "",
  direct = false,
  preview = "sprite",
  previewContent,
}: {
  source?: SpriteZoomSource;
  details?: SpriteZoomDetails;
  children: ReactNode;
  className?: string;
  /** Skip the popunder. Click opens the centered zoom modal. */
  direct?: boolean;
  /** `card` clones the trigger contents, scaled up, instead of a sprite sheet. */
  preview?: "sprite" | "card";
  /** Optional full-size card for the zoom modal. Defaults to `children`. */
  previewContent?: ReactNode;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [zoomOpen, setZoomOpen] = useState(false);
  const [cardScale, setCardScale] = useState(1.25);
  const [cardWidth, setCardWidth] = useState<number | undefined>(undefined);
  const anchorRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const title = details?.title || source?.alt || "Zoom";

  useEffect(() => {
    if (!menuOpen && !zoomOpen) return;
    function onDocClick(e: MouseEvent) {
      const target = e.target as Node;
      if (anchorRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setMenuOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      if (zoomOpen) setZoomOpen(false);
      else setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen, zoomOpen]);

  useLayoutEffect(() => {
    if (!zoomOpen || preview !== "card") return;
    const width = anchorRef.current?.offsetWidth ?? 360;
    setCardWidth(width);
  }, [preview, zoomOpen]);

  useLayoutEffect(() => {
    if (!zoomOpen || preview !== "card" || cardWidth == null) return;
    const height = previewRef.current?.offsetHeight ?? anchorRef.current?.offsetHeight ?? 80;
    setCardScale(cardZoomScale(cardWidth, height));
  }, [cardWidth, preview, zoomOpen]);

  const zoomSprite = source ? (
    <div
      className="flex shrink-0 items-center justify-center"
      style={{ width: ZOOM_SIZE, height: ZOOM_SIZE }}
    >
      <DecoratedItemSprite source={source} details={details} size={ZOOM_SIZE} />
    </div>
  ) : null;

  const zoomBody =
    preview === "card" ? (
      <div
        ref={previewRef}
        className="pointer-events-none origin-center rounded-xl shadow-2xl"
        style={{
          width: cardWidth,
          transform: `scale(${cardScale})`,
        }}
      >
        {previewContent ?? children}
      </div>
    ) : (
      <>
        {zoomSprite}
        <p className="mt-4 w-full text-center text-sm font-medium leading-snug text-[#ececec]">
          {title}
        </p>
        {details?.caption ? (
          <p className="mt-2 w-full max-w-xs text-center text-xs leading-snug text-[#a3a3a3] whitespace-pre-line">
            {details.caption}
          </p>
        ) : null}
        {!direct && details?.wikiUrl ? (
          <a
            href={details.wikiUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-4 inline-flex items-center gap-1.5 text-xs text-[#a3a3a3] transition-colors hover:text-[#ececec]"
          >
            <ExternalLinkIcon />
            View on RealmEye
          </a>
        ) : null}
      </>
    );

  return (
    <>
      <div ref={anchorRef} className={`relative ${direct ? "block" : "inline-block"} ${className}`}>
        <span
          role="button"
          tabIndex={0}
          className="block cursor-pointer"
          aria-label={`Zoom ${title}`}
          aria-expanded={direct ? zoomOpen : menuOpen}
          onClick={(e) => {
            if (isNestedControl(e)) return;
            e.stopPropagation();
            e.preventDefault();
            if (direct) setZoomOpen(true);
            else setMenuOpen((open) => !open);
          }}
          onKeyDown={(e) => {
            if (e.key !== "Enter" && e.key !== " ") return;
            if (isNestedControl(e)) return;
            e.preventDefault();
            e.stopPropagation();
            if (direct) setZoomOpen(true);
            else setMenuOpen((open) => !open);
          }}
        >
          {children}
        </span>
        {!direct && menuOpen && (
          <div
            ref={menuRef}
            className="absolute z-50 left-1/2 top-full mt-1 -translate-x-1/2 flex items-center gap-0.5 rounded-md border border-[#404040] bg-[#0d0d0d] px-1.5 py-1 shadow-xl"
            role="menu"
          >
            <MenuIconButton
              label={`View ${title} full size`}
              onClick={() => {
                setMenuOpen(false);
                setZoomOpen(true);
              }}
            />
            {details?.wikiUrl ? (
              <MenuIconButton label={`Open ${title} on RealmEye`} href={details.wikiUrl} />
            ) : null}
          </div>
        )}
      </div>
      {zoomOpen && typeof document !== "undefined" && (
        <ZoomModal title={title} onClose={() => setZoomOpen(false)} frame={preview === "card" ? "card" : "sprite"}>
          {zoomBody}
        </ZoomModal>
      )}
    </>
  );
}
