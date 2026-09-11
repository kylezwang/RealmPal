"use client";
import { useEffect, useState } from "react";
import { fetchSkinPortrait, type DyeChip, type SkinPortrait as SkinPortraitData } from "@/lib/api";
import { type SkinSpec } from "@/lib/skinShowcase";
import { SpriteIcon } from "./SpriteIcon";

const TILE = 80;
const SKIN_IMG = 60;
const DYE_ICON = 48;

function DyeTile({ dye, label }: { dye?: DyeChip | null; label: string }) {
  const hasSprite =
    Boolean(dye?.sprite_sheet_url) && dye?.sprite_x != null && dye?.sprite_y != null;
  return (
    <div className="flex flex-col items-center gap-1 min-w-[80px]">
      <span className="text-[10px] uppercase tracking-wide text-[#8a8a8a]">{label}</span>
      <div
        className="flex items-center justify-center rounded-lg border border-[#404040] bg-[#2a2a2a] p-2"
        style={{ width: TILE, height: TILE }}
      >
        {hasSprite ? (
          <SpriteIcon
            sheetUrl={dye!.sprite_sheet_url!}
            x={dye!.sprite_x!}
            y={dye!.sprite_y!}
            nativeSize={dye!.sprite_size ?? 48}
            displaySize={DYE_ICON}
            alt={dye?.name || label}
          />
        ) : (
          <span className="text-[11px] text-[#9a9a9a]">None</span>
        )}
      </div>
      <span className="text-[11px] leading-tight text-center text-[#d4d4d4] max-w-[88px]">
        {dye?.name || "None"}
      </span>
    </div>
  );
}

export function SkinPortrait({ spec }: { spec: SkinSpec }) {
  const [portrait, setPortrait] = useState<SkinPortraitData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchSkinPortrait({
      className: spec.className,
      skinName: spec.skinName,
      clothing: spec.clothing,
      accessory: spec.accessory,
    })
      .then((row) => {
        if (!cancelled) setPortrait(row);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message || "Could not render that skin");
      });
    return () => {
      cancelled = true;
    };
  }, [spec.className, spec.skinName, spec.clothing, spec.accessory]);

  if (error) {
    return <p className="mt-3 text-sm text-[#c4a882]">{error}</p>;
  }

  return (
    <div className="mt-3 flex flex-wrap items-start gap-3" aria-label="Requested outfit">
      <div className="flex flex-col items-center gap-1 min-w-[96px]">
        <span className="text-[10px] uppercase tracking-wide text-[#8a8a8a]">Skin</span>
        <div
          className="flex items-center justify-center rounded-lg border border-[#404040] bg-[#2a2a2a] p-2 overflow-hidden"
          style={{ width: TILE, height: TILE }}
        >
          {portrait?.portrait_data_uri ? (
            <img
              src={portrait.portrait_data_uri}
              alt={portrait.skin_name}
              width={SKIN_IMG}
              height={SKIN_IMG}
              style={{ imageRendering: "pixelated", width: SKIN_IMG, height: SKIN_IMG }}
            />
          ) : (
            <div
              className="rounded-md border border-dashed border-[#444444]"
              style={{ width: SKIN_IMG, height: SKIN_IMG }}
              aria-hidden
            />
          )}
        </div>
        <span className="text-[11px] leading-tight text-center text-[#d4d4d4] max-w-[110px]">
          {portrait?.skin_name || spec.skinName}
        </span>
      </div>
      <DyeTile dye={portrait?.clothing} label="Clothing" />
      <DyeTile dye={portrait?.accessory} label="Accessory" />
    </div>
  );
}
