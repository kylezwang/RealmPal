/**
 * Sprite TLDR cards for a few well-known farms (Ogmur, Jailer's Scythe).
 * Backend emits `[farm:ogmur]`; the UI paints sprites, arrows, and marks.
 */

export type FarmMark = "ok" | "no" | "bonus";
export type FarmEnemyId =
  | "ice-golem"
  | "knight"
  | "guardian"
  | "jailer"
  | "centipede"
  | "pickaxe"
  | "gold-shield"
  | "stun-helm";

export interface FarmNode {
  enemy?: FarmEnemyId;
  item?: string;
  mark?: FarmMark;
  caption?: string;
}

export interface FarmRow {
  kind: "swap" | "avoid" | "kit";
  nodes: FarmNode[];
  banner?: string;
  note?: string;
}

export interface FarmGuide {
  id: string;
  title: string;
  theme: "snow" | "shadow";
  itemNames: string[];
  rows: FarmRow[];
  blurb: string;
}

const FARM_TOKEN = /\[farm:([a-z0-9-]+)\]/i;

export const FARM_GUIDES: Record<string, FarmGuide> = {
  ogmur: {
    id: "ogmur",
    title: "Ogmur farm",
    theme: "snow",
    itemNames: ["Shield of Ogmur", "Crystallised Fang's Venom"],
    rows: [
      {
        kind: "swap",
        nodes: [
          { enemy: "ice-golem", caption: "Lord of the Lost Lands" },
          { enemy: "gold-shield", mark: "no", caption: "Plain shield" },
          { item: "Shield of Ogmur", mark: "ok", caption: "Ogmur" },
        ],
      },
      {
        kind: "avoid",
        banner: "Do not chase these",
        nodes: [
          { enemy: "knight", mark: "no", caption: "Knights" },
          { enemy: "guardian", mark: "no", caption: "Guardians" },
        ],
      },
      {
        kind: "kit",
        note: "Stun as the last crystal breaks. Fang's Venom also Armor Breaks.",
        nodes: [
          { enemy: "stun-helm", mark: "ok", caption: "Stun" },
          { item: "Crystallised Fang's Venom", mark: "ok", caption: "Fang" },
          { enemy: "pickaxe", mark: "bonus", caption: "Bonus pots" },
        ],
      },
    ],
    blurb:
      "Runic Tundra encounter. Cosmically rare. Also Bilgewater's Galleon and Skeletal Centipede.",
  },
  scythe: {
    id: "scythe",
    title: "Scythe farm",
    theme: "shadow",
    itemNames: ["Jailer's Scythe"],
    rows: [
      {
        kind: "swap",
        nodes: [
          { enemy: "jailer", caption: "Spectral Jailer" },
          { item: "Jailer's Scythe", mark: "ok", caption: "Scythe" },
        ],
      },
      {
        kind: "avoid",
        banner: "No quest marker",
        nodes: [
          { enemy: "jailer", caption: "Easy to walk past" },
        ],
      },
      {
        kind: "kit",
        note: "Loot can hide under the Penitentiary portal. Check the bag.",
        nodes: [
          { enemy: "centipede", mark: "bonus", caption: "Sanguine Centipede" },
        ],
      },
    ],
    blurb:
      "Rare Veteran biome spawn, any of Floral Escape, Carboniferous, Sanguine Forest, Runic Tundra, or Deep Sea Abyss. Skeletal Centipede in Sanguine Forest is the easier dungeon source.",
  },
};

export function parseFarmToken(content: string): string | null {
  const match = content.match(FARM_TOKEN);
  return match ? match[1].toLowerCase() : null;
}

export function farmGuideFromContent(content: string): FarmGuide | null {
  const id = parseFarmToken(content);
  return id ? FARM_GUIDES[id] ?? null : null;
}

export function stripFarmToken(content: string): string {
  return content.replace(FARM_TOKEN, "").replace(/\n{3,}/g, "\n\n").trim();
}

export function farmItemNamesFromContent(content: string): string[] {
  const guide = farmGuideFromContent(content);
  return guide ? [...guide.itemNames] : [];
}
