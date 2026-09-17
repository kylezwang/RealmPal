"use client";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { ItemProfile } from "@/lib/api";
import { cleanItemName, isGridWearableItem, ITEM_CARD_ROW_SIZE, skipDungeonItemCard } from "@/lib/itemLookup";
import { ShinyStar } from "./SpriteIcon";
import { SpriteZoomTrigger } from "./SpriteZoom";

const ITEM_ROW_MAX_HEIGHT = 170;

function formatTier(tier: string): string {
  const trimmed = tier.trim();
  if (/^\d+$/.test(trimmed)) return `T${trimmed}`;
  return trimmed;
}

function formatStatValue(key: string, value: string): string {
  if (!/^tier$/i.test(key)) return value;
  return formatTier(value);
}

function displayName(item: ItemProfile | string): string {
  return cleanItemName(typeof item === "string" ? item : item.name);
}

function Glimmer({ className }: { className: string }) {
  return <div className={`glimmer rounded ${className}`} />;
}

function formatItemCaption(item: ItemProfile): string | undefined {
  const stats = Object.entries(item.stats || {}).filter(
    ([key, value]) => key && value && !/^reskin/i.test(key),
  );
  const lines = stats.map(([key, value]) => `${key}: ${formatStatValue(key, value)}`);
  if (item.drop_locations?.length) {
    lines.push(`Drops from: ${item.drop_locations.join(", ")}`);
  }
  if (lines.length === 0) return undefined;
  return lines.join("\n");
}

function WikiSprite({
  src,
  alt,
  size,
  shiny,
  item,
}: {
  src: string;
  alt: string;
  size: number;
  shiny?: boolean;
  item?: ItemProfile;
}) {
  const title = alt || item?.name || "";
  return (
    <SpriteZoomTrigger
      source={{ kind: "url", src, alt: title }}
      details={{
        title,
        wikiUrl: item?.wiki_url,
        caption: item ? formatItemCaption(item) : undefined,
        shiny,
      }}
      className="flex-shrink-0"
    >
      <span className="relative inline-block" style={{ width: size, height: size }}>
        <img
          src={src}
          alt=""
          width={size}
          height={size}
          className="pointer-events-none"
          style={{ imageRendering: "pixelated", width: size, height: size }}
        />
        {shiny && <ShinyStar size={Math.max(8, Math.round(size * 0.28))} />}
      </span>
    </SpriteZoomTrigger>
  );
}

