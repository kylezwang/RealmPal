const GUIDE_RE =
  /(?:guide\s+to\s+complete|guide\s+to\s+(?:beat|clear|finish)|how\s+(?:do\s+i|to)\s+(?:complete|beat|clear|finish)|walkthrough\s+(?:for|of)|(?:dungeon\s+)?guide\s+(?:for|to))\s+(.+?)\s*$/i;

export function extractDungeonLookup(message: string): string | null {
  const text = (message || "").trim().replace(/[?.!]+$/, "");
  const match = text.match(GUIDE_RE);
  if (!match) return null;
  let name = match[1].trim();
  name = name.replace(/^(?:the\s+)?dungeon\s+/i, "");
  name = name.replace(/\s+dungeon$/i, "");
  return name || null;
}
