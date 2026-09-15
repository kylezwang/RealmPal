/**
 * Pulls item names out of assistant text so the UI can fetch dedicated
 * wiki cards. Supports [item:Name] tokens, older [sprite:Name] tokens,
 * and RealmEye wiki markdown links (what the model often puts in tables).
 */

const TIERED_RING_FAMILIES: { t7: string; lower: string[]; t6: RegExp; t7b: string }[] = [
  { t7: "Ring of Transcendent Attack", lower: ["Ring of Unbound Attack", "Ring of Exalted Attack", "Ring of Paramount Attack", "Ring of Superior Attack", "Ring of Greater Attack", "Ring of Attack"], t6: /\+10(\s*ATT)/gi, t7b: "+11$1" },
  { t7: "Ring of Transcendent Defense", lower: ["Ring of Unbound Defense", "Ring of Exalted Defense", "Ring of Paramount Defense", "Ring of Superior Defense", "Ring of Greater Defense", "Ring of Defense", "Ring of Minor Defense"], t6: /\+10(\s*DEF)/gi, t7b: "+11$1" },
  { t7: "Ring of Transcendent Speed", lower: ["Ring of Unbound Speed", "Ring of Exalted Speed", "Ring of Paramount Speed", "Ring of Superior Speed", "Ring of Greater Speed", "Ring of Speed"], t6: /\+10(\s*SPD)/gi, t7b: "+11$1" },
  { t7: "Ring of Transcendent Dexterity", lower: ["Ring of Unbound Dexterity", "Ring of Exalted Dexterity", "Ring of Paramount Dexterity", "Ring of Superior Dexterity", "Ring of Greater Dexterity", "Ring of Dexterity"], t6: /\+10(\s*DEX)/gi, t7b: "+11$1" },
  { t7: "Ring of Transcendent Vitality", lower: ["Ring of Unbound Vitality", "Ring of Exalted Vitality", "Ring of Paramount Vitality", "Ring of Superior Vitality", "Ring of Greater Vitality", "Ring of Vitality"], t6: /\+10(\s*VIT)/gi, t7b: "+11$1" },
  { t7: "Ring of Transcendent Wisdom", lower: ["Ring of Unbound Wisdom", "Ring of Exalted Wisdom", "Ring of Paramount Wisdom", "Ring of Superior Wisdom", "Ring of Greater Wisdom", "Ring of Wisdom"], t6: /\+10(\s*WIS)/gi, t7b: "+11$1" },
  { t7: "Ring of Transcendent Health", lower: ["Ring of Unbound Health", "Ring of Exalted Health", "Ring of Paramount Health", "Ring of Superior Health", "Ring of Greater Health", "Ring of Health"], t6: /\+140(\s*HP)/gi, t7b: "+160$1" },
  { t7: "Ring of Transcendent Magic", lower: ["Ring of Unbound Magic", "Ring of Exalted Magic", "Ring of Paramount Magic", "Ring of Superior Magic", "Ring of Greater Magic", "Ring of Magic"], t6: /\+140(\s*MP)/gi, t7b: "+160$1" },
];