/** Inline sprite + name for markdown tables and prose. */
export function ItemChip({
  name,
  item,
  loading,
}: {
  name: string;
  item?: ItemProfile;
  loading?: boolean;
}) {
  const label = displayName(item ?? name);
  if (loading && !item) {
    return (
      <span className="inline-flex items-center gap-1 align-middle py-0.5" aria-busy="true">
        <Glimmer className="w-6 h-6" />
        <Glimmer className="h-3 w-20" />
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 align-middle max-w-[12rem]">
      {item?.sprite_url ? (
        <WikiSprite src={item.sprite_url} alt={label} size={24} item={item} />
      ) : null}
      <span className="truncate text-[12px] leading-tight">{label}</span>
    </span>
  );
}

export function ItemCardSkeleton() {
  return (
    <div
      className="item-card-panel rounded-xl bg-[#212121] border border-[#333333] px-3 py-3 overflow-hidden"
      style={{ maxHeight: "var(--item-card-max-height, 170px)" }}
      aria-busy="true"
    >
      <div className="flex items-start gap-3">
        <Glimmer className="w-10 h-10" />
        <div className="flex-1 space-y-2 pt-1">
          <Glimmer className="h-4 w-2/3" />
          <Glimmer className="h-3 w-12" />
        </div>
      </div>
      <Glimmer className="h-3 w-full mt-3" />
      <Glimmer className="h-3 w-5/6 mt-2" />
      <div className="mt-3 space-y-1.5">
        <Glimmer className="h-3 w-full" />
        <Glimmer className="h-3 w-4/5" />
        <Glimmer className="h-3 w-3/4" />
      </div>
    </div>
  );
}

/**
 * Dedicated item card modeled on RealmEye's wiki infobox: sprite (+ shiny
 * recast when present), flavor text, and the full stat table. Reskins are
 * never shown | the scraper drops that row before we get here.
 */
function CardSprite({
  src,
  size,
  shiny,
}: {
  src: string;
  size: number;
  shiny?: boolean;
}) {
  return (
    <span className="relative inline-block" style={{ width: size, height: size }}>
      <img
        src={src}
        alt=""
        width={size}
        height={size}
        className="pointer-events-none"
        style={{ imageRendering: "pixelated", width: size, height: size }}
      />
      {shiny && <ShinyStar size={Math.max(8, Math.round(size * 0.28))} />}
    </span>
  );
}

function ItemCardBody({
  item,
  name,
  stats,
  expanded = false,
}: {
  item: ItemProfile;
  name: string;
  stats: [string, string][];
  expanded?: boolean;
}) {
  return (
    <div
      className={`item-card-panel rounded-xl bg-[#212121] border border-[#333333] px-3 py-2.5 ${
        expanded ? "overflow-visible" : "h-full overflow-hidden"
      }`}
      style={expanded ? undefined : { maxHeight: "var(--item-card-max-height, 170px)" }}
    >
      <div className="flex items-start gap-2.5">
        <div className="flex items-start gap-1 flex-shrink-0">
          {item.sprite_url && <CardSprite src={item.sprite_url} size={36} />}
          {item.shiny_sprite_url && (
            <CardSprite src={item.shiny_sprite_url} size={36} shiny />
          )}
        </div>
        <div className="min-w-0">
          <div className="font-semibold text-sm text-[#ececec] leading-tight">{name}</div>
          {item.tier && (
            <div className="text-[11px] text-amber-400/90 mt-0.5">{formatTier(item.tier)}</div>
          )}
        </div>
      </div>

      {item.description && (
        <p className="text-[11px] text-[#a3a3a3] mt-2 leading-snug">{item.description}</p>
      )}

      {stats.length > 0 && (
        <table className="mt-2 w-full text-[11px] border-collapse">
          <tbody>
            {stats.map(([key, value]) => (
              <tr key={key} className="align-top">
                <th className="text-left font-medium text-[#8a8a8a] pr-2 py-0.5 whitespace-nowrap w-[32%]">
                  {key}
                </th>
                <td className="text-[#ececec] py-0.5 whitespace-pre-line">
                  {formatStatValue(key, value)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {item.drop_locations && item.drop_locations.length > 0 && (
        <p className="text-[11px] text-[#a3a3a3] mt-2 leading-snug">
          Drops from {item.drop_locations.join(", ")}
        </p>
      )}

      {item.wiki_url && (
        <a
          href={item.wiki_url}
          target="_blank"
          rel="noopener noreferrer"
          className="relative z-10 inline-block mt-2 text-[11px] text-blue-400 hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          {item.wiki_url.replace(/^https?:\/\//, "")}
        </a>
      )}
    </div>
  );
}

export function ItemCard({ item }: { item: ItemProfile }) {
  const stats = Object.entries(item.stats || {}).filter(
    ([key, value]) => key && value && !/^reskin/i.test(key)
  );
  const name = displayName(item);

  return (
    <SpriteZoomTrigger
      details={{
        title: item.shiny_sprite_url ? `Shiny ${name}` : name,
        shiny: Boolean(item.shiny_sprite_url),
      }}
      direct
      preview="card"
      previewContent={<ItemCardBody item={item} name={name} stats={stats} expanded />}
      className="h-full"
    >
      <ItemCardBody item={item} name={name} stats={stats} />
    </SpriteZoomTrigger>
  );
}

function CollapsibleItemRow({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const innerRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const el = innerRef.current;
    if (!el) return;
    const measure = () => {
      const panels = el.querySelectorAll<HTMLElement>(".item-card-panel");
      const tallest = Math.max(
        el.scrollHeight,
        ...Array.from(panels, (panel) => panel.scrollHeight),
      );
      setOverflows(tallest > ITEM_ROW_MAX_HEIGHT + 4);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [children]);

  return (
    <div
      className="relative"
      style={{ ["--item-card-max-height" as string]: open ? "none" : `${ITEM_ROW_MAX_HEIGHT}px` }}
    >
      <div
        ref={innerRef}
        className={open ? "" : "overflow-hidden"}
        style={open ? undefined : { maxHeight: ITEM_ROW_MAX_HEIGHT }}
      >
        {children}
      </div>
      {overflows && !open && (
        <div
          className="absolute inset-x-0 bottom-0 flex justify-center pt-12 pb-1
            bg-gradient-to-t from-[#1a1a1a] via-[#1a1a1a]/85 to-transparent"
        >
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="text-[11px] text-[#ececec] bg-[#2a2a2a] border border-[#404040]
              hover:border-white rounded-md px-2.5 py-1 cursor-pointer"
          >
            See more
          </button>
        </div>
      )}
      {overflows && open && (
        <div className="flex justify-center mt-1">
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="text-[11px] text-[#a3a3a3] hover:text-[#ececec] cursor-pointer"
          >
            See less
          </button>
        </div>
      )}
    </div>
  );
}

export function ItemCardGrid({
  items,
  pendingNames,
}: {
  items?: ItemProfile[];
  pendingNames?: string[];
}) {
  const loaded = (items ?? []).filter(isGridWearableItem);
  const hidden = new Set(
    (items ?? [])
      .filter((item) => !isGridWearableItem(item))
      .flatMap((item) => [item.name, item.requestedAs ?? ""])
      .map((name) => cleanItemName(name).toLowerCase())
      .filter(Boolean),
  );
  const byKey = new Map(loaded.map((item) => [cleanItemName(item.name).toLowerCase(), item]));
  const order = (
    pendingNames && pendingNames.length > 0
      ? pendingNames
      : loaded.map((item) => item.name)
  ).filter(
    (name) =>
      !skipDungeonItemCard(name) && !hidden.has(cleanItemName(name).toLowerCase()),
  );
  if (order.length === 0) return null;

  const ready = order.filter((name) => byKey.has(cleanItemName(name).toLowerCase()));
  const waiting = order.filter((name) => !byKey.has(cleanItemName(name).toLowerCase()));
  const loading = waiting.slice(0, ITEM_CARD_ROW_SIZE);

  const colsForRow = (row: number) =>
    row % 2 === 0
      ? "grid-cols-1 sm:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]"
      : "grid-cols-1 sm:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]";

  const readyRows: string[][] = [];
  for (let i = 0; i < ready.length; i += ITEM_CARD_ROW_SIZE) {
    readyRows.push(ready.slice(i, i + ITEM_CARD_ROW_SIZE));
  }

  if (ready.length === 0 && loading.length === 1) {
    return (
      <div className="mt-3 max-w-md">
        <CollapsibleItemRow>
          <ItemCardSkeleton />
        </CollapsibleItemRow>
      </div>
    );
  }

  if (ready.length === 1 && loading.length === 0) {
    const item = byKey.get(cleanItemName(ready[0]).toLowerCase());
    return (
      <div className="mt-3 max-w-md">
        <CollapsibleItemRow>
          {item ? <ItemCard item={item} /> : <ItemCardSkeleton />}
        </CollapsibleItemRow>
      </div>
    );
  }

  return (
    <div className="mt-3 flex flex-col gap-2">
      {readyRows.map((row, ri) => (
        <CollapsibleItemRow key={`ready-${ri}`}>
          <div className={`grid ${colsForRow(ri)} gap-2 items-start`}>
            {row.map((rawName, i) => {
              const key = cleanItemName(rawName).toLowerCase();
              const item = byKey.get(key);
              if (item) return <ItemCard key={`${key}-${ri}-${i}`} item={item} />;
              return <ItemCardSkeleton key={`${key}-${ri}-${i}`} />;
            })}
          </div>
        </CollapsibleItemRow>
      ))}
      {loading.length > 0 && (
        <div className={`grid ${colsForRow(readyRows.length)} gap-2 items-start`}>
          {loading.map((rawName, i) => (
            <ItemCardSkeleton key={`load-${cleanItemName(rawName).toLowerCase()}-${i}`} />
          ))}
        </div>
      )}
    </div>
  );
}
