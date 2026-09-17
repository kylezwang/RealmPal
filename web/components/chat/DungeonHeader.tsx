"use client";
import type { DungeonGuide } from "@/lib/api";
import { skipDungeonItemCard, isRealmBiome } from "@/lib/itemLookup";
import { portalForDungeon } from "@/lib/quests";

function WikiImg({
  src,
  alt,
  size,
  layout,
}: {
  src: string;
  alt: string;
  size?: number;
  layout?: boolean;
}) {
  return (
    <img
      src={src}
      alt={alt}
      width={size}
      height={size}
      className={layout ? "max-w-md max-h-72 w-auto h-auto mx-auto" : undefined}
      style={{
        imageRendering: "pixelated",
        width: size ?? "auto",
        height: size ?? "auto",
        maxWidth: layout ? undefined : "100%",
      }}
    />
  );
}

function GraveRow({
  difficulty,
  gravesUrl,
}: {
  difficulty: number;
  gravesUrl?: string;
}) {
  const count = Math.max(0, Math.min(10, Math.round(difficulty)));
  return (
    <div
      className="flex justify-center items-end gap-0.5 my-1"
      aria-label={`${count} out of 10`}
    >
      {Array.from({ length: count }, (_, i) =>
        gravesUrl ? (
          <WikiImg key={i} src={gravesUrl} alt="" size={16} />
        ) : (
          <span
            key={i}
            className="inline-block w-2.5 h-3.5 rounded-sm bg-[#c8c8c8]"
            aria-hidden
          />
        ),
      )}
    </div>
  );
}

export function DungeonHeader({ guide }: { guide: DungeonGuide }) {
  const title = guide.title.replace(/\s*[-–—]\s*the RotMG Wiki.*$/i, "").trim();
  const portalUrl = portalForDungeon(title, guide.portal_url);
  const portalSize = guide.large_portal || /hard mode/i.test(title) ? 160 : 72;
  return (
    <div className="text-center mb-3">
      {portalUrl && (
        <div className="flex justify-center mb-1.5">
          <WikiImg src={portalUrl} alt={`${title} portal`} size={portalSize} />
        </div>
      )}
      {guide.difficulty != null && (
        <GraveRow difficulty={guide.difficulty} gravesUrl={guide.graves_url} />
      )}
      <p className="text-xl font-semibold text-[#ececec] leading-tight mt-1">{title}</p>
      {(guide.tips ?? []).map((tip) => (
        <p
          key={tip}
          className="mt-3 mx-auto max-w-xl text-sm text-[#d4d4d4] leading-relaxed border border-[#404040] bg-[#262626] rounded-lg px-3 py-2 text-left"
        >
          <span className="font-semibold text-[#ececec]">Tip: </span>
          {tip}
        </p>
      ))}
    </div>
  );
}

export function DungeonLayouts({ guide }: { guide: DungeonGuide }) {
  if (!guide.layouts.length) return null;
  return (
    <div className="mt-3 space-y-2">
      <p className="text-lg font-semibold text-[#ececec] leading-tight">Example Layout</p>
      {guide.layouts.map((layout) => (
        <figure key={layout.url} className="my-2">
          <WikiImg src={layout.url} alt={layout.caption} layout />
          {layout.caption && (
            <figcaption className="text-xs text-[#8a8a8a] mt-1">{layout.caption}</figcaption>
          )}
        </figure>
      ))}
    </div>
  );
}

const DROP_ICON_SIZE = 25;

export function DungeonDrops({ guide }: { guide: DungeonGuide }) {
  const drops = guide.drops.filter(
    (drop) => isRealmBiome(guide.title) || !skipDungeonItemCard(drop.name),
  );
  if (!drops.length) return null;
  return (
    <div className="mt-3">
      <p className="text-lg font-semibold text-[#ececec] leading-tight mb-1.5">Drops of Interest</p>
      <ul className="list-disc pl-5 mb-2 space-y-0.5">
        {drops.map((drop) => (
          <li key={drop.name} className="pl-0.5">
            <span className="inline-flex items-start gap-1.5">
              {drop.sprite_url && <WikiImg src={drop.sprite_url} alt="" size={DROP_ICON_SIZE} />}
              <span>
                {drop.name}
                {drop.drops_from ? (
                  <span className="text-[#8a8a8a]">{`, drops from ${drop.drops_from}`}</span>
                ) : null}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