function escapeRe(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function mentionsName(content: string, name: string): boolean {
  return new RegExp(`\\b${escapeRe(name)}\\b`, "i").test(content);
}

function isLoadoutTableHeader(line: string): boolean {
  const n = line.toLowerCase();
  return n.includes("|") && /\brank\b/.test(n) && /\b(player|dps)\b/.test(n) && /\bring\b/.test(n);
}

/** RealmShark tables and their section stay verbatim — worn T6 rings are real. */
function partitionLoadoutRegions(content: string): { keep: boolean; text: string }[] {
  const lines = content.split("\n");
  const parts: { keep: boolean; text: string }[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (isLoadoutTableHeader(line) || /^\s*#{1,4}\s+.*realmshark/i.test(line)) {
      const start = i;
      if (isLoadoutTableHeader(line)) {
        i += 1;
        while (i < lines.length && /^\s*\|/.test(lines[i])) i += 1;
      } else {
        i += 1;
        while (i < lines.length && !/^\s*#{1,4}\s+/.test(lines[i])) i += 1;
      }
      parts.push({ keep: true, text: lines.slice(start, i).join("\n") });
      continue;
    }
    const start = i;
    i += 1;
    while (
      i < lines.length &&
      !isLoadoutTableHeader(lines[i]) &&
      !/^\s*#{1,4}\s+.*realmshark/i.test(lines[i])
    ) {
      i += 1;
    }
    parts.push({ keep: false, text: lines.slice(start, i).join("\n") });
  }
  return parts;
}

function upgradeRegion(content: string): string {
  let out = content;
  for (const family of TIERED_RING_FAMILIES) {
    if (!mentionsName(out, family.t7)) continue;
    for (const lower of family.lower) {
      out = out.replace(new RegExp(escapeRe(lower), "gi"), family.t7);
    }
    out = out
      .split("\n")
      .map((line) => (mentionsName(line, family.t7) ? line.replace(family.t6, family.t7b) : line))
      .join("\n");
  }
  return out;
}

export function upgradeTieredRingsInText(content: string): string {
  return partitionLoadoutRegions(content)
    .map((part) => (part.keep ? part.text : upgradeRegion(part.text)))
    .join("\n");
}

export function preferT7RingNames(names: string[]): string[] {
  const keys = new Set(names.map((n) => n.trim().toLowerCase()));
  return names.filter((name) => {
    const key = name.trim().toLowerCase();
    return !TIERED_RING_FAMILIES.some(
      (family) =>
        family.lower.some((n) => n.toLowerCase() === key) && keys.has(family.t7.toLowerCase()),
    );
  });
}

export function cleanItemName(name: string): string {
  return name.trim().replace(/\s*[-–—]\s*the RotMG Wiki.*$/i, "").trim();
}

/** One item-card grid row. Uncached fetches and skeletons stay at this size. */
export const ITEM_CARD_ROW_SIZE = 2;

/** HP/MP/stat potions and generic Tier 6/12 gear rows are not item cards. */
export function isGridWearableItem(item: { wearable?: boolean | null }): boolean {
  return item.wearable !== false;
}

export function skipDungeonItemCard(name: string): boolean {
  const text = cleanItemName(name);
  if (!text || /\bmark\b/i.test(text)) return false;
  if (/\bpotion\b/i.test(text)) return true;
  if (/(?:pet\s+)?skins?$/i.test(text)) return true;
  return /^tier\s+\d+\s+(?:alternate\s+)?(?:abilities|ability|rings?|weapons?|armou?r)s?\b/i.test(
    text,
  );
}

export function isDungeonPotion(name: string): boolean {
  return skipDungeonItemCard(name);
}

export function wikiSlug(url: string): string {
  const match = url.match(/\/wiki\/([^/?#]+)/i);
  return match ? decodeURIComponent(match[1]).toLowerCase() : "";
}

export function extractItemNames(content: string): string[] {
  const names: string[] = [];
  const seen = new Set<string>();
  const push = (raw: string) => {
    const name = cleanItemName(raw);
    const key = name.toLowerCase();
    if (!name || seen.has(key)) return;
    if (/\/|realmeye\.com|umienjoyers\.com|^https?:/i.test(name)) return;
    // Claude sometimes falls back to a generic "check the wiki page
    // directly" style link (e.g. `[RealmEye wiki dungeon page](.../wiki/...)`)
    // when it lacks real context. The wiki-link regex above can't tell that
    // apart from a real item/dungeon citation since both just point at
    // `/wiki/<slug>` - but no real item, dungeon, or set name ever contains
    // these generic referral words, so filter them out here instead. Without
    // this, the UI fires a doomed fetchItem() for a name that will never
    // exist, and the backend burns 15-30s of scraper time (shared by every
    // concurrent user) trying to scrape a URL that was never a real page.
    if (/\b(?:wiki|page|guide|directly|article)\b/i.test(name)) return;
    seen.add(key);
    names.push(name);
  };
  const collect = (text: string, collapseT7: boolean) => {
    const tokenRe = /\[(?:item|sprite):([^\]]+)\]/gi;
    let match: RegExpExecArray | null;
    const found: string[] = [];
    while ((match = tokenRe.exec(text)) !== null) found.push(match[1]);
    const wikiLinkRe =
      /\[([^\]]+)\]\((?:https?:\/\/(?:www\.)?realmeye\.com)?\/wiki\/[^)]+\)/gi;
    while ((match = wikiLinkRe.exec(text)) !== null) found.push(match[1]);
    const list = collapseT7 ? preferT7RingNames(found.map(cleanItemName)) : found;
    for (const raw of list) push(raw);
  };
  for (const part of partitionLoadoutRegions(content)) {
    collect(part.keep ? part.text : upgradeRegion(part.text), !part.keep);
  }
  return names;
}

export function findItem<T extends { name: string; wiki_url?: string }>(
  items: T[] | undefined,
  name?: string,
  href?: string,
): T | undefined {
  if (!items?.length) return undefined;
  if (name) {
    const key = cleanItemName(name).toLowerCase();
    const hit = items.find((item) => cleanItemName(item.name).toLowerCase() === key);
    if (hit) return hit;
  }
  if (href) {
    const slug = wikiSlug(href);
    if (slug) {
      return items.find((item) => item.wiki_url && wikiSlug(item.wiki_url) === slug);
    }
  }
  return undefined;
}

export function itemTokensToLinks(content: string): string {
  const upgraded = upgradeTieredRingsInText(content);
  return upgraded.replace(/\[(?:item|sprite):([^\]]+)\]/gi, (_full, raw: string) => {
    const name = cleanItemName(raw);
    return `[${name}](item://${encodeURIComponent(name)})`;
  });
}

export function stripItemTokens(content: string): string {
  return content.replace(/\[(?:item|sprite):[^\]]+\]/g, "").replace(/\n{3,}/g, "\n\n");
}
