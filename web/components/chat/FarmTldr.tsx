"use client";
import type { ItemProfile } from "@/lib/api";
import { findItem } from "@/lib/itemLookup";
import {
  type FarmEnemyId,
  type FarmGuide,
  type FarmMark,
  type FarmNode,
} from "@/lib/farmTldr";

const TILE = 48;

const ENEMY_PIXELS: Record<FarmEnemyId, string[][]> = {
  "ice-golem": [
    ["", "", "A", "A", "A", "A", "", ""],
    ["", "A", "W", "A", "A", "W", "A", ""],
    ["A", "A", "C", "A", "A", "C", "A", "A"],
    ["A", "B", "B", "B", "B", "B", "B", "A"],
    ["", "B", "W", "B", "B", "W", "B", ""],
    ["", "B", "B", "B", "B", "B", "B", ""],
    ["", "", "D", "B", "B", "D", "", ""],
    ["", "", "D", "", "", "D", "", ""],
  ],
  knight: [
    ["", "", "S", "S", "S", "S", "", ""],
    ["", "S", "S", "S", "S", "S", "S", ""],
    ["", "S", "K", "S", "S", "K", "S", ""],
    ["", "S", "S", "S", "S", "S", "S", ""],
    ["G", "G", "S", "S", "S", "S", "N", "N"],
    ["", "", "T", "T", "T", "T", "", ""],
    ["", "", "T", "", "", "T", "", ""],
    ["", "H", "H", "", "", "H", "H", ""],
  ],
  guardian: [
    ["", "", "O", "O", "O", "O", "", ""],
    ["", "O", "O", "F", "F", "O", "O", ""],
    ["", "O", "K", "O", "O", "K", "O", ""],
    ["", "O", "O", "O", "O", "O", "O", ""],
    ["O", "O", "V", "V", "V", "V", "O", "O"],
    ["", "", "V", "V", "V", "V", "", ""],
    ["", "", "L", "", "", "L", "", ""],
    ["", "L", "L", "", "", "L", "L", ""],
  ],
  jailer: [
    ["", "P", "P", "P", "P", "P", "P", ""],
    ["P", "U", "P", "P", "P", "P", "U", "P"],
    ["P", "P", "C", "P", "P", "C", "P", "P"],
    ["", "P", "P", "P", "P", "P", "P", ""],
    ["", "U", "U", "U", "U", "U", "U", ""],
    ["", "U", "R", "U", "U", "R", "U", ""],
    ["", "", "U", "U", "U", "U", "", ""],
    ["", "R", "R", "", "", "R", "R", ""],
  ],
  centipede: [
    ["", "M", "M", "", "", "M", "M", ""],
    ["M", "R", "M", "M", "M", "M", "R", "M"],
    ["M", "M", "C", "M", "M", "C", "M", "M"],
    ["", "M", "M", "M", "M", "M", "M", ""],
    ["M", "M", "", "M", "M", "", "M", "M"],
    ["", "M", "M", "M", "M", "M", "M", ""],
    ["M", "", "M", "", "", "M", "", "M"],
    ["", "M", "", "", "", "", "M", ""],
  ],
  pickaxe: [
    ["", "", "I", "I", "I", "", "", ""],
    ["", "I", "I", "I", "I", "I", "", ""],
    ["", "", "", "W", "I", "", "", ""],
    ["", "", "W", "W", "", "", "", ""],
    ["", "W", "W", "", "", "", "", ""],
    ["W", "W", "", "", "", "", "", ""],
    ["W", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", ""],
  ],
  "gold-shield": [
    ["", "", "Y", "Y", "Y", "Y", "", ""],
    ["", "Y", "Y", "K", "K", "Y", "Y", ""],
    ["Y", "Y", "K", "K", "K", "K", "Y", "Y"],
    ["Y", "Y", "K", "K", "K", "K", "Y", "Y"],
    ["", "Y", "Y", "K", "K", "Y", "Y", ""],
    ["", "", "Y", "Y", "Y", "Y", "", ""],
    ["", "", "", "Y", "Y", "", "", ""],
    ["", "", "", "Y", "Y", "", "", ""],
  ],
  "stun-helm": [
    ["", "S", "S", "S", "S", "S", "S", ""],
    ["S", "S", "Y", "S", "S", "Y", "S", "S"],
    ["S", "K", "S", "S", "S", "S", "K", "S"],
    ["S", "S", "S", "S", "S", "S", "S", "S"],
    ["", "S", "S", "S", "S", "S", "S", ""],
    ["", "", "S", "", "", "S", "", ""],
    ["", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", ""],
  ],
};

const PIXEL_COLORS: Record<string, string> = {
  A: "#7ec8e8",
  B: "#4aa4d4",
  C: "#1a1a2e",
  D: "#3d7ea8",
  W: "#f4fbff",
  S: "#9aa3ad",
  K: "#2a2a2a",
  G: "#c9a227",
  N: "#6e7c8a",
  T: "#5c6570",
  H: "#3a4048",
  O: "#d9894b",
  F: "#f0c48a",
  V: "#b8612c",
  L: "#8a3d18",
  P: "#6b5b95",
  U: "#3d3358",
  R: "#cfc6e8",
  M: "#8b1e3f",
  I: "#c0c6ce",
  Y: "#e2b537",
};

function PixelSprite({ id, label }: { id: FarmEnemyId; label: string }) {
  const grid = ENEMY_PIXELS[id];
  return (
    <span
      className="relative block"
      style={{ width: TILE, height: TILE, imageRendering: "pixelated" }}
      aria-label={label}
    >
      <span
        className="grid h-full w-full"
        style={{ gridTemplateColumns: `repeat(${grid[0].length}, 1fr)` }}
      >
        {grid.flatMap((row, y) =>
          row.map((cell, x) => (
            <span
              key={`${y}-${x}`}
              style={{ background: cell ? PIXEL_COLORS[cell] : "transparent" }}
            />
          )),
        )}
      </span>
    </span>
  );
}

function SwapArrows() {
  return (
    <svg width="36" height="40" viewBox="0 0 36 40" aria-hidden className="shrink-0">
      <path
        d="M10 8a10 10 0 0 1 16 4"
        fill="none"
        stroke="#e11d2a"
        strokeWidth="3.5"
        strokeLinecap="round"
      />
      <path d="M26 6l4 7-8 0z" fill="#e11d2a" />
      <path
        d="M26 32a10 10 0 0 1-16-4"
        fill="none"
        stroke="#e11d2a"
        strokeWidth="3.5"
        strokeLinecap="round"
      />
      <path d="M10 34l-4-7 8 0z" fill="#e11d2a" />
    </svg>
  );
}

function Mark({ kind }: { kind: FarmMark }) {
  if (kind === "ok") {
    return (
      <span className="pointer-events-none absolute -right-1 -top-1 text-lg leading-none text-green-400 drop-shadow">
        ✓
      </span>
    );
  }
  if (kind === "bonus") {
    return null;
  }
  return (
    <svg
      viewBox="0 0 48 48"
      className="pointer-events-none absolute inset-[-6px]"
      aria-hidden
    >
      <circle cx="24" cy="24" r="20" fill="none" stroke="#e11d2a" strokeWidth="4" />
      <line x1="11" y1="11" x2="37" y2="37" stroke="#e11d2a" strokeWidth="4" />
    </svg>
  );
}

function NodeView({
  node,
  items,
  light,
}: {
  node: FarmNode;
  items?: ItemProfile[];
  light: boolean;
}) {
  const item = node.item ? findItem(items, node.item) : undefined;
  const label = node.caption || node.item || node.enemy || "sprite";
  return (
    <span className="flex w-[4.6rem] flex-col items-center gap-1">
      <span className="relative" style={{ width: TILE, height: TILE }}>
        {item?.sprite_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={item.sprite_url}
            alt=""
            width={TILE}
            height={TILE}
            className="pointer-events-none"
            style={{ imageRendering: "pixelated", width: TILE, height: TILE }}
          />
        ) : node.enemy ? (
          <PixelSprite id={node.enemy} label={label} />
        ) : (
          <span
            className="block rounded bg-black/20"
            style={{ width: TILE, height: TILE }}
            aria-hidden
          />
        )}
        {node.mark ? <Mark kind={node.mark} /> : null}
      </span>
      {label ? (
        <span
          className={`text-center text-[10px] leading-tight ${
            light ? "text-[#1f1f1f]" : "text-[#ececec]"
          }`}
        >
          {label}
        </span>
      ) : null}
    </span>
  );
}

export function FarmTldr({
  guide,
  items,
}: {
  guide: FarmGuide;
  items?: ItemProfile[];
}) {
  const snow = guide.theme === "snow";
  return (
    <figure
      className={`mt-3 max-w-md overflow-hidden rounded-xl border border-[#404040] shadow-lg ${
        snow ? "bg-[#c5e4f2]" : "bg-[#2a2438]"
      }`}
      aria-label={guide.title}
    >
      <div
        className="px-3 py-2"
        style={
          snow
            ? {
                backgroundImage:
                  "linear-gradient(#a8d0e6 1px, transparent 1px), linear-gradient(90deg, #a8d0e6 1px, transparent 1px)",
                backgroundSize: "16px 16px",
              }
            : {
                backgroundImage:
                  "linear-gradient(#3a3350 1px, transparent 1px), linear-gradient(90deg, #3a3350 1px, transparent 1px)",
                backgroundSize: "16px 16px",
              }
        }
      >
        <p
          className={`mb-2 text-xs font-semibold tracking-wide ${
            snow ? "text-[#16324a]" : "text-[#ececec]"
          }`}
        >
          {guide.title}
        </p>
        <div className="flex flex-col gap-3">
          {guide.rows.map((row, index) => (
            <div key={`${row.kind}-${index}`} className="flex items-center gap-2">
              <div className="flex flex-wrap items-center gap-1">
                {row.nodes.map((node, nodeIndex) => (
                  <span key={`${node.item || node.enemy}-${nodeIndex}`} className="flex items-center gap-1">
                    {row.kind === "swap" && nodeIndex === 1 ? <SwapArrows /> : null}
                    <NodeView node={node} items={items} light={snow} />
                  </span>
                ))}
              </div>
              {row.banner ? (
                <p className="ml-1 max-w-[9rem] text-sm font-black uppercase leading-tight text-[#e11d2a] drop-shadow">
                  {row.banner}
                  <span className="ml-1 inline-block text-lg leading-none">←</span>
                </p>
              ) : null}
              {row.note && row.kind === "kit" ? (
                <p
                  className={`ml-1 max-w-[11rem] text-[11px] font-semibold leading-snug ${
                    snow ? "text-[#14532d]" : "text-[#86efac]"
                  }`}
                >
                  {row.note}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      </div>
    </figure>
  );
}
