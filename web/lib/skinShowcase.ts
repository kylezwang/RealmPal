/**
 * [skin:Class|Skin Name|Clothing|Accessory] tokens from the skin visualizer.
 */

export interface SkinSpec {
  className: string;
  skinName: string;
  clothing: string;
  accessory: string;
}

const SKIN_TOKEN = /\[skin:([^\]\n]+)\]/i;

export function parseSkinToken(content: string): SkinSpec | null {
  const match = content.match(SKIN_TOKEN);
  if (!match) return null;
  const parts = match[1].split("|").map((part) => part.trim());
  const className = parts[0] || "";
  const skinName = parts[1] || "";
  if (!className && !skinName) return null;
  return {
    className,
    skinName,
    clothing: parts[2] || "",
    accessory: parts[3] || "",
  };
}

const SKIN_CLASSES = [
  "Rogue", "Archer", "Wizard", "Priest", "Warrior", "Knight", "Paladin",
  "Assassin", "Necromancer", "Huntress", "Mystic", "Trickster", "Sorcerer",
  "Ninja", "Samurai", "Bard", "Summoner", "Kensei", "Druid",
] as const;

function stripTrailingClass(skinPart: string): { className: string; skinName: string } {
  for (const cls of SKIN_CLASSES) {
    const re = new RegExp(`\\b${cls}\\s*$`, "i");
    if (re.test(skinPart)) {
      return {
        className: cls,
        skinName: skinPart.replace(re, "").trim(),
      };
    }
  }
  return { className: "", skinName: skinPart };
}

/** Fallback when the assistant reply omitted the [skin:...] token. */
export function parseSkinFromPrompt(prompt: string | undefined): SkinSpec | null {
  if (!prompt) return null;
  const match = prompt.match(
    /\bwhat\s+does\s+(.+?)\s+look\s+like\s+(?:with|if\s+i\s+(?:use|put|wear|add)\s+)(.+?)(?:[.!?]|$)/i,
  );
  if (!match) return null;
  const { className, skinName } = stripTrailingClass(match[1].trim());
  const withPart = match[2].trim();
  const paired = withPart.match(
    /\b(?:large\s+and\s+small|small\s+and\s+large)\s+(.+?)\s+(cloths?|dyes?)\b/i,
  );
  if (paired) {
    const color = paired[1].trim();
    const kind = paired[2].toLowerCase().startsWith("dye") ? "dye" : "cloth";
    return {
      className,
      skinName,
      clothing: `Large ${color} ${kind}`,
      accessory: `Small ${color} ${kind}`,
    };
  }
  const largeCloth = withPart.match(/\b(large\s+(?!and\b).+\s+cloth)\b/i);
  const smallCloth = withPart.match(/\b(small\s+(?!and\b).+\s+cloth)\b/i);
  return {
    className,
    skinName,
    clothing: largeCloth?.[1] ?? (smallCloth ? "" : withPart),
    accessory: smallCloth?.[1] ?? "",
  };
}

export function stripSkinToken(content: string): string {
  return content.replace(SKIN_TOKEN, "").replace(/\n{3,}/g, "\n\n").trim();
}

export function inferSkinVisualize(prompt: string | undefined): boolean {
  if (!prompt) return false;
  if (/\bskin count\b|\bskins?\s+armor\b/i.test(prompt)) return false;
  if (/\b(?:all\s+)?(?:shiny|divine)\b/i.test(prompt) && /\b(?:set|loadout)\b/i.test(prompt)) {
    return false;
  }
  return (
    /\b(?:skins?\s+visuali[sz]e|visuali[sz]e\s+(?:this\s+|the\s+|my\s+)?(?:skin|outfit)|skin\s+visuali[sz]er?)\b/i.test(
      prompt,
    ) ||
    /\b(?:show|preview|render)\b.{0,120}\b(?:skin|outfit|dye|cloth)\b/i.test(prompt) ||
    /\blook like\b.{0,80}\b(?:cloth|dye)\b/i.test(prompt) ||
    /\bif i (?:use|put|wear|add)\b.{0,40}\b(?:cloth|dye)\b/i.test(prompt) ||
    /\b(?:large|small)\s+\S.+\s+cloth\b/i.test(prompt) ||
    /\b(?:clothing|accessory)\s+dye\b/i.test(prompt) ||
    /\b(?:let me see|show me|can i see|how about|what about)\b.{0,100}\b(?:cloth|dye)\b/i.test(prompt) ||
    /\b(?:now\s+)?(?:swap|switch|flip)\b/i.test(prompt)
  );
}
